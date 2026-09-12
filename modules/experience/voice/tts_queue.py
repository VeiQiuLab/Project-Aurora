"""Single-worker FIFO queue for generation-owned Voice TTS segments."""

from __future__ import annotations

from queue import Empty, Queue
from threading import Event, Lock, Thread
from typing import Callable, Generic, Mapping, TypeVar

from modules.logger import logger

from .latency import VoiceTurnTrace
from .models import SpeechSegment


Speech = TypeVar("Speech")
SynthesizeCallback = Callable[[SpeechSegment, Event], Speech]
SpeechCallback = Callable[[SpeechSegment, Speech], None]
GenerationActive = Callable[[str, str], bool]
GenerationFailed = Callable[[SpeechSegment, Exception], None]


class TTSQueue(Generic[Speech]):
    """Synthesize immutable speech segments in FIFO order on one worker."""

    _STOP = object()

    def __init__(
        self,
        synthesize: SynthesizeCallback[Speech],
        *,
        on_speech: SpeechCallback[Speech] | None = None,
        cancel_event: Event | None = None,
        latency_trace: VoiceTurnTrace | None = None,
        session_id: str = "",
        generation_id: str = "",
        generation_active: GenerationActive | None = None,
        on_generation_failed: GenerationFailed | None = None,
    ):
        if not callable(synthesize):
            raise TypeError("synthesize must be callable")
        if on_speech is not None and not callable(on_speech):
            raise TypeError("on_speech must be callable or None")
        if generation_active is not None and not callable(generation_active):
            raise TypeError("generation_active must be callable or None")
        if on_generation_failed is not None and not callable(on_generation_failed):
            raise TypeError("on_generation_failed must be callable or None")
        self._synthesize = synthesize
        self._on_speech = on_speech
        self._on_generation_failed = on_generation_failed
        self.cancel_event = cancel_event or Event()
        self.latency_trace = latency_trace
        self.session_id = str(session_id)
        self.generation_id = str(generation_id)
        self._generation_active = generation_active
        self._items: Queue[SpeechSegment | object] = Queue()
        self._lock = Lock()
        self._diagnostics_lock = Lock()
        self._worker: Thread | None = None
        self._closed = False
        self._failed = False
        self._last_error: Exception | None = None
        self._pending = 0
        self._next_enqueue_index = 0
        self._last_dequeued_index = -1
        self._diagnostics: list[dict[str, object]] = []
        self._idle = Event()
        self._idle.set()

    @property
    def last_error(self) -> Exception | None:
        with self._lock:
            return self._last_error

    @property
    def running(self) -> bool:
        with self._lock:
            return self._worker is not None and self._worker.is_alive()

    @property
    def diagnostics(self) -> tuple[Mapping[str, object], ...]:
        with self._diagnostics_lock:
            return tuple(dict(item) for item in self._diagnostics)

    def start(self) -> None:
        """Start the single queue worker; repeated calls are harmless."""

        with self._lock:
            if self._closed:
                raise RuntimeError("TTSQueue is closed")
            if self._worker is not None and self._worker.is_alive():
                return
            self._idle.clear() if self._pending else self._idle.set()
            self._worker = Thread(target=self._run, name="aurora-tts-queue", daemon=True)
            worker = self._worker
        worker.start()

    def put(self, segment: SpeechSegment) -> bool:
        """Append an active, generation-owned segment to the FIFO queue."""

        if not isinstance(segment, SpeechSegment):
            raise TypeError("segment must be a SpeechSegment")
        if not self._matches_queue_scope(segment) or not self._is_segment_active(segment):
            self._record("stale_dropped", segment, checkpoint="enqueue")
            return False

        anomaly = ""
        expected_index = 0
        with self._lock:
            if self._closed:
                raise RuntimeError("TTSQueue is closed")
            expected_index = self._next_enqueue_index
            if self._failed or self.cancel_event.is_set() or not self._is_segment_active(segment):
                accepted = False
            elif segment.segment_index < expected_index:
                anomaly = "duplicate_or_lower_index"
                accepted = False
            else:
                if segment.segment_index > expected_index:
                    anomaly = "skipped_index"
                self._next_enqueue_index = segment.segment_index + 1
                self._pending += 1
                self._idle.clear()
                self._items.put(segment)
                accepted = True

        if anomaly:
            self._record(
                "ordering_anomaly",
                segment,
                reason=anomaly,
                expected_index=expected_index,
            )
        if not accepted:
            self._record("stale_dropped", segment, checkpoint="enqueue")
            return False
        self._record("segment_enqueued", segment)
        return True

    def note_emitted(self, segment: SpeechSegment) -> None:
        """Record the owner-side emit checkpoint before enqueue."""

        if not isinstance(segment, SpeechSegment):
            raise TypeError("segment must be a SpeechSegment")
        self._record("segment_emitted", segment)

    def is_segment_active(self, segment: SpeechSegment) -> bool:
        """Return whether a segment still belongs to this active queue generation."""

        if not isinstance(segment, SpeechSegment):
            return False
        return self._matches_queue_scope(segment) and self._is_segment_active(segment)

    def clear_current_generation(self) -> int:
        """Discard queued segments without affecting an item already executing."""

        return self._discard_pending(event="segment_cancelled")

    def flush(self, timeout_seconds: float | None = None) -> bool:
        """Wait until all accepted segments have finished or been discarded."""

        if timeout_seconds is not None and timeout_seconds < 0:
            raise ValueError("timeout_seconds must be non-negative")
        return self._idle.wait(timeout_seconds)

    def cancel(self, *, wait: bool = True, timeout_seconds: float | None = 5.0) -> bool:
        """Abort this generation, discard queued work, and stop its worker."""

        self.cancel_event.set()
        with self._lock:
            already_closed = self._closed
            self._closed = True
            worker = self._worker
        if not already_closed:
            self._discard_pending(event="segment_cancelled")
            if worker is not None:
                self._items.put(self._STOP)
        if wait and worker is not None:
            worker.join(timeout_seconds)
        return worker is None or not worker.is_alive()

    def shutdown(self, *, wait: bool = True, timeout_seconds: float | None = 5.0) -> bool:
        """Abort all queue work and join the worker when requested."""

        return self.cancel(wait=wait, timeout_seconds=timeout_seconds)

    def close(self, *, wait: bool = True, timeout_seconds: float | None = 5.0) -> bool:
        """Drain accepted work, then stop the worker without cancelling it."""

        with self._lock:
            if self._closed:
                worker = self._worker
            else:
                self._closed = True
                worker = self._worker
                if worker is not None:
                    self._items.put(self._STOP)
        if worker is None:
            self._discard_pending(event="stale_dropped")
        if wait:
            if not self.flush(timeout_seconds):
                return False
            if worker is not None:
                worker.join(timeout_seconds)
        return worker is None or not worker.is_alive()

    def _run(self) -> None:
        while True:
            item = self._items.get()
            try:
                if item is self._STOP:
                    return
                assert isinstance(item, SpeechSegment)
                segment = item
                self._record("segment_dequeued", segment)
                if not self._is_segment_active(segment):
                    self._record("stale_dropped", segment, checkpoint="dequeue")
                    continue
                if segment.segment_index <= self._last_dequeued_index:
                    self._record(
                        "ordering_anomaly",
                        segment,
                        reason="non_increasing_dequeue",
                    )
                    self._record("stale_dropped", segment, checkpoint="dequeue_order")
                    continue
                self._last_dequeued_index = segment.segment_index
                if not self._is_segment_active(segment):
                    self._record("stale_dropped", segment, checkpoint="before_tts")
                    continue

                if self.latency_trace:
                    self.latency_trace.mark("first_tts_start", first=True)
                self._record("segment_tts_started", segment)
                speech = self._synthesize(segment, self.cancel_event)
                if not self._is_segment_active(segment):
                    self._record_cancel_or_stale(segment, checkpoint="after_tts")
                    continue
                self._record("segment_tts_completed", segment)
                if self._on_speech is not None:
                    self._record("segment_playback_started", segment)
                    self._on_speech(segment, speech)
                    if not self._is_segment_active(segment):
                        self._record_cancel_or_stale(segment, checkpoint="after_playback")
                        continue
                self._record("segment_completed", segment)
            except Exception as error:
                if item is not self._STOP and isinstance(item, SpeechSegment):
                    if self.cancel_event.is_set() or not self._is_segment_active(item):
                        self._record_cancel_or_stale(item, checkpoint="error", error=error)
                    else:
                        self._fail_generation(item, error)
            finally:
                if item is not self._STOP:
                    with self._lock:
                        self._pending = max(self._pending - 1, 0)
                        if self._pending == 0:
                            self._idle.set()
                self._items.task_done()

    def _fail_generation(self, segment: SpeechSegment, error: Exception) -> None:
        with self._lock:
            if self._failed:
                return
            self._failed = True
            self._last_error = error
        self._record("segment_failed", segment, error=type(error).__name__)
        if self._on_generation_failed is not None:
            try:
                self._on_generation_failed(segment, error)
            except Exception as callback_error:
                logger.warning(f"TTSQueue generation failure callback failed: {callback_error}")
        self._discard_pending(event="stale_dropped", reason="generation_failed")

    def _discard_pending(self, *, event: str, reason: str = "") -> int:
        discarded: list[SpeechSegment] = []
        stop_seen = False
        while True:
            try:
                item = self._items.get_nowait()
            except Empty:
                break
            if item is self._STOP:
                self._items.task_done()
                stop_seen = True
                continue
            assert isinstance(item, SpeechSegment)
            discarded.append(item)
            self._items.task_done()
        if discarded:
            with self._lock:
                self._pending = max(self._pending - len(discarded), 0)
                if self._pending == 0:
                    self._idle.set()
            for segment in discarded:
                self._record(event, segment, checkpoint="pending", reason=reason)
        if stop_seen:
            self._items.put(self._STOP)
        return len(discarded)

    def _matches_queue_scope(self, segment: SpeechSegment) -> bool:
        return (
            (not self.session_id or segment.session_id == self.session_id)
            and (not self.generation_id or segment.generation_id == self.generation_id)
        )

    def _is_segment_active(self, segment: SpeechSegment) -> bool:
        if self.cancel_event.is_set() or self._failed or not self._matches_queue_scope(segment):
            return False
        return self._generation_active is None or self._generation_active(
            segment.session_id, segment.generation_id
        )

    def _record_cancel_or_stale(
        self,
        segment: SpeechSegment,
        *,
        checkpoint: str,
        error: Exception | None = None,
    ) -> None:
        event = "segment_cancelled" if self.cancel_event.is_set() else "stale_dropped"
        fields: dict[str, object] = {"checkpoint": checkpoint}
        if error is not None:
            fields["error"] = type(error).__name__
        self._record(event, segment, **fields)

    def _record(self, event: str, segment: SpeechSegment, **fields: object) -> None:
        entry: dict[str, object] = {
            "event": event,
            "session_id": segment.session_id,
            "generation_id": segment.generation_id,
            "segment_index": segment.segment_index,
            "text_length": len(segment.text),
            **fields,
        }
        with self._diagnostics_lock:
            self._diagnostics.append(entry)
        details = " ".join(f"{key}={value!r}" for key, value in entry.items())
        logger.info(f"[VOICE_SEGMENT] {details}")
