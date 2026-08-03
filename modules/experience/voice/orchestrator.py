"""Coordinate the optional voice pipeline without owning any core workflow."""

from __future__ import annotations

from dataclasses import dataclass, field
from threading import Event, RLock
from time import monotonic
from typing import Callable, Mapping

from modules.diagnostics import create_diagnostics
from modules.experience.audio.playback import (
    AudioPlaybackController,
    PlaybackEvent,
    PlaybackEventType,
)
from modules.experience.audio.recorder import AudioRecorder
from modules.experience.state import CompanionState, CompanionStateStore

from .interfaces import SpeechToTextProvider, TextToSpeechProvider
from .models import SpeechResult, TranscriptionResult


TextInputHandler = Callable[[str], str]


@dataclass(frozen=True)
class VoiceOrchestrationResult:
    """Detached result for a complete, failed, or cancelled voice run."""

    success: bool
    cancelled: bool = False
    stage: str = ""
    transcription: TranscriptionResult | None = None
    response_text: str | None = None
    speech: SpeechResult | None = None
    diagnostics: Mapping[str, object] = field(default_factory=dict)


class VoiceOrchestrator:
    """Coordinate recorder, providers, playback, and one shared state store."""

    def __init__(
        self,
        *,
        recorder: AudioRecorder,
        stt_provider: SpeechToTextProvider,
        tts_provider: TextToSpeechProvider,
        playback: AudioPlaybackController,
        state_store: CompanionStateStore,
        text_input_handler: TextInputHandler,
        wait_for_playback_completion: bool = False,
        playback_timeout_seconds: float = 120.0,
    ):
        self.recorder = recorder
        self.stt_provider = stt_provider
        self.tts_provider = tts_provider
        self.playback = playback
        self.state_store = state_store
        self.text_input_handler = text_input_handler
        self.wait_for_playback_completion = bool(wait_for_playback_completion)
        self.playback_timeout_seconds = float(playback_timeout_seconds)
        self._cancel_requested = Event()
        self._playback_finished = Event()
        self._playback_error = ""
        self._playback_started_at: float | None = None
        self._playback_latency_ms = 0
        self._lock = RLock()
        self._runtime_cancelled = False
        self.playback.subscribe(self._handle_playback_event)

    def run(self) -> VoiceOrchestrationResult:
        """Run one complete voice interaction using the injected boundaries."""

        with self._lock:
            self._cancel_requested.clear()
            self._runtime_cancelled = False
            self._playback_finished.clear()
            self._playback_error = ""
            self._playback_started_at = None
            self._playback_latency_ms = 0
        pipeline_started_at = monotonic()
        transcription = None
        speech = None
        response_text = None
        try:
            self._transition(CompanionState.LISTENING, "recording_started")
            self.recorder.start()
            audio_input = self.recorder.stop()
            self._raise_if_cancelled()

            self._transition(CompanionState.TRANSCRIBING, "transcription_started")
            stt_started_at = monotonic()
            transcription = self.stt_provider.transcribe(
                audio_input,
                cancel_event=self._cancel_requested,
            )
            stt_latency_ms = int((monotonic() - stt_started_at) * 1000)
            self._raise_if_cancelled()
            if not transcription.diagnostics.get("success", True):
                raise RuntimeError(
                    f"stt: {transcription.diagnostics.get('reason', 'transcription failed')}"
                )

            self._transition(CompanionState.THINKING, "text_input_started")
            response_text = self.text_input_handler(transcription.text)
            if not isinstance(response_text, str):
                raise TypeError("text_input_handler must return a string")
            self._raise_if_cancelled()

            self._transition(CompanionState.SPEAKING, "speech_synthesis_started")
            tts_started_at = monotonic()
            speech = self.tts_provider.synthesize(
                response_text,
                cancel_event=self._cancel_requested,
            )
            tts_latency_ms = int((monotonic() - tts_started_at) * 1000)
            self._raise_if_cancelled()
            if not speech.diagnostics.get("success", True):
                raise RuntimeError(
                    f"tts: {speech.diagnostics.get('reason', 'speech synthesis failed')}"
                )
            self.playback.play(speech)
            if self.wait_for_playback_completion:
                if not self._playback_finished.wait(self.playback_timeout_seconds):
                    raise TimeoutError("audio playback did not complete in time")
                if self._playback_error:
                    raise RuntimeError(self._playback_error)

            diagnostics = create_diagnostics(
                stage="experience.voice.orchestration",
                success=True,
                reason="completed",
                metrics={
                    "audio_duration_ms": audio_input.duration_ms,
                    "sample_rate": audio_input.sample_rate,
                    "audio_path": audio_input.path,
                    "stt_latency_ms": stt_latency_ms,
                    "tts_latency_ms": tts_latency_ms,
                    "playback_latency_ms": self._playback_latency_ms,
                    "pipeline_latency_ms": int((monotonic() - pipeline_started_at) * 1000),
                },
            )
            self.state_store.force_idle(reason="voice_run_finished", source="voice_orchestrator")
            return VoiceOrchestrationResult(
                success=True,
                stage="completed",
                transcription=transcription,
                response_text=response_text,
                speech=speech,
                diagnostics=diagnostics,
            )
        except _VoiceCancelled:
            self._safe_cancel_runtime()
            self.state_store.force_idle(reason="voice_run_cancelled", source="voice_orchestrator")
            return VoiceOrchestrationResult(
                success=False,
                cancelled=True,
                stage="cancelled",
                transcription=transcription,
                diagnostics=create_diagnostics(
                    stage="experience.voice.orchestration",
                    success=False,
                    reason="cancelled",
                ),
            )
        except Exception as error:
            self._safe_cancel_runtime()
            self.state_store.transition(
                CompanionState.ERROR,
                reason="voice_run_failed",
                source="voice_orchestrator",
            )
            self.state_store.force_idle(reason="voice_run_failed", source="voice_orchestrator")
            return VoiceOrchestrationResult(
                success=False,
                stage=self._stage_for_error(error),
                transcription=transcription,
                response_text=response_text,
                speech=speech,
                diagnostics=create_diagnostics(
                    stage="experience.voice.orchestration",
                    success=False,
                    reason=str(error),
                    warnings=[type(error).__name__],
                ),
            )

    def cancel(self) -> None:
        """Request cancellation and stop active runtime boundaries safely."""

        self._cancel_requested.set()
        self._safe_cancel_runtime()
        self.state_store.force_idle(reason="voice_cancel_requested", source="voice_orchestrator")

    def _transition(self, state: CompanionState, reason: str) -> None:
        result = self.state_store.transition(state, reason=reason, source="voice_orchestrator")
        if not result.success:
            raise RuntimeError(f"invalid voice state transition: {result.diagnostics}")

    def _handle_playback_event(self, event: PlaybackEvent) -> None:
        if event.event_type is PlaybackEventType.STARTED:
            self._playback_started_at = monotonic()
            return
        if event.event_type is PlaybackEventType.FAILED:
            self._playback_error = event.error or "audio playback failed"
            self._playback_finished.set()
            self.state_store.transition(
                CompanionState.ERROR,
                reason="playback_failed",
                source="voice_orchestrator",
            )
            self.state_store.force_idle(reason="playback_failed", source="voice_orchestrator")
            return
        if event.event_type in (PlaybackEventType.COMPLETED, PlaybackEventType.STOPPED):
            if self._playback_started_at is not None:
                self._playback_latency_ms = int((monotonic() - self._playback_started_at) * 1000)
            self._playback_finished.set()
            self.state_store.force_idle(
                reason=event.event_type.value,
                source="voice_orchestrator",
            )

    def _raise_if_cancelled(self) -> None:
        if self._cancel_requested.is_set():
            raise _VoiceCancelled()

    def _safe_cancel_runtime(self) -> None:
        with self._lock:
            if self._runtime_cancelled:
                return
            self._runtime_cancelled = True
            try:
                self.recorder.cancel()
            except Exception:
                pass
            try:
                self.playback.stop()
            except Exception:
                pass

    @staticmethod
    def _stage_for_error(error: Exception) -> str:
        name = type(error).__name__.lower()
        if "record" in name or "microphone" in str(error).lower():
            return "recorder"
        if "speech" in name or "transcrib" in str(error).lower() or "stt" in str(error).lower():
            return "stt"
        if "play" in name or "speaker" in str(error).lower():
            return "playback"
        if "tts" in str(error).lower() or "synth" in str(error).lower():
            return "tts"
        return "voice_pipeline"


class _VoiceCancelled(Exception):
    """Internal control flow marker for cancellation."""
