"""Shared audio-frame fan-out and pre-roll buffering primitives."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections import deque
from dataclasses import dataclass, field
from threading import Condition, Event, RLock
from time import time
from typing import Mapping

from modules.logger import logger


@dataclass(frozen=True)
class AudioFrame:
    """One immutable PCM frame shared by audio consumers."""

    data: bytes
    timestamp: float = field(default_factory=time)
    sample_rate: int = 16000
    channels: int = 1
    sequence: int = 0
    diagnostics: Mapping[str, object] = field(default_factory=dict)


class AudioFrameSource(ABC):
    """Read frames without opening or owning a microphone device."""

    @abstractmethod
    def read_frame(self, cancel_event: Event, timeout_seconds: float) -> AudioFrame | None:
        """Return the next frame, or None when the read times out."""

    def close(self) -> None:
        """Release this consumer subscription."""


class AudioFrameReader(AudioFrameSource):
    """Independent consumer cursor attached to an AudioFrameBuffer."""

    def __init__(self, buffer: "AudioFrameBuffer", frames: list[AudioFrame]):
        self._buffer = buffer
        self._condition = Condition(RLock())
        self._frames = deque(frames)
        self._closed = False

    def read_frame(self, cancel_event: Event, timeout_seconds: float) -> AudioFrame | None:
        deadline = time() + max(float(timeout_seconds), 0.0)
        with self._condition:
            while not self._frames and not self._closed and not cancel_event.is_set():
                remaining = deadline - time()
                if remaining <= 0:
                    return None
                self._condition.wait(remaining)
            if self._frames:
                return self._frames.popleft()
            return None

    def _push(self, frame: AudioFrame) -> None:
        with self._condition:
            if not self._closed:
                self._frames.append(frame)
                self._condition.notify()

    def close(self) -> None:
        self._buffer._unsubscribe(self)
        with self._condition:
            self._closed = True
            self._condition.notify_all()


class AudioFrameBuffer:
    """Bounded pre-roll buffer that fans each frame out to subscribers."""

    def __init__(self, *, max_duration_ms: int = 1000):
        if max_duration_ms <= 0:
            raise ValueError("max_duration_ms must be positive")
        self.max_duration_ms = int(max_duration_ms)
        self._frames: deque[AudioFrame] = deque()
        self._subscribers: list[AudioFrameReader] = []
        self._sequence = 0
        self._lock = RLock()

    def publish(
        self,
        data: bytes,
        *,
        timestamp: float | None = None,
        sample_rate: int = 16000,
        channels: int = 1,
        diagnostics: Mapping[str, object] | None = None,
    ) -> AudioFrame:
        if not isinstance(data, bytes):
            raise TypeError("audio frame data must be bytes")
        with self._lock:
            self._sequence += 1
            frame = AudioFrame(
                data=data,
                timestamp=time() if timestamp is None else float(timestamp),
                sample_rate=sample_rate,
                channels=channels,
                sequence=self._sequence,
                diagnostics=dict(diagnostics or {}),
            )
            if self._sequence == 1:
                logger.info(f"AudioFrameBuffer first_frame_time={frame.timestamp:.6f}")
            if self._sequence == 1 or self._sequence % 50 == 0:
                logger.info(
                    f"AudioFrameBuffer publish called cumulative_frames={self._sequence} "
                    f"bytes={len(data)}"
                )
            self._frames.append(frame)
            self._trim_locked()
            subscribers = tuple(self._subscribers)
        for subscriber in subscribers:
            subscriber._push(frame)
        return frame

    def subscribe(self, *, pre_roll_ms: int = 0) -> AudioFrameReader:
        with self._lock:
            if pre_roll_ms < 0:
                raise ValueError("pre_roll_ms must not be negative")
            newest = self._frames[-1].timestamp if self._frames else time()
            cutoff = newest - (pre_roll_ms / 1000.0)
            initial = [frame for frame in self._frames if frame.timestamp >= cutoff]
            reader = AudioFrameReader(self, initial)
            self._subscribers.append(reader)
            return reader

    def snapshot(self) -> tuple[AudioFrame, ...]:
        with self._lock:
            return tuple(self._frames)

    def _unsubscribe(self, reader: AudioFrameReader) -> None:
        with self._lock:
            if reader in self._subscribers:
                self._subscribers.remove(reader)

    def _trim_locked(self) -> None:
        if not self._frames:
            return
        cutoff = self._frames[-1].timestamp - (self.max_duration_ms / 1000.0)
        while len(self._frames) > 1 and self._frames[0].timestamp < cutoff:
            self._frames.popleft()
