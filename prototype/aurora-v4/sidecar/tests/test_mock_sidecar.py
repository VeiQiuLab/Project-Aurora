from __future__ import annotations

import asyncio
import json
import os
import sys
import unittest
from pathlib import Path
from uuid import uuid4

from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed, InvalidStatus


SIDECAR_ROOT = Path(__file__).resolve().parents[1]
SERVER = SIDECAR_ROOT / "mock_sidecar" / "server.py"
TOKEN = "test-only-" + "a" * 48


def envelope(message_type: str, request_id: str, **fields):
    return {
        "protocol": "aurora-ipc",
        "version": 1,
        "type": message_type,
        "request_id": request_id,
        "payload": fields.pop("payload", {}),
        **fields,
    }


class MockSidecarIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        environment = os.environ.copy()
        environment.update(
            {
                "AURORA_IPC_TOKEN": TOKEN,
                "AURORA_IPC_PROTOCOL": "aurora-ipc",
                "AURORA_IPC_SUPPORTED_VERSIONS": "1",
                "AURORA_MOCK_DELTA_DELAY_MS": "5",
            }
        )
        self.process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-u",
            str(SERVER),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=environment,
            cwd=SIDECAR_ROOT,
        )
        assert self.process.stdout is not None
        ready_line = await asyncio.wait_for(self.process.stdout.readline(), timeout=5)
        self.ready = json.loads(ready_line.decode("utf-8"))
        self.uri = f"ws://127.0.0.1:{self.ready['port']}"

    async def asyncTearDown(self):
        if self.process.returncode is None:
            self.process.terminate()
            try:
                await asyncio.wait_for(self.process.wait(), timeout=3)
            except asyncio.TimeoutError:
                self.process.kill()
                await self.process.wait()

    async def open(self, token=TOKEN):
        return await connect(
            self.uri,
            additional_headers={"Authorization": f"Bearer {token}"},
            compression=None,
            max_size=1_048_576,
        )

    async def handshake(self, connection, *, versions=None):
        request_id = f"hello-{uuid4().hex}"
        await connection.send(
            json.dumps(
                envelope(
                    "hello",
                    request_id,
                    payload={
                        "client": "aurora-desktop",
                        "supported_versions": versions or [1],
                    },
                )
            )
        )
        return json.loads(await connection.recv())

    async def start_chat(self, connection, generation_id=None):
        generation_id = generation_id or f"generation-{uuid4().hex}"
        request_id = f"chat-{uuid4().hex}"
        session_id = "test-runtime-session"
        await connection.send(
            json.dumps(
                envelope(
                    "chat.request",
                    request_id,
                    session_id=session_id,
                    generation_id=generation_id,
                    payload={"conversation_id": None, "input": "synthetic test input"},
                )
            )
        )
        accepted = json.loads(await connection.recv())
        self.assertEqual(accepted["type"], "chat.accepted")
        return request_id, session_id, generation_id

    async def test_bootstrap_handshake_health_and_graceful_shutdown(self):
        self.assertEqual(self.ready["protocol"], "aurora-ipc")
        self.assertEqual(self.ready["version"], 1)
        self.assertGreater(self.ready["pid"], 0)
        self.assertNotIn("token", self.ready)
        connection = await self.open()
        async with connection:
            hello_ack = await self.handshake(connection)
            self.assertEqual(hello_ack["type"], "hello_ack")
            capabilities = hello_ack["payload"]["capabilities"]
            self.assertTrue(capabilities["chat_streaming"])
            self.assertFalse(capabilities["voice"]["cosyvoice_local"])
            self.assertFalse(capabilities["voice"]["streaming_pcm"])

            await connection.send(json.dumps(envelope("health.request", "health-1")))
            health = json.loads(await connection.recv())
            self.assertEqual(health["type"], "health.response")
            self.assertEqual(health["payload"]["state"], "READY")

            await connection.send(json.dumps(envelope("shutdown.request", "shutdown-1")))
            shutdown = json.loads(await connection.recv())
            self.assertEqual(shutdown["type"], "shutdown.ack")
        await asyncio.wait_for(self.process.wait(), timeout=3)
        self.assertEqual(self.process.returncode, 0)

    async def test_authentication_is_required_at_websocket_upgrade(self):
        with self.assertRaises(InvalidStatus) as captured:
            await self.open("wrong-token-that-is-long-but-still-invalid")
        self.assertEqual(captured.exception.response.status_code, 401)

    async def test_protocol_version_mismatch_is_explicit(self):
        connection = await self.open()
        async with connection:
            request_id = "hello-mismatch"
            message = envelope(
                "hello",
                request_id,
                payload={"client": "aurora-desktop", "supported_versions": [2]},
            )
            message["version"] = 2
            await connection.send(json.dumps(message))
            error = json.loads(await connection.recv())
            self.assertEqual(error["payload"]["code"], "PROTOCOL_VERSION_MISMATCH")
            with self.assertRaises(ConnectionClosed):
                await connection.recv()

    async def test_mock_stream_has_ordered_incremental_deltas_and_one_terminal(self):
        connection = await self.open()
        async with connection:
            await self.handshake(connection)
            _, _, generation_id = await self.start_chat(connection)
            sequence = []
            terminal = None
            while terminal is None:
                message = json.loads(await connection.recv())
                self.assertEqual(message.get("generation_id"), generation_id)
                if message["type"] == "chat.delta":
                    sequence.append(message["seq"])
                elif message["type"] == "chat.completed":
                    terminal = message["payload"]["terminal_state"]
            self.assertEqual(sequence, list(range(30)))
            self.assertEqual(terminal, "completed")

    async def test_cancel_stops_old_deltas_and_next_generation_recovers(self):
        connection = await self.open()
        async with connection:
            await self.handshake(connection)
            request_id, session_id, generation_id = await self.start_chat(connection)
            first_delta = json.loads(await connection.recv())
            self.assertEqual(first_delta["type"], "chat.delta")
            await connection.send(
                json.dumps(
                    envelope(
                        "chat.cancel.request",
                        "cancel-1",
                        session_id=session_id,
                        generation_id=generation_id,
                        payload={"target_request_id": request_id},
                    )
                )
            )
            ack = None
            terminal = None
            deltas_after_ack = 0
            observed_types = []
            while terminal is None:
                message = json.loads(await connection.recv())
                observed_types.append(message["type"])
                if message["type"] == "chat.cancel.ack":
                    ack = message
                elif message["type"] == "chat.delta" and ack is not None:
                    deltas_after_ack += 1
                elif message["type"] == "chat.completed":
                    terminal = message
            self.assertIsNotNone(ack, observed_types)
            assert ack is not None
            self.assertEqual(ack["payload"]["outcome"], "cancel_requested")
            self.assertEqual(terminal["payload"]["terminal_state"], "cancelled")
            self.assertEqual(deltas_after_ack, 0)

            next_request, _, next_generation = await self.start_chat(
                connection, "generation-recovery"
            )
            self.assertNotEqual(next_request, request_id)
            seen_old_delta = False
            next_terminal = None
            while next_terminal is None:
                message = json.loads(await connection.recv())
                if message["type"] == "chat.delta":
                    seen_old_delta |= message["generation_id"] == generation_id
                elif message["type"] == "chat.completed":
                    next_terminal = message
            self.assertFalse(seen_old_delta)
            self.assertEqual(next_terminal["generation_id"], next_generation)
            self.assertEqual(next_terminal["payload"]["terminal_state"], "completed")

    async def test_process_crash_closes_connection_without_hanging_client(self):
        connection = await self.open()
        await self.handshake(connection)
        await self.start_chat(connection)
        self.process.kill()
        await asyncio.wait_for(self.process.wait(), timeout=3)
        with self.assertRaises(ConnectionClosed):
            while True:
                await asyncio.wait_for(connection.recv(), timeout=3)


if __name__ == "__main__":
    unittest.main()
