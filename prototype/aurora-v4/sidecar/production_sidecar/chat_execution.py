"""Single owned generation, bounded blocking→async bridge, one terminal."""
from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import threading
from dataclasses import dataclass, field
from time import monotonic, time

from websockets.exceptions import ConnectionClosed
from production_sidecar.direct_chat import ChatRequest, DirectChatAdapter

LOGGER = logging.getLogger("aurora-v4-chat")
TIMING_KEYS = (
    "request_to_headers_ms", "request_to_first_model_output_ms", "request_to_first_content_ms",
    "first_raw_to_first_content_ms", "load_duration_ms", "prompt_eval_duration_ms",
    "eval_duration_ms", "total_duration_ms", "stream_total_ms", "cancel_transport_latency_ms",
    "prompt_eval_count", "eval_count", "reasoning_chars",
)


@dataclass
class Execution:
    request: ChatRequest
    connection: object
    handle: object
    queue: asyncio.Queue = field(default_factory=lambda: asyncio.Queue(maxsize=16))
    task: asyncio.Task | None = None
    terminal: str | None = None
    cancel_at: float | None = None
    received_at: float = field(default_factory=monotonic)
    received_unix_ms: float = field(default_factory=lambda: time() * 1000)
    started_at: float | None = None
    first_delta_at: float | None = None
    seq: int = 0
    output_chars: int = 0
    ack_pending: bool = False
    ack_done: asyncio.Event = field(default_factory=asyncio.Event)


class ChatExecution:
    def __init__(self, sidecar):
        self.sidecar = sidecar
        self.adapter = DirectChatAdapter(sidecar.composition)
        self.active = None
        self.last = None  # bounded one-generation terminal tombstone for repeat cancel

    async def send(self, run, kind, payload, **extra):
        r = run.request
        await self.sidecar.send(run.connection, {
            "protocol": "aurora-ipc", "version": 1, "type": kind,
            "request_id": r.request_id, "session_id": r.session_id,
            "generation_id": r.generation_id, "payload": payload, **extra,
        })

    async def start(self, connection, message):
        request = ChatRequest(message["request_id"], message["session_id"],
                              message["generation_id"], message["payload"]["input"])
        # Register then reject so even concurrent attempts have a unique terminal.
        run = Execution(request, connection, self.adapter.new_handle(threading.Event(), {}))
        for previous in (self.active, self.last):
            if previous and (previous.request.request_id == request.request_id or
                             previous.request.generation_id == request.generation_id):
                # A replay must never create a second terminal for an owned ID.
                return
        if self.active is not None:
            await self.send(run, "chat.accepted", {"status": "accepted", "ipc_received_unix_ms": run.received_unix_ms})
            await self.send(run, "chat.completed", {"terminal_state": "rejected",
                "error": {"code": "BACKEND_NOT_READY", "message": "Another generation is active.", "retryable": True}})
            return
        self.active = run  # ownership before first await
        try:
            await self.send(run, "chat.accepted", {"status": "accepted", "ipc_received_unix_ms": run.received_unix_ms})
        except BaseException:
            self.active = None
            raise
        run.task = asyncio.create_task(self.execute(run), name="production-generation")

    async def execute(self, run):
        worker = None
        status, code = "completed", None
        try:
            health = await self.sidecar.composition.refresh()
            probe = health["ollama"]
            if not probe["reachable"]:
                code = "PROVIDER_UNAVAILABLE"
            elif not probe["model_available"]:
                code = "MODEL_UNAVAILABLE"
            if code:
                status = "failed"
            elif not run.handle.stop_event.is_set():
                loop = asyncio.get_running_loop()
                run.started_at = monotonic()

                def forward(chunk):
                    # Each event stays well under the IPC byte limit, even UTF-8.
                    for offset in range(0, len(chunk), 4096):
                        if run.handle.stop_event.is_set():
                            raise InterruptedError("Generation cancelled during forwarding")
                        future = asyncio.run_coroutine_threadsafe(run.queue.put(chunk[offset:offset + 4096]), loop)
                        while not run.handle.stop_event.is_set():
                            try:
                                future.result(timeout=0.02)
                                break
                            except concurrent.futures.TimeoutError:
                                continue
                        else:
                            future.cancel()
                            raise InterruptedError("Generation cancelled during backpressure")
                    if run.handle.stop_event.is_set():
                        raise InterruptedError("Generation cancelled during forwarding")

                worker = asyncio.create_task(asyncio.to_thread(
                    self.adapter.stream, run.request, probe["configured_model"], run.handle, forward))
                while not worker.done() or not run.queue.empty():
                    try:
                        delta = await asyncio.wait_for(run.queue.get(), 0.02)
                    except asyncio.TimeoutError:
                        continue
                    if run.handle.stop_event.is_set() or self.active is not run:
                        continue
                    run.first_delta_at = run.first_delta_at or monotonic()
                    await self.send(run, "chat.delta", {"delta": delta, "python_sent_unix_ms": time() * 1000}, seq=run.seq)
                    run.seq += 1
                    run.output_chars += len(delta)
                await worker  # rethrow real transport errors after draining accepted deltas
        except asyncio.CancelledError:
            run.cancel_at = run.cancel_at or monotonic()
            run.handle.stop_event.set()
        except ConnectionClosed:
            status = "backend_lost"
            run.handle.stop_event.set()
        except Exception as error:
            status, code = "failed", self.adapter.error_code(error)
        finally:
            # No terminal/reuse until the actual blocking worker has exited.
            if run.handle.stop_event.is_set():
                await asyncio.to_thread(run.handle.cancel)
            if worker is not None:
                await asyncio.gather(worker, return_exceptions=True)
            await asyncio.to_thread(run.handle.close)
            if run.ack_pending:
                await run.ack_done.wait()
            if run.cancel_at is not None:
                status, code = "cancelled", None
            elif run.handle.stop_event.is_set():
                status, code = "backend_lost", "BACKEND_LOST"
            run.terminal = status  # one loop-owned atomic winner before send yields
            if self.active is run:
                self.active = None
                self.last = run
            now = monotonic()
            diagnostics = {key: run.handle.diagnostics.get(key) for key in TIMING_KEYS}
            diagnostics.update({
                "ipc_to_stream_start_ms": (run.started_at - run.received_at) * 1000 if run.started_at else None,
                "ipc_to_first_delta_ms": (run.first_delta_at - run.received_at) * 1000 if run.first_delta_at else None,
                "ipc_to_terminal_ms": (now - run.received_at) * 1000,
                "cancel_to_terminal_ms": (now - run.cancel_at) * 1000 if run.cancel_at else None,
                "active_response": run.handle.active_response is not None,
                "worker_exited": worker is None or worker.done(),
                **self.sidecar.composition.settings.policy.diagnostics(),
            })
            payload = {"terminal_state": status, "output_chars": run.output_chars,
                       "duration_ms": (now - run.received_at) * 1000, "diagnostics": diagnostics}
            if code:
                payload["error"] = {"code": code, "message": "Chat request could not complete.", "retryable": True}
            LOGGER.info("event=direct_chat_terminal generation=%s status=%s deltas=%s error=%s",
                        run.request.generation_id[-8:], status, run.seq, code or "")
            try:
                await self.send(run, "chat.completed", payload)
            except ConnectionClosed:
                pass

    async def cancel(self, connection, message):
        candidate = self.active or self.last
        match = candidate is not None and candidate.connection is connection and (
            candidate.request.session_id == message["session_id"] and
            candidate.request.generation_id == message["generation_id"] and
            candidate.request.request_id == message["payload"]["target_request_id"])
        outcome = "not_found"
        try:
            if match:
                if candidate.terminal:
                    outcome = "cancelled" if candidate.terminal == "cancelled" else "already_completed"
                else:
                    outcome = "cancel_requested"
                    candidate.cancel_at = candidate.cancel_at or monotonic()
                    candidate.ack_pending = True
                    candidate.handle.stop_event.set()  # truth before socket side effects
                    await asyncio.to_thread(candidate.handle.cancel)
            await self.sidecar.send(connection, {**message, "type": "chat.cancel.ack",
                "payload": {"target_request_id": message["payload"]["target_request_id"], "outcome": outcome}})
        finally:
            if match:
                candidate.ack_done.set()

    async def close(self, connection=None):
        run = self.active
        if run is not None and (connection is None or run.connection is connection):
            run.cancel_at = run.cancel_at or monotonic()
            run.handle.stop_event.set()
            await asyncio.to_thread(run.handle.cancel)
            if run.task:
                await asyncio.gather(run.task, return_exceptions=True)
