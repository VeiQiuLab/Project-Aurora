"""Aurora v4 mock sidecar.

This process validates lifecycle and IPC only. It must not import stable Aurora
AI, persistence, or voice modules.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from dataclasses import dataclass
from http import HTTPStatus
from pathlib import Path
from time import monotonic
from typing import Any
from uuid import uuid4

from websockets.asyncio.server import ServerConnection, serve
from websockets.exceptions import ConnectionClosed


V4_ROOT = Path(__file__).resolve().parents[2]
CONTRACT_DIR = V4_ROOT / "contracts"
sys.path.insert(0, str(CONTRACT_DIR))
from validate_contracts import ContractError, validate_message  # noqa: E402


PROTOCOL = "aurora-ipc"
VERSION = 1
BOOTSTRAP_MAX_BYTES = 8192
JSON_FRAME_MAX_BYTES = 1_048_576
CHAT_INPUT_MAX_BYTES = 262_144
EVENT_MAX_BYTES = 262_144
BINARY_FRAME_MAX_BYTES = 262_144
MOCK_CHUNKS = (
    "Aurora ",
    "v4 ",
    "keeps ",
    "the ",
    "desktop ",
    "responsive ",
    "while ",
    "an ",
    "isolated ",
    "Python ",
    "sidecar ",
    "streams ",
    "ordered ",
    "synthetic ",
    "tokens. ",
    "The ",
    "Rust ",
    "gateway ",
    "validates ",
    "request, ",
    "session, ",
    "generation, ",
    "sequence, ",
    "and ",
    "terminal ",
    "ownership ",
    "before ",
    "updating ",
    "the ",
    "WebView.",
)


logging.basicConfig(
    level=logging.INFO,
    stream=sys.stderr,
    format="%(asctime)s %(levelname)s %(message)s",
)
LOGGER = logging.getLogger("aurora-v4-mock-sidecar")


@dataclass
class Generation:
    request_id: str
    session_id: str
    generation_id: str
    task: asyncio.Task[None] | None = None
    cancel_requested: bool = False
    cancel_ack_sent: asyncio.Event | None = None
    terminal_state: str | None = None

    @property
    def owner(self) -> tuple[str, str]:
        return self.session_id, self.generation_id


class MockSidecar:
    def __init__(self, token: str, delta_delay_seconds: float) -> None:
        self.token = token
        self.delta_delay_seconds = delta_delay_seconds
        self.instance_id = f"sidecar-{uuid4().hex}"
        self.stop_event = asyncio.Event()
        self.generations: dict[tuple[str, str], Generation] = {}
        self._send_locks: dict[int, asyncio.Lock] = {}

    @staticmethod
    def capabilities() -> dict[str, Any]:
        return {
            "chat_streaming": True,
            "chat_cancel": True,
            "memory": False,
            "knowledge": False,
            "rag": False,
            "voice": {
                "ipc": False,
                "edge_tts": True,
                "cosyvoice_remote": True,
                "cosyvoice_local": False,
                "streaming_pcm": False,
            },
        }

    @staticmethod
    def limits() -> dict[str, int]:
        return {
            "json_frame_max_bytes": JSON_FRAME_MAX_BYTES,
            "chat_input_max_bytes": CHAT_INPUT_MAX_BYTES,
            "event_max_bytes": EVENT_MAX_BYTES,
            "binary_frame_max_bytes": BINARY_FRAME_MAX_BYTES,
        }

    def process_request(self, connection: ServerConnection, request: Any):
        expected = f"Bearer {self.token}"
        if request.headers.get("Authorization") != expected:
            LOGGER.warning("event=authentication_failed")
            return connection.respond(HTTPStatus.UNAUTHORIZED, "Unauthorized\n")
        return None

    async def send(self, connection: ServerConnection, message: dict[str, Any]) -> None:
        validate_message(message)
        serialized = json.dumps(message, ensure_ascii=False, separators=(",", ":"))
        if len(serialized.encode("utf-8")) > EVENT_MAX_BYTES:
            raise ContractError("outbound event exceeds event_max_bytes")
        lock = self._send_locks.setdefault(id(connection), asyncio.Lock())
        async with lock:
            await connection.send(serialized)

    async def send_error(
        self,
        connection: ServerConnection,
        *,
        code: str,
        message: str,
        retryable: bool,
        envelope: dict[str, Any] | None = None,
    ) -> None:
        response: dict[str, Any] = {
            "protocol": PROTOCOL,
            "version": VERSION,
            "type": "error",
            "payload": {"code": code, "message": message, "retryable": retryable},
        }
        if envelope:
            for field in ("request_id", "session_id", "generation_id"):
                value = envelope.get(field)
                if isinstance(value, str) and value:
                    response[field] = value
        await self.send(connection, response)

    async def handle_connection(self, connection: ServerConnection) -> None:
        LOGGER.info("event=websocket_connected")
        try:
            raw_hello = await asyncio.wait_for(connection.recv(), timeout=5.0)
            if not isinstance(raw_hello, str):
                await self.send_error(
                    connection,
                    code="INVALID_REQUEST",
                    message="The first frame must be JSON text.",
                    retryable=False,
                )
                return
            hello = self._parse_json(raw_hello)
            if hello.get("protocol") != PROTOCOL or hello.get("version") != VERSION:
                await self.send_error(
                    connection,
                    code="PROTOCOL_VERSION_MISMATCH",
                    message="Backend version incompatible.",
                    retryable=False,
                    envelope=hello,
                )
                await connection.close(code=1002, reason="protocol version mismatch")
                return
            validate_message(hello)
            if hello["type"] != "hello" or VERSION not in hello["payload"]["supported_versions"]:
                raise ContractError("hello negotiation is invalid")
            await self.send(
                connection,
                {
                    "protocol": PROTOCOL,
                    "version": VERSION,
                    "type": "hello_ack",
                    "request_id": hello["request_id"],
                    "payload": {
                        "selected_version": VERSION,
                        "sidecar_instance_id": self.instance_id,
                        "state": "READY",
                        "capabilities": self.capabilities(),
                        "limits": self.limits(),
                    },
                },
            )

            async for raw in connection:
                if not isinstance(raw, str):
                    await self.send_error(
                        connection,
                        code="INVALID_REQUEST",
                        message="Binary frames are reserved in IPC v1.",
                        retryable=False,
                    )
                    continue
                try:
                    message = self._parse_json(raw)
                    validate_message(message)
                    await self.dispatch(connection, message)
                except (ContractError, KeyError, TypeError, ValueError) as error:
                    LOGGER.warning("event=invalid_request error_type=%s", type(error).__name__)
                    await self.send_error(
                        connection,
                        code="INVALID_REQUEST",
                        message="The request does not match Aurora IPC v1.",
                        retryable=False,
                    )
        except asyncio.TimeoutError:
            LOGGER.warning("event=handshake_timeout")
        except (ConnectionClosed, asyncio.IncompleteReadError):
            LOGGER.info("event=websocket_disconnected")
        except (ContractError, json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
            LOGGER.warning("event=handshake_rejected error_type=%s", type(error).__name__)
            try:
                await self.send_error(
                    connection,
                    code="INVALID_REQUEST",
                    message="Handshake rejected.",
                    retryable=False,
                )
            except ConnectionClosed:
                pass
        finally:
            self._send_locks.pop(id(connection), None)

    @staticmethod
    def _parse_json(raw: str) -> dict[str, Any]:
        if len(raw.encode("utf-8")) > JSON_FRAME_MAX_BYTES:
            raise ContractError("PAYLOAD_TOO_LARGE")
        message = json.loads(raw)
        if not isinstance(message, dict):
            raise ContractError("message must be an object")
        return message

    async def dispatch(self, connection: ServerConnection, message: dict[str, Any]) -> None:
        message_type = message["type"]
        if message_type == "health.request":
            await self.send(
                connection,
                {
                    "protocol": PROTOCOL,
                    "version": VERSION,
                    "type": "health.response",
                    "request_id": message["request_id"],
                    "payload": {
                        "state": "READY",
                        "sidecar_instance_id": self.instance_id,
                        "capabilities": self.capabilities(),
                        "limits": self.limits(),
                    },
                },
            )
        elif message_type == "chat.request":
            await self.start_chat(connection, message)
        elif message_type == "chat.cancel.request":
            await self.cancel_chat(connection, message)
        elif message_type == "shutdown.request":
            await self.send(
                connection,
                {
                    "protocol": PROTOCOL,
                    "version": VERSION,
                    "type": "shutdown.ack",
                    "request_id": message["request_id"],
                    "payload": {"accepted": True},
                },
            )
            self.stop_event.set()
        else:
            await self.send_error(
                connection,
                code="PROTOCOL_ERROR",
                message="Message type is not a client command.",
                retryable=False,
                envelope=message,
            )

    async def start_chat(self, connection: ServerConnection, message: dict[str, Any]) -> None:
        if len(message["payload"]["input"].encode("utf-8")) > CHAT_INPUT_MAX_BYTES:
            await self.send_error(
                connection,
                code="PAYLOAD_TOO_LARGE",
                message="Chat input exceeds the negotiated limit.",
                retryable=False,
                envelope=message,
            )
            return
        active = any(item.terminal_state is None for item in self.generations.values())
        if active:
            await self.send_error(
                connection,
                code="BACKEND_NOT_READY",
                message="The mock backend already owns an active generation.",
                retryable=True,
                envelope=message,
            )
            return
        generation = Generation(
            request_id=message["request_id"],
            session_id=message["session_id"],
            generation_id=message["generation_id"],
            cancel_ack_sent=asyncio.Event(),
        )
        self.generations[generation.owner] = generation
        LOGGER.info(
            "event=chat_start request=%s generation=%s",
            _short_id(generation.request_id),
            _short_id(generation.generation_id),
        )
        await self.send(
            connection,
            {
                "protocol": PROTOCOL,
                "version": VERSION,
                "type": "chat.accepted",
                "request_id": generation.request_id,
                "session_id": generation.session_id,
                "generation_id": generation.generation_id,
                "payload": {"status": "accepted"},
            },
        )
        generation.task = asyncio.create_task(
            self.stream_generation(connection, generation),
            name=f"mock-generation-{generation.generation_id[:8]}",
        )

    async def stream_generation(
        self, connection: ServerConnection, generation: Generation
    ) -> None:
        started = monotonic()
        try:
            for seq, chunk in enumerate(MOCK_CHUNKS):
                await asyncio.sleep(self.delta_delay_seconds)
                if generation.cancel_requested:
                    assert generation.cancel_ack_sent is not None
                    await generation.cancel_ack_sent.wait()
                    raise asyncio.CancelledError
                await self.send(
                    connection,
                    {
                        "protocol": PROTOCOL,
                        "version": VERSION,
                        "type": "chat.delta",
                        "request_id": generation.request_id,
                        "session_id": generation.session_id,
                        "generation_id": generation.generation_id,
                        "seq": seq,
                        "payload": {"delta": chunk},
                    },
                )
            generation.terminal_state = "completed"
            LOGGER.info(
                "event=chat_terminal request=%s generation=%s state=completed",
                _short_id(generation.request_id),
                _short_id(generation.generation_id),
            )
            await self.send(
                connection,
                {
                    "protocol": PROTOCOL,
                    "version": VERSION,
                    "type": "chat.completed",
                    "request_id": generation.request_id,
                    "session_id": generation.session_id,
                    "generation_id": generation.generation_id,
                    "payload": {
                        "terminal_state": "completed",
                        "output_chars": sum(len(chunk) for chunk in MOCK_CHUNKS),
                        "duration_ms": round((monotonic() - started) * 1000, 3),
                    },
                },
            )
        except asyncio.CancelledError:
            if generation.terminal_state is None:
                generation.terminal_state = "cancelled"
                LOGGER.info(
                    "event=chat_terminal request=%s generation=%s state=cancelled",
                    _short_id(generation.request_id),
                    _short_id(generation.generation_id),
                )
                try:
                    await self.send(
                        connection,
                        {
                            "protocol": PROTOCOL,
                            "version": VERSION,
                            "type": "chat.completed",
                            "request_id": generation.request_id,
                            "session_id": generation.session_id,
                            "generation_id": generation.generation_id,
                            "payload": {"terminal_state": "cancelled"},
                        },
                    )
                except ConnectionClosed:
                    pass
            raise
        except ConnectionClosed:
            generation.terminal_state = "backend_lost"

    async def cancel_chat(self, connection: ServerConnection, message: dict[str, Any]) -> None:
        owner = message["session_id"], message["generation_id"]
        generation = self.generations.get(owner)
        outcome: str
        if generation is None or generation.request_id != message["payload"]["target_request_id"]:
            outcome = "not_found"
        elif generation.terminal_state == "cancelled":
            outcome = "cancelled"
        elif generation.terminal_state is not None:
            outcome = "already_completed"
        else:
            outcome = "cancel_requested"
            generation.cancel_requested = True
        await self.send(
            connection,
            {
                "protocol": PROTOCOL,
                "version": VERSION,
                "type": "chat.cancel.ack",
                "request_id": message["request_id"],
                "session_id": message["session_id"],
                "generation_id": message["generation_id"],
                "payload": {
                    "target_request_id": message["payload"]["target_request_id"],
                    "outcome": outcome,
                },
            },
        )
        if outcome == "cancel_requested":
            assert generation is not None and generation.cancel_ack_sent is not None
            generation.cancel_ack_sent.set()
            assert generation.task is not None
            generation.task.cancel()
        LOGGER.info(
            "event=chat_cancel generation=%s outcome=%s",
            _short_id(message["generation_id"]),
            outcome,
        )

    async def cancel_all(self) -> None:
        tasks = []
        for generation in self.generations.values():
            if generation.task is not None and not generation.task.done():
                generation.cancel_requested = True
                if generation.cancel_ack_sent is not None:
                    generation.cancel_ack_sent.set()
                generation.task.cancel()
                tasks.append(generation.task)
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)


def _required_environment() -> tuple[str, list[int]]:
    token = os.environ.get("AURORA_IPC_TOKEN", "")
    protocol = os.environ.get("AURORA_IPC_PROTOCOL", "")
    versions_raw = os.environ.get("AURORA_IPC_SUPPORTED_VERSIONS", "")
    if len(token) < 32:
        raise RuntimeError("AURORA_IPC_TOKEN is missing or too short")
    if protocol != PROTOCOL:
        raise RuntimeError("AURORA_IPC_PROTOCOL is incompatible")
    try:
        versions = [int(value.strip()) for value in versions_raw.split(",") if value.strip()]
    except ValueError as error:
        raise RuntimeError("AURORA_IPC_SUPPORTED_VERSIONS is invalid") from error
    if VERSION not in versions:
        raise RuntimeError("no supported Aurora IPC version")
    return token, versions


def _short_id(value: str) -> str:
    return value.rsplit("-", 1)[-1][:8]


async def run() -> None:
    token, versions = _required_environment()
    delay_ms = max(1.0, float(os.environ.get("AURORA_MOCK_DELTA_DELAY_MS", "45")))
    sidecar = MockSidecar(token, delay_ms / 1000.0)
    async with serve(
        sidecar.handle_connection,
        "127.0.0.1",
        0,
        process_request=sidecar.process_request,
        compression=None,
        max_size=JSON_FRAME_MAX_BYTES,
        max_queue=16,
        write_limit=32_768,
        server_header=None,
    ) as server:
        assert server.sockets
        port = server.sockets[0].getsockname()[1]
        ready = {
            "protocol": PROTOCOL,
            "version": VERSION,
            "type": "bootstrap.ready",
            "port": port,
            "pid": os.getpid(),
            "supported_versions": versions,
            "sidecar_instance_id": sidecar.instance_id,
        }
        serialized = json.dumps(ready, ensure_ascii=False, separators=(",", ":"))
        if len(serialized.encode("utf-8")) > BOOTSTRAP_MAX_BYTES:
            raise RuntimeError("bootstrap envelope exceeds limit")
        print(serialized, flush=True)
        LOGGER.info("event=ready pid=%s", os.getpid())
        await sidecar.stop_event.wait()
        await sidecar.cancel_all()
        LOGGER.info("event=stopping")


def main() -> int:
    try:
        asyncio.run(run())
        return 0
    except KeyboardInterrupt:
        LOGGER.info("event=keyboard_interrupt")
        return 130
    except Exception as error:
        LOGGER.error("event=startup_failed error_type=%s", type(error).__name__)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
