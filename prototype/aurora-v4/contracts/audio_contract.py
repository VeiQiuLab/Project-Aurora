"""Private Python/Rust complete-file playback. Not frontend audio transport."""
import re

IDENTITY = {"generation_id", "revision"}
ERRORS = {"", "INVALID_AUDIO_FILE", "AUDIO_FILE_UNAVAILABLE", "AUDIO_SIZE_LIMIT",
          "AUDIO_DECODE_FAILED", "AUDIO_DEVICE_UNAVAILABLE", "AUDIO_DEVICE_FAILED",
          "AUDIO_TIMEOUT", "AUDIO_INTERNAL_ERROR", "AUDIO_BUSY"}


def validate_audio(kind, payload):
    extra = {"file"} if kind == "audio.play.request" else {"state", "error_code"} if kind == "audio.event" else set()
    if set(payload) != IDENTITY | extra:
        raise ValueError("Invalid audio fields")
    if not isinstance(payload["generation_id"], str) or not 0 < len(payload["generation_id"]) <= 128:
        raise ValueError("Invalid audio identity")
    if type(payload["revision"]) is not int or not 0 <= payload["revision"] <= 9007199254740991:
        raise ValueError("Invalid audio revision")
    if kind == "audio.play.request":
        value = payload["file"]
        if not isinstance(value, str) or len(value)>256 or not re.fullmatch(r"[A-Za-z0-9_-]+/[A-Za-z0-9_-]+\.(mp3|wav)", value):
            raise ValueError("Invalid audio file")
    if kind == "audio.event":
        if payload["state"] not in {"started", "completed", "stopped", "failed"} or payload["error_code"] not in ERRORS:
            raise ValueError("Invalid audio event")
        if (payload["state"] == "failed") != bool(payload["error_code"]):
            raise ValueError("Invalid audio error")
