from functools import lru_cache
from pathlib import Path
import os
import subprocess
import tempfile
import logging

from app.config import settings

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def get_whisper():
    from faster_whisper import WhisperModel
    return WhisperModel(
        settings.whisper_model,
        device=settings.whisper_device,
        compute_type=settings.whisper_compute_type,
    )


@lru_cache(maxsize=1)
def get_diarization_pipeline():
    if not settings.hf_token:
        logger.warning("diarization_unavailable reason=hf_token_not_configured")
        return None
    try:
        from pyannote.audio import Pipeline
        return Pipeline.from_pretrained(
            "pyannote/speaker-diarization-3.1",
            use_auth_token=settings.hf_token,
        )
    except Exception:
        logger.warning("diarization_unavailable reason=pipeline_initialization_failed")
        return None


def align_speakers(raw_segments, turns):
    """Split Whisper segments at word boundaries when acoustic speakers change."""
    def speaker_at(start, end):
        overlaps = {}
        for turn in turns:
            overlap = max(0.0, min(end, turn["end"]) - max(start, turn["start"]))
            if overlap:
                overlaps[turn["speaker"]] = overlaps.get(turn["speaker"], 0) + overlap
        return max(overlaps, key=overlaps.get) if overlaps else "SPEAKER_UNKNOWN"
    merged = []
    for segment in raw_segments:
        words = segment.get("words")
        if words:
            groups = []
            for word in words:
                speaker = speaker_at(word["start"], word["end"])
                sentence_break = (not turns and groups and (
                    groups[-1]["text"].rstrip().endswith((".", "?", "!", "।"))
                    or word["start"] - groups[-1]["end"] >= 0.6
                    or word["end"] - groups[-1]["start"] > 12))
                if groups and groups[-1]["speaker"] == speaker and not sentence_break:
                    groups[-1]["text"] += word["word"]
                    groups[-1]["end"] = word["end"]
                else:
                    groups.append({"start": word["start"], "end": word["end"], "text": word["word"], "speaker": speaker})
            for group in groups:
                group["text"] = group["text"].strip()
                if group["text"]:
                    merged.append({**group, "role": "Unknown"})
        else:
            merged.append({"start": segment["start"], "end": segment["end"], "text": segment["text"],
                           "speaker": speaker_at(segment["start"], segment["end"]), "role": "Unknown"})
    return merged


def normalize_audio_to_wav(audio_path: str) -> str:
    """Convert any FFmpeg-decodable input to mono, 16 kHz PCM WAV.

    A temporary file is returned; the caller is responsible for deleting it.
    This consistent format is accepted by both Faster-Whisper and pyannote.
    """
    temp = tempfile.NamedTemporaryFile(prefix="call-analytics-", suffix=".wav", delete=False)
    normalized_path = temp.name
    temp.close()
    command = [
        "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(audio_path), "-vn", "-ac", "1", "-ar", "16000",
        "-c:a", "pcm_s16le", normalized_path,
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=900)
        if result.returncode != 0:
            detail = (result.stderr or "Unknown FFmpeg error").strip()[-1500:]
            raise RuntimeError(f"Could not decode/convert audio. Ensure the file contains a supported audio stream. FFmpeg: {detail}")
        return normalized_path
    except Exception:
        try:
            os.remove(normalized_path)
        except OSError:
            pass
        raise


def transcribe_and_diarize(audio_path: str) -> dict:
    normalized_path = normalize_audio_to_wav(audio_path)
    try:
        model = get_whisper()
        segments_iter, info = model.transcribe(normalized_path, vad_filter=True, word_timestamps=True)
        raw_segments = [
            {"start": float(s.start), "end": float(s.end), "text": s.text.strip(),
             "words": [{"start": float(w.start), "end": float(w.end), "word": w.word} for w in (s.words or [])]}
            for s in segments_iter
        ]

        pipeline = get_diarization_pipeline()
        turns = []
        if pipeline:
            try:
                diarization = pipeline(normalized_path)
                for turn, _, speaker in diarization.itertracks(yield_label=True):
                    turns.append({"start": float(turn.start), "end": float(turn.end), "speaker": str(speaker)})
            except Exception:
                logger.warning("diarization_unavailable reason=inference_failed")

        merged = align_speakers(raw_segments, turns)
        transcript = "\n".join(f'[Unassigned | {s["speaker"]}]: {s["text"]}' for s in merged)
        duration = max((s["end"] for s in raw_segments), default=0.0)
        return {
            "segments": merged,
            "transcript": transcript,
            "duration_seconds": duration,
            "language": getattr(info, "language", None),
            "diarization_status": "available" if turns else "unavailable",
            "role_resolution_required": True,
        }
    finally:
        try:
            os.remove(normalized_path)
        except OSError:
            pass
