from functools import lru_cache
from pathlib import Path
import os
import subprocess
import tempfile

from app.config import settings


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
        return None
    try:
        from pyannote.audio import Pipeline
        return Pipeline.from_pretrained(
            "pyannote/speaker-diarization-3.1",
            use_auth_token=settings.hf_token,
        )
    except Exception as exc:
        print(f"pyannote pipeline unavailable; using single-speaker fallback: {exc}")
        return None


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
        segments_iter, info = model.transcribe(normalized_path, vad_filter=True)
        raw_segments = [
            {"start": float(s.start), "end": float(s.end), "text": s.text.strip()}
            for s in segments_iter
        ]

        pipeline = get_diarization_pipeline()
        turns = []
        if pipeline:
            try:
                diarization = pipeline(normalized_path)
                for turn, _, speaker in diarization.itertracks(yield_label=True):
                    turns.append({"start": float(turn.start), "end": float(turn.end), "speaker": str(speaker)})
            except Exception as exc:
                print(f"Diarization failed; using single-speaker fallback: {exc}")

        merged = []
        for seg in raw_segments:
            overlaps = {}
            for turn in turns:
                overlap = max(0.0, min(seg["end"], turn["end"]) - max(seg["start"], turn["start"]))
                if overlap:
                    overlaps[turn["speaker"]] = overlaps.get(turn["speaker"], 0.0) + overlap
            speaker = max(overlaps, key=overlaps.get) if overlaps else "SPEAKER_00"
            merged.append({**seg, "speaker": speaker, "role": "Caller"})

        # Role names are heuristics: the first speaker heard is labeled Caller.
        seen = []
        for seg in merged:
            if seg["speaker"] not in seen:
                seen.append(seg["speaker"])
        for seg in merged:
            seg["role"] = "Caller" if seen.index(seg["speaker"]) == 0 else "Customer"

        transcript = "\n".join(f'[{s["role"]}]: {s["text"]}' for s in merged)
        duration = max((s["end"] for s in raw_segments), default=0.0)
        return {
            "segments": merged,
            "transcript": transcript,
            "duration_seconds": duration,
            "language": getattr(info, "language", None),
        }
    finally:
        try:
            os.remove(normalized_path)
        except OSError:
            pass
