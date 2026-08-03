"""Edge TTS provider with a synchronous TextToSpeechProvider boundary."""

from __future__ import annotations

import asyncio
import os
import tempfile
import time
from pathlib import Path
from threading import Event
from typing import Any, Callable

from modules.diagnostics import create_diagnostics

from ..interfaces import TextToSpeechProvider
from ..models import SpeechResult, VoiceOptions


CommunicateFactory = Callable[..., Any]


class EdgeTTSProvider(TextToSpeechProvider):
    """Generate an MP3 file through the online Edge TTS service."""

    _DEFAULT_VOICES = {
        "zh": "zh-CN-XiaoxiaoNeural",
        "en": "en-US-AriaNeural",
        "ja": "ja-JP-NanamiNeural",
    }

    def __init__(
        self,
        *,
        default_voice: str = "zh-CN-XiaoxiaoNeural",
        output_dir: str | os.PathLike[str] | None = None,
        communicate_factory: CommunicateFactory | None = None,
        max_retries: int = 2,
        retry_delay_seconds: float = 0.5,
    ):
        self.default_voice = default_voice
        self.output_dir = Path(output_dir) if output_dir is not None else None
        self._communicate_factory = communicate_factory
        self.max_retries = max(int(max_retries), 0)
        self.retry_delay_seconds = max(float(retry_delay_seconds), 0.0)

    def synthesize(
        self,
        text: str,
        options: VoiceOptions | None = None,
        *,
        timeout_seconds: float | None = None,
        cancel_event: Event | None = None,
    ) -> SpeechResult:
        if not isinstance(text, str):
            return self._failure("invalid_text", "text must be a string")
        if not text.strip():
            return self._failure("empty_text", "text must not be empty")
        if cancel_event is not None and cancel_event.is_set():
            return self._failure("cancelled", "speech synthesis was cancelled")

        options = options or VoiceOptions()
        if options.rate <= 0:
            return self._failure("invalid_options", "voice rate must be greater than zero")

        voice = options.voice.strip() or self._voice_for_language(options.language)
        rate = self._format_rate(options.rate)
        factory = self._get_communicate_factory()
        if isinstance(factory, Exception):
            return self._failure(
                "dependency_missing",
                "edge-tts is not installed",
                warning="install edge-tts before enabling EdgeTTSProvider",
            )
        last_reason = "generation_failed"
        last_message = "Edge TTS generation failed"
        last_warning = None
        attempts = 0
        for attempt in range(self.max_retries + 1):
            attempts += 1
            output_path = None
            try:
                output_path = self._allocate_output_path()
                communicator = factory(text, voice=voice, rate=rate)
                self._run_save(communicator, output_path, timeout_seconds)
                if cancel_event is not None and cancel_event.is_set():
                    self._remove_output(output_path)
                    return self._failure("cancelled", "speech synthesis was cancelled", metrics={"attempts": attempts})
                diagnostics = create_diagnostics(
                    stage="experience.voice.tts.edge",
                    success=True,
                    reason="synthesized",
                    warnings=["VoiceOptions.style is not supported by edge-tts"]
                    if options.style
                    else [],
                    metrics={
                        "provider": "edge-tts",
                        "voice": voice,
                        "language": options.language,
                        "rate": rate,
                        "format": "mp3",
                        "attempts": attempts,
                        "max_retries": self.max_retries,
                    },
                )
                return SpeechResult(audio_path=str(output_path), mime_type="audio/mpeg", diagnostics=diagnostics)
            except asyncio.TimeoutError as error:
                last_reason, last_message, last_warning = "timeout", "Edge TTS synthesis timed out", type(error).__name__
                self._remove_output(output_path)
            except Exception as error:
                last_reason, last_message, last_warning = "generation_failed", str(error), type(error).__name__
                self._remove_output(output_path)
            if attempt < self.max_retries:
                if cancel_event is not None and cancel_event.is_set():
                    return self._failure("cancelled", "speech synthesis was cancelled", metrics={"attempts": attempts})
                time.sleep(self.retry_delay_seconds * (attempt + 1))
        return self._failure(
            last_reason,
            last_message,
            warning=last_warning,
            metrics={"attempts": attempts, "max_retries": self.max_retries},
        )

    def _get_communicate_factory(self) -> CommunicateFactory | Exception:
        if self._communicate_factory is not None:
            return self._communicate_factory
        try:
            from edge_tts import Communicate

            self._communicate_factory = Communicate
            return Communicate
        except ImportError as error:
            return error

    def _allocate_output_path(self) -> Path:
        if self.output_dir is not None:
            self.output_dir.mkdir(parents=True, exist_ok=True)
        handle, path = tempfile.mkstemp(
            prefix="aurora_tts_",
            suffix=".mp3",
            dir=str(self.output_dir) if self.output_dir is not None else None,
        )
        os.close(handle)
        return Path(path)

    @staticmethod
    def _run_save(communicator: Any, output_path: Path, timeout_seconds: float | None) -> None:
        async def save():
            operation = communicator.save(str(output_path))
            if timeout_seconds is None:
                await operation
            else:
                await asyncio.wait_for(operation, timeout=timeout_seconds)

        asyncio.run(save())

    def _voice_for_language(self, language: str) -> str:
        language_key = (language or "zh_CN").replace("-", "_").split("_", 1)[0].lower()
        return self._DEFAULT_VOICES.get(language_key, self.default_voice)

    @staticmethod
    def _format_rate(rate: float) -> str:
        percentage = round((float(rate) - 1.0) * 100)
        return f"{percentage:+d}%"

    @staticmethod
    def _remove_output(output_path: Path | None) -> None:
        if output_path is not None:
            try:
                output_path.unlink(missing_ok=True)
            except OSError:
                pass

    @staticmethod
    def _failure(reason: str, message: str, *, warning: str | None = None, metrics: dict | None = None) -> SpeechResult:
        return SpeechResult(
            diagnostics=create_diagnostics(
                stage="experience.voice.tts.edge",
                success=False,
                reason=reason,
                warnings=[warning] if warning else [message],
                metrics=metrics or {},
                trace={"message": message},
            )
        )
