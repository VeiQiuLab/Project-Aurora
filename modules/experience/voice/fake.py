"""Deterministic providers for interface and integration tests."""

from __future__ import annotations

from threading import Event

from .interfaces import SpeechToTextProvider, TextToSpeechProvider
from .models import AudioInput, SpeechResult, TranscriptionResult, VoiceOptions


class FakeSpeechToTextProvider(SpeechToTextProvider):
    """Return a configured result without a microphone or model dependency."""

    def __init__(self, result: TranscriptionResult | None = None, error: Exception | None = None):
        self.result = result or TranscriptionResult(text="fake transcription", language="en")
        self.error = error
        self.inputs: list[AudioInput] = []

    def transcribe(
        self,
        audio_input: AudioInput,
        *,
        timeout_seconds: float | None = None,
        cancel_event: Event | None = None,
    ) -> TranscriptionResult:
        if not isinstance(audio_input, AudioInput):
            raise TypeError("audio_input must be an AudioInput")
        self.inputs.append(audio_input)
        if self.error is not None:
            raise self.error
        return self.result


class FakeTextToSpeechProvider(TextToSpeechProvider):
    """Return configured audio bytes without a voice engine or sound card."""

    def __init__(self, result: SpeechResult | None = None, error: Exception | None = None):
        self.result = result or SpeechResult(audio_bytes=b"fake-audio")
        self.error = error
        self.requests: list[tuple[str, VoiceOptions | None]] = []

    def synthesize(
        self,
        text: str,
        options: VoiceOptions | None = None,
        *,
        timeout_seconds: float | None = None,
        cancel_event: Event | None = None,
    ) -> SpeechResult:
        if not isinstance(text, str):
            raise TypeError("text must be a string")
        if not text.strip():
            raise ValueError("text must not be empty")
        if options is not None and not isinstance(options, VoiceOptions):
            raise TypeError("options must be VoiceOptions or None")
        self.requests.append((text, options))
        if self.error is not None:
            raise self.error
        return self.result
