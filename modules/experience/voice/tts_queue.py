"""Single-worker FIFO queue for incremental Voice TTS preparation."""

from __future__ import annotations

from queue import Empty, Queue
from threading import Event, Lock, Thread
from typing import Callable, Generic, TypeVar

from modules.logger import logger

from .latency import VoiceTurnTrace

Speech = TypeVar("Speech")
SynthesizeCallback = Callable[[str, Event], Speech]
SpeechCallback = Callable[[str, Speech], None]
GenerationActive = Callable[[str], bool]


class TTSQueue(Generic[Speech]):
    """Synthesize queued sentences in order on one background worker."""

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
    ):
        if not callable(synthesize):
            raise TypeError("synthesize must be callable")
        if on_speech is not None and not callable(on_speech):
            raise TypeError("on_speech must be callable or None")
        self._synthesize = synthesize
        self._on_speech = on_speech
        self.cancel_event = cancel_event or Event()
        self.latency_trace = latency_trace
        self.session_id = str(session_id)
        self.generation_id = str(generation_id)
        self._generation_active = generation_active
        self._items: Queue[str | object] = Queue()
        self._lock = Lock()
        self._worker: Thread | None = None
        self._closed = False
        self._last_error: Exception | None = None
        self._pending = 0
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

    def put(
        self,
        text: str,
        *,
        session_id: str | None = None,
        generation_id: str | None = None,
    ) -> None:
        """Append one non-empty sentence to the FIFO queue."""

        if not isinstance(text, str):
            raise TypeError("text must be a string")
        if not text.strip():
            return
        if session_id is not None and str(session_id) != self.session_id:
            logger.info(
                f"[VOICE] session={self.session_id or '-'} generation={self.generation_id} "
                f"event=discard_stale_enqueue received_session={session_id!r}"
            )
            return
        if generation_id is not None and str(generation_id) != self.generation_id:
            logger.info(
                f"[VOICE] session={self.session_id or '-'} generation={self.generation_id} "
                f"event=discard_stale_enqueue received_generation={generation_id!r}"
            )
            return
        with self._lock:
            if self._closed:
                raise RuntimeError("TTSQueue is closed")
            self._pending += 1
            self._idle.clear()
        if not self.is_generation_active():
            logger.info(
                f"[VOICE] session={self.session_id or '-'} generation={self.generation_id} "
                "event=discard_stale_enqueue reason=inactive"
            )
            with self._lock:
                self._pending -= 1
                if self._pending == 0:
                    self._idle.set()
            return
        self._items.put(text)
        elapsed = self.latency_trace.now_elapsed_ms() if self.latency_trace else None
        logger.info(
            f"[VOICE_TTS_QUEUE] enqueue: sentence={text!r} "
            f"elapsed_ms={elapsed if elapsed is not None else 'n/a'}"
        )

    def is_generation_active(self) -> bool:
        return not self.cancel_event.is_set() and (
            self._generation_active is None or self._generation_active(self.generation_id)
        )

    def clear_current_generation(self) -> int:
        discarded = 0
        while True:
            try:
                self._items.get_nowait()
            except Empty:
                break
            else:
                discarded += 1
                self._items.task_done()
        if discarded:
            with self._lock:
                self._pending = max(self._pending - discarded, 0)
                if self._pending == 0:
                    self._idle.set()
        return discarded

    def flush(self, timeout_seconds: float | None = None) -> bool:
        """Wait until all currently queued sentences have been consumed."""

        if timeout_seconds is not None and timeout_seconds < 0:
            raise ValueError("timeout_seconds must be non-negative")
        return self._idle.wait(timeout_seconds)

    def cancel(self, *, wait: bool = True, timeout_seconds: float | None = 5.0) -> bool:
        """Cancel pending work and stop the worker after the active item returns."""

        self.cancel_event.set()
        with self._lock:
            already_closed = self._closed
            self._closed = True
            worker = self._worker
        if worker is None:
            self._discard_pending()
        elif not already_closed:
            self._items.put(self._STOP)
        if wait and worker is not None:
            worker.join(timeout_seconds)
        return worker is None or not worker.is_alive()

    def close(self, *, wait: bool = True, timeout_seconds: float | None = 5.0) -> bool:
        """Drain queued work, then stop the worker without cancelling it."""

        with self._lock:
            if self._closed:
                worker = self._worker
            else:
                self._closed = True
                worker = self._worker
                if worker is None:
                    self._discard_pending()
                else:
                    self._items.put(self._STOP)
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
                if not self.is_generation_active():
                    logger.info(
                        f"[VOICE] session={self.session_id or '-'} generation={self.generation_id} "
                        "event=discard_stale_tts"
                    )
                    continue
                if self.latency_trace:
                    self.latency_trace.mark("first_tts_start", first=True)
                    elapsed = self.latency_trace.now_elapsed_ms()
                else:
                    elapsed = None
                logger.info(
                    f"[VOICE_TTS_QUEUE] tts_start: sentence={item!r} "
                    f"elapsed_ms={elapsed if elapsed is not None else 'n/a'}"
                )
                speech = self._synthesize(item, self.cancel_event)
                if not self.is_generation_active():
                    logger.info(
                        f"[VOICE] session={self.session_id or '-'} generation={self.generation_id} "
                        "event=discard_stale_speech"
                    )
                    continue
                if self._on_speech is not None:
                    self._on_speech(item, speech)
            except Exception as error:
                with self._lock:
                    self._last_error = error
            finally:
                if item is not self._STOP:
                    with self._lock:
                        self._pending -= 1
                        if self._pending == 0:
                            self._idle.set()
                self._items.task_done()

    def _discard_pending(self) -> None:
        discarded = 0
        while True:
            try:
                self._items.get_nowait()
            except Empty:
                break
            else:
                discarded += 1
                self._items.task_done()
        if discarded:
            with self._lock:
                self._pending = max(self._pending - discarded, 0)
        with self._lock:
            if self._pending == 0:
                self._idle.set()
