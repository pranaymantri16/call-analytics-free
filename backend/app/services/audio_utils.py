"""Shared audio-format validation and FFmpeg normalization helpers."""
from pathlib import Path

# FFmpeg can decode many codecs/containers. This allowlist covers common audio
# formats plus common media containers that may contain an audio track.
SUPPORTED_AUDIO_EXTENSIONS = {
    ".wav", ".mp3", ".m4a", ".mp4", ".aac", ".ogg", ".opus", ".flac",
    ".wma", ".aiff", ".aif", ".amr", ".webm", ".mka", ".mkv", ".mov",
    ".3gp", ".ac3", ".ape", ".caf", ".mp2", ".mpga", ".mpeg", ".wv",
}


def get_audio_suffix(filename: str) -> str:
    """Return a normalized extension or an empty string."""
    return Path(filename.split("?", 1)[0].split("#", 1)[0]).suffix.lower()
