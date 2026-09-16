"""Real production functions and real loopback sockets, but no real model."""
import asyncio
import builtins
import json
import socket
import tempfile
import threading
import unittest
import sys
import subprocess
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from test_production_sidecar import ROOT, ProductionComposition, write_settings, envelope, validate_message
from production_sidecar.server import ProductionSidecar
from production_sidecar.direct_chat import ChatRequest, DirectChatAdapter


@contextmanager
def model_server(mode="success", models=True):
    calls, release = [], threading.Event()

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):
            pass

        def do_GET(self):
            data = json.dumps({"models": [{"name": "test-model:latest"}] if models else []}).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self):
            calls.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            self.send_response(200)
            self.send_header("Connection", "close")
            self.end_headers()
            frames = [{"message": {"thinking": "hidden fixture"}},
                      {"message": {"content": "你好"}}, {"message": {"content": "，世界。"}}]
            try:
                for frame in frames:
                    self.wfile.write((json.dumps(frame) + "\n").encode())
                    self.wfile.flush()
                if mode == "blocked":
                    release.wait(5)
                if mode != "incomplete":
                    self.wfile.write(b'{"done":true,"eval_count":3}\n')
                    self.wfile.flush()
            except (ConnectionError, OSError):
                pass
            self.close_connection = True

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", calls
    finally:
        release.set()
        server.shutdown()
        server.server_close()
        thread.join(3)
        assert not thread.is_alive()


def request(index="1"):
    result = envelope("chat.request", "r" + index, input="private user input", conversation_id=None)
    result.update(session_id="session", generation_id="g" + index)
    return result


def cancel(index="1"):
    result = envelope("chat.cancel.request", "c" + index, target_request_id="r" + index)
    result.update(session_id="session", generation_id="g" + index)
    return result


class BridgeTests(unittest.IsolatedAsyncioTestCase):
    async def setup_bridge(self, host, directory):
        self.events = []
        self.connection = object()
        root = Path(directory)
        c = ProductionComposition(ROOT, write_settings(directory, host,
                                  persona={"enabled": False}, knowledge={"enabled": False},
                                  rag={"pipeline_enabled": False}),
                                  conversation_root=root / "conversations",
                                  context_root=root)
        self.sidecar = ProductionSidecar("test-token", c)

        async def send(connection, event):
            validate_message(event)
            self.events.append(event)
        self.sidecar.send = send
        return self.sidecar.chat

    async def wait_delta(self):
        async with asyncio.timeout(5):
            while not any(e["type"] == "chat.delta" for e in self.events):
                await asyncio.sleep(.01)

    async def test_success_mapping_policy_context_privacy_and_sequence(self):
        with tempfile.TemporaryDirectory() as directory, model_server() as (host, calls):
            bridge = await self.setup_bridge(host, directory)
            original_import = builtins.__import__

            def guarded(name, *args, **kwargs):
                if name.startswith(("widgets", "tkinter", "modules.memory_intelligence",
                                    "modules.conversation_intelligence")):
                    raise AssertionError("UI/post-turn intelligence must not be imported")
                return original_import(name, *args, **kwargs)
            with patch("builtins.__import__", side_effect=guarded):
                await bridge.start(self.connection, request())
                await asyncio.wait_for(bridge.active.task, 5)
            self.assertEqual(calls[0]["model"], "test-model")
            self.assertEqual(calls[0]["messages"], [{"role": "user", "content": "private user input"}])
            self.assertIs(calls[0]["think"], False)
            self.assertEqual(calls[0]["keep_alive"], "30m")
            deltas = [e for e in self.events if e["type"] == "chat.delta"]
            self.assertEqual([e["seq"] for e in deltas], [0, 1])
            self.assertEqual("".join(e["payload"]["delta"] for e in deltas), "你好，世界。")
            terminal = self.events[-1]["payload"]
            self.assertEqual(terminal["terminal_state"], "completed")
            self.assertEqual(terminal["diagnostics"]["reasoning_chars"], len("hidden fixture"))
            self.assertNotIn("hidden fixture", json.dumps(self.events))
            self.assertFalse(terminal["diagnostics"]["active_response"])
            self.assertTrue(terminal["diagnostics"]["worker_exited"])
            self.assertIsNone(bridge.active)

    async def test_blocked_read_cancel_ack_terminal_repeated_cancel_and_recovery(self):
        with tempfile.TemporaryDirectory() as directory, model_server("blocked") as (host, calls):
            bridge = await self.setup_bridge(host, directory)
            await bridge.start(self.connection, request())
            old = bridge.active
            await self.wait_delta()
            await asyncio.wait_for(bridge.cancel(self.connection, cancel()), 2)
            await asyncio.wait_for(old.task, 2)
            self.assertEqual(old.terminal, "cancelled")
            self.assertLess(old.handle.diagnostics["cancel_transport_latency_ms"], 1500)
            self.assertFalse(old.handle.active_response)
            types = [e["type"] for e in self.events]
            self.assertLess(types.index("chat.cancel.ack"), types.index("chat.completed"))
            await bridge.cancel(self.connection, cancel())
            self.assertEqual(self.events[-1]["payload"]["outcome"], "cancelled")
            await bridge.start(self.connection, request("2"))
            next_run = bridge.active
            await bridge.cancel(self.connection, cancel())  # old cleanup cannot touch N+1
            self.assertFalse(next_run.handle.stop_event.is_set())
            await bridge.cancel(self.connection, cancel("2"))
            await asyncio.wait_for(next_run.task, 3)
            self.assertEqual(next_run.terminal, "cancelled")
            self.assertEqual(len([e for e in self.events if e["type"] == "chat.completed"]), 2)

    async def test_cancel_before_worker_and_completion_winner(self):
        with tempfile.TemporaryDirectory() as directory, model_server() as (host, calls):
            bridge = await self.setup_bridge(host, directory)
            await bridge.start(self.connection, request())
            run = bridge.active
            await bridge.cancel(self.connection, cancel())
            await asyncio.wait_for(run.task, 5)
            self.assertEqual(run.terminal, "cancelled")
            self.assertEqual(calls, [])
            await bridge.start(self.connection, request("2"))
            run = bridge.active
            await asyncio.wait_for(run.task, 5)
            await bridge.cancel(self.connection, cancel("2"))
            self.assertEqual(self.events[-1]["payload"]["outcome"], "already_completed")
            self.assertEqual(run.terminal, "completed")

    async def test_incomplete_failure_sanitized_and_no_fallback(self):
        with tempfile.TemporaryDirectory() as directory, model_server("incomplete") as (host, calls):
            bridge = await self.setup_bridge(host, directory)
            await bridge.start(self.connection, request())
            await asyncio.wait_for(bridge.active.task, 5)
            self.assertEqual(self.events[-1]["payload"]["terminal_state"], "failed")
            self.assertEqual(self.events[-1]["payload"]["error"]["code"], "INTERNAL_ERROR")
            self.assertEqual(len(calls), 1)

    async def test_missing_model_failed_terminal_no_post(self):
        with tempfile.TemporaryDirectory() as directory, model_server(models=False) as (host, calls):
            bridge = await self.setup_bridge(host, directory)
            await bridge.start(self.connection, request())
            await asyncio.wait_for(bridge.active.task, 5)
            self.assertEqual(self.events[-1]["payload"]["error"]["code"], "MODEL_UNAVAILABLE")
            self.assertEqual(calls, [])

    async def test_offline_failed_terminal(self):
        with tempfile.TemporaryDirectory() as directory, socket.socket() as reserved:
            reserved.bind(("127.0.0.1", 0))
            bridge = await self.setup_bridge(f"http://127.0.0.1:{reserved.getsockname()[1]}", directory)
            await bridge.start(self.connection, request())
            await asyncio.wait_for(bridge.active.task, 5)
            self.assertEqual(self.events[-1]["payload"]["error"]["code"], "PROVIDER_UNAVAILABLE")

    async def test_one_active_replay_and_shutdown_cleanup(self):
        with tempfile.TemporaryDirectory() as directory, model_server("blocked") as (host, calls):
            bridge = await self.setup_bridge(host, directory)
            await bridge.start(self.connection, request())
            run = bridge.active
            await self.wait_delta()
            await bridge.start(self.connection, request())  # no duplicate terminal
            await bridge.start(self.connection, request("2"))
            self.assertEqual(self.events[-1]["payload"]["terminal_state"], "rejected")
            self.assertIs(bridge.active, run)
            await asyncio.wait_for(bridge.close(), 2)
            self.assertIsNone(bridge.active)
            self.assertTrue(run.task.done())
            self.assertIsNone(run.handle.active_response)
            self.assertEqual(len(calls), 1)

    async def test_cancel_wakes_full_bounded_queue_and_discards_late_text(self):
        with tempfile.TemporaryDirectory() as directory, model_server() as (host, _):
            bridge = await self.setup_bridge(host, directory)
            release_send = asyncio.Event()
            saturated = threading.Event()
            exited = threading.Event()
            original_send = self.sidecar.send

            async def slow_send(connection, event):
                if event["type"] == "chat.delta":
                    await release_send.wait()
                await original_send(connection, event)

            def fast_producer(request, model, handle, forward, context_snapshot):
                try:
                    for i in range(1000):
                        if i == 17:
                            saturated.set()
                        forward("片段")
                finally:
                    handle.finish("cancelled" if handle.cancelled else "completed")
                    exited.set()

            self.sidecar.send = slow_send
            bridge.adapter.stream = fast_producer
            await bridge.start(self.connection, request())
            run = bridge.active
            async with asyncio.timeout(3):
                while not saturated.is_set():
                    await asyncio.sleep(.01)
            self.assertEqual(run.queue.qsize(), 16)
            await asyncio.wait_for(bridge.cancel(self.connection, cancel()), 2)
            release_send.set()
            await asyncio.wait_for(run.task, 2)
            self.assertTrue(exited.is_set())
            self.assertEqual(run.terminal, "cancelled")
            self.assertLessEqual(len([e for e in self.events if e["type"] == "chat.delta"]), 1)

    async def test_error_mapping_and_cancel_wins_transport_side_effect(self):
        with tempfile.TemporaryDirectory() as directory, model_server() as (host, _):
            bridge = await self.setup_bridge(host, directory)
            for category, expected in (("timeout", "REQUEST_TIMEOUT"), ("model_capability", "MODEL_UNAVAILABLE"),
                                       ("ollama_unavailable", "PROVIDER_UNAVAILABLE"), ("other", "INTERNAL_ERROR")):
                error = bridge.adapter.api["ChatError"]("private path/token", category=category)
                self.assertEqual(bridge.adapter.error_code(error), expected)
            entered = threading.Event()
            def broken_after_cancel(request, model, handle, forward, context_snapshot):
                entered.set()
                handle.stop_event.wait(3)
                raise ConnectionResetError("private socket detail")
            bridge.adapter.stream = broken_after_cancel
            await bridge.start(self.connection, request())
            run = bridge.active
            async with asyncio.timeout(3):
                while not entered.is_set():
                    await asyncio.sleep(.01)
            await bridge.cancel(self.connection, cancel())
            await asyncio.wait_for(run.task, 2)
            self.assertEqual(self.events[-1]["payload"]["terminal_state"], "cancelled")
            self.assertNotIn("error", self.events[-1]["payload"])


class BoundaryTests(unittest.TestCase):
    def test_settings_policy_not_hardcoded_and_safe_direct_import(self):
        with tempfile.TemporaryDirectory() as directory:
            path = write_settings(directory, "http://127.0.0.1:1",
                                  ollama={"host": "http://127.0.0.1:1", "thinking_mode": "on", "keep_alive": "5m"})
            adapter = DirectChatAdapter(ProductionComposition(ROOT, path))
            payload = adapter.composition.settings.policy.apply({})
            self.assertEqual(payload, {"think": True, "keep_alive": "5m"})
            self.assertEqual(adapter.prepare_context().snapshot(), [])
            self.assertNotIn("private", repr(ChatRequest("r", "s", "g", "private")))

    def test_headless_chat_adapter_load_has_no_eager_settings_or_context_import(self):
        from test_production_sidecar import SIDECAR
        import os
        with tempfile.TemporaryDirectory() as directory:
            code = """
import os,sys,threading
sys.path[:0]=[os.environ['TEST_SIDECAR'],os.environ['TEST_ROOT']]
def audit(event,args):
    if event in {'os.mkdir','subprocess.Popen','socket.connect'}: raise AssertionError(event)
    if event == 'open' and isinstance(args[2],int) and args[2] & (os.O_WRONLY|os.O_RDWR|os.O_CREAT): raise AssertionError('write')
sys.addaudithook(audit)
from production_sidecar.composition import ProductionComposition
from production_sidecar.direct_chat import DirectChatAdapter
a=DirectChatAdapter(ProductionComposition())
assert a.prepare_context().snapshot()==[]
assert len(threading.enumerate())==1
assert not any(n.startswith(('modules.memory','widgets','tkinter','modules.conversation')) for n in sys.modules)
from modules.settings import settings
assert settings._instance is None
"""
            result = subprocess.run([sys.executable, "-B", "-c", code], cwd=directory,
                env={**os.environ, "TEST_SIDECAR": str(SIDECAR), "TEST_ROOT": str(ROOT),
                     "AURORA_USER_DATA_DIR": directory}, capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr.decode())


if __name__ == "__main__":
    unittest.main()
