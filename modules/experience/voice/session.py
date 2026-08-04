"""Controlled, user-started voice session coordination."""

from __future__ import annotations

from dataclasses import dataclass, field
from threading import Event, RLock, Thread
from time import monotonic, sleep
from typing import Callable, Mapping

from modules.diagnostics import create_diagnostics
from modules.experience.state import CompanionState, CompanionStateStore
from modules.logger import logger
from modules.experience.audio.frame_pipeline import AudioFrameBuffer
from modules.experience.audio.frame_recorder import FrameRecorder
from modules.experience.audio.vad import VADAdapter
from modules.experience.voice.models import AudioInput

from .orchestrator import VoiceOrchestrationResult


VoiceWaiter = Callable[[Event, float], bool]
SessionCycle = Callable[[], VoiceOrchestrationResult]
CleanupCallback = Callable[[], None]
PipelineOrchestratorFactory = Callable[["CapturedAudioRecorder"], object]


@dataclass(frozen=True)
class VoiceSessionResult:
    """Final result and diagnostics for one user-started voice session."""

    completed: bool
    cancelled: bool = False
    reason: str = ""
    diagnostics: Mapping[str, object] = field(default_factory=dict)


class VoiceSessionManager:
    """Keep a finite voice session alive without owning audio or Core logic."""

    def __init__(
        self,
        *,
        state_store: CompanionStateStore,
        wait_for_voice: VoiceWaiter | None = None,
        run_cycle: SessionCycle | None = None,
        cleanup_microphone: CleanupCallback | None = None,
        inactivity_timeout_seconds: float = 180.0,
        wait_slice_seconds: float = 1.0,
        vad_adapter: VADAdapter | None = None,
        audio_buffer: AudioFrameBuffer | None = None,
        audio_source=None,
        orchestrator_factory: PipelineOrchestratorFactory | None = None,
        frame_recorder_factory=None,
        pre_roll_ms: int = 500,
        maximum_recording_duration_seconds: float = 180.0,
        silence_end_threshold_seconds: float = 10.0,
        recording_window_seconds: float | None = None,
    ):
        pipeline_mode = vad_adapter is not None
        if (not pipeline_mode and not callable(wait_for_voice)) or (not callable(run_cycle) and not pipeline_mode):
            raise TypeError("wait_for_voice and run_cycle must be callable")
        if pipeline_mode and (not isinstance(audio_buffer, AudioFrameBuffer) or not callable(orchestrator_factory)):
            raise TypeError("pipeline mode requires audio_buffer and orchestrator_factory")
        self.state_store = state_store
        self.wait_for_voice = wait_for_voice
        self.run_cycle = run_cycle
        self.cleanup_microphone = cleanup_microphone
        self.inactivity_timeout_seconds = max(float(inactivity_timeout_seconds), 0.0)
        self.wait_slice_seconds = max(float(wait_slice_seconds), 0.01)
        self.vad_adapter = vad_adapter
        self.audio_buffer = audio_buffer
        self.audio_source = audio_source
        self.orchestrator_factory = orchestrator_factory
        self.pre_roll_ms = max(int(pre_roll_ms), 0)
        self.maximum_recording_duration_seconds = max(float(maximum_recording_duration_seconds), 0.1)
        self.silence_end_threshold_seconds = max(float(silence_end_threshold_seconds), 0.1)
        self.recording_window_seconds = (
            max(float(recording_window_seconds), 0.1)
            if recording_window_seconds is not None
            else None
        )
        if frame_recorder_factory is None:
            self.frame_recorder_factory = lambda reader: FrameRecorder(
                reader,
                max_duration_ms=int(self.maximum_recording_duration_seconds * 1000),
                silence_end_threshold_ms=int(self.silence_end_threshold_seconds * 1000),
            )
        else:
            self.frame_recorder_factory = frame_recorder_factory
        self._lock = RLock()
        self._cancel_event = Event()
        self._running = False
        self._thread: Thread | None = None
        self._last_result: VoiceSessionResult | None = None

    @property
    def session_running(self) -> bool:
        with self._lock:
            return self._running

    @property
    def last_result(self) -> VoiceSessionResult | None:
        with self._lock:
            return self._last_result

    def start_session(self) -> bool:
        logger.info(
            f"VoiceSessionManager.start_session time={monotonic():.3f} "
            f"current_state={self.state_store.current_state.value}"
        )
        with self._lock:
            if self._running:
                return False
            transition = self.state_store.transition(
                CompanionState.VOICE_READY,
                reason="voice_session_started",
                source="voice_session_manager",
            )
            if not transition.success:
                logger.warning(
                    f"VoiceSessionManager VOICE_READY transition failed: "
                    f"{transition.diagnostics}"
                )
                return False
            logger.info(
                f"VoiceSessionManager state transition completed "
                f"state={self.state_store.current_state.value}"
            )
            self._cancel_event.clear()
            self._last_result = None
            self._running = True
            self._thread = Thread(target=self._run, name="aurora-voice-session", daemon=True)
            thread = self._thread
        try:
            if self.vad_adapter is not None and self.audio_source is not None:
                logger.info("VoiceSessionManager audio_source.start called")
                self.audio_source.start()
                logger.info("VoiceSessionManager audio_source.start returned successfully")
            thread.start()
        except Exception:
            with self._lock:
                self._running = False
            self.state_store.force_idle(reason="voice_session_start_failed", source="voice_session_manager")
            raise
        return True

    def cancel_session(self) -> bool:
        with self._lock:
            if not self._running:
                return False
            self._cancel_event.set()
        self._cleanup()
        return True

    def _run(self) -> None:
        started_at = monotonic()
        last_valid_input_at = started_at
        cycles = 0
        valid_inputs = 0
        pipeline_metrics = []
        reason = "completed"
        cancelled = False
        try:
            while not self._cancel_event.is_set():
                remaining = self.inactivity_timeout_seconds - (monotonic() - last_valid_input_at)
                if remaining <= 0:
                    reason = "inactivity_timeout"
                    break
                wait_started = monotonic()
                detected = self.vad_adapter.wait_for_voice(
                    self._cancel_event, min(self.wait_slice_seconds, remaining)
                ) if self.vad_adapter is not None else self.wait_for_voice(
                    self._cancel_event, min(self.wait_slice_seconds, remaining)
                )
                vad_latency_ms = int((monotonic() - wait_started) * 1000)
                if self._cancel_event.is_set():
                    cancelled = True
                    reason = "cancelled"
                    break
                if not detected:
                    continue
                cycles += 1
                cycle_result, cycle_metrics = self._run_pipeline_cycle(vad_latency_ms) if self.vad_adapter is not None else (self.run_cycle(), {})
                pipeline_metrics.append(cycle_metrics)
                if cycle_result.transcription is not None and cycle_result.transcription.text.strip():
                    valid_inputs += 1
                    last_valid_input_at = monotonic()
                if cycle_result.cancelled:
                    cancelled = True
                    reason = "cancelled"
                    break
                self.state_store.force_idle(reason="voice_turn_finished", source="voice_session_manager")
                if self._cancel_event.is_set():
                    cancelled = True
                    reason = "cancelled"
                    break
                self.state_store.transition(
                    CompanionState.VOICE_READY,
                    reason="voice_session_waiting",
                    source="voice_session_manager",
                )
        except Exception as error:
            reason = "session_failed"
            self.state_store.transition(CompanionState.ERROR, reason=reason, source="voice_session_manager")
            self.state_store.force_idle(reason=reason, source="voice_session_manager")
        finally:
            self._cleanup()
            self.state_store.force_idle(reason=reason, source="voice_session_manager")
            diagnostics = create_diagnostics(
                stage="experience.voice.session",
                success=reason in {"completed", "inactivity_timeout", "cancelled"},
                reason=reason,
                metrics={
                    "session_duration_ms": int((monotonic() - started_at) * 1000),
                    "inactivity_timeout_seconds": self.inactivity_timeout_seconds,
                    "cycles": cycles,
                    "valid_inputs": valid_inputs,
                    "pipeline_cycles": pipeline_metrics,
                },
            )
            with self._lock:
                self._last_result = VoiceSessionResult(
                    completed=reason in {"completed", "inactivity_timeout"},
                    cancelled=cancelled,
                    reason=reason,
                    diagnostics=diagnostics,
                )
                self._running = False
                self._thread = None

    def _cleanup(self) -> None:
        if self.vad_adapter is not None:
            try:
                self.vad_adapter.close()
            except Exception:
                pass
        if self.audio_source is not None:
            try:
                self.audio_source.stop()
            except Exception:
                pass
        if callable(self.cleanup_microphone):
            try:
                self.cleanup_microphone()
            except Exception:
                return

    def _run_pipeline_cycle(self, vad_latency_ms: int):
        reader = self.audio_buffer.subscribe(pre_roll_ms=self.pre_roll_ms)
        recorder = self.frame_recorder_factory(reader)
        recorder.start()
        deadline = monotonic() + (
            self.recording_window_seconds
            if self.recording_window_seconds is not None
            else self.maximum_recording_duration_seconds
        )
        while (
            not self._cancel_event.is_set()
            and recorder.recording
            and not recorder.completed
            and monotonic() < deadline
        ):
            sleep(0.05)
        if self._cancel_event.is_set():
            recorder.cancel()
            return VoiceOrchestrationResult(success=False, cancelled=True, stage="cancelled"), {
                "vad_latency_ms": vad_latency_ms,
            }
        audio_input = recorder.stop()
        orchestrator = self.orchestrator_factory(_CapturedAudioRecorder(audio_input))
        result = orchestrator.run()
        return result, {
            "vad_latency_ms": vad_latency_ms,
            "recording_duration_ms": audio_input.duration_ms,
            "recording_duration": audio_input.diagnostics.get("recording_duration", audio_input.duration_ms),
            "silence_detected_time": audio_input.diagnostics.get("silence_detected_time"),
            "stop_reason": audio_input.diagnostics.get("stop_reason", "manual_stop"),
            "frame_count": audio_input.diagnostics.get("frame_count", 0),
            "pre_roll_frames": audio_input.diagnostics.get("pre_roll_frames", 0),
        }


class _CapturedAudioRecorder:
    """Adapter that gives an existing Orchestrator one already-recorded input."""

    def __init__(self, audio_input: AudioInput):
        self.audio_input = audio_input

    def start(self) -> None:
        return None

    def stop(self) -> AudioInput:
        return self.audio_input

    def cancel(self) -> None:
        return None
