"""HTTP-backed CosyVoice provider for an optional Aurora Voice Node."""

from __future__ import annotations

import http.client
import json
import os
import socket
import tempfile
from collections import deque
from pathlib import Path
from threading import Event, Lock
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from modules.diagnostics import create_diagnostics

from aurora_voice_node.stream_protocol import CONTENT_TYPE, StreamFrame, StreamFrameDecoder, StreamProtocolError

from ..interfaces import StreamingTTSProvider, TTSProvider
from ..models import SpeechResult, StreamingSpeechResult, VoiceOptions
from ..wav_utils import inspect_wav


HttpOpen = Callable[..., Any]


class StreamingSynthesisError(RuntimeError):
    """A Voice Node stream failed after its response had started."""


class _RemotePcmIterator:
    def __init__(self, response: Any, cancel_event: Event | None, diagnostics: dict[str, object]) -> None:
        self.response = response
        self.cancel_event = cancel_event
        self.diagnostics = diagnostics
        self.decoder = StreamFrameDecoder()
        self.pending: deque[StreamFrame] = deque()
        self.closed = False
        self.completed = False
        self._close_lock = Lock()

    def read_metadata(self) -> dict[str, object]:
        frame = self._next_frame()
        if frame.frame_type != "M" or frame.data is None:
            self.close()
            raise StreamProtocolError("metadata must be the first frame")
        return frame.data

    def __iter__(self) -> "_RemotePcmIterator":
        return self

    def __next__(self) -> bytes:
        if self.completed or self.closed:
            raise StopIteration
        if self.cancel_event is not None and self.cancel_event.is_set():
            self._fail("cancelled", "speech streaming was cancelled")
        try:
            while True:
                frame = self._next_frame()
                if frame.frame_type == "A":
                    return frame.payload
                if frame.frame_type == "E":
                    self.completed = True
                    metrics = self.diagnostics.setdefault("metrics", {})
                    if isinstance(metrics, dict) and frame.data is not None:
                        metrics.update(frame.data)
                    self.diagnostics["success"] = True
                    self.diagnostics["reason"] = "stream_completed"
                    self.close(mark_cancelled=False)
                    raise StopIteration
                if frame.frame_type == "X":
                    detail = frame.data or {}
                    self._fail(str(detail.get("code", "stream_error")), str(detail.get("message", "stream failed")))
        except StopIteration:
            raise
        except StreamingSynthesisError:
            raise
        except (
            StreamProtocolError,
            http.client.IncompleteRead,
            http.client.RemoteDisconnected,
            OSError,
            ValueError,
        ) as error:
            self._fail("invalid_stream", str(error))

    def close(self, *, mark_cancelled: bool = True) -> None:
        with self._close_lock:
            if self.closed:
                return
            self.closed = True
        _shutdown_response_socket(self.response)
        try:
            self.response.close()
        finally:
            if mark_cancelled and not self.completed and self.diagnostics.get("success") is True:
                self.diagnostics["success"] = False
                self.diagnostics["reason"] = "cancelled"

    def _next_frame(self) -> StreamFrame:
        while not self.pending:
            reader = getattr(self.response, "read1", None)
            data = reader(8192) if callable(reader) else self.response.read(8192)
            if not data:
                self.decoder.finish()
                raise StreamProtocolError("stream ended without a pending terminal frame")
            self.pending.extend(self.decoder.feed(data))
        return self.pending.popleft()

    def _fail(self, code: str, message: str) -> None:
        self.diagnostics["success"] = False
        self.diagnostics["reason"] = code
        warnings = self.diagnostics.setdefault("warnings", [])
        if isinstance(warnings, list):
            warnings.append(message)
        self.close(mark_cancelled=False)
        raise StreamingSynthesisError(message)


def _shutdown_response_socket(response: Any) -> None:
    """Interrupt a concurrent buffered HTTP read before response.close()."""

    pending = [response]
    visited: set[int] = set()
    while pending:
        current = pending.pop()
        identity = id(current)
        if identity in visited:
            continue
        visited.add(identity)
        if isinstance(current, socket.socket):
            try:
                current.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            return
        for name in ("fp", "raw", "_sock"):
            try:
                child = getattr(current, name, None)
            except Exception:
                child = None
            if child is not None:
                pending.append(child)


class RemoteCosyVoiceProvider(TTSProvider, StreamingTTSProvider):
    """Synthesize WAV or framed PCM through the optional Voice Node."""

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

    def synthesize_stream(
        self,
        text: str,
        options: VoiceOptions | None = None,
        *,
        timeout_seconds: float | None = None,
        cancel_event: Event | None = None,
    ) -> StreamingSpeechResult:
        validation = self._stream_parameters(text, options, timeout_seconds, cancel_event)
        if isinstance(validation, StreamingSpeechResult):
            return validation
        speed, timeout = validation
        request = Request(
            f"{self.base_url}/tts/stream",
            data=json.dumps({"text": text, "speed": speed}, ensure_ascii=False).encode("utf-8"),
            headers={"Accept": CONTENT_TYPE, "Content-Type": "application/json; charset=utf-8"},
            method="POST",
        )
        try:
            response = self._http_open(request, timeout=timeout)
            status = int(getattr(response, "status", 200))
            if status != 200:
                response.close()
                return self._stream_failure(
                    "server_error", f"Voice Node returned HTTP {status}", metrics={"status": status}
                )
            content_type = str(response.headers.get("Content-Type", "")).lower()
            if "application/vnd.aurora.pcm-stream" not in content_type or "version=1" not in content_type:
                response.close()
                return self._stream_failure("invalid_response", "Voice Node returned an unsupported stream type")
            diagnostics = create_diagnostics(
                stage="experience.voice.tts.remote_cosyvoice.stream",
                success=True,
                reason="stream_open",
                metrics={"provider": "remote_cosyvoice", "speed": speed},
            )
            stream = _RemotePcmIterator(response, cancel_event, diagnostics)
            try:
                metadata = stream.read_metadata()
            except Exception:
                stream.close(mark_cancelled=False)
                raise
        except HTTPError as error:
            return self._stream_failure(
                "server_error", self._http_error_message(error), metrics={"status": int(error.code)}
            )
        except (TimeoutError, socket.timeout) as error:
            return self._stream_failure("timeout", "Voice Node request timed out", warning=type(error).__name__)
        except URLError as error:
            reason = "timeout" if isinstance(error.reason, (TimeoutError, socket.timeout)) else "connection_failed"
            return self._stream_failure(reason, "Voice Node is unavailable", warning=type(error.reason).__name__)
        except (
            OSError,
            ValueError,
            StreamProtocolError,
            http.client.IncompleteRead,
            http.client.RemoteDisconnected,
        ) as error:
            return self._stream_failure("invalid_stream", str(error), warning=type(error).__name__)
        metrics = diagnostics.get("metrics")
        if isinstance(metrics, dict):
            metrics.update(
                {
                    "sample_rate": metadata["sample_rate"],
                    "channels": metadata["channels"],
                    "bits_per_sample": metadata["bits_per_sample"],
                }
            )
        return StreamingSpeechResult(metadata=metadata, chunks=stream, diagnostics=diagnostics, _close=stream.close)

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

    def _stream_parameters(
        self,
        text: str,
        options: VoiceOptions | None,
        timeout_seconds: float | None,
        cancel_event: Event | None,
    ) -> tuple[float, float] | StreamingSpeechResult:
        if not isinstance(text, str):
            return self._stream_failure("invalid_text", "text must be a string")
        if not text.strip():
            return self._stream_failure("empty_text", "text must not be empty")
        if cancel_event is not None and cancel_event.is_set():
            return self._stream_failure("cancelled", "speech streaming was cancelled")
        try:
            speed = float((options or VoiceOptions()).rate)
            timeout = self.default_timeout_seconds if timeout_seconds is None else float(timeout_seconds)
        except (AttributeError, TypeError, ValueError):
            return self._stream_failure("invalid_options", "voice rate and timeout must be numbers")
        if not 0 < speed <= 4.0:
            return self._stream_failure("invalid_options", "voice rate must be greater than zero and at most 4.0")
        if timeout <= 0:
            return self._stream_failure("invalid_options", "timeout must be greater than zero")
        return speed, timeout

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

    @staticmethod
    def _stream_failure(
        reason: str,
        message: str,
        *,
        warning: str | None = None,
        metrics: dict[str, object] | None = None,
    ) -> StreamingSpeechResult:
        return StreamingSpeechResult(
            metadata={},
            chunks=iter(()),
            diagnostics=create_diagnostics(
                stage="experience.voice.tts.remote_cosyvoice.stream",
                success=False,
                reason=reason,
                warnings=[warning or message],
                metrics=metrics or {},
                trace={"message": message},
            ),
        )
