"""Provider boundaries for speech recognition and speech synthesis."""

from __future__ import annotations

from abc import ABC, abstractmethod
from threading import Event

from .models import AudioInput, SpeechResult, TranscriptionResult, VoiceOptions


class SpeechToTextProvider(ABC):
    """Recognize audio; orchestration remains outside the provider."""

    @abstractmethod
    def transcribe(
        self,
        audio_input: AudioInput,
        *,
        timeout_seconds: float | None = None,
        cancel_event: Event | None = None,
    ) -> TranscriptionResult:
        """Return a transcription for the supplied audio input."""


class TextToSpeechProvider(ABC):
    """Synthesize text into audio; playback remains outside the provider."""

    @abstractmethod
    def synthesize(
        self,
        text: str,
        options: VoiceOptions | None = None,
        *,
        timeout_seconds: float | None = None,
        cancel_event: Event | None = None,
    ) -> SpeechResult:
        """Return generated audio for the supplied text."""
