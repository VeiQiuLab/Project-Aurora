"""Recorder that consumes frames from the shared audio pipeline."""

from __future__ import annotations

from pathlib import Path
from array import array
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
        max_duration_ms: int = 180000,
        silence_end_threshold_ms: int = 800,
        activity_rms_threshold: float = 0.014,
        activity_peak_threshold: float | None = 0.03,
        read_timeout_seconds: float = 0.1,
    ):
        if not isinstance(reader, AudioFrameReader):
            raise TypeError("reader must be an AudioFrameReader")
        if min_duration_ms < 0 or max_duration_ms <= 0 or silence_end_threshold_ms <= 0:
            raise ValueError("invalid recorder duration configuration")
        self.reader = reader
        self.output_dir = Path(output_dir) if output_dir else None
        self.min_duration_ms = int(min_duration_ms)
        self.max_duration_ms = int(max_duration_ms)
        self.silence_end_threshold_ms = int(silence_end_threshold_ms)
        self.activity_rms_threshold = max(float(activity_rms_threshold), 0.0)
        self.activity_peak_threshold = (
            None if activity_peak_threshold is None else max(float(activity_peak_threshold), 0.0)
        )
        self.read_timeout_seconds = max(float(read_timeout_seconds), 0.01)
        self._lock = RLock()
        self._stop_event = Event()
        self._thread: Thread | None = None
        self._recording = False
        self._cancelled = False
        self._timed_out = False
        self._completed = False
        self._stop_reason = "manual_stop"
        self._silence_detected_time_ms: int | None = None
        self._started_at: float | None = None
        self._frames: list[AudioFrame] = []

    @property
    def recording(self) -> bool:
        with self._lock:
            return self._recording

    @property
    def completed(self) -> bool:
        """Whether the recorder reached an automatic stop condition."""

        with self._lock:
            return self._completed

    def start(self) -> None:
        with self._lock:
            if self._recording:
                raise RuntimeError("frame recording is already active")
            self._stop_event.clear()
            self._cancelled = False
            self._timed_out = False
            self._completed = False
            self._stop_reason = "manual_stop"
            self._silence_detected_time_ms = None
            self._started_at = time.monotonic()
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
            if (
                self._started_at is not None
                and (time.monotonic() - self._started_at) * 1000 >= self.max_duration_ms
            ):
                self._timed_out = True
                self._stop_reason = "maximum_recording_duration"
        self.reader.close()
        if thread is not None:
            thread.join(timeout=5)
        with self._lock:
            frames = list(self._frames)
            timed_out = self._timed_out
            stop_reason = self._stop_reason
            silence_detected_time_ms = self._silence_detected_time_ms
            self._recording = False
            self._thread = None
        return self._write_audio(
            frames,
            timed_out=timed_out,
            stop_reason=stop_reason,
            silence_detected_time_ms=silence_detected_time_ms,
        )

    def cancel(self) -> None:
        with self._lock:
            if not self._recording:
                return
            self._cancelled = True
            self._stop_event.set()
            self._stop_reason = "cancelled"
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
        last_active_at = started
        try:
            while not self._stop_event.is_set():
                now = time.monotonic()
                elapsed_ms = int((now - started) * 1000)
                if elapsed_ms >= self.max_duration_ms:
                    with self._lock:
                        self._timed_out = True
                        self._stop_reason = "maximum_recording_duration"
                        self._completed = True
                    self._stop_event.set()
                    break
                frame = self.reader.read_frame(self._stop_event, self.read_timeout_seconds)
                if frame is None:
                    now = time.monotonic()
                    if (now - last_active_at) * 1000 >= self.silence_end_threshold_ms:
                        with self._lock:
                            self._stop_reason = "silence_detected"
                            self._silence_detected_time_ms = int((now - started) * 1000)
                            self._completed = True
                        self._stop_event.set()
                    continue
                if self._is_active(frame.data):
                    last_active_at = time.monotonic()
                with self._lock:
                    if self._frames and frame.sequence <= self._frames[-1].sequence:
                        continue
                    self._frames.append(frame)
                if (time.monotonic() - last_active_at) * 1000 >= self.silence_end_threshold_ms:
                    now = time.monotonic()
                    with self._lock:
                        self._stop_reason = "silence_detected"
                        self._silence_detected_time_ms = int((now - started) * 1000)
                        self._completed = True
                    self._stop_event.set()
        finally:
            return

    def _write_audio(
        self,
        frames: list[AudioFrame],
        *,
        timed_out: bool,
        stop_reason: str,
        silence_detected_time_ms: int | None,
    ) -> AudioInput:
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
                "recording_duration": duration_ms,
                "recording_duration_ms": duration_ms,
                "silence_detected_time": silence_detected_time_ms,
                "silence_detected_time_ms": silence_detected_time_ms,
                "stop_reason": stop_reason,
                "maximum_recording_duration_ms": self.max_duration_ms,
                "silence_end_threshold_ms": self.silence_end_threshold_ms,
            },
        )

    def _is_active(self, data: bytes) -> bool:
        samples = array("h")
        usable = len(data) - (len(data) % 2)
        samples.frombytes(data[:usable])
        if not samples:
            return False
        normalized = (sample / 32768.0 for sample in samples)
        total = 0.0
        peak = 0.0
        count = 0
        for value in normalized:
            total += value * value
            peak = max(peak, abs(value))
            count += 1
        rms = (total / count) ** 0.5 if count else 0.0
        return rms >= self.activity_rms_threshold or (
            self.activity_peak_threshold is not None and peak >= self.activity_peak_threshold
        )
