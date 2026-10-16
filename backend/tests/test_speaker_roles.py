import unittest
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from app.services.speaker_roles import resolve_speaker_roles, validated_assignments
from app.services.stt_service import align_speakers


def stt(segments, available=True):
    return {"segments": segments, "transcript": "original", "duration_seconds": 20,
            "role_resolution_required": True, "diarization_status": "available" if available else "unavailable"}


class SpeakerAlignmentTests(unittest.TestCase):
    def test_word_alignment_separates_two_voices_inside_whisper_segment(self):
        words = [{"start": 0, "end": 1, "word": " I need a quote."},
                 {"start": 1, "end": 2, "word": " I will send pricing."}]
        result = align_speakers([{"start": 0, "end": 2, "text": "I need a quote. I will send pricing.", "words": words}],
                                [{"start": 0, "end": 1, "speaker": "A"}, {"start": 1, "end": 2, "speaker": "B"}])
        self.assertEqual([item["speaker"] for item in result], ["A", "B"])
        self.assertEqual([item["role"] for item in result], ["Unknown", "Unknown"])
        self.assertEqual(" ".join(item["text"] for item in result), "I need a quote. I will send pricing.")

    def test_missing_diarization_does_not_label_everything_as_caller(self):
        result = align_speakers([{"start": 0, "end": 1, "text": "Hello"}], [])
        self.assertEqual(result[0]["role"], "Unknown")
        self.assertEqual(result[0]["speaker"], "SPEAKER_UNKNOWN")

    def test_fallback_splits_sentences_for_content_role_inference(self):
        result = align_speakers([{"start": 0, "end": 4, "text": "I need pricing. I am the agent.", "words": [
            {"start": 0, "end": 1, "word": " I need pricing."},
            {"start": 1, "end": 2, "word": " I am the agent."}]}], [])
        self.assertEqual(len(result), 2)
        self.assertTrue(all(item["role"] == "Unknown" for item in result))


class SpeakerRoleTests(unittest.IsolatedAsyncioTestCase):
    async def test_customer_can_speak_first_and_acoustic_identity_is_consistent(self):
        segments = [
            {"start": 0, "end": 3, "speaker": "A", "text": "I am looking for a loan."},
            {"start": 4, "end": 7, "speaker": "B", "text": "I am calling from the bank."},
            {"start": 8, "end": 9, "speaker": "A", "text": "What are the rates?"},
        ]
        classifier = AsyncMock(return_value={"assignments": [
            {"id": "A", "role": "Customer", "confidence": "high", "evidence": "I am looking for a loan."},
            {"id": "B", "role": "Agent", "confidence": "high", "evidence": "I am calling from the bank."},
        ]})
        result = await resolve_speaker_roles(stt(segments), classifier)
        self.assertEqual([item["role"] for item in result["segments"]], ["Customer", "Caller", "Customer"])
        self.assertTrue(result["transcript"].startswith("[Customer | A]"))
        self.assertEqual([item["text"] for item in result["segments"]], [item["text"] for item in segments])
        self.assertEqual(result["role_resolution"]["method"], "acoustic_speaker_mapping")

    async def test_no_diarization_uses_marked_content_inference(self):
        segments = [{"start": 0, "end": 3, "speaker": "SPEAKER_UNKNOWN", "text": "Please send me a quotation."},
                    {"start": 4, "end": 7, "speaker": "SPEAKER_UNKNOWN", "text": "I will send our quotation."}]
        classifier = AsyncMock(return_value={"assignments": [
            {"id": "0", "role": "Customer", "confidence": "high", "evidence": segments[0]["text"]},
            {"id": "1", "role": "Agent", "confidence": "medium", "evidence": segments[1]["text"]},
        ]})
        result = await resolve_speaker_roles(stt(segments, False), classifier)
        self.assertEqual([item["role"] for item in result["segments"]], ["Customer", "Caller"])
        self.assertTrue(all(item["role_source"] == "ollama_content_inference" for item in result["segments"]))

    async def test_low_confidence_hallucinated_quotes_and_missing_roles_stay_unknown(self):
        entries = [{"id": "0", "text": "Hello"}, {"id": "1", "text": "Okay"}]
        result = validated_assignments({"assignments": [
            {"id": "0", "role": "Caller", "confidence": "low", "evidence": "Hello"},
            {"id": "1", "role": "Customer", "confidence": "high", "evidence": "I need a quote"},
            {"id": "99", "role": "Caller", "confidence": "high", "evidence": "Hello"},
        ]}, entries)
        self.assertEqual(result, {})

    async def test_role_service_failure_does_not_lose_transcript(self):
        segment = {"start": 0, "end": 3, "speaker": "SPEAKER_UNKNOWN", "text": "Original speech"}
        with self.assertLogs("app.services.speaker_roles", "WARNING"):
            result = await resolve_speaker_roles(stt([segment], False), AsyncMock(side_effect=RuntimeError("private-key")))
        self.assertEqual(result["segments"][0]["role"], "Unknown")
        self.assertIn("Original speech", result["transcript"])
        self.assertEqual(result["role_resolution"]["failed_batches"], 1)

    async def test_long_calls_are_batched_without_losing_segments(self):
        segments = [{"start": index, "end": index+1, "speaker": "SPEAKER_UNKNOWN", "text": "Hello"} for index in range(170)]
        classifier = AsyncMock(return_value={"assignments": []})
        result = await resolve_speaker_roles(stt(segments, False), classifier)
        self.assertEqual(classifier.await_count, 3)
        self.assertEqual(len(result["segments"]), 170)

    async def test_legacy_adapter_labels_are_preserved(self):
        legacy = {"segments": [], "transcript": "Synthetic transcript"}
        classifier = AsyncMock()
        self.assertIs(await resolve_speaker_roles(legacy, classifier), legacy)
        classifier.assert_not_called()


class RoleSummaryTests(unittest.IsolatedAsyncioTestCase):
    async def test_structured_summaries_preserve_roles_and_public_output(self):
        from app.services.llm_service import summarize_call
        result = {"caller_summary": "The agent offered a demonstration.",
                  "customer_summary": "The customer asked for pricing.",
                  "unassigned_summary": "A follow-up date was mentioned by an unidentified speaker.",
                  "customer_interest_level": "High", "key_topics": ["Pricing"],
                  "action_items": ["Send pricing"], "agent_performance_score": 8}
        chat = AsyncMock(return_value=SimpleNamespace(message=SimpleNamespace(content=json.dumps(result))))
        with patch("app.services.llm_service.AsyncClient", return_value=SimpleNamespace(chat=chat)):
            response = await summarize_call("[Caller | B]: I can offer a demo.\n[Customer | A]: What is the price?")
        self.assertIn("Caller (agent): The agent offered a demonstration.", response["call_summary"])
        self.assertIn("Customer: The customer asked for pricing.", response["call_summary"])
        self.assertIn("Unassigned speech:", response["call_summary"])
        self.assertEqual(response["agent_performance_score"], 8)
        self.assertNotIn("caller_summary", response)
