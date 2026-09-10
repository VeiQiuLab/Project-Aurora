"""Lifecycle adapter for cosyvoice-cli interactive mode."""

from __future__ import annotations

import codecs
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from threading import Condition, Lock, Thread
from time import monotonic
from typing import Any, Callable, Mapping, Sequence

from .wav_utils import inspect_wav, normalize_to_pcm16_wav


class RuntimeUnavailable(RuntimeError):
    """The cosyvoice process is not available or exited unexpectedly."""


class RuntimeTimedOut(RuntimeError):
    """The cosyvoice process exceeded a bounded startup or synthesis wait."""


class RuntimeSynthesisError(RuntimeError):
    """The cosyvoice process stayed alive but did not produce valid audio."""


@dataclass(frozen=True)
class CosyVoiceRuntimeConfig:
    cli_path: Path
    model_path: Path
    prompt_speech_path: Path
    backend: str | None = None
    backend_path: Path | None = None
    working_directory: Path | None = None
    output_directory: Path | None = None
    startup_timeout_seconds: float = 120.0
    synthesis_timeout_seconds: float = 120.0
    extra_args: tuple[str, ...] = field(default_factory=tuple)

    def command(self, speed: float) -> list[str]:
        command = [
            str(self.cli_path),
            "--model",
            str(self.model_path),
            "--prompt-speech",
            str(self.prompt_speech_path),
            "--interactive",
            "--speed",
            format(speed, ".6g"),
        ]
        if self.backend:
            command.extend(("--backend", self.backend))
        if self.backend_path:
            command.extend(("--backend-path", str(self.backend_path)))
        command.extend(self.extra_args)
        return command

    def validate(self) -> None:
        for label, path in (
            ("cosyvoice-cli", self.cli_path),
            ("model", self.model_path),
            ("prompt_speech", self.prompt_speech_path),
        ):
            if not Path(path).is_file():
                raise RuntimeUnavailable(f"{label} file is unavailable")
        if self.backend_path is not None and not Path(self.backend_path).is_dir():
            raise RuntimeUnavailable("backend directory is unavailable")
        if self.working_directory is not None and not Path(self.working_directory).is_dir():
            raise RuntimeUnavailable("working directory is unavailable")


ProcessFactory = Callable[..., Any]


class CosyVoiceRuntime:
    """Own one interactive CLI process and serialize its request/response REPL."""

    _GENERATED_RE = re.compile(r"Generated audio\s+(\d+)\s+\(")
    _MAX_DIAGNOSTIC_CHARS = 64 * 1024

    def __init__(
        self,
        config: CosyVoiceRuntimeConfig,
        *,
        process_factory: ProcessFactory = subprocess.Popen,
        environment: Mapping[str, str] | None = None,
    ) -> None:
        self.config = config
        self._process_factory = process_factory
        self._environment = dict(environment) if environment is not None else None
        self._operation_lock = Lock()
        self._condition = Condition()
        self._process: Any | None = None
        self._reader_thread: Thread | None = None
        self._output = ""
        self._prompt_count = 0
        self._state = "stopped"
        self._current_speed: float | None = None
        self._last_error = ""
        self._startup_output_tail = ""
        self._process_start_count = 0

    def start(self, speed: float = 1.0) -> None:
        with self._operation_lock:
            self._start_locked(self._validate_speed(speed))

    def synthesize(
        self,
        text: str,
        speed: float,
        *,
        timeout_seconds: float | None = None,
    ) -> bytes:
        normalized_text = self._validate_text(text)
        requested_speed = self._validate_speed(speed)
        timeout = (
            self.config.synthesis_timeout_seconds
            if timeout_seconds is None
            else max(float(timeout_seconds), 0.1)
        )
        with self._operation_lock:
            if not self._is_running() or self._current_speed != requested_speed:
                if self._process is not None:
                    self._stop_locked()
                self._start_locked(requested_speed)

            generated = self._send_and_wait(normalized_text, timeout, "synthesis")
            match = self._GENERATED_RE.search(generated)
            if match is None:
                if not self._is_running():
                    raise RuntimeUnavailable(self._exit_message("cosyvoice-cli exited during synthesis"))
                raise RuntimeSynthesisError(self._diagnostic_message("cosyvoice-cli did not generate audio", generated))

            audio_id = match.group(1)
            output_path = self._allocate_output_path()
            try:
                saved = self._send_and_wait(
                    f'/save "{output_path}" {audio_id}',
                    timeout,
                    "WAV export",
                )
                if f"Saved audio {audio_id} to " not in saved or not output_path.is_file():
                    raise RuntimeSynthesisError(self._diagnostic_message("cosyvoice-cli did not save WAV output", saved))
                audio_bytes = output_path.read_bytes()
                try:
                    audio_bytes = normalize_to_pcm16_wav(audio_bytes)
                    inspect_wav(audio_bytes)
                except ValueError as error:
                    raise RuntimeSynthesisError(f"cosyvoice-cli returned invalid WAV: {error}") from error
                return audio_bytes
            finally:
                output_path.unlink(missing_ok=True)
                if self._is_running():
                    try:
                        self._send_and_wait(f"/delete {audio_id}", 5.0, "cache cleanup")
                    except RuntimeError:
                        pass

    def health(self) -> dict[str, object]:
        """Return process readiness and the last bounded diagnostic."""

        with self._condition:
            process = self._process
            exit_code = process.poll() if process is not None else None
            if process is not None and exit_code is not None and self._state in {"starting", "ready"}:
                self._state = "failed"
                self._last_error = self._exit_message("cosyvoice-cli exited unexpectedly")
            available = process is not None and exit_code is None and self._state == "ready"
            return {
                "available": available,
                "state": self._state,
                "process_running": process is not None and exit_code is None,
                "pid": process.pid if process is not None and exit_code is None else None,
                "speed": self._current_speed,
                "restart_count": max(self._process_start_count - 1, 0),
                "last_error": self._last_error,
                "startup_output_tail": self._startup_output_tail,
            }

    def stop(self) -> None:
        with self._operation_lock:
            self._stop_locked()

    def _start_locked(self, speed: float) -> None:
        if self._is_running() and self._current_speed == speed:
            return
        with self._condition:
            self._state = "starting"
            self._last_error = ""
            self._startup_output_tail = ""
            self._output = ""
            self._prompt_count = 0
        try:
            self.config.validate()
        except RuntimeUnavailable as error:
            with self._condition:
                self._state = "failed"
                self._last_error = str(error)
            raise

        kwargs: dict[str, object] = {
            "stdin": subprocess.PIPE,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.STDOUT,
            "bufsize": 0,
            "cwd": str(self.config.working_directory or self.config.cli_path.parent),
        }
        if self._environment is not None:
            kwargs["env"] = self._environment
        if os.name == "nt" and hasattr(subprocess, "CREATE_NO_WINDOW"):
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        try:
            process = self._process_factory(self.config.command(speed), **kwargs)
        except (OSError, ValueError) as error:
            with self._condition:
                self._state = "failed"
                self._last_error = f"could not start cosyvoice-cli: {type(error).__name__}"
            raise RuntimeUnavailable(self._last_error) from error

        if process.stdin is None or process.stdout is None:
            try:
                process.terminate()
            except Exception:
                pass
            raise RuntimeUnavailable("cosyvoice-cli did not expose stdin/stdout pipes")

        with self._condition:
            self._process = process
        self._reader_thread = Thread(target=self._read_output, args=(process,), daemon=True)
        self._reader_thread.start()
        try:
            self._wait_for_prompt(max(float(self.config.startup_timeout_seconds), 0.1), "startup")
        except RuntimeError:
            self._terminate_locked("failed")
            raise
        with self._condition:
            self._process_start_count += 1
            self._current_speed = speed
            self._state = "ready"
            self._startup_output_tail = self._output[-8192:]
            self._output = ""
            self._prompt_count = 0

    def _send_and_wait(self, line: str, timeout: float, operation: str) -> str:
        process = self._process
        if process is None or process.poll() is not None or process.stdin is None:
            raise RuntimeUnavailable(self._exit_message(f"cosyvoice-cli is unavailable before {operation}"))
        with self._condition:
            self._output = ""
            self._prompt_count = 0
        try:
            process.stdin.write((line + "\n").encode("utf-8"))
            process.stdin.flush()
        except (BrokenPipeError, OSError) as error:
            self._terminate_locked("failed")
            raise RuntimeUnavailable(f"cosyvoice-cli pipe failed during {operation}") from error
        try:
            return self._wait_for_prompt(timeout, operation)
        except RuntimeTimedOut:
            self._terminate_locked("failed")
            raise

    def _wait_for_prompt(self, timeout: float, operation: str) -> str:
        deadline = monotonic() + max(float(timeout), 0.1)
        with self._condition:
            while self._prompt_count < 1:
                process = self._process
                if process is None or process.poll() is not None or self._state == "failed":
                    raise RuntimeUnavailable(self._exit_message(f"cosyvoice-cli exited during {operation}"))
                remaining = deadline - monotonic()
                if remaining <= 0:
                    self._last_error = self._diagnostic_message(
                        f"cosyvoice-cli timed out during {operation}",
                        self._output,
                    )
                    raise RuntimeTimedOut(self._last_error)
                self._condition.wait(min(remaining, 0.25))
            return self._output

    def _read_output(self, process: Any) -> None:
        decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        try:
            while True:
                chunk = process.stdout.read(1)
                if not chunk:
                    break
                text = decoder.decode(chunk)
                if text:
                    with self._condition:
                        self._output = (self._output + text)[-self._MAX_DIAGNOSTIC_CHARS :]
                        if self._output == "> " or self._output.endswith("\n> "):
                            self._prompt_count += 1
                        self._condition.notify_all()
        except Exception as error:
            with self._condition:
                if self._state not in {"stopping", "stopped"}:
                    self._last_error = f"cosyvoice-cli output reader failed: {type(error).__name__}"
        finally:
            try:
                exit_code = process.wait(timeout=0.2)
            except Exception:
                exit_code = process.poll()
            with self._condition:
                if self._process is process and self._state not in {"stopping", "stopped"}:
                    self._state = "failed"
                    self._last_error = self._diagnostic_message(
                        f"cosyvoice-cli exited unexpectedly with code {exit_code}",
                        self._output,
                    )
                self._condition.notify_all()

    def _stop_locked(self) -> None:
        self._terminate_locked("stopped")

    def _terminate_locked(self, final_state: str) -> None:
        process = self._process
        if process is None:
            with self._condition:
                self._state = final_state
                self._current_speed = None
            return
        with self._condition:
            self._state = "stopping"
        if process.poll() is None:
            try:
                if process.stdin is not None:
                    process.stdin.write(b"/exit\n")
                    process.stdin.flush()
                process.wait(timeout=2.0)
            except Exception:
                try:
                    process.terminate()
                    process.wait(timeout=2.0)
                except Exception:
                    try:
                        process.kill()
                    except Exception:
                        pass
        with self._condition:
            self._process = None
            self._current_speed = None
            self._state = final_state
            self._condition.notify_all()

    def _allocate_output_path(self) -> Path:
        directory = self.config.output_directory
        if directory is not None:
            directory.mkdir(parents=True, exist_ok=True)
        handle, name = tempfile.mkstemp(
            prefix="aurora_voice_node_",
            suffix=".wav",
            dir=str(directory) if directory is not None else None,
        )
        os.close(handle)
        path = Path(name)
        path.unlink(missing_ok=True)
        return path

    def _is_running(self) -> bool:
        process = self._process
        return process is not None and process.poll() is None and self._state in {"starting", "ready"}

    def _exit_message(self, prefix: str) -> str:
        process = self._process
        exit_code = process.poll() if process is not None else None
        detail = f"{prefix}; exit_code={exit_code}"
        return self._diagnostic_message(detail, self._output)

    @staticmethod
    def _diagnostic_message(prefix: str, output: str) -> str:
        tail = " ".join(output.strip().split())[-1000:]
        return f"{prefix}: {tail}" if tail else prefix

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
        if normalized.startswith("/"):
            raise ValueError("text must not begin with '/' in interactive mode")
        return normalized
