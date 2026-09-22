"""Instance-local, best-effort post-turn scheduling; no persistent job queue."""
from __future__ import annotations

from collections import deque
from copy import deepcopy
import logging
import threading
from time import monotonic

from modules.conversation import TITLE_GENERATION_IDLE_SECONDS, _trigger_conversation_memory
from modules.conversation_intelligence import (
    analyze_conversation, generate_title_summary, TITLE_GENERATION_MAX_TOKENS,
    TITLE_GENERATION_TIMEOUT_SECONDS,
)

LOGGER = logging.getLogger("aurora-v4-post-turn")
AUTO_TITLES = {"New Conversation", "新对话", ""}


class Deferred(Exception):
    pass


class PostTurnCoordinator:
    """One daemon worker, one idle gate, sequential business calls.

    Built-in title transport is actively cancelled on foreground start. Legacy
    non-streaming urlopen keeps its existing timeout boundary. Shutdown invalidates
    publication and drops pending work; the daemon cannot keep the process alive.
    """

    def __init__(self, composition, chat_api, changed, *, idle_seconds=TITLE_GENERATION_IDLE_SECONDS,
                 clock=monotonic):
        self.composition, self.chat_api, self.changed = composition, chat_api, changed
        self.idle_seconds, self.clock = idle_seconds, clock
        self.condition = threading.Condition(threading.RLock())
        self.pending = deque()
        self.seen = set()
        self.title_attempts = set()
        self.foreground = None
        self.epoch = 0
        self.idle_since = clock()
        self.closed = False
        self.worker = None
        self.events = deque(maxlen=256)

    def record(self, event, job=None, **values):
        item = dict(event=event, monotonic=self.clock(), **values)
        if job:
            item.update(conversation_id=job["conversation_id"][-8:], generation_id=job["generation_id"][-8:])
        with self.condition:
            self.events.append(item)
        LOGGER.info("post_turn %s", item)

    def foreground_started(self, generation_id):
        with self.condition:
            self.foreground = generation_id
            self.epoch += 1
            if self.pending:
                self.record("deferred_foreground")
            self.condition.notify_all()
        # Invalidate publication BEFORE transport abort wakes the title worker.
        provider = getattr(self.composition, "local_provider", None)
        if provider is not None:
            provider.foreground_started()

    def foreground_finished(self, generation_id):
        with self.condition:
            if self.foreground == generation_id:
                self.foreground = None
                provider = getattr(self.composition, "local_provider", None)
                if provider is not None:
                    provider.foreground_finished()
                self.idle_since = self.clock()
                self.condition.notify_all()

    def schedule(self, conversation_id, generation_id, messages, model, *, status="completed", settings_snapshot=None):
        with self.condition:
            key = (conversation_id, generation_id)
            if self.closed or status != "completed" or key in self.seen:
                return False
            self.seen.add(key)
            self.pending.append(dict(conversation_id=conversation_id, generation_id=generation_id,
                                     messages=deepcopy(messages), model=model, cpu_done=False,
                                     settings_snapshot=settings_snapshot))
            self.record("scheduled", self.pending[-1])
            if self.worker is None:
                self.worker = threading.Thread(target=self._run, name="post-turn", daemon=True)
                self.worker.start()
            self.condition.notify_all()
            return True

    def _guard(self, epoch):
        with self.condition:
            if self.closed or self.foreground is not None or self.epoch != epoch:
                raise Deferred()

    def _run(self):
        while True:
            with self.condition:
                while not self.closed:
                    delay = self.idle_seconds - (self.clock() - self.idle_since)
                    if self.pending and self.foreground is None and delay <= 0:
                        job, epoch = self.pending[0], self.epoch
                        break
                    self.condition.wait(timeout=max(0.001, delay) if self.pending and self.foreground is None else None)
                else:
                    return
            try:
                self._guard(epoch)
                self.record("started", job)
                self._process(job, epoch)
            except Deferred:
                self.record("deferred_foreground", job)
                continue
            except Exception as error:
                self.record("failed", job, error_code=type(error).__name__)
            else:
                self.record("completed", job)
            with self.condition:
                if self.pending and self.pending[0] is job:
                    self.pending.popleft()

    def _publish(self, job):
        # Callback only schedules a safe metadata event, never waits for UI.
        detail = self.composition.conversations.get(job["conversation_id"])
        with self.condition:
            if not self.closed:
                self.changed({key: value for key, value in detail.items() if key != "messages"})

    def _process(self, job, epoch):
        store = self.composition.conversations
        cid, messages = job["conversation_id"], job["messages"]
        if not job["cpu_done"]:
            # Preserve production algorithms. Candidate creation is CPU/IO only;
            # no approve/save_candidates/delete/archive/forget operation here.
            started = self.clock()
            self._guard(epoch)
            # No scheduler lock around CPU/IO: accepted foreground hooks must
            # remain prompt even when the filesystem is slow. These local
            # operations finish best-effort; no model slot is occupied.
            try:
                memory = self.composition.context.memory
                memory.file_path.parent.mkdir(parents=True, exist_ok=True)
                candidates = memory.queue_candidates(messages, source="chat")
                self.record("memory_completed", job, duration_ms=(self.clock()-started)*1000,
                            candidates_created=len(candidates))
            except Exception as error:
                self.record("memory_failed", job, error_code=type(error).__name__)
            started = self.clock()
            try:
                analysis = analyze_conversation(messages)
                with store.transaction(cid):
                    current = store.manager.load(cid)
                    if not self.closed and current.get("messages") == messages:
                        saved = store.manager.save_conversation_intelligence(cid, analysis)
                        _trigger_conversation_memory(store.manager, cid, messages, analysis, saved,
                                                     memory_store=self.composition.context.memory)
                self.record("intelligence_completed", job, duration_ms=(self.clock()-started)*1000)
            except Exception as error:
                self.record("intelligence_failed", job, error_code=type(error).__name__)
            job["cpu_done"] = True
            self._publish(job)

        with store.transaction(cid):
            current = store.manager.load(cid)
        eligible = (sum(m.get("role") == "user" for m in messages) == 1
                    and sum(m.get("role") == "assistant" for m in messages) == 1
                    and current.get("title", "") in AUTO_TITLES
                    and not current.get("metadata", {}).get("title_manual"))
        if not eligible or cid in self.title_attempts:
            return
        diagnostics = {}
        def call(prompt):
            # Last guard is at the actual model-call boundary, after CPU/IO.
            self._guard(epoch)
            self.title_attempts.add(cid)
            started = self.clock()
            self.record("title_started", job, wait_ms=(started-self.idle_since)*1000)
            request_diagnostics = {}
            try:
                settings_args = ({"settings_store": job["settings_snapshot"]}
                                 if job.get("settings_snapshot") is not None else {})
                result = self.chat_api["chat_with_messages"](
                    job["model"], [{"role": "user", "content": prompt}],
                    timeout=TITLE_GENERATION_TIMEOUT_SECONDS, thinking_mode="off",
                    num_predict=TITLE_GENERATION_MAX_TOKENS, diagnostics=request_diagnostics, **settings_args)
                self._guard(epoch)
                return result
            except Exception:
                if getattr(self.composition, "local_provider", None) is not None:
                    try:
                        self._guard(epoch)
                    except Deferred:
                        self.title_attempts.discard(cid)
                        raise
                raise
            finally:
                self.record("title_request_finished", job, duration_ms=(self.clock()-started)*1000,
                            **request_diagnostics)
        title, source = generate_title_summary(messages, job["model"], llm_call=call, diagnostics=diagnostics)
        # Production title helper catches exceptions for rule fallback; a guard
        # deferral must NOT be mistaken for a failed model attempt.
        if diagnostics.get("error_type") == "Deferred":
            raise Deferred()
        with store.transaction(cid):
            if self.closed:
                return
            saved = store.manager.update_title_if_auto(cid, title, expected_title=current.get("title"))
            if saved is not None:
                analysis = saved.get("metadata", {}).get("conversation_intelligence", {}).copy()
                analysis.update(title_summary=title, title_source=source)
                store.manager.save_conversation_intelligence(cid, analysis)
        self.record("title_completed", job, source=source, status=diagnostics.get("llm_status"))
        self._publish(job)

    def close(self):
        with self.condition:
            self.closed = True
            self.pending.clear()
            self.condition.notify_all()
        provider = getattr(self.composition, "local_provider", None)
        if provider is not None:
            provider.cancel_background()
        if self.worker is not None and self.worker is not threading.current_thread():
            self.worker.join(timeout=0.25)
