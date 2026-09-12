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
from modules.experience.audio.streaming_playback import (
    StreamingPlaybackController,
    StreamingPlaybackReport,
    StreamingPlaybackSession,
)
from modules.experience.state import CompanionState, CompanionStateStore

from .interfaces import SpeechToTextProvider, StreamingTTSProvider, TextToSpeechProvider
from .models import SpeechResult, SpeechSegment, StreamingSpeechResult, TranscriptionResult
from .sentence_splitter import SentenceSplitter
from .tts_router import TTSRouter
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
        streaming_enabled: bool = False,
        streaming_playback: StreamingPlaybackController | None = None,
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
        self.streaming_enabled = bool(streaming_enabled)
        self.streaming_playback = streaming_playback
        self._cancel_requested = cancel_event or Event()
        self._external_cancel_event = cancel_event is not None
        self._playback_finished = Event()
        self._playback_error = ""
        self._playback_started_at: float | None = None
        self._playback_latency_ms = 0
        self._lock = RLock()
        self._runtime_cancelled_generations: set[tuple[str, str]] = set()
        self._tts_queue_active = False
        self._tts_queue: TTSQueue | None = None
        self._active_splitter: SentenceSplitter | None = None
        self._legacy_playback_context: tuple[SpeechSegment, SpeechResult] | None = None
        self._playback_owners: dict[int, SpeechSegment] = {}
        self.session_id = uuid4().hex
        self.generation_id = uuid4().hex
        self._generation_active = Event()
        self._generation_active.set()
        self._interrupt_lock = RLock()
        self._latency_trace: VoiceTurnTrace | None = None
        self._current_streaming_session: StreamingPlaybackSession | None = None
        self._streaming_playback_context: (
            tuple[SpeechSegment, StreamingPlaybackSession] | None
        ) = None
        self.playback.subscribe(self._handle_playback_event)

    def set_latency_trace(self, trace: VoiceTurnTrace) -> None:
        """Attach the current Voice Turn timing context for diagnostics only."""

        if not isinstance(trace, VoiceTurnTrace):
            raise TypeError("trace must be a VoiceTurnTrace")
        self._latency_trace = trace

    def set_generation_context(self, session_id: str, generation_id: str) -> None:
        session = str(session_id)
        generation = str(generation_id)
        if not session or not generation:
            raise ValueError("session_id and generation_id must not be empty")
        with self._interrupt_lock:
            with self._lock:
                self.session_id = session
                self.generation_id = generation
                if not self._external_cancel_event:
                    self._cancel_requested = Event()
                self._generation_active.set()
                self._latency_trace = None
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

    def is_generation_active(
        self,
        generation_id: str | None = None,
        *,
        session_id: str | None = None,
    ) -> bool:
        return self._generation_active.is_set() and not self._cancel_requested.is_set() and (
            generation_id is None or generation_id == self.generation_id
        ) and (
            session_id is None or session_id == self.session_id
        )

    def _owns_generation(self, session_id: str, generation_id: str) -> bool:
        return self.is_generation_active(generation_id, session_id=session_id)

    def _is_current_generation(self, session_id: str, generation_id: str) -> bool:
        return session_id == self.session_id and generation_id == self.generation_id

    def run(self) -> VoiceOrchestrationResult:
        """Run one complete voice interaction using the injected boundaries."""

        with self._interrupt_lock:
            with self._lock:
                if self._latency_trace is None:
                    self._latency_trace = VoiceTurnTrace()
                self._playback_finished.clear()
                self._playback_error = ""
                self._playback_started_at = None
                self._playback_latency_ms = 0
                run_session_id = self.session_id
                run_generation_id = self.generation_id
                run_cancel_event = self._cancel_requested
                run_latency_trace = self._latency_trace
            generation_active = self._owns_generation(
                run_session_id, run_generation_id
            )
        if not generation_active:
            return VoiceOrchestrationResult(success=False, cancelled=True, stage="cancelled")
        pipeline_started_at = monotonic()
        transcription = None
        speech = None
        response_text = None
        tts_queue = None
        speech_results: list[SpeechResult] = []
        streaming_selected = False
        streaming_status = "not_selected"
        streaming_report: StreamingPlaybackReport | None = None
        streaming_provider_diagnostics: Mapping[str, object] | None = None
        streaming_segment_states: dict[int, dict[str, object]] = {}
        completed_segment_count = 0
        queue_streaming_provider: StreamingTTSProvider | None = None
        selected_tts_provider = self.tts_provider
        tts_provider_name = self._tts_provider_name(selected_tts_provider)
        try:
            selected_tts_provider = self._selected_tts_provider()
            tts_provider_name = self._tts_provider_name(selected_tts_provider)
            self._transition(
                CompanionState.LISTENING,
                "recording_started",
                session_id=run_session_id,
                generation_id=run_generation_id,
            )
            self.recorder.start()
            audio_input = self.recorder.stop()
            self._raise_if_cancelled(run_cancel_event)

            self._transition(
                CompanionState.TRANSCRIBING,
                "transcription_started",
                session_id=run_session_id,
                generation_id=run_generation_id,
            )
            stt_started_at = monotonic()
            run_latency_trace.mark("whisper_start")
            logger.info(
                f"[VOICE_STT] whisper_start elapsed_ms={run_latency_trace.now_elapsed_ms()}"
            )
            transcription = self.stt_provider.transcribe(
                audio_input,
                cancel_event=run_cancel_event,
            )
            stt_latency_ms = int((monotonic() - stt_started_at) * 1000)
            whisper_elapsed = run_latency_trace.mark("whisper_end")
            logger.info(
                f"[VOICE_STT] whisper_end elapsed_ms={whisper_elapsed} "
                f"duration_ms={stt_latency_ms} transcription_text={transcription.text!r}"
            )
            self._raise_if_cancelled(run_cancel_event)
            if not transcription.diagnostics.get("success", True):
                raise RuntimeError(
                    f"stt: {transcription.diagnostics.get('reason', 'transcription failed')}"
                )

            self._transition(
                CompanionState.THINKING,
                "text_input_started",
                session_id=run_session_id,
                generation_id=run_generation_id,
            )
            splitter = SentenceSplitter()
            sentence_count = 0
            next_segment_index = 0
            with self._lock:
                if self._owns_generation(run_session_id, run_generation_id):
                    self._active_splitter = splitter

            if self.stream_text_input_handler is not None:
                tts_started_at = monotonic()
                queue_streaming_provider = self._streaming_provider(
                    selected_tts_provider
                )
                if queue_streaming_provider is not None:
                    streaming_selected = True
                    streaming_status = "queued"

                def update_streaming_segment(
                    segment: SpeechSegment,
                    **fields: object,
                ) -> None:
                    if queue_streaming_provider is None:
                        return
                    with self._lock:
                        state = streaming_segment_states.setdefault(
                            segment.segment_index,
                            {
                                "session_id": segment.session_id,
                                "generation_id": segment.generation_id,
                                "segment_index": segment.segment_index,
                                "provider": tts_provider_name,
                                "streaming_selected": True,
                                "segment_emit_monotonic": None,
                                "tts_request_start": None,
                                "first_pcm_received": None,
                                "first_audio_submission": None,
                                "upstream_end": None,
                                "playback_end": None,
                                "audio_duration_ms": None,
                                "received_pcm_bytes": None,
                                "played_pcm_bytes": None,
                                "underrun_count": None,
                                "buffer_peak_bytes": None,
                                "cancel_latency_ms": None,
                                "status": "pending",
                                "error": "",
                            },
                        )
                        state.update(fields)

                def finish_streaming_segment(
                    segment: SpeechSegment,
                    *,
                    status: str,
                    report: StreamingPlaybackReport | None = None,
                    error: str = "",
                ) -> None:
                    source: Mapping[str, object] = {}
                    if report is not None:
                        metrics = report.diagnostics.get("metrics", {})
                        if isinstance(metrics, Mapping):
                            source = metrics
                    update_streaming_segment(
                        segment,
                        first_pcm_received=source.get("first_pcm_received_monotonic"),
                        first_audio_submission=source.get(
                            "first_audio_submission_monotonic"
                        ),
                        upstream_end=source.get("upstream_end_monotonic"),
                        playback_end=source.get("playback_end_monotonic"),
                        audio_duration_ms=source.get("audio_duration_ms"),
                        received_pcm_bytes=source.get("received_pcm_bytes"),
                        played_pcm_bytes=source.get("played_pcm_bytes"),
                        underrun_count=source.get("underrun_count"),
                        buffer_peak_bytes=source.get("buffer_peak_bytes"),
                        cancel_latency_ms=source.get("cancel_latency_ms"),
                        status=status,
                        error=error,
                    )

                def synthesize_sentence(segment, cancel_event):
                    if queue_streaming_provider is None:
                        return selected_tts_provider.synthesize(
                            segment.text,
                            timeout_seconds=self.tts_timeout_seconds,
                            cancel_event=cancel_event,
                        )
                    request_start = monotonic()
                    update_streaming_segment(
                        segment,
                        tts_request_start=request_start,
                        status="creating",
                        error="",
                    )
                    try:
                        stream = queue_streaming_provider.synthesize_stream(
                            segment.text,
                            timeout_seconds=self.tts_timeout_seconds,
                            cancel_event=cancel_event,
                        )
                    except Exception as error:
                        finish_streaming_segment(
                            segment,
                            status=(
                                "cancelled"
                                if cancel_event.is_set()
                                or not self._owns_generation(
                                    segment.session_id, segment.generation_id
                                )
                                else "failed"
                            ),
                            error=str(error) or type(error).__name__,
                        )
                        raise _StreamingStageError("tts", str(error)) from error
                    update_streaming_segment(
                        segment,
                        provider_metadata_monotonic=monotonic(),
                        status="stream_open",
                    )
                    return stream

                def discard_sentence_speech(segment, speech_result):
                    if isinstance(speech_result, StreamingSpeechResult):
                        speech_result.cancel()
                        finish_streaming_segment(
                            segment,
                            status=(
                                "cancelled"
                                if run_cancel_event.is_set()
                                else "stale"
                            ),
                        )

                def play_sentence(segment, speech_result):
                    nonlocal completed_segment_count
                    nonlocal streaming_provider_diagnostics
                    nonlocal streaming_report
                    nonlocal streaming_status
                    if queue_streaming_provider is not None:
                        if not isinstance(speech_result, StreamingSpeechResult):
                            raise TypeError(
                                "streaming provider must return StreamingSpeechResult"
                            )
                        with self._lock:
                            state = streaming_segment_states.get(
                                segment.segment_index, {}
                            )
                            request_start = float(
                                state.get("tts_request_start", monotonic())
                            )
                            metadata_received = float(
                                state.get("provider_metadata_monotonic", monotonic())
                            )
                        try:
                            (
                                report,
                                _segment_tts_latency_ms,
                                provider_diagnostics,
                            ) = self._play_streaming_result(
                                segment,
                                speech_result,
                                request_start_monotonic=request_start,
                                provider_metadata_monotonic=metadata_received,
                                cancel_event=run_cancel_event,
                                latency_trace=run_latency_trace,
                            )
                        except BaseException as error:
                            finish_streaming_segment(
                                segment,
                                status=(
                                    "cancelled"
                                    if run_cancel_event.is_set()
                                    or not self._owns_generation(
                                        segment.session_id, segment.generation_id
                                    )
                                    else "failed"
                                ),
                                error=str(error) or type(error).__name__,
                            )
                            raise
                        streaming_report = report
                        streaming_provider_diagnostics = provider_diagnostics
                        streaming_status = report.status
                        self._apply_streaming_playback_latency(report)
                        finish_streaming_segment(
                            segment,
                            status=report.status,
                            report=report,
                            error=self._streaming_report_error(report),
                        )
                        if report.status == "cancelled":
                            if run_cancel_event.is_set() or not self._owns_generation(
                                segment.session_id, segment.generation_id
                            ):
                                raise _VoiceCancelled()
                            raise _StreamingStageError(
                                "playback", "streaming playback was cancelled"
                            )
                        if not report.success:
                            raise self._streaming_failure(report)
                        if not self._owns_generation(
                            segment.session_id, segment.generation_id
                        ):
                            raise _VoiceCancelled()
                        completed_segment_count += 1
                        return

                    if not self._owns_generation(
                        segment.session_id, segment.generation_id
                    ):
                        return
                    if not speech_result.diagnostics.get("success", True):
                        raise RuntimeError(
                            f"tts: {speech_result.diagnostics.get('reason', 'speech synthesis failed')}"
                        )
                    self._play_speech_and_wait(
                        segment,
                        speech_result,
                        cancel_event=run_cancel_event,
                        latency_trace=run_latency_trace,
                    )
                    if self._owns_generation(segment.session_id, segment.generation_id):
                        speech_results.append(speech_result)
                        completed_segment_count += 1

                tts_queue = TTSQueue(
                    synthesize_sentence,
                    on_speech=play_sentence,
                    cancel_event=run_cancel_event,
                    latency_trace=run_latency_trace,
                    session_id=run_session_id,
                    generation_id=run_generation_id,
                    generation_active=self._owns_generation,
                    on_generation_failed=self._invalidate_failed_generation,
                    discard_speech=(
                        discard_sentence_speech
                        if queue_streaming_provider is not None
                        else None
                    ),
                )
                with self._lock:
                    if not self._owns_generation(run_session_id, run_generation_id):
                        tts_queue.cancel(wait=False)
                        raise _VoiceCancelled()
                    self._tts_queue_active = True
                    self._tts_queue = tts_queue
                tts_queue.start()

            def emit_sentences(sentences):
                nonlocal sentence_count, next_segment_index
                for sentence in sentences:
                    if not sentence.strip():
                        continue
                    if not self._owns_generation(run_session_id, run_generation_id):
                        self._voice_log("discard_stale_sentence")
                        return
                    segment = SpeechSegment(
                        session_id=run_session_id,
                        generation_id=run_generation_id,
                        segment_index=next_segment_index,
                        text=sentence,
                    )
                    emitted_at = monotonic()
                    run_latency_trace.mark_at(
                        "first_sentence_emit", emitted_at, first=True
                    )
                    run_latency_trace.mark_at("final_segment_emit", emitted_at)
                    update_streaming_segment(
                        segment,
                        segment_emit_monotonic=emitted_at,
                        status="emitted",
                        error="",
                    )
                    logger.info(
                        f"[VOICE_SPLITTER] emit: segment_index={segment.segment_index} "
                        f"text_length={len(segment.text)} "
                        f"elapsed_ms={run_latency_trace.now_elapsed_ms()}"
                    )
                    if tts_queue is not None:
                        tts_queue.note_emitted(segment)
                    if tts_queue is not None and sentence_count == 0:
                        self._transition(
                            CompanionState.SPEAKING,
                            "speech_synthesis_started",
                            session_id=run_session_id,
                            generation_id=run_generation_id,
                        )
                    if tts_queue is not None and not tts_queue.put(segment):
                        return
                    next_segment_index += 1
                    sentence_count += 1
                    if self.sentence_callback is not None:
                        self.sentence_callback(sentence)

            def handle_chunk(chunk):
                if not self._owns_generation(run_session_id, run_generation_id):
                    self._voice_log("discard_stale_chunk", length=len(chunk))
                    return
                chunk_length = len(chunk)
                run_latency_trace.mark("first_llm_chunk", first=True)
                logger.info(
                    f"[VOICE_SPLITTER] feed: chunk_length={chunk_length} "
                    f"elapsed_ms={run_latency_trace.now_elapsed_ms()}"
                )
                with self._lock:
                    if (
                        self._active_splitter is not splitter
                        or not self._owns_generation(run_session_id, run_generation_id)
                    ):
                        emitted = []
                    else:
                        emitted = splitter.feed(chunk)
                emit_sentences(emitted)

            if self.stream_text_input_handler is not None:
                run_latency_trace.mark("llm_start")
                try:
                    response_text = self.stream_text_input_handler(
                        transcription.text,
                        on_chunk=handle_chunk,
                        cancel_event=run_cancel_event,
                    )
                finally:
                    run_latency_trace.mark("llm_complete")
                with self._lock:
                    if (
                        self._active_splitter is splitter
                        and self._owns_generation(run_session_id, run_generation_id)
                    ):
                        final_segments = splitter.flush()
                    else:
                        final_segments = []
                emit_sentences(final_segments)
                if not tts_queue.flush(self.playback_timeout_seconds):
                    raise TimeoutError("TTS queue did not drain in time")
                if tts_queue.last_error is not None:
                    raise tts_queue.last_error
                if completed_segment_count == 0:
                    raise RuntimeError("TTS queue produced no speech")
                if speech_results:
                    speech = speech_results[-1]
                if queue_streaming_provider is None:
                    run_latency_trace.mark("final_playback_end")
                tts_latency_ms = int((monotonic() - tts_started_at) * 1000)
            else:
                run_latency_trace.mark("llm_start")
                try:
                    response_text = self.text_input_handler(transcription.text)
                finally:
                    run_latency_trace.mark("llm_complete")
            if not isinstance(response_text, str):
                raise TypeError("text_input_handler must return a string")
            self._raise_if_cancelled(run_cancel_event)

            if tts_queue is None:
                self._transition(
                    CompanionState.SPEAKING,
                    "speech_synthesis_started",
                    session_id=run_session_id,
                    generation_id=run_generation_id,
                )
                tts_started_at = monotonic()
                direct_segment = SpeechSegment(
                    session_id=run_session_id,
                    generation_id=run_generation_id,
                    segment_index=0,
                    text=response_text,
                )
                streaming_provider = self._streaming_provider(selected_tts_provider)
                if streaming_provider is not None:
                    streaming_selected = True
                    streaming_status = "creating"
                    (
                        streaming_result,
                        tts_latency_ms,
                        streaming_provider_diagnostics,
                    ) = self._play_streaming_speech(
                        response_text,
                        streaming_provider,
                        segment=direct_segment,
                        request_start_monotonic=tts_started_at,
                        cancel_event=run_cancel_event,
                        latency_trace=run_latency_trace,
                    )
                    streaming_report = streaming_result
                    streaming_status = streaming_report.status
                    self._apply_streaming_playback_latency(streaming_report)
                    if streaming_report.status == "cancelled":
                        raise _VoiceCancelled()
                    if not streaming_report.success:
                        raise self._streaming_failure(streaming_report)
                    self._raise_if_cancelled(run_cancel_event)
                else:
                    speech = self.tts_provider.synthesize(
                        response_text,
                        timeout_seconds=self.tts_timeout_seconds,
                        cancel_event=run_cancel_event,
                    )
                    tts_latency_ms = int((monotonic() - tts_started_at) * 1000)
                    self._raise_if_cancelled(run_cancel_event)
                    if not speech.diagnostics.get("success", True):
                        raise RuntimeError(
                            f"tts: {speech.diagnostics.get('reason', 'speech synthesis failed')}"
                        )
                    self._play_owned_speech(
                        direct_segment,
                        speech,
                        wait=self.wait_for_playback_completion,
                        cancel_event=run_cancel_event,
                        latency_trace=run_latency_trace,
                    )
                    self._raise_if_cancelled(run_cancel_event)

            diagnostics = create_diagnostics(
                stage="experience.voice.orchestration",
                success=True,
                reason="completed",
                metrics={
                    "audio_duration_ms": self._streaming_metric_value(
                        streaming_report, "audio_duration_ms", audio_input.duration_ms
                    ),
                    "sample_rate": self._streaming_metric_value(
                        streaming_report, "sample_rate", audio_input.sample_rate
                    ),
                    "audio_path": audio_input.path,
                    "stt_latency_ms": stt_latency_ms,
                    "tts_latency_ms": tts_latency_ms,
                    "playback_latency_ms": self._playback_latency_ms,
                    "sentence_count": sentence_count,
                    "pipeline_latency_ms": int((monotonic() - pipeline_started_at) * 1000),
                    **self._streaming_metrics(
                        selected=streaming_selected,
                        provider=tts_provider_name,
                        status=streaming_status,
                        report=streaming_report,
                    ),
                    **self._turn_latency_metrics(run_latency_trace),
                },
                trace=self._voice_trace(
                    streaming_report,
                    streaming_provider_diagnostics,
                    tts_queue,
                    turn_trace=run_latency_trace,
                    streaming_segments=self._streaming_segment_snapshot(
                        streaming_segment_states,
                        tts_queue=tts_queue,
                    ),
                ),
            )
            with self._interrupt_lock:
                if self._is_current_generation(run_session_id, run_generation_id):
                    self.state_store.force_idle(
                        reason="voice_run_finished", source="voice_orchestrator"
                    )
            return VoiceOrchestrationResult(
                success=True,
                stage="completed",
                transcription=transcription,
                response_text=response_text,
                speech=speech,
                diagnostics=diagnostics,
            )
        except _VoiceCancelled:
            if streaming_selected:
                streaming_status = "cancelled"
            self._safe_cancel_runtime(run_session_id, run_generation_id)
            with self._interrupt_lock:
                if self._is_current_generation(run_session_id, run_generation_id):
                    self.state_store.force_idle(
                        reason="voice_run_cancelled", source="voice_orchestrator"
                    )
            return VoiceOrchestrationResult(
                success=False,
                cancelled=True,
                stage="cancelled",
                transcription=transcription,
                diagnostics=create_diagnostics(
                    stage="experience.voice.orchestration",
                    success=False,
                    reason="cancelled",
                    metrics={
                        **self._streaming_metrics(
                            selected=streaming_selected,
                            provider=tts_provider_name,
                            status=streaming_status,
                            report=streaming_report,
                        ),
                        **self._turn_latency_metrics(run_latency_trace),
                    },
                    trace=self._voice_trace(
                        streaming_report,
                        streaming_provider_diagnostics,
                        tts_queue,
                        turn_trace=run_latency_trace,
                        streaming_segments=self._streaming_segment_snapshot(
                            streaming_segment_states,
                            tts_queue=tts_queue,
                        ),
                    ),
                ),
            )
        except Exception as error:
            self._safe_cancel_runtime(run_session_id, run_generation_id)
            if run_cancel_event.is_set() or not self._is_current_generation(
                run_session_id, run_generation_id
            ):
                if streaming_selected:
                    streaming_status = "cancelled"
                with self._interrupt_lock:
                    if self._is_current_generation(run_session_id, run_generation_id):
                        self.state_store.force_idle(
                            reason="voice_run_cancelled", source="voice_orchestrator"
                        )
                return VoiceOrchestrationResult(
                    success=False,
                    cancelled=True,
                    stage="cancelled",
                    transcription=transcription,
                    diagnostics=create_diagnostics(
                        stage="experience.voice.orchestration",
                        success=False,
                        reason="cancelled",
                        metrics={
                            **self._streaming_metrics(
                                selected=streaming_selected,
                                provider=tts_provider_name,
                                status=streaming_status,
                                report=streaming_report,
                            ),
                            **self._turn_latency_metrics(run_latency_trace),
                        },
                        trace=self._voice_trace(
                            streaming_report,
                            streaming_provider_diagnostics,
                            tts_queue,
                            turn_trace=run_latency_trace,
                            streaming_segments=self._streaming_segment_snapshot(
                                streaming_segment_states,
                                tts_queue=tts_queue,
                            ),
                        ),
                    ),
                )
            if streaming_selected:
                streaming_status = "failed"
            with self._interrupt_lock:
                if self._is_current_generation(run_session_id, run_generation_id):
                    self.state_store.transition(
                        CompanionState.ERROR,
                        reason="voice_run_failed",
                        source="voice_orchestrator",
                    )
                    self.state_store.force_idle(
                        reason="voice_run_failed", source="voice_orchestrator"
                    )
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
                    metrics={
                        **self._streaming_metrics(
                            selected=streaming_selected,
                            provider=tts_provider_name,
                            status=streaming_status,
                            report=streaming_report,
                        ),
                        **self._turn_latency_metrics(run_latency_trace),
                    },
                    trace=self._voice_trace(
                        streaming_report,
                        streaming_provider_diagnostics,
                        tts_queue,
                        turn_trace=run_latency_trace,
                        streaming_segments=self._streaming_segment_snapshot(
                            streaming_segment_states,
                            tts_queue=tts_queue,
                        ),
                    ),
                ),
            )
        finally:
            if "splitter" in locals():
                with self._lock:
                    splitter.clear()
                    if self._active_splitter is splitter:
                        self._active_splitter = None
            if tts_queue is not None:
                if run_cancel_event.is_set():
                    tts_queue.cancel()
                else:
                    tts_queue.close()
                with self._lock:
                    if self._tts_queue is tts_queue:
                        self._tts_queue_active = False
                        self._tts_queue = None
            self._log_latency_summary(run_latency_trace)

    def cancel(self) -> None:
        """Request cancellation and stop active runtime boundaries safely."""

        with self._interrupt_lock:
            if not self._generation_active.is_set():
                return
            session_id = self.session_id
            generation_id = self.generation_id
            cancel_event = self._cancel_requested
            self._generation_active.clear()
            cancel_event.set()
            with self._lock:
                splitter = self._active_splitter
                queue = self._tts_queue
                if splitter is not None:
                    splitter.clear()
            self._voice_log("interrupt")
            if queue is not None:
                queue.clear_current_generation()
                queue.cancel(wait=False)
            self._safe_cancel_runtime(session_id, generation_id)
            if self._is_current_generation(session_id, generation_id):
                self.state_store.force_idle(
                    reason="voice_cancel_requested", source="voice_orchestrator"
                )

    def _invalidate_failed_generation(
        self, segment: SpeechSegment, error: Exception
    ) -> None:
        """Fail one generation without turning the provider error into cancellation."""

        with self._interrupt_lock:
            if not self._owns_generation(segment.session_id, segment.generation_id):
                return
            self._generation_active.clear()
            with self._lock:
                splitter = self._active_splitter
                if splitter is not None:
                    splitter.clear()
        self._voice_log(
            "generation_failed",
            segment_index=segment.segment_index,
            error=type(error).__name__,
        )
        self._safe_cancel_runtime(segment.session_id, segment.generation_id)

    def _transition(
        self,
        state: CompanionState,
        reason: str,
        *,
        session_id: str | None = None,
        generation_id: str | None = None,
    ) -> None:
        with self._interrupt_lock:
            active = (
                self.is_generation_active()
                if session_id is None or generation_id is None
                else self._owns_generation(session_id, generation_id)
            )
            if not active:
                self._voice_log("discard_stale_state", requested=state.value, reason=reason)
                return
            logger.info(
                f"VoiceOrchestrator state transition requested "
                f"{self.state_store.current_state.value}->{state.value} reason={reason}"
            )
            result = self.state_store.transition(
                state, reason=reason, source="voice_orchestrator"
            )
            if not result.success:
                logger.warning(
                    f"VoiceOrchestrator state transition failed: {result.diagnostics}"
                )
                raise RuntimeError(
                    f"invalid voice state transition: {result.diagnostics}"
                )
            logger.info(
                f"VoiceOrchestrator state transition completed state={state.value}"
            )
            self._voice_log("state_change", reason=reason)

    def _handle_playback_event(self, event: PlaybackEvent) -> None:
        terminal = event.event_type in (
            PlaybackEventType.COMPLETED,
            PlaybackEventType.STOPPED,
            PlaybackEventType.FAILED,
        )
        with self._interrupt_lock:
            with self._lock:
                context = self._legacy_playback_context
                owner = (
                    self._playback_owners.get(id(event.speech))
                    if event.speech is not None
                    else context[0] if context is not None else None
                )
                expected_speech = context[1] if context is not None else None
                if terminal and event.speech is not None:
                    self._playback_owners.pop(id(event.speech), None)
            if owner is None or (
                event.speech is not None
                and expected_speech is not None
                and event.speech is not expected_speech
            ):
                self._voice_log(
                    "discard_unowned_playback", playback_event=event.event_type.value
                )
                return
            if not self._owns_generation(owner.session_id, owner.generation_id):
                with self._lock:
                    if (
                        terminal
                        and event.speech is not None
                        and self._legacy_playback_context is not None
                        and self._legacy_playback_context[1] is event.speech
                    ):
                        self._legacy_playback_context = None
                self._voice_log(
                    "discard_stale_playback", playback_event=event.event_type.value
                )
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
                    self.state_store.force_idle(
                        reason="playback_failed", source="voice_orchestrator"
                    )
                with self._lock:
                    if (
                        self._legacy_playback_context is not None
                        and self._legacy_playback_context[0] == owner
                    ):
                        self._legacy_playback_context = None
                return
            if event.event_type in (
                PlaybackEventType.COMPLETED,
                PlaybackEventType.STOPPED,
            ):
                if self._playback_started_at is not None:
                    self._playback_latency_ms = int(
                        (monotonic() - self._playback_started_at) * 1000
                    )
                self._playback_finished.set()
                if not self._tts_queue_active:
                    self.state_store.force_idle(
                        reason=event.event_type.value,
                        source="voice_orchestrator",
                    )

                with self._lock:
                    if (
                        self._legacy_playback_context is not None
                        and self._legacy_playback_context[0] == owner
                    ):
                        self._legacy_playback_context = None

    def _play_speech_and_wait(
        self,
        segment: SpeechSegment,
        speech: SpeechResult,
        *,
        cancel_event: Event,
        latency_trace: VoiceTurnTrace,
    ) -> None:
        """Play one queue item and wait so PlaybackController remains FIFO."""

        self._play_owned_speech(
            segment,
            speech,
            wait=True,
            cancel_event=cancel_event,
            latency_trace=latency_trace,
        )

    def _play_owned_speech(
        self,
        segment: SpeechSegment,
        speech: SpeechResult,
        *,
        wait: bool,
        cancel_event: Event,
        latency_trace: VoiceTurnTrace,
    ) -> None:
        with self._interrupt_lock:
            if not self._owns_generation(segment.session_id, segment.generation_id):
                return
            self._playback_finished.clear()
            self._playback_error = ""
            with self._lock:
                self._legacy_playback_context = (segment, speech)
                self._playback_owners[id(speech)] = segment
            latency_trace.mark("first_audio_play", first=True)
            logger.info(
                f"[VOICE_PLAYBACK] play_start: segment_index={segment.segment_index} "
                f"text_length={len(segment.text)} "
                f"elapsed_ms={latency_trace.now_elapsed_ms()}"
            )
        try:
            with self._interrupt_lock:
                if not self._owns_generation(
                    segment.session_id, segment.generation_id
                ):
                    return
                self.playback.play(speech)
            if wait:
                self._wait_for_playback(segment, speech, cancel_event)
        finally:
            if wait:
                with self._lock:
                    if self._legacy_playback_context == (segment, speech):
                        self._legacy_playback_context = None
                    self._playback_owners.pop(id(speech), None)

    @staticmethod
    def _log_latency_summary(trace: VoiceTurnTrace) -> None:

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

    def _wait_for_playback(
        self,
        segment: SpeechSegment,
        speech: SpeechResult,
        cancel_event: Event,
    ) -> None:
        deadline = monotonic() + self.playback_timeout_seconds
        while not self._playback_finished.is_set():
            remaining = deadline - monotonic()
            if remaining <= 0:
                raise TimeoutError("audio playback did not complete in time")
            if cancel_event.wait(min(remaining, 0.1)):
                with self._interrupt_lock:
                    with self._lock:
                        owns_playback = self._legacy_playback_context == (
                            segment,
                            speech,
                        )
                    if owns_playback:
                        try:
                            self.playback.stop()
                        except Exception:
                            pass
                return
            self._playback_finished.wait(min(remaining, 0.1))
        if self._playback_error:
            raise RuntimeError(self._playback_error)

    @staticmethod
    def _raise_if_cancelled(cancel_event: Event) -> None:
        if cancel_event.is_set():
            raise _VoiceCancelled()

    def _safe_cancel_runtime(self, session_id: str, generation_id: str) -> None:
        key = (session_id, generation_id)
        with self._interrupt_lock:
            with self._lock:
                if key in self._runtime_cancelled_generations:
                    return
                self._runtime_cancelled_generations.add(key)
                is_current = self._is_current_generation(session_id, generation_id)
                streaming_context = self._streaming_playback_context
                streaming_session = (
                    streaming_context[1]
                    if streaming_context is not None
                    and streaming_context[0].session_id == session_id
                    and streaming_context[0].generation_id == generation_id
                    else None
                )
            if streaming_session is not None:
                try:
                    streaming_session.cancel()
                except Exception:
                    pass
            if not is_current:
                return
            try:
                self.recorder.cancel()
            except Exception:
                pass
            try:
                self.playback.stop()
            except Exception:
                pass

    def _selected_tts_provider(self) -> TextToSpeechProvider:
        if isinstance(self.tts_provider, TTSRouter):
            return self.tts_provider.provider_for()
        return self.tts_provider

    def _streaming_provider(
        self,
        provider: TextToSpeechProvider,
    ) -> StreamingTTSProvider | None:
        if not self.streaming_enabled or self.streaming_playback is None:
            return None
        return provider if isinstance(provider, StreamingTTSProvider) else None

    def _play_streaming_speech(
        self,
        text: str,
        provider: StreamingTTSProvider,
        *,
        segment: SpeechSegment,
        request_start_monotonic: float,
        cancel_event: Event,
        latency_trace: VoiceTurnTrace,
    ) -> tuple[StreamingPlaybackReport, int, Mapping[str, object]]:
        try:
            speech = provider.synthesize_stream(
                text,
                timeout_seconds=self.tts_timeout_seconds,
                cancel_event=cancel_event,
            )
        except Exception as error:
            raise _StreamingStageError("tts", str(error)) from error
        metadata_received = monotonic()
        return self._play_streaming_result(
            segment,
            speech,
            request_start_monotonic=request_start_monotonic,
            provider_metadata_monotonic=metadata_received,
            cancel_event=cancel_event,
            latency_trace=latency_trace,
        )

    def _play_streaming_result(
        self,
        segment: SpeechSegment,
        speech: StreamingSpeechResult,
        *,
        request_start_monotonic: float,
        provider_metadata_monotonic: float,
        cancel_event: Event,
        latency_trace: VoiceTurnTrace,
    ) -> tuple[StreamingPlaybackReport, int, Mapping[str, object]]:
        session: StreamingPlaybackSession | None = None
        try:
            tts_latency_ms = int(
                (provider_metadata_monotonic - request_start_monotonic) * 1000
            )
            self._raise_if_cancelled(cancel_event)
            if speech.diagnostics.get("success") is not True or not speech.metadata:
                raise _StreamingStageError(
                    "tts",
                    str(speech.diagnostics.get("reason", "stream creation failed")),
                )
            assert self.streaming_playback is not None
            try:
                with self._interrupt_lock:
                    if not self._owns_generation(
                        segment.session_id, segment.generation_id
                    ):
                        raise _VoiceCancelled()
                    session = self.streaming_playback.play(
                        speech,
                        request_start_monotonic=request_start_monotonic,
                        provider_metadata_monotonic=provider_metadata_monotonic,
                    )
                    with self._lock:
                        self._current_streaming_session = session
                        self._streaming_playback_context = (segment, session)
                    cancelled = cancel_event.is_set()
            except _VoiceCancelled:
                raise
            except Exception as error:
                raise _StreamingStageError("playback", str(error)) from error
            if cancelled:
                session.cancel()
            try:
                report = session.wait(self.playback_timeout_seconds)
            except Exception as error:
                raise _StreamingStageError("playback", str(error)) from error
            self._apply_streaming_turn_markers(report, latency_trace)
            return report, tts_latency_ms, dict(speech.diagnostics)
        except BaseException:
            if session is not None:
                session.cancel()
            else:
                speech.cancel()
            raise
        finally:
            with self._lock:
                if self._streaming_playback_context == (segment, session):
                    self._streaming_playback_context = None
                if self._current_streaming_session is session:
                    self._current_streaming_session = None

    def _apply_streaming_playback_latency(
        self, report: StreamingPlaybackReport
    ) -> None:
        metrics = report.diagnostics.get("metrics", {})
        if not isinstance(metrics, Mapping):
            return
        started = metrics.get("playback_start_monotonic")
        ended = metrics.get("playback_end_monotonic")
        if isinstance(started, (int, float)) and isinstance(ended, (int, float)):
            self._playback_latency_ms = max(int((float(ended) - float(started)) * 1000), 0)

    @staticmethod
    def _apply_streaming_turn_markers(
        report: StreamingPlaybackReport,
        trace: VoiceTurnTrace,
    ) -> None:
        metrics = report.diagnostics.get("metrics", {})
        if not isinstance(metrics, Mapping):
            return
        for source, target, first in (
            ("first_pcm_received_monotonic", "first_pcm_received", True),
            (
                "first_audio_submission_monotonic",
                "first_audio_submission",
                True,
            ),
            ("upstream_end_monotonic", "upstream_end", False),
            ("playback_end_monotonic", "final_playback_end", False),
        ):
            value = metrics.get(source)
            if isinstance(value, (int, float)) and float(value) >= trace.started_at:
                trace.mark_at(target, float(value), first=first)

    @staticmethod
    def _streaming_report_error(report: StreamingPlaybackReport) -> str:
        if report.success:
            return ""
        metrics = report.diagnostics.get("metrics", {})
        if isinstance(metrics, Mapping):
            for key in (
                "playback_error",
                "provider_error",
                "producer_error",
                "provider_close_error",
            ):
                value = metrics.get(key)
                if value:
                    return str(value)
        return str(report.diagnostics.get("reason", report.status))

    @staticmethod
    def _turn_latency_metrics(trace: VoiceTurnTrace) -> dict[str, object]:
        first_audio = trace.timestamp("first_audio_submission")
        llm_start = trace.timestamp("llm_start")
        llm_complete = trace.timestamp("llm_complete")

        def duration(start: float | None, end: float | None) -> float | None:
            if start is None or end is None:
                return None
            return round((end - start) * 1000.0, 3)

        lead = duration(first_audio, llm_complete)
        return {
            "llm_request_to_first_audio_submission_ms": duration(
                llm_start, first_audio
            ),
            "voice_turn_to_first_audio_submission_ms": duration(
                trace.started_at, first_audio
            ),
            "first_audio_before_llm_complete": (
                first_audio < llm_complete
                if first_audio is not None and llm_complete is not None
                else None
            ),
            "first_audio_lead_before_llm_complete_ms": lead,
        }

    def _streaming_segment_snapshot(
        self,
        states: Mapping[int, Mapping[str, object]],
        *,
        tts_queue: TTSQueue | None = None,
    ) -> list[dict[str, object]]:
        with self._lock:
            snapshot = {index: dict(state) for index, state in states.items()}
        if tts_queue is not None:
            terminal_events = {
                "segment_completed": "completed",
                "segment_failed": "failed",
                "segment_cancelled": "cancelled",
                "stale_dropped": "stale",
            }
            for entry in tts_queue.diagnostics:
                status = terminal_events.get(str(entry.get("event", "")))
                index = entry.get("segment_index")
                if status is None or not isinstance(index, int) or index not in snapshot:
                    continue
                current = snapshot[index].get("status")
                if current not in {"completed", "failed", "cancelled", "stale"}:
                    snapshot[index]["status"] = status
        return [snapshot[index] for index in sorted(snapshot)]

    @staticmethod
    def _tts_provider_name(provider: TextToSpeechProvider) -> str:
        return type(provider).__name__

    @staticmethod
    def _streaming_failure(
        report: StreamingPlaybackReport,
    ) -> "_StreamingStageError":
        metrics = report.diagnostics.get("metrics", {})
        if isinstance(metrics, Mapping):
            for key, stage in (
                ("playback_error", "playback"),
                ("provider_error", "tts"),
                ("producer_error", "tts"),
            ):
                message = metrics.get(key)
                if message:
                    return _StreamingStageError(stage, str(message))
        return _StreamingStageError(
            "playback", str(report.diagnostics.get("reason", report.status))
        )

    @staticmethod
    def _streaming_metrics(
        *,
        selected: bool,
        provider: str,
        status: str,
        report: StreamingPlaybackReport | None,
    ) -> dict[str, object]:
        metrics: dict[str, object] = {
            "tts_provider": provider,
            "streaming_selected": selected,
            "streaming_status": status,
        }
        if report is None:
            return metrics
        source = report.diagnostics.get("metrics", {})
        if not isinstance(source, Mapping):
            return metrics
        for key in (
            "request_to_first_audio_submission_ms",
            "upstream_end_monotonic",
            "playback_end_monotonic",
            "underrun_count",
            "buffer_peak_bytes",
            "cancel_latency_ms",
            "producer_error",
            "playback_error",
            "provider_close_error",
        ):
            metrics[f"streaming_{key}"] = source.get(key)
        return metrics

    @staticmethod
    def _streaming_metric_value(
        report: StreamingPlaybackReport | None,
        key: str,
        default: object,
    ) -> object:
        if report is None:
            return default
        metrics = report.diagnostics.get("metrics", {})
        if not isinstance(metrics, Mapping):
            return default
        value = metrics.get(key)
        return default if value is None else value

    @staticmethod
    def _voice_trace(
        report: StreamingPlaybackReport | None,
        provider_diagnostics: Mapping[str, object] | None,
        tts_queue: TTSQueue | None,
        *,
        turn_trace: VoiceTurnTrace | None = None,
        streaming_segments: list[dict[str, object]] | None = None,
    ) -> dict[str, object]:
        trace: dict[str, object] = {}
        if report is not None:
            trace["streaming_playback"] = dict(report.diagnostics)
        if provider_diagnostics is not None:
            trace["streaming_provider"] = dict(provider_diagnostics)
        if tts_queue is not None:
            trace["speech_segments"] = [dict(item) for item in tts_queue.diagnostics]
        if turn_trace is not None:
            trace["turn_timing"] = turn_trace.snapshot()
        if streaming_segments:
            trace["streaming_segments"] = [dict(item) for item in streaming_segments]
        return trace

    @staticmethod
    def _stage_for_error(error: Exception) -> str:
        if isinstance(error, _StreamingStageError):
            return error.stage
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


class _StreamingStageError(RuntimeError):
    """Preserve whether a terminal streaming failure came from TTS or output."""

    def __init__(self, stage: str, message: str) -> None:
        self.stage = stage
        super().__init__(f"streaming {stage} failed: {message}")
