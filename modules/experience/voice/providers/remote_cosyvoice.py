"""HTTP-backed CosyVoice provider for an optional Aurora Voice Node."""

from __future__ import annotations

import json
import os
import socket
import tempfile
from pathlib import Path
from threading import Event
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from modules.diagnostics import create_diagnostics

from ..interfaces import TTSProvider
from ..models import SpeechResult, VoiceOptions
from ..wav_utils import inspect_wav


HttpOpen = Callable[..., Any]


class RemoteCosyVoiceProvider(TTSProvider):
    """Synthesize WAV audio through the Voice Node's blocking HTTP API."""

    def __init__(
        self,
        base_url: str,
        *,
        default_timeout_seconds: float = 30.0,
        output_dir: str | os.PathLike[str] | None = None,
        http_open: HttpOpen = urlopen,
        max_response_bytes: int = 64 * 1024 * 1024,
    ) -> None:
        self.base_url = self._normalize_base_url(base_url)
        self.default_timeout_seconds = max(float(default_timeout_seconds), 0.1)
        self.output_dir = Path(output_dir) if output_dir is not None else None
        self._http_open = http_open
        self.max_response_bytes = max(int(max_response_bytes), 1024)

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

        try:
            options = options or VoiceOptions()
            speed = float(options.rate)
        except (AttributeError, TypeError, ValueError):
            return self._failure("invalid_options", "voice rate must be a number")
        if not 0 < speed <= 4.0:
            return self._failure("invalid_options", "voice rate must be greater than zero and at most 4.0")

        try:
            timeout = self.default_timeout_seconds if timeout_seconds is None else float(timeout_seconds)
        except (TypeError, ValueError):
            return self._failure("invalid_options", "timeout must be a number")
        if timeout <= 0:
            return self._failure("invalid_options", "timeout must be greater than zero")
        request = Request(
            f"{self.base_url}/tts",
            data=json.dumps({"text": text, "speed": speed}, ensure_ascii=False).encode("utf-8"),
            headers={"Accept": "audio/wav", "Content-Type": "application/json; charset=utf-8"},
            method="POST",
        )

        try:
            with self._http_open(request, timeout=timeout) as response:
                status = int(getattr(response, "status", 200))
                content_type = str(response.headers.get("Content-Type", "")).split(";", 1)[0].strip().lower()
                if status != 200:
                    return self._failure("server_error", f"Voice Node returned HTTP {status}", metrics={"status": status})
                if content_type not in {"audio/wav", "audio/x-wav"}:
                    return self._failure("invalid_response", "Voice Node did not return WAV audio")
                audio_bytes = response.read(self.max_response_bytes + 1)
        except HTTPError as error:
            return self._failure(
                "server_error",
                self._http_error_message(error),
                metrics={"status": int(error.code)},
            )
        except (TimeoutError, socket.timeout) as error:
            return self._failure("timeout", "Voice Node request timed out", warning=type(error).__name__)
        except URLError as error:
            if isinstance(error.reason, (TimeoutError, socket.timeout)):
                return self._failure("timeout", "Voice Node request timed out", warning=type(error.reason).__name__)
            return self._failure("connection_failed", "Voice Node is unavailable", warning=type(error.reason).__name__)
        except (OSError, ValueError) as error:
            return self._failure("connection_failed", "Voice Node request failed", warning=type(error).__name__)

        if len(audio_bytes) > self.max_response_bytes:
            return self._failure("invalid_response", "Voice Node WAV response exceeded the size limit")
        try:
            wav_info = inspect_wav(audio_bytes)
        except ValueError as error:
            return self._failure("invalid_wav", str(error))
        if cancel_event is not None and cancel_event.is_set():
            return self._failure("cancelled", "speech synthesis was cancelled")

        output_path: Path | None = None
        try:
            output_path = self._write_output(audio_bytes)
        except OSError as error:
            return self._failure("output_failed", "could not save Voice Node WAV", warning=type(error).__name__)
        if cancel_event is not None and cancel_event.is_set():
            output_path.unlink(missing_ok=True)
            return self._failure("cancelled", "speech synthesis was cancelled")

        return SpeechResult(
            audio_path=str(output_path),
            audio_bytes=audio_bytes,
            mime_type="audio/wav",
            duration_ms=wav_info.duration_ms,
            diagnostics=create_diagnostics(
                stage="experience.voice.tts.remote_cosyvoice",
                success=True,
                reason="synthesized",
                metrics={
                    "provider": "remote_cosyvoice",
                    "speed": speed,
                    "sample_rate": wav_info.sample_rate,
                    "channels": wav_info.channels,
                    "response_bytes": len(audio_bytes),
                },
            ),
        )

    def health(self, *, timeout_seconds: float = 2.0) -> tuple[bool, str]:
        """Probe node and runtime readiness without synthesizing audio."""

        request = Request(f"{self.base_url}/health", headers={"Accept": "application/json"}, method="GET")
        try:
            with self._http_open(request, timeout=max(float(timeout_seconds), 0.1)) as response:
                if int(getattr(response, "status", 200)) != 200:
                    return False, "Remote CosyVoice Voice Node returned an unhealthy status."
                payload = json.loads(response.read(64 * 1024).decode("utf-8"))
        except Exception:
            return False, "Remote CosyVoice Voice Node is unavailable."
        runtime = payload.get("runtime") if isinstance(payload, dict) else None
        if not isinstance(runtime, dict) or runtime.get("available") is not True:
            return False, "Remote CosyVoice Voice Node is reachable, but its runtime is unavailable."
        return True, "Remote CosyVoice Voice Node and runtime are available."

    def _write_output(self, audio_bytes: bytes) -> Path:
        if self.output_dir is not None:
            self.output_dir.mkdir(parents=True, exist_ok=True)
        handle, name = tempfile.mkstemp(
            prefix="aurora_remote_tts_",
            suffix=".wav",
            dir=str(self.output_dir) if self.output_dir is not None else None,
        )
        try:
            with os.fdopen(handle, "wb") as output:
                output.write(audio_bytes)
        except Exception:
            Path(name).unlink(missing_ok=True)
            raise
        return Path(name)

    @staticmethod
    def _normalize_base_url(value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("Remote CosyVoice Voice Node URL is required")
        normalized = value.strip().rstrip("/")
        parsed = urlsplit(normalized)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.query or parsed.fragment:
            raise ValueError("Remote CosyVoice Voice Node URL must be an HTTP(S) base URL")
        return normalized

    @staticmethod
    def _http_error_message(error: HTTPError) -> str:
        try:
            payload = json.loads(error.read(64 * 1024).decode("utf-8"))
            detail = payload.get("error", {}).get("message")
            if isinstance(detail, str) and detail.strip():
                return f"Voice Node error: {detail.strip()}"
        except Exception:
            pass
        return f"Voice Node returned HTTP {error.code}"

    @staticmethod
    def _failure(
        reason: str,
        message: str,
        *,
        warning: str | None = None,
        metrics: dict[str, object] | None = None,
    ) -> SpeechResult:
        return SpeechResult(
            diagnostics=create_diagnostics(
                stage="experience.voice.tts.remote_cosyvoice",
                success=False,
                reason=reason,
                warnings=[warning or message],
                metrics=metrics or {},
                trace={"message": message},
            )
        )
