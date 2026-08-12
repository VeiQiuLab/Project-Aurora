"""Coordinate the optional voice pipeline without owning any core workflow."""

from __future__ import annotations

from dataclasses import dataclass, field
from threading import Event, RLock
from time import monotonic
from typing import Callable, Mapping
from uuid import uuid4

from modules.diagnostics import create_diagnostics
from modules.logger import logger
from modules.experience.audio.playback import (
    AudioPlaybackController,
    PlaybackEvent,
    PlaybackEventType,
)
from modules.experience.audio.recorder import AudioRecorder
from modules.experience.state import CompanionState, CompanionStateStore

from .interfaces import SpeechToTextProvider, TextToSpeechProvider
from .models import SpeechResult, TranscriptionResult
from .sentence_splitter import SentenceSplitter
from .tts_queue import TTSQueue
from .latency import VoiceTurnTrace


TextInputHandler = Callable[[str], str]
StreamTextInputHandler = Callable[..., str]
SentenceCallback = Callable[[str], None]


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
        stream_text_input_handler: StreamTextInputHandler | None = None,
        sentence_callback: SentenceCallback | None = None,
        cancel_event: Event | None = None,
        tts_timeout_seconds: float | None = 30.0,
        wait_for_playback_completion: bool = False,
        playback_timeout_seconds: float = 120.0,
    ):
        self.recorder = recorder
        self.stt_provider = stt_provider
        self.tts_provider = tts_provider
        self.playback = playback
        self.state_store = state_store
        self.text_input_handler = text_input_handler
        self.stream_text_input_handler = stream_text_input_handler
        self.sentence_callback = sentence_callback
        self.wait_for_playback_completion = bool(wait_for_playback_completion)
        self.playback_timeout_seconds = max(float(playback_timeout_seconds), 0.1)
        self.tts_timeout_seconds = (
            None if tts_timeout_seconds is None else max(float(tts_timeout_seconds), 0.1)
        )
        self._cancel_requested = cancel_event or Event()
        self._external_cancel_event = cancel_event is not None
        self._playback_finished = Event()
        self._playback_error = ""
        self._playback_started_at: float | None = None
        self._playback_latency_ms = 0
        self._lock = RLock()
        self._runtime_cancelled = False
        self._tts_queue_active = False
        self._tts_queue: TTSQueue | None = None
        self.session_id = ""
        self.generation_id = uuid4().hex
        self._generation_active = Event()
        self._generation_active.set()
        self._interrupt_lock = RLock()
        self._latency_trace: VoiceTurnTrace | None = None
        self.playback.subscribe(self._handle_playback_event)

    def set_latency_trace(self, trace: VoiceTurnTrace) -> None:
        """Attach the current Voice Turn timing context for diagnostics only."""

        if not isinstance(trace, VoiceTurnTrace):
            raise TypeError("trace must be a VoiceTurnTrace")
        self._latency_trace = trace

    def set_generation_context(self, session_id: str, generation_id: str) -> None:
        self.session_id = str(session_id)
        self.generation_id = str(generation_id)
        self._voice_log("generation_created")

    def _voice_log(self, event: str, **fields: object) -> None:
        details = " ".join(
            f"{key}={value!r}" for key, value in fields.items()
        )
        logger.info(
            f"[VOICE] session={self.session_id or '-'} "
            f"generation={self.generation_id} event={event} "
            f"state={self.state_store.current_state.value} {details}".rstrip()
        )

    def is_generation_active(self, generation_id: str | None = None) -> bool:
        return self._generation_active.is_set() and not self._cancel_requested.is_set() and (
            generation_id is None or generation_id == self.generation_id
        )

    def run(self) -> VoiceOrchestrationResult:
        """Run one complete voice interaction using the injected boundaries."""

        with self._lock:
            if self._latency_trace is None:
                self._latency_trace = VoiceTurnTrace()
            if not self._external_cancel_event:
                self._cancel_requested.clear()
            self._runtime_cancelled = False
            self._playback_finished.clear()
            self._playback_error = ""
            self._playback_started_at = None
            self._playback_latency_ms = 0
        if not self.is_generation_active():
            return VoiceOrchestrationResult(success=False, cancelled=True, stage="cancelled")
        pipeline_started_at = monotonic()
        transcription = None
        speech = None
        response_text = None
        tts_queue = None
        speech_results: list[SpeechResult] = []
        try:
            self._transition(CompanionState.LISTENING, "recording_started")
            self.recorder.start()
            audio_input = self.recorder.stop()
            self._raise_if_cancelled()

            self._transition(CompanionState.TRANSCRIBING, "transcription_started")
            stt_started_at = monotonic()
            self._latency_trace.mark("whisper_start")
            logger.info(
                f"[VOICE_STT] whisper_start elapsed_ms={self._latency_trace.now_elapsed_ms()}"
            )
            transcription = self.stt_provider.transcribe(
                audio_input,
                cancel_event=self._cancel_requested,
            )
            stt_latency_ms = int((monotonic() - stt_started_at) * 1000)
            whisper_elapsed = self._latency_trace.mark("whisper_end")
            logger.info(
                f"[VOICE_STT] whisper_end elapsed_ms={whisper_elapsed} "
                f"duration_ms={stt_latency_ms} transcription_text={transcription.text!r}"
            )
            self._raise_if_cancelled()
            if not transcription.diagnostics.get("success", True):
                raise RuntimeError(
                    f"stt: {transcription.diagnostics.get('reason', 'transcription failed')}"
                )

            self._transition(CompanionState.THINKING, "text_input_started")
            splitter = SentenceSplitter()
            sentence_count = 0

            if self.stream_text_input_handler is not None:
                tts_started_at = monotonic()

                def synthesize_sentence(text, cancel_event):
                    return self.tts_provider.synthesize(
                        text,
                        timeout_seconds=self.tts_timeout_seconds,
                        cancel_event=cancel_event,
                    )

                def play_sentence(_text, speech_result):
                    if not speech_result.diagnostics.get("success", True):
                        raise RuntimeError(
                            f"tts: {speech_result.diagnostics.get('reason', 'speech synthesis failed')}"
                        )
                    speech_results.append(speech_result)
                    self._play_speech_and_wait(_text, speech_result)

                tts_queue = TTSQueue(
                    synthesize_sentence,
                    on_speech=play_sentence,
                    cancel_event=self._cancel_requested,
                    latency_trace=self._latency_trace,
                    session_id=self.session_id,
                    generation_id=self.generation_id,
                    generation_active=self.is_generation_active,
                )
                self._tts_queue_active = True
                self._tts_queue = tts_queue
                tts_queue.start()

            def emit_sentences(sentences):
                nonlocal sentence_count
                for sentence in sentences:
                    if not self.is_generation_active():
                        self._voice_log("discard_stale_sentence")
                        return
                    sentence_count += 1
                    self._latency_trace.mark("first_sentence_emit", first=True)
                    logger.info(
                        f"[VOICE_SPLITTER] emit: sentence={sentence!r} "
                        f"elapsed_ms={self._latency_trace.now_elapsed_ms()}"
                    )
                    if tts_queue is not None and sentence_count == 1:
                        self._transition(CompanionState.SPEAKING, "speech_synthesis_started")
                    if tts_queue is not None:
                        tts_queue.put(
                            sentence,
                            session_id=self.session_id,
                            generation_id=self.generation_id,
                        )
                    if self.sentence_callback is not None:
                        self.sentence_callback(sentence)

            def handle_chunk(chunk):
                if not self.is_generation_active():
                    self._voice_log("discard_stale_chunk", length=len(chunk))
                    return
                chunk_length = len(chunk)
                self._latency_trace.mark("first_llm_chunk", first=True)
                logger.info(
                    f"[VOICE_SPLITTER] feed: chunk_length={chunk_length} "
                    f"elapsed_ms={self._latency_trace.now_elapsed_ms()}"
                )
                emit_sentences(splitter.feed(chunk))

            if self.stream_text_input_handler is not None:
                response_text = self.stream_text_input_handler(
                    transcription.text,
                    on_chunk=handle_chunk,
                    cancel_event=self._cancel_requested,
                )
                emit_sentences(splitter.flush())
                if not tts_queue.flush(self.playback_timeout_seconds):
                    raise TimeoutError("TTS queue did not drain in time")
                if tts_queue.last_error is not None:
                    raise tts_queue.last_error
                if not speech_results:
                    raise RuntimeError("TTS queue produced no speech")
                speech = speech_results[-1]
                tts_latency_ms = int((monotonic() - tts_started_at) * 1000)
            else:
                response_text = self.text_input_handler(transcription.text)
            if not isinstance(response_text, str):
                raise TypeError("text_input_handler must return a string")
            self._raise_if_cancelled()

            if tts_queue is None:
                self._transition(CompanionState.SPEAKING, "speech_synthesis_started")
                tts_started_at = monotonic()
                speech = self.tts_provider.synthesize(
                    response_text,
                    timeout_seconds=self.tts_timeout_seconds,
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
                    self._wait_for_playback()
                    self._raise_if_cancelled()

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
                    "sentence_count": sentence_count,
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
            if self.is_generation_active():
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
            if self._cancel_requested.is_set():
                if self.is_generation_active():
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
        finally:
            if "splitter" in locals():
                splitter.clear()
            if tts_queue is not None:
                if self._cancel_requested.is_set():
                    tts_queue.cancel()
                else:
                    tts_queue.close()
                self._tts_queue_active = False
                self._tts_queue = None
            self._log_latency_summary()

    def cancel(self) -> None:
        """Request cancellation and stop active runtime boundaries safely."""

        with self._interrupt_lock:
            if not self._generation_active.is_set():
                return
            self._generation_active.clear()
            self._cancel_requested.set()
        self._voice_log("interrupt")
        queue = self._tts_queue
        if queue is not None:
            queue.clear_current_generation()
            queue.cancel(wait=False)
        self._safe_cancel_runtime()
        self.state_store.force_idle(reason="voice_cancel_requested", source="voice_orchestrator")

    def _transition(self, state: CompanionState, reason: str) -> None:
        if not self.is_generation_active():
            self._voice_log("discard_stale_state", requested=state.value, reason=reason)
            return
        logger.info(
            f"VoiceOrchestrator state transition requested "
            f"{self.state_store.current_state.value}->{state.value} reason={reason}"
        )
        result = self.state_store.transition(state, reason=reason, source="voice_orchestrator")
        if not result.success:
            logger.warning(f"VoiceOrchestrator state transition failed: {result.diagnostics}")
            raise RuntimeError(f"invalid voice state transition: {result.diagnostics}")
        logger.info(f"VoiceOrchestrator state transition completed state={state.value}")
        self._voice_log("state_change", reason=reason)

    def _handle_playback_event(self, event: PlaybackEvent) -> None:
        if not self.is_generation_active():
            self._voice_log("discard_stale_playback", event=event.event_type.value)
            return
        if event.event_type is PlaybackEventType.STARTED:
            self._playback_started_at = monotonic()
            return
        if event.event_type is PlaybackEventType.FAILED:
            self._playback_error = event.error or "audio playback failed"
            self._playback_finished.set()
            if not self._tts_queue_active:
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
            if not self._tts_queue_active:
                self.state_store.force_idle(
                    reason=event.event_type.value,
                    source="voice_orchestrator",
                )

    def _play_speech_and_wait(self, sentence: str, speech: SpeechResult) -> None:
        """Play one queue item and wait so PlaybackController remains FIFO."""

        self._playback_finished.clear()
        self._playback_error = ""
        self._latency_trace.mark("first_audio_play", first=True)
        logger.info(
            f"[VOICE_PLAYBACK] play_start: sentence={sentence!r} "
            f"elapsed_ms={self._latency_trace.now_elapsed_ms()}"
        )
        self.playback.play(speech)
        self._wait_for_playback()

    def _log_latency_summary(self) -> None:
        trace = self._latency_trace
        if trace is None:
            return

        def value(item: int | None) -> str:
            return "n/a" if item is None else str(item)

        logger.info(
            "Voice latency summary:\n"
            f"recording: {value(trace.duration_ms('recording_start', 'recording_end'))} ms\n"
            f"whisper: {value(trace.duration_ms('whisper_start', 'whisper_end'))} ms\n"
            f"first_llm_chunk: {value(trace.elapsed_ms('first_llm_chunk'))} ms\n"
            f"first_sentence_emit: {value(trace.elapsed_ms('first_sentence_emit'))} ms\n"
            f"first_tts_start: {value(trace.elapsed_ms('first_tts_start'))} ms\n"
            f"first_audio_play: {value(trace.elapsed_ms('first_audio_play'))} ms"
        )

    def _wait_for_playback(self) -> None:
        deadline = monotonic() + self.playback_timeout_seconds
        while not self._playback_finished.is_set():
            remaining = deadline - monotonic()
            if remaining <= 0:
                raise TimeoutError("audio playback did not complete in time")
            if self._cancel_requested.wait(min(remaining, 0.1)):
                try:
                    self.playback.stop()
                except Exception:
                    pass
                return
            self._playback_finished.wait(min(remaining, 0.1))
        if self._playback_error:
            raise RuntimeError(self._playback_error)

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
