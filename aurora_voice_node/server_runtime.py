"""Lifecycle and HTTP adapter for one loopback-only cosyvoice-server process."""

from __future__ import annotations

import http.client
import json
import os
import socket
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock, Thread
from time import monotonic, sleep
from typing import Any, Callable, Iterator, Mapping

from .runtime import RuntimeSynthesisError, RuntimeTimedOut, RuntimeUnavailable


ProcessFactory = Callable[..., Any]
ConnectionFactory = Callable[..., Any]


@dataclass(frozen=True)
class CosyVoiceServerRuntimeConfig:
    server_path: Path
    model_path: Path
    prompt_speech_path: Path
    served_model_name: str = "aurora-cosyvoice3"
    voice: str = "aurora"
    backend: str | None = None
    backend_path: Path | None = None
    working_directory: Path | None = None
    internal_port: int = 0
    sample_rate: int = 24000
    channels: int = 1
    startup_timeout_seconds: float = 120.0
    synthesis_timeout_seconds: float = 120.0
    shutdown_timeout_seconds: float = 5.0
    max_response_bytes: int = 64 * 1024 * 1024
    extra_args: tuple[str, ...] = field(default_factory=tuple)

    def command(self, port: int) -> list[str]:
        command = [
            str(self.server_path),
            "--api",
            "--model",
            str(self.model_path),
            "--served-model-name",
            self.served_model_name,
            "--voice",
            self.voice,
            "--prompt-speech",
            str(self.prompt_speech_path),
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--concurrency",
            "1",
        ]
        if self.backend:
            command.extend(("--backend", self.backend))
        if self.backend_path:
            command.extend(("--backend-path", str(self.backend_path)))
        command.extend(self.extra_args)
        return command

    def validate(self) -> None:
        for label, path in (
            ("cosyvoice-server", self.server_path),
            ("model", self.model_path),
            ("prompt_speech", self.prompt_speech_path),
        ):
            if not Path(path).is_file():
                raise RuntimeUnavailable(f"{label} file is unavailable")
        if self.backend_path is not None and not Path(self.backend_path).is_dir():
            raise RuntimeUnavailable("backend directory is unavailable")
        if self.working_directory is not None and not Path(self.working_directory).is_dir():
            raise RuntimeUnavailable("working directory is unavailable")
        if not 0 <= int(self.internal_port) <= 65535:
            raise RuntimeUnavailable("internal port must be between 0 and 65535")
        if int(self.channels) != 1:
            raise RuntimeUnavailable("cosyvoice-server streaming requires one channel")
        if int(self.sample_rate) <= 0:
            raise RuntimeUnavailable("sample rate must be positive")


class CosyVoiceServerPcmStream:
    """One leased upstream HTTP response; closing it cancels generation."""

    def __init__(self, connection: Any, response: Any, release: Callable[[], None]) -> None:
        self._connection = connection
        self._response = response
        self._release = release
        self._closed = False
        self._close_lock = Lock()

    def __iter__(self) -> Iterator[bytes]:
        try:
            while not self._closed:
                reader = getattr(self._response, "read1", None)
                chunk = reader(8192) if callable(reader) else self._response.read(8192)
                if not chunk:
                    return
                yield bytes(chunk)
        except (http.client.IncompleteRead, http.client.RemoteDisconnected) as error:
            raise RuntimeSynthesisError("cosyvoice-server returned an incomplete PCM stream") from error
        except (TimeoutError, socket.timeout) as error:
            raise RuntimeTimedOut("cosyvoice-server streaming request timed out") from error
        except OSError as error:
            raise RuntimeSynthesisError(
                f"cosyvoice-server PCM stream failed: {type(error).__name__}"
            ) from error
        finally:
            self.close()

    def close(self) -> None:
        with self._close_lock:
            if self._closed:
                return
            self._closed = True
            try:
                self._response.close()
            finally:
                try:
                    self._connection.close()
                finally:
                    self._release()

    def __enter__(self) -> "CosyVoiceServerPcmStream":
        return self

    def __exit__(self, *_args: object) -> bool:
        self.close()
        return False


class CosyVoiceServerRuntime:
    """Own one persistent cosyvoice-server and serialize its model requests."""

    _MAX_LOG_CHARS = 64 * 1024

    def __init__(
        self,
        config: CosyVoiceServerRuntimeConfig,
        *,
        process_factory: ProcessFactory = subprocess.Popen,
        connection_factory: ConnectionFactory = http.client.HTTPConnection,
        environment: Mapping[str, str] | None = None,
    ) -> None:
        self.config = config
        self._process_factory = process_factory
        self._connection_factory = connection_factory
        self._environment = dict(environment) if environment is not None else None
        self._lifecycle_lock = Lock()
        self._request_lock = Lock()
        self._state_lock = Lock()
        self._process: Any | None = None
        self._reader_thread: Thread | None = None
        self._state = "stopped"
        self._internal_port: int | None = None
        self._last_error = ""
        self._log_tail = ""
        self._process_start_count = 0

    def start(self) -> None:
        with self._lifecycle_lock:
            self._start_locked()

    def synthesize(
        self,
        text: str,
        speed: float,
        *,
        timeout_seconds: float | None = None,
    ) -> bytes:
        normalized_text = self._validate_text(text)
        requested_speed = self._validate_speed(speed)
        timeout = self._timeout(timeout_seconds)
        with self._request_lock:
            self._ensure_ready()
            connection, response = self._open_speech_response(
                normalized_text,
                requested_speed,
                stream=False,
                response_format="wav",
                timeout=timeout,
            )
            try:
                audio = response.read(self.config.max_response_bytes + 1)
            except (TimeoutError, socket.timeout) as error:
                raise RuntimeTimedOut("cosyvoice-server synthesis timed out") from error
            except (http.client.IncompleteRead, http.client.RemoteDisconnected, OSError) as error:
                raise RuntimeSynthesisError("cosyvoice-server returned an incomplete WAV response") from error
            finally:
                response.close()
                connection.close()
            if len(audio) > self.config.max_response_bytes:
                raise RuntimeSynthesisError("cosyvoice-server WAV response exceeded the size limit")
            return bytes(audio)

    def stream_pcm(
        self,
        text: str,
        speed: float,
        *,
        timeout_seconds: float | None = None,
    ) -> CosyVoiceServerPcmStream:
        normalized_text = self._validate_text(text)
        requested_speed = self._validate_speed(speed)
        timeout = self._timeout(timeout_seconds)
        self._request_lock.acquire()
        try:
            self._ensure_ready()
            connection, response = self._open_speech_response(
                normalized_text,
                requested_speed,
                stream=True,
                response_format="pcm",
                timeout=timeout,
            )
        except Exception:
            self._request_lock.release()
            raise
        return CosyVoiceServerPcmStream(connection, response, self._request_lock.release)

    def health(self) -> dict[str, object]:
        with self._state_lock:
            process = self._process
            exit_code = process.poll() if process is not None else None
            if process is not None and exit_code is not None and self._state in {"starting", "ready"}:
                self._state = "failed"
                self._last_error = self._diagnostic_message_unlocked(
                    f"cosyvoice-server exited unexpectedly with code {exit_code}"
                )
            running = process is not None and exit_code is None
            available = running and self._state == "ready"
            return {
                "backend": "server",
                "available": available,
                "state": self._state,
                "process_running": running,
                "pid": process.pid if running else None,
                "restart_count": max(self._process_start_count - 1, 0),
                "streaming": True,
                "sample_rate": int(self.config.sample_rate),
                "channels": int(self.config.channels),
                "last_error": self._last_error,
                "startup_output_tail": self._log_tail[-8192:],
            }

    def stop(self) -> None:
        with self._lifecycle_lock:
            self._terminate_locked("stopped")

    def _ensure_ready(self) -> None:
        with self._lifecycle_lock:
            if self._is_ready_locked():
                return
            if self._process is not None:
                self._terminate_locked("stopped")
            self._start_locked()

    def _start_locked(self) -> None:
        if self._is_ready_locked():
            return
        with self._state_lock:
            self._state = "starting"
            self._last_error = ""
            self._log_tail = ""
        try:
            self.config.validate()
            port = int(self.config.internal_port) or self._allocate_loopback_port()
            kwargs: dict[str, object] = {
                "stdin": subprocess.DEVNULL,
                "stdout": subprocess.PIPE,
                "stderr": subprocess.STDOUT,
                "bufsize": 0,
                "cwd": str(self.config.working_directory or self.config.server_path.parent),
            }
            if self._environment is not None:
                kwargs["env"] = self._environment
            if os.name == "nt" and hasattr(subprocess, "CREATE_NO_WINDOW"):
                kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
            process = self._process_factory(self.config.command(port), **kwargs)
        except RuntimeUnavailable as error:
            self._mark_failed(str(error))
            raise
        except (OSError, ValueError) as error:
            message = f"could not start cosyvoice-server: {type(error).__name__}"
            self._mark_failed(message)
            raise RuntimeUnavailable(message) from error
        if process.stdout is None:
            try:
                process.terminate()
            except Exception:
                pass
            self._mark_failed("cosyvoice-server did not expose an output pipe")
            raise RuntimeUnavailable(self._last_error)
        with self._state_lock:
            self._process = process
            self._internal_port = port
        self._reader_thread = Thread(target=self._read_output, args=(process,), daemon=True)
        self._reader_thread.start()
        try:
            self._wait_for_health()
        except RuntimeError:
            self._terminate_locked("failed")
            raise
        with self._state_lock:
            self._process_start_count += 1
            self._state = "ready"

    def _wait_for_health(self) -> None:
        deadline = monotonic() + max(float(self.config.startup_timeout_seconds), 0.1)
        last_detail = "health endpoint is not ready"
        while monotonic() < deadline:
            process = self._process
            if process is None or process.poll() is not None:
                message = self._diagnostic_message("cosyvoice-server exited during startup")
                self._mark_failed(message)
                raise RuntimeUnavailable(message)
            connection = None
            response = None
            try:
                connection = self._connection_factory("127.0.0.1", self._internal_port, timeout=0.5)
                connection.request("GET", "/healthz", headers={"Accept": "application/json"})
                response = connection.getresponse()
                body = response.read(64 * 1024)
                status = int(response.status)
                if status == 200:
                    payload = json.loads(body.decode("utf-8"))
                    if isinstance(payload, dict) and payload.get("status") == "ok":
                        return
                last_detail = f"health endpoint returned HTTP {status}"
            except Exception as error:
                last_detail = f"health check failed: {type(error).__name__}"
            finally:
                if response is not None:
                    response.close()
                if connection is not None:
                    connection.close()
            sleep(0.05)
        message = self._diagnostic_message(f"cosyvoice-server startup timed out; {last_detail}")
        self._mark_failed(message)
        raise RuntimeTimedOut(message)

    def _open_speech_response(
        self,
        text: str,
        speed: float,
        *,
        stream: bool,
        response_format: str,
        timeout: float,
    ) -> tuple[Any, Any]:
        process = self._process
        if process is None or process.poll() is not None or self._internal_port is None:
            raise RuntimeUnavailable(self._diagnostic_message("cosyvoice-server is unavailable"))
        payload = json.dumps(
            {
                "model": self.config.served_model_name,
                "voice": self.config.voice,
                "input": text,
                "speed": speed,
                "response_format": response_format,
                "stream": stream,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        connection = self._connection_factory("127.0.0.1", self._internal_port, timeout=timeout)
        try:
            connection.request(
                "POST",
                "/v1/audio/speech",
                body=payload,
                headers={
                    "Accept": "audio/pcm" if stream else "audio/wav",
                    "Content-Type": "application/json; charset=utf-8",
                    "Content-Length": str(len(payload)),
                },
            )
            response = connection.getresponse()
        except (TimeoutError, socket.timeout) as error:
            connection.close()
            raise RuntimeTimedOut("cosyvoice-server request timed out") from error
        except OSError as error:
            connection.close()
            raise RuntimeUnavailable(
                self._diagnostic_message(f"cosyvoice-server HTTP request failed: {type(error).__name__}")
            ) from error
        if int(response.status) != 200:
            detail = self._response_error(response)
            response.close()
            connection.close()
            raise RuntimeSynthesisError(detail)
        expected = "audio/pcm" if stream else "audio/wav"
        content_type = str(response.getheader("Content-Type", "")).split(";", 1)[0].strip().lower()
        if content_type != expected:
            response.close()
            connection.close()
            raise RuntimeSynthesisError(f"cosyvoice-server returned unexpected Content-Type: {content_type}")
        return connection, response

    @staticmethod
    def _response_error(response: Any) -> str:
        try:
            payload = json.loads(response.read(64 * 1024).decode("utf-8"))
            detail = payload.get("error", {}).get("message")
            if isinstance(detail, str) and detail.strip():
                return f"cosyvoice-server error: {detail.strip()}"
        except Exception:
            pass
        return f"cosyvoice-server returned HTTP {response.status}"

    def _read_output(self, process: Any) -> None:
        try:
            while True:
                chunk = process.stdout.read(4096)
                if not chunk:
                    break
                text = bytes(chunk).decode("utf-8", errors="replace")
                with self._state_lock:
                    self._log_tail = (self._log_tail + text)[-self._MAX_LOG_CHARS :]
        except Exception as error:
            with self._state_lock:
                if self._state not in {"stopping", "stopped"}:
                    self._last_error = f"cosyvoice-server output reader failed: {type(error).__name__}"
        finally:
            exit_code = process.poll()
            with self._state_lock:
                if self._process is process and exit_code is not None and self._state not in {
                    "stopping",
                    "stopped",
                }:
                    self._state = "failed"
                    self._last_error = self._diagnostic_message_unlocked(
                        f"cosyvoice-server exited unexpectedly with code {exit_code}"
                    )

    def _terminate_locked(self, final_state: str) -> None:
        process = self._process
        if process is not None and process.poll() is None:
            try:
                process.terminate()
                process.wait(timeout=max(float(self.config.shutdown_timeout_seconds), 0.1))
            except Exception:
                try:
                    process.kill()
                    process.wait(timeout=2.0)
                except Exception:
                    pass
        with self._state_lock:
            self._process = None
            self._internal_port = None
            self._state = final_state

    def _is_ready_locked(self) -> bool:
        process = self._process
        return process is not None and process.poll() is None and self._state == "ready"

    def _mark_failed(self, message: str = "") -> None:
        with self._state_lock:
            self._state = "failed"
            if message:
                self._last_error = message

    def _diagnostic_message(self, prefix: str) -> str:
        with self._state_lock:
            return self._diagnostic_message_unlocked(prefix)

    def _diagnostic_message_unlocked(self, prefix: str) -> str:
        tail = " ".join(self._log_tail.strip().split())[-1000:]
        return f"{prefix}: {tail}" if tail else prefix

    def _timeout(self, value: float | None) -> float:
        timeout = self.config.synthesis_timeout_seconds if value is None else float(value)
        if timeout <= 0:
            raise ValueError("timeout must be greater than zero")
        return timeout

    @staticmethod
    def _allocate_loopback_port() -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind(("127.0.0.1", 0))
            return int(listener.getsockname()[1])

    @staticmethod
    def _validate_speed(value: float) -> float:
        try:
            speed = float(value)
        except (TypeError, ValueError) as error:
            raise ValueError("speed must be a number") from error
        if not 0 < speed <= 4.0:
            raise ValueError("speed must be greater than zero and at most 4.0")
        return speed

    @staticmethod
    def _validate_text(value: str) -> str:
        if not isinstance(value, str):
            raise ValueError("text must be a string")
        normalized = " ".join(value.splitlines()).strip()
        if not normalized:
            raise ValueError("text must not be empty")
        return normalized
