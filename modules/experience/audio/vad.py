"""Low-dependency voice activity detection boundaries."""

from __future__ import annotations

from abc import ABC, abstractmethod
from array import array
from dataclasses import dataclass, field
from enum import Enum
from threading import Event, RLock
from time import monotonic, time
from typing import Callable, Mapping, Sequence

from modules.diagnostics import create_diagnostics

from .frame_pipeline import AudioFrame, AudioFrameSource


class VoiceActivityType(str, Enum):
    STARTED = "VOICE_STARTED"
    CONTINUED = "VOICE_CONTINUED"
    STOPPED = "VOICE_STOPPED"
    ERROR = "VOICE_ERROR"


@dataclass(frozen=True)
class VoiceActivityEvent:
    active: bool
    event_type: VoiceActivityType
    confidence: float | None = None
    duration_ms: int = 0
    timestamp: float = field(default_factory=time)
    diagnostics: Mapping[str, object] = field(default_factory=dict)


class VADAdapterError(RuntimeError):
    """Controlled VAD source or processing failure."""

    def __init__(self, message: str, *, code: str = "vad_error"):
        super().__init__(message)
        self.code = code
        self.diagnostics = create_diagnostics(
            stage="experience.audio.vad",
            success=False,
            reason=code,
            trace={"message": message},
        )


class VADAdapter(ABC):
    """Detect voice activity without owning recording or application state."""

    @abstractmethod
    def wait_for_voice(self, cancel_event: Event, timeout_seconds: float) -> VoiceActivityEvent | None:
        """Wait for a voice-start event until timeout or cancellation."""

    def close(self) -> None:
        """Release the underlying frame source."""


class RMSVADAdapter(VADAdapter):
    """Detect voice from normalized PCM16 RMS energy."""

    def __init__(
        self,
        source: AudioFrameSource,
        *,
        threshold: float = 0.014,
        frame_duration_ms: int = 20,
        minimum_active_duration_ms: int = 100,
        start_threshold: float | None = None,
        stop_threshold: float | None = None,
        peak_threshold: float | None = 0.03,
    ):
        if not isinstance(source, AudioFrameSource):
            raise TypeError("source must be an AudioFrameSource")
        if threshold < 0 or frame_duration_ms <= 0 or minimum_active_duration_ms <= 0:
            raise ValueError("invalid RMS VAD configuration")
        self.source = source
        self.threshold = float(threshold)
        self.start_threshold = float(start_threshold if start_threshold is not None else threshold)
        self.stop_threshold = float(stop_threshold if stop_threshold is not None else self.start_threshold)
        self.peak_threshold = None if peak_threshold is None else float(peak_threshold)
        if self.start_threshold < 0 or self.stop_threshold < 0 or self.stop_threshold > self.start_threshold:
            raise ValueError("stop_threshold must be non-negative and no greater than start_threshold")
        if self.peak_threshold is not None and self.peak_threshold < 0:
            raise ValueError("peak_threshold must be non-negative")
        self.frame_duration_ms = int(frame_duration_ms)
        self.minimum_active_duration_ms = int(minimum_active_duration_ms)
        self.minimum_active_frames = max(
            1,
            (self.minimum_active_duration_ms + self.frame_duration_ms - 1) // self.frame_duration_ms,
        )
        self._diagnostic_lock = RLock()
        self._diagnostic_count = 0
        self._diagnostic_rms_min = None
        self._diagnostic_rms_max = 0.0
        self._diagnostic_rms_sum = 0.0
        self._diagnostic_peak_max = 0.0
        self._diagnostic_pcm_min = 0
        self._diagnostic_pcm_max = 0
        self._last_wait_diagnostics: Mapping[str, object] = {}

    @property
    def diagnostics(self) -> Mapping[str, object]:
        """Return read-only aggregate frame metrics without changing detection."""

        with self._diagnostic_lock:
            count = self._diagnostic_count
            return {
                "frame_count": count,
                "rms_min": self._diagnostic_rms_min or 0.0,
                "rms_max": self._diagnostic_rms_max,
                "rms_mean": self._diagnostic_rms_sum / count if count else 0.0,
                "peak_amplitude": self._diagnostic_peak_max,
                "pcm_min": self._diagnostic_pcm_min,
                "pcm_max": self._diagnostic_pcm_max,
                "threshold": self.threshold,
                "start_threshold": self.start_threshold,
                "stop_threshold": self.stop_threshold,
                "minimum_active_frames": self.minimum_active_frames,
                "peak_threshold": self.peak_threshold,
            }

    @property
    def last_wait_diagnostics(self) -> Mapping[str, object]:
        """Return diagnostics for the most recent wait without changing the API contract."""

        return dict(self._last_wait_diagnostics)

    def wait_for_voice(self, cancel_event: Event, timeout_seconds: float) -> VoiceActivityEvent | None:
        deadline = monotonic() + max(float(timeout_seconds), 0.0)
        active_ms = 0
        frames_checked = 0
        above_threshold_frames = 0
        max_rms = 0.0
        max_peak = 0.0
        while not cancel_event.is_set() and monotonic() < deadline:
            remaining = max(deadline - monotonic(), 0.0)
            try:
                frame = self.source.read_frame(cancel_event, remaining)
            except VADAdapterError:
                raise
            except Exception as error:
                raise VADAdapterError(str(error), code="frame_source_error") from error
            if frame is None:
                continue
            rms, peak, pcm_min, pcm_max = self._frame_stats(
                frame.data if isinstance(frame, AudioFrame) else frame
            )
            frames_checked += 1
            max_rms = max(max_rms, rms)
            max_peak = max(max_peak, peak)
            with self._diagnostic_lock:
                self._diagnostic_count += 1
                self._diagnostic_rms_min = rms if self._diagnostic_rms_min is None else min(self._diagnostic_rms_min, rms)
                self._diagnostic_rms_max = max(self._diagnostic_rms_max, rms)
                self._diagnostic_rms_sum += rms
                self._diagnostic_peak_max = max(self._diagnostic_peak_max, peak)
                self._diagnostic_pcm_min = min(self._diagnostic_pcm_min, pcm_min)
                self._diagnostic_pcm_max = max(self._diagnostic_pcm_max, pcm_max)
            candidate = rms >= self.start_threshold or (
                self.peak_threshold is not None and peak >= self.peak_threshold
            )
            if candidate:
                above_threshold_frames += 1
                active_ms += self.frame_duration_ms
                if active_ms >= self.minimum_active_frames * self.frame_duration_ms:
                    diagnostics = create_diagnostics(
                        stage="experience.audio.vad.rms",
                        success=True,
                        reason="voice_started",
                        metrics={"rms": rms, "peak_amplitude": peak, "pcm_min": pcm_min, "pcm_max": pcm_max, "frames_checked": frames_checked, "above_threshold_frames": above_threshold_frames, "max_rms": max_rms, "max_peak": max_peak, **self.diagnostics},
                    )
                    self._last_wait_diagnostics = diagnostics
                    return VoiceActivityEvent(
                        active=True,
                        event_type=VoiceActivityType.STARTED,
                        confidence=min(rms / max(self.threshold, 1e-9), 1.0),
                        duration_ms=active_ms,
                        diagnostics=diagnostics,
                    )
            else:
                active_ms = 0
        if cancel_event.is_set():
            return VoiceActivityEvent(
                active=False,
                event_type=VoiceActivityType.STOPPED,
                diagnostics=create_diagnostics(
                    stage="experience.audio.vad.rms", success=True, reason="cancelled"
                ),
            )
        self._last_wait_diagnostics = create_diagnostics(
            stage="experience.audio.vad.rms",
            success=False,
            reason="trigger_timeout",
            warnings=["insufficient_consecutive_frames"],
            metrics={
                "frames_checked": frames_checked,
                "above_threshold_frames": above_threshold_frames,
                "max_rms": max_rms,
                "max_peak": max_peak,
                "trigger_failure_reason": "insufficient_consecutive_frames",
                **self.diagnostics,
            },
        )
        return None

    def close(self) -> None:
        self.source.close()

    @staticmethod
    def _frame_stats(frame: bytes | Sequence[float]) -> tuple[float, float, int, int]:
        if isinstance(frame, bytes):
            samples = array("h")
            usable = len(frame) - (len(frame) % 2)
            samples.frombytes(frame[:usable])
            raw_values = list(samples)
            values = (sample / 32768.0 for sample in raw_values)
            pcm_min = min(raw_values) if raw_values else 0
            pcm_max = max(raw_values) if raw_values else 0
        else:
            raw_values = [float(sample) for sample in frame]
            values = iter(raw_values)
            pcm_min = min(raw_values) if raw_values else 0
            pcm_max = max(raw_values) if raw_values else 0
        total = 0.0
        count = 0
        peak = 0.0
        for value in values:
            total += value * value
            count += 1
            peak = max(peak, abs(value))
        return (total / count) ** 0.5 if count else 0.0, peak, int(pcm_min), int(pcm_max)

    @staticmethod
    def _rms(frame: bytes | Sequence[float]) -> float:
        return RMSVADAdapter._frame_stats(frame)[0]


class FakeVAD(VADAdapter):
    """Deterministic VAD for session tests."""

    def __init__(
        self,
        *,
        event: VoiceActivityEvent | None = None,
        timeout: bool = False,
        cancel: bool = False,
        error: Exception | None = None,
    ):
        self.event = event or VoiceActivityEvent(
            active=True,
            event_type=VoiceActivityType.STARTED,
            confidence=1.0,
            duration_ms=100,
        )
        self.timeout = timeout
        self.cancel = cancel
        self.error = error
        self.calls = 0

    def wait_for_voice(self, cancel_event: Event, timeout_seconds: float) -> VoiceActivityEvent | None:
        self.calls += 1
        if self.error is not None:
            raise self.error
        if self.cancel:
            cancel_event.set()
            return VoiceActivityEvent(False, VoiceActivityType.STOPPED)
        if self.timeout:
            return None
        return self.event
