"""Replaceable audio recording boundary."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from threading import RLock
import shutil
import subprocess
import tempfile
import time
import wave

from modules.experience.subprocess_utils import with_hidden_console
from modules.experience.voice.models import AudioInput


class AudioRecorder(ABC):
    """Record audio without knowing how it will later be transcribed."""

    @abstractmethod
    def start(self) -> None:
        """Begin recording from the configured audio source."""

    @abstractmethod
    def stop(self) -> AudioInput:
        """Stop recording and return the captured audio input."""

    @abstractmethod
    def cancel(self) -> None:
        """Cancel the current recording without returning audio."""


class AudioRecorderError(RuntimeError):
    """Recoverable microphone error with a stable diagnostic code."""

    def __init__(self, message: str, *, code: str):
        super().__init__(message)
        self.code = code
        self.diagnostics = {"success": False, "stage": "audio.recorder", "reason": code}


class MicrophoneRecorder(AudioRecorder):
    """Capture one push-to-talk recording and store it as a temporary WAV."""

    def __init__(
        self,
        *,
        sample_rate: int = 16000,
        channels: int = 1,
        dtype: str = "int16",
        output_dir: str | Path | None = None,
        device=None,
        audio_backend=None,
        min_duration_ms: int = 750,
        warmup_seconds: float = 0.15,
    ):
        if sample_rate <= 0 or channels <= 0:
            raise ValueError("sample_rate and channels must be positive")
        self.sample_rate = int(sample_rate)
        self.channels = int(channels)
        self.dtype = dtype
        self.output_dir = Path(output_dir) if output_dir else None
        self.device = device
        self.min_duration_ms = max(int(min_duration_ms), 0)
        self.warmup_seconds = max(float(warmup_seconds), 0.0)
        self._audio_backend = audio_backend
        self._recording = False
        self._stream = None
        self._chunks = []
        self._lock = RLock()

    def start(self) -> None:
        with self._lock:
            if self._recording:
                raise AudioRecorderError("recording is already active", code="already_recording")
            backend = self._backend()
            try:
                self._chunks = []
                self._stream = backend.InputStream(
                    samplerate=self.sample_rate,
                    channels=self.channels,
                    dtype=self.dtype,
                    device=self.device,
                    callback=self._on_audio,
                )
                self._stream.start()
                if self.warmup_seconds:
                    time.sleep(self.warmup_seconds)
            except Exception as error:
                self._stream = None
                raise AudioRecorderError(
                    f"microphone start failed: {error}", code="microphone_unavailable"
                ) from error
            self._recording = True

    def stop(self) -> AudioInput:
        with self._lock:
            if not self._recording:
                raise AudioRecorderError("recording is not active", code="not_recording")
            backend = self._backend()
            try:
                if self._stream is None:
                    raise AudioRecorderError("recording stream is unavailable", code="not_recording")
                self._stream.stop()
                self._stream.close()
                data = b"".join(chunk.tobytes() for chunk in self._chunks)
                path = self._write_wav(data)
                duration_ms = self._wav_duration_ms(path)
                if duration_ms < self.min_duration_ms:
                    path.unlink(missing_ok=True)
                    raise AudioRecorderError(
                        f"recording is too short: {duration_ms}ms",
                        code="recording_too_short",
                    )
            except AudioRecorderError:
                raise
            except Exception as error:
                raise AudioRecorderError(
                    f"microphone capture failed: {error}", code="capture_failed"
                ) from error
            finally:
                self._recording = False
                self._stream = None
                self._chunks = []
            return AudioInput(
                kind="microphone",
                path=str(path),
                sample_rate=self.sample_rate,
                duration_ms=duration_ms,
                diagnostics={"success": True, "sample_rate": self.sample_rate, "channels": self.channels, "audio_path": str(path)},
            )

    def cancel(self) -> None:
        with self._lock:
            if not self._recording:
                return
            try:
                if self._stream is not None:
                    self._stream.stop()
                    self._stream.close()
            except Exception as error:
                raise AudioRecorderError(
                    f"microphone cancel failed: {error}", code="cancel_failed"
                ) from error
            finally:
                self._recording = False
                self._stream = None
                self._chunks = []

    def _on_audio(self, indata, _frames, _time, _status) -> None:
        with self._lock:
            if self._recording:
                self._chunks.append(indata.copy())

    def _backend(self):
        if self._audio_backend is not None:
            return self._audio_backend
        try:
            import sounddevice
        except ImportError as error:
            raise AudioRecorderError(
                "sounddevice is required for microphone input", code="dependency_missing"
            ) from error
        self._audio_backend = sounddevice
        return self._audio_backend

    def _write_wav(self, data: bytes) -> Path:
        self.output_dir and self.output_dir.mkdir(parents=True, exist_ok=True)
        handle = tempfile.NamedTemporaryFile(
            prefix="aurora-recording-",
            suffix=".wav",
            dir=str(self.output_dir) if self.output_dir else None,
            delete=False,
        )
        path = Path(handle.name)
        try:
            with handle:
                with wave.open(handle, "wb") as wav_file:
                    wav_file.setnchannels(self.channels)
                    wav_file.setsampwidth(2 if self.dtype in {"int16", "short"} else 4)
                    wav_file.setframerate(self.sample_rate)
                    wav_file.writeframes(data)
        except Exception:
            path.unlink(missing_ok=True)
            raise
        return path

    @staticmethod
    def _wav_duration_ms(path: Path) -> int:
        with wave.open(str(path), "rb") as wav_file:
            rate = wav_file.getframerate()
            return int(wav_file.getnframes() * 1000 / rate) if rate else 0


class FFmpegMicrophoneRecorder(AudioRecorder):
    """Capture one Windows DirectShow microphone session through FFmpeg."""

    def __init__(
        self,
        *,
        device_name: str,
        sample_rate: int = 16000,
        channels: int = 1,
        output_dir: str | Path | None = None,
        ffmpeg_path: str = "ffmpeg",
        popen_factory=None,
        min_duration_ms: int = 750,
        tail_seconds: float = 0.15,
        warmup_seconds: float = 0.2,
    ):
        if not device_name or not str(device_name).strip():
            raise ValueError("device_name is required")
        if sample_rate <= 0 or channels <= 0:
            raise ValueError("sample_rate and channels must be positive")
        self.device_name = str(device_name).strip()
        self.sample_rate = int(sample_rate)
        self.channels = int(channels)
        self.output_dir = Path(output_dir) if output_dir else None
        self.ffmpeg_path = ffmpeg_path
        self.min_duration_ms = max(int(min_duration_ms), 0)
        self.tail_seconds = max(float(tail_seconds), 0.0)
        self.warmup_seconds = max(float(warmup_seconds), 0.0)
        self._popen_factory = popen_factory or subprocess.Popen
        self._process = None
        self._path = None
        self._lock = RLock()

    def start(self) -> None:
        with self._lock:
            if self._process is not None:
                raise AudioRecorderError("recording is already active", code="already_recording")
            executable = shutil.which(self.ffmpeg_path) or self.ffmpeg_path
            if shutil.which(self.ffmpeg_path) is None and not Path(self.ffmpeg_path).exists():
                raise AudioRecorderError(
                    "ffmpeg is required for DirectShow microphone input",
                    code="dependency_missing",
                )
            self.output_dir and self.output_dir.mkdir(parents=True, exist_ok=True)
            handle = tempfile.NamedTemporaryFile(
                prefix="aurora-ffmpeg-recording-",
                suffix=".wav",
                dir=str(self.output_dir) if self.output_dir else None,
                delete=False,
            )
            handle.close()
            self._path = Path(handle.name)
            command = [
                executable,
                "-hide_banner",
                "-loglevel",
                "error",
                "-f",
                "dshow",
                "-i",
                f"audio={self.device_name}",
                "-ac",
                str(self.channels),
                "-ar",
                str(self.sample_rate),
                "-y",
                str(self._path),
            ]
            try:
                self._process = self._popen_factory(
                    command,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    **with_hidden_console(),
                )
                if self.warmup_seconds:
                    time.sleep(self.warmup_seconds)
            except Exception as error:
                self._path.unlink(missing_ok=True)
                self._path = None
                raise AudioRecorderError(
                    f"ffmpeg recorder start failed: {error}", code="recorder_start_failed"
                ) from error

    def stop(self) -> AudioInput:
        with self._lock:
            if self._process is None or self._path is None:
                raise AudioRecorderError("recording is not active", code="not_recording")
            process = self._process
            path = self._path
            try:
                if self.tail_seconds:
                    time.sleep(self.tail_seconds)
                self._finish_process(process)
                if process.returncode not in (0, None):
                    error = self._stderr_text(process)
                    raise AudioRecorderError(
                        f"ffmpeg recording failed: {error}", code="capture_failed"
                    )
                wav_info = self._validate_wav(path)
                if wav_info["duration_ms"] < self.min_duration_ms:
                    raise AudioRecorderError(
                        f"recording is too short: {wav_info['duration_ms']}ms",
                        code="recording_too_short",
                    )
                return AudioInput(
                    kind="file",
                    path=str(path),
                    sample_rate=self.sample_rate,
                    duration_ms=wav_info["duration_ms"],
                    diagnostics={"success": True, **wav_info, "audio_path": str(path)},
                )
            except AudioRecorderError:
                path.unlink(missing_ok=True)
                raise
            finally:
                self._process = None
                self._path = None

    def cancel(self) -> None:
        with self._lock:
            process = self._process
            path = self._path
            if process is None:
                return
            try:
                process.terminate()
                process.wait(timeout=5)
            except Exception:
                try:
                    process.kill()
                except Exception:
                    pass
            finally:
                self._process = None
                self._path = None
                if path is not None:
                    path.unlink(missing_ok=True)

    @staticmethod
    def _finish_process(process) -> None:
        try:
            if process.stdin is not None:
                process.stdin.write(b"q\n")
                process.stdin.flush()
            process.wait(timeout=10)
        except Exception:
            process.terminate()
            process.wait(timeout=5)

    @staticmethod
    def _stderr_text(process) -> str:
        stderr = getattr(process, "stderr", None)
        if stderr is None:
            return "unknown error"
        try:
            value = stderr.read()
            return value.decode(errors="replace").strip() or "unknown error"
        except Exception:
            return "unknown error"

    @staticmethod
    def _validate_wav(path: Path) -> dict[str, int]:
        if not path.exists() or path.stat().st_size <= 44:
            raise AudioRecorderError("ffmpeg produced an empty WAV", code="empty_audio")
        try:
            with wave.open(str(path), "rb") as wav_file:
                if wav_file.getnframes() <= 0:
                    raise AudioRecorderError("ffmpeg produced no audio frames", code="empty_audio")
                rate = wav_file.getframerate()
                return {
                    "channels": wav_file.getnchannels(),
                    "sample_rate": rate,
                    "frames": wav_file.getnframes(),
                    "duration_ms": int(wav_file.getnframes() * 1000 / rate) if rate else 0,
                }
        except AudioRecorderError:
            raise
        except Exception as error:
            raise AudioRecorderError(
                f"invalid WAV from ffmpeg: {error}", code="invalid_audio"
            ) from error
