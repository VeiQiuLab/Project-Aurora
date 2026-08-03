"""Lazy Faster-Whisper STT provider with safe diagnostics fallback."""

from __future__ import annotations

from pathlib import Path
from threading import Event, RLock
from time import monotonic
from typing import Any, Callable

from modules.diagnostics import create_diagnostics

from ..interfaces import SpeechToTextProvider
from ..models import AudioInput, TranscriptionResult


ModelLoader = Callable[[str, str, str], Any]


class FasterWhisperProvider(SpeechToTextProvider):
    """Recognize file-backed audio without owning recording or chat behavior."""

    def __init__(
        self,
        model_size: str = "small",
        *,
        device: str = "auto",
        compute_type: str = "auto",
        beam_size: int = 5,
        language: str | None = "zh",
        model: Any | None = None,
        model_loader: ModelLoader | None = None,
    ):
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type
        self.beam_size = beam_size
        self.language = language
        self._model = model
        self._model_loader = model_loader or self._default_model_loader
        self._model_error: Exception | None = None
        self._lock = RLock()

    @property
    def model_loaded(self) -> bool:
        with self._lock:
            return self._model is not None

    def transcribe(
        self,
        audio_input: AudioInput,
        *,
        timeout_seconds: float | None = None,
        cancel_event: Event | None = None,
    ) -> TranscriptionResult:
        started_at = monotonic()
        if not isinstance(audio_input, AudioInput):
            return self._failure("invalid_audio_input", "audio_input must be an AudioInput")
        if audio_input.kind != "file" or not audio_input.path:
            return self._failure(
                "unsupported_audio_input",
                "Faster-Whisper provider currently accepts AudioInput(kind='file') only",
            )
        if cancel_event is not None and cancel_event.is_set():
            return self._failure("cancelled", "transcription was cancelled")

        audio_path = Path(audio_input.path)
        if not audio_path.is_file():
            return self._failure("audio_file_not_found", f"audio file does not exist: {audio_path}")

        model = self._get_model()
        if model is None:
            if isinstance(self._model_error, ImportError):
                return self._failure(
                    "dependency_missing",
                    "faster-whisper is not installed",
                    warning="install faster-whisper and its runtime dependencies before enabling this provider",
                )
            return self._failure(
                "model_unavailable",
                str(self._model_error or "Faster-Whisper model is unavailable"),
            )
        if self._timed_out(started_at, timeout_seconds):
            return self._failure("timeout", "transcription timed out before inference")

        try:
            segments, info = model.transcribe(
                str(audio_path),
                language=audio_input.language_hint or self.language or None,
                beam_size=self.beam_size,
            )
            text_parts = []
            for segment in segments:
                if cancel_event is not None and cancel_event.is_set():
                    return self._failure("cancelled", "transcription was cancelled")
                if self._timed_out(started_at, timeout_seconds):
                    return self._failure("timeout", "transcription timed out during inference")
                text_parts.append(str(getattr(segment, "text", "")))
        except Exception as error:
            return self._failure("transcription_failed", str(error), warning=type(error).__name__)

        duration = getattr(info, "duration", None)
        duration_ms = int(float(duration) * 1000) if duration is not None else 0
        diagnostics = create_diagnostics(
            stage="experience.voice.stt.faster_whisper",
            success=True,
            reason="transcribed",
            metrics={
                "model_size": self.model_size,
                "device": self.device,
                "compute_type": self.compute_type,
                "beam_size": self.beam_size,
                "language_config": self.language,
            },
        )
        return TranscriptionResult(
            text="".join(text_parts).strip(),
            language=str(getattr(info, "language", "") or ""),
            confidence=self._language_probability(info),
            duration_ms=duration_ms,
            diagnostics=diagnostics,
        )

    def _get_model(self) -> Any | None:
        with self._lock:
            if self._model is not None:
                return self._model
            if self._model_error is not None:
                return None
            try:
                self._model = self._model_loader(
                    self.model_size,
                    self.device,
                    self.compute_type,
                )
            except Exception as error:
                self._model_error = error
            return self._model

    @staticmethod
    def _default_model_loader(model_size: str, device: str, compute_type: str) -> Any:
        from faster_whisper import WhisperModel

        return WhisperModel(model_size, device=device, compute_type=compute_type)

    @staticmethod
    def _language_probability(info: Any) -> float | None:
        value = getattr(info, "language_probability", None)
        return float(value) if value is not None else None

    @staticmethod
    def _timed_out(started_at: float, timeout_seconds: float | None) -> bool:
        return timeout_seconds is not None and monotonic() - started_at >= timeout_seconds

    @staticmethod
    def _failure(reason: str, message: str, *, warning: str | None = None) -> TranscriptionResult:
        return TranscriptionResult(
            text="",
            diagnostics=create_diagnostics(
                stage="experience.voice.stt.faster_whisper",
                success=False,
                reason=reason,
                warnings=[warning] if warning else [message],
                trace={"message": message},
            ),
        )
