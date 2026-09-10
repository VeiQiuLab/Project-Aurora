"""Small WAV validation helpers shared by TTS transport boundaries."""

from __future__ import annotations

import io
import wave
from dataclasses import dataclass


@dataclass(frozen=True)
class WavInfo:
    channels: int
    sample_rate: int
    sample_width: int
    frame_count: int
    duration_ms: int


def inspect_wav(data: bytes) -> WavInfo:
    """Return basic PCM WAV metadata, raising ValueError for unusable audio."""

    if not isinstance(data, bytes) or len(data) < 44:
        raise ValueError("WAV response is too short")
    if data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise ValueError("response is not a RIFF/WAVE file")
    try:
        with wave.open(io.BytesIO(data), "rb") as audio:
            channels = audio.getnchannels()
            sample_rate = audio.getframerate()
            sample_width = audio.getsampwidth()
            frame_count = audio.getnframes()
            compression = audio.getcomptype()
    except (EOFError, wave.Error) as error:
        raise ValueError(f"invalid WAV structure: {error}") from error

    if compression != "NONE":
        raise ValueError("compressed WAV audio is not supported")
    if channels <= 0 or sample_rate <= 0 or sample_width <= 0 or frame_count <= 0:
        raise ValueError("WAV contains no playable PCM frames")
    return WavInfo(
        channels=channels,
        sample_rate=sample_rate,
        sample_width=sample_width,
        frame_count=frame_count,
        duration_ms=round(frame_count * 1000 / sample_rate),
    )
