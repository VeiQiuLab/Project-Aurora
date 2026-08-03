"""Recorder that consumes frames from the shared audio pipeline."""

from __future__ import annotations

from pathlib import Path
from threading import Event, RLock, Thread
import tempfile
import time
import wave

from modules.experience.voice.models import AudioInput

from .frame_pipeline import AudioFrame, AudioFrameReader


class FrameRecorder:
    """Collect ordered AudioFrame values and write one temporary WAV file."""

    def __init__(
        self,
        reader: AudioFrameReader,
        *,
        output_dir: str | Path | None = None,
        min_duration_ms: int = 750,
        max_duration_ms: int = 30000,
        read_timeout_seconds: float = 0.1,
    ):
        if not isinstance(reader, AudioFrameReader):
            raise TypeError("reader must be an AudioFrameReader")
        if min_duration_ms < 0 or max_duration_ms <= 0:
            raise ValueError("invalid recorder duration configuration")
        self.reader = reader
        self.output_dir = Path(output_dir) if output_dir else None
        self.min_duration_ms = int(min_duration_ms)
        self.max_duration_ms = int(max_duration_ms)
        self.read_timeout_seconds = max(float(read_timeout_seconds), 0.01)
        self._lock = RLock()
        self._stop_event = Event()
        self._thread: Thread | None = None
        self._recording = False
        self._cancelled = False
        self._timed_out = False
        self._frames: list[AudioFrame] = []

    @property
    def recording(self) -> bool:
        with self._lock:
            return self._recording

    def start(self) -> None:
        with self._lock:
            if self._recording:
                raise RuntimeError("frame recording is already active")
            self._stop_event.clear()
            self._cancelled = False
            self._timed_out = False
            self._frames = []
            self._recording = True
            self._thread = Thread(target=self._collect, name="aurora-frame-recorder", daemon=True)
            self._thread.start()

    def stop(self) -> AudioInput:
        with self._lock:
            if not self._recording:
                raise RuntimeError("frame recording is not active")
            thread = self._thread
            self._stop_event.set()
        self.reader.close()
        if thread is not None:
            thread.join(timeout=5)
        with self._lock:
            frames = list(self._frames)
            timed_out = self._timed_out
            self._recording = False
            self._thread = None
        return self._write_audio(frames, timed_out=timed_out)

    def cancel(self) -> None:
        with self._lock:
            if not self._recording:
                return
            self._cancelled = True
            self._stop_event.set()
            thread = self._thread
            self._recording = False
            self._thread = None
        self.reader.close()
        if thread is not None:
            thread.join(timeout=5)
        with self._lock:
            self._frames = []

    def _collect(self) -> None:
        started = time.monotonic()
        try:
            while not self._stop_event.is_set():
                if (time.monotonic() - started) * 1000 >= self.max_duration_ms:
                    self._timed_out = True
                    self._stop_event.set()
                    break
                frame = self.reader.read_frame(self._stop_event, self.read_timeout_seconds)
                if frame is None:
                    continue
                with self._lock:
                    if self._frames and frame.sequence <= self._frames[-1].sequence:
                        continue
                    self._frames.append(frame)
        finally:
            return

    def _write_audio(self, frames: list[AudioFrame], *, timed_out: bool) -> AudioInput:
        if not frames:
            raise RuntimeError("no audio frames were collected")
        sample_rate = frames[0].sample_rate
        channels = frames[0].channels
        if any(frame.sample_rate != sample_rate or frame.channels != channels for frame in frames):
            raise RuntimeError("audio frame format changed during recording")
        data = b"".join(frame.data for frame in frames)
        duration_ms = int(len(data) / (sample_rate * channels * 2) * 1000)
        if duration_ms < self.min_duration_ms:
            raise RuntimeError(f"frame recording is too short: {duration_ms}ms")
        self.output_dir and self.output_dir.mkdir(parents=True, exist_ok=True)
        handle = tempfile.NamedTemporaryFile(
            prefix="aurora-frame-recording-",
            suffix=".wav",
            dir=str(self.output_dir) if self.output_dir else None,
            delete=False,
        )
        path = Path(handle.name)
        try:
            with handle:
                with wave.open(handle, "wb") as wav_file:
                    wav_file.setnchannels(channels)
                    wav_file.setsampwidth(2)
                    wav_file.setframerate(sample_rate)
                    wav_file.writeframes(data)
        except Exception:
            path.unlink(missing_ok=True)
            raise
        return AudioInput(
            kind="file",
            path=str(path),
            sample_rate=sample_rate,
            duration_ms=duration_ms,
            diagnostics={
                "success": True,
                "audio_path": str(path),
                "sample_rate": sample_rate,
                "channels": channels,
                "frame_count": len(frames),
                "first_sequence": frames[0].sequence,
                "last_sequence": frames[-1].sequence,
                "pre_roll_frames": sum(1 for frame in frames if frame.diagnostics.get("pre_roll")),
                "timed_out": timed_out,
            },
        )
