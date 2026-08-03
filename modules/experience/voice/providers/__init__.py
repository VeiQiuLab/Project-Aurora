"""Concrete voice providers behind the Experience Layer interfaces."""

from .edge_tts import EdgeTTSProvider
from .faster_whisper import FasterWhisperProvider

__all__ = ["EdgeTTSProvider", "FasterWhisperProvider"]
