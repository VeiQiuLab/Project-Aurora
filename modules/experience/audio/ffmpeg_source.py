"""FFmpeg DirectShow producer for the shared audio-frame pipeline."""

from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
from threading import Event, RLock, Thread
from time import time
from typing import Callable, Sequence

from modules.logger import logger
from modules.experience.subprocess_utils import with_hidden_console

from .frame_pipeline import AudioFrameBuffer


class FFmpegAudioFrameSource:
    """Read raw PCM from FFmpeg and publish frames to one AudioFrameBuffer."""

    def __init__(
        self,
        *,
        device_name: str,
        buffer: AudioFrameBuffer,
        sample_rate: int = 16000,
        channels: int = 1,
        frame_duration_ms: int = 20,
        ffmpeg_path: str = "ffmpeg",
        popen_factory=None,
    ):
        if not device_name or not isinstance(buffer, AudioFrameBuffer):
            raise ValueError("device_name and AudioFrameBuffer are required")
        if sample_rate <= 0 or channels <= 0 or frame_duration_ms <= 0:
            raise ValueError("invalid audio frame configuration")
        self.device_name = str(device_name)
        self.buffer = buffer
        self.sample_rate = int(sample_rate)
        self.channels = int(channels)
        self.frame_duration_ms = int(frame_duration_ms)
        self.ffmpeg_path = ffmpeg_path
        self._popen_factory = popen_factory or subprocess.Popen
        self._process = None
        self._thread: Thread | None = None
        self._stop_event = Event()
        self._lock = RLock()
        self._last_error: Exception | None = None

    @property
    def running(self) -> bool:
        with self._lock:
            return self._process is not None

    @property
    def last_error(self) -> Exception | None:
        return self._last_error

    def start(self) -> None:
        logger.info(
            f"FFmpegAudioFrameSource.start called device={self.device_name!r} "
            f"sample_rate={self.sample_rate} channels={self.channels}"
        )
        with self._lock:
            if self._process is not None:
                raise RuntimeError("FFmpeg audio source is already running")
            executable = shutil.which(self.ffmpeg_path) or self.ffmpeg_path
            if shutil.which(self.ffmpeg_path) is None and not Path(self.ffmpeg_path).exists():
                raise RuntimeError("ffmpeg is required for DirectShow audio input")
            command = [
                executable,
                "-hide_banner",
                "-loglevel",
                "error",
                "-f",
                "dshow",
                "-i",
                f"audio={self.device_name}",
                "-f",
                "s16le",
                "-ar",
                str(self.sample_rate),
                "-ac",
                str(self.channels),
                "-",
            ]
            command_line = subprocess.list2cmdline(command)
            logger.info(f"FFmpegAudioFrameSource command={command_line}")
            self._stop_event.clear()
            self._last_error = None
            try:
                self._process = self._popen_factory(
                    command,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    **with_hidden_console(),
                )
            except Exception:
                logger.exception(
                    f"FFmpegAudioFrameSource process creation failed command={command_line}"
                )
                raise
            logger.info(
                f"FFmpegAudioFrameSource process created pid={getattr(self._process, 'pid', None)}"
            )
            self._thread = Thread(target=self._pump, name="aurora-ffmpeg-frames", daemon=True)
            self._thread.start()
        logger.info("FFmpegAudioFrameSource.start returned successfully")

    def stop(self) -> None:
        with self._lock:
            process = self._process
            thread = self._thread
            if process is None:
                return
            self._stop_event.set()
        try:
            process.terminate()
            process.wait(timeout=5)
        except Exception:
            try:
                process.kill()
            except Exception:
                pass
        if thread is not None:
            thread.join(timeout=5)
        with self._lock:
            self._process = None
            self._thread = None

    cancel = stop

    def _pump(self) -> None:
        process = self._process
        if process is None or process.stdout is None:
            logger.warning("FFmpegAudioFrameSource pump not started: stdout unavailable")
            return
        frame_bytes = int(self.sample_rate * self.channels * 2 * self.frame_duration_ms / 1000)
        total_bytes = 0
        audio_frames = 0
        logger.info(
            f"FFmpegAudioFrameSource pump loop entered frame_bytes={frame_bytes}"
        )
        try:
            while not self._stop_event.is_set():
                data = process.stdout.read(frame_bytes)
                if not data:
                    logger.warning(
                        f"FFmpegAudioFrameSource read ended bytes={total_bytes} "
                        f"audio_frames={audio_frames} returncode={process.poll()} "
                        f"stderr={self._stderr_text(process)!r}"
                    )
                    break
                total_bytes += len(data)
                if total_bytes == len(data) or audio_frames % 50 == 0:
                    logger.info(
                        f"FFmpegAudioFrameSource read bytes={len(data)} "
                        f"total_bytes={total_bytes} audio_frames={audio_frames}"
                    )
                if len(data) < frame_bytes:
                    logger.warning(
                        f"FFmpegAudioFrameSource partial frame bytes={len(data)} "
                        f"expected={frame_bytes} total_bytes={total_bytes}"
                    )
                    break
                self.buffer.publish(
                    data,
                    timestamp=time(),
                    sample_rate=self.sample_rate,
                    channels=self.channels,
                    diagnostics={
                        "source": "ffmpeg.dshow",
                        "frame_duration_ms": self.frame_duration_ms,
                    },
                )
                audio_frames += 1
                if audio_frames == 1 or audio_frames % 50 == 0:
                    logger.info(
                        f"FFmpegAudioFrameSource published audio_frames={audio_frames} "
                        f"total_bytes={total_bytes}"
                    )
        except Exception as error:
            self._last_error = error
            logger.exception(
                f"FFmpegAudioFrameSource pump failed bytes={total_bytes} "
                f"audio_frames={audio_frames} stderr={self._stderr_text(process)!r}"
            )

    @staticmethod
    def _stderr_text(process) -> str:
        if process is None or process.stderr is None or process.poll() is None:
            return "<unavailable: process still running>"
        try:
            data = process.stderr.read()
            if isinstance(data, bytes):
                return data.decode(errors="replace").strip()
            return str(data).strip()
        except Exception as error:
            return f"<stderr read failed: {error}>"


class FakeFFmpegAudioFrameSource:
    """Deterministic producer for frame-pipeline tests."""

    def __init__(self, buffer: AudioFrameBuffer, frames: Sequence[bytes]):
        self.buffer = buffer
        self.frames = list(frames)
        self.started = 0
        self.stopped = 0

    def start(self) -> None:
        self.started += 1
        for frame in self.frames:
            self.buffer.publish(frame, diagnostics={"source": "fake.ffmpeg"})

    def stop(self) -> None:
        self.stopped += 1

    cancel = stop
