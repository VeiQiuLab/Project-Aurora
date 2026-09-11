"""Provider boundaries for speech recognition and speech synthesis."""

from __future__ import annotations

from abc import ABC, abstractmethod
from threading import Event

from .models import (
    AudioInput,
    SpeechResult,
    StreamingSpeechResult,
    TTSRequest,
    TTSResponse,
    TranscriptionResult,
    VoiceOptions,
)


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


class TTSProvider(ABC):
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

    def synthesize_request(self, request: TTSRequest) -> TTSResponse:
        """Adapt the provider-neutral request to the legacy call contract."""

        if not isinstance(request, TTSRequest):
            raise TypeError("request must be a TTSRequest")
        return self.synthesize(
            request.text,
            request.options,
            timeout_seconds=request.timeout_seconds,
            cancel_event=request.cancel_event,
        )


class StreamingTTSProvider(ABC):
    """Optional synchronous PCM streaming capability independent of playback."""

    @abstractmethod
    def synthesize_stream(
        self,
        text: str,
        options: VoiceOptions | None = None,
        *,
        timeout_seconds: float | None = None,
        cancel_event: Event | None = None,
    ) -> StreamingSpeechResult:
        """Return metadata plus a blocking iterator of aligned PCM chunks."""


# Keep the established public name source-compatible while TTSProvider is the
# canonical interface for new integrations.
TextToSpeechProvider = TTSProvider
