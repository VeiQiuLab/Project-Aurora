"""V4-3A tests use disposable settings and fake HTTP, never a real model."""
from __future__ import annotations

import asyncio
import copy
import http.client
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
from contextlib import asynccontextmanager, contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

SIDECAR = Path(__file__).resolve().parents[1]
ROOT = SIDECAR.parents[2]
sys.path[:0] = [str(SIDECAR), str(ROOT)]
from production_sidecar.aurora_adapter import ReadOnlySettings
from modules.settings import Settings
from production_sidecar.composition import ProductionComposition
from production_sidecar.server import ProductionSidecar
from mock_sidecar.server import PROTOCOL, validate_message
from websockets.asyncio.client import connect
from websockets.exceptions import InvalidStatus


@contextmanager
def fake_ollama(payload=None):
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            calls.append((self.command, self.path))
            data = json.dumps(payload if payload is not None else {"models": [{"name": "test-model:latest"}]}).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", calls
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
        assert not thread.is_alive()


def write_settings(directory, host, **extra):
    path = Path(directory) / "config" / "settings.json"
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps({"chat_model_mode": "manual", "chat_model": "test-model",
                               "ollama": {"host": host, "thinking_mode": "off", "keep_alive": "30m"},
                               **extra}), encoding="utf-8")
    return path


def envelope(kind, request="test", **payload):
    return {"protocol": PROTOCOL, "version": 1, "type": kind, "request_id": request, "payload": payload}


@asynccontextmanager
async def child_sidecar(directory):
    token = uuid4().hex + uuid4().hex
    env = {**os.environ, "AURORA_USER_DATA_DIR": str(directory), "PYTHONDONTWRITEBYTECODE": "1",
           "AURORA_IPC_TOKEN": token, "AURORA_IPC_PROTOCOL": PROTOCOL,
           "AURORA_IPC_SUPPORTED_VERSIONS": "1"}
    process = await asyncio.create_subprocess_exec(
        sys.executable, "-u", str(SIDECAR / "production_sidecar/server.py"),
        cwd=directory, env=env, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    stderr_task = asyncio.create_task(process.stderr.read())
    try:
        raw = await asyncio.wait_for(process.stdout.readline(), 8)
        if not raw:
            raise AssertionError((await stderr_task).decode())
        bootstrap = json.loads(raw)
        validate_message(bootstrap)
        yield process, bootstrap, token
    finally:
        if process.returncode is None:
            try:
                await asyncio.wait_for(process.wait(), 4)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
        stderr = (await stderr_task).decode(errors="replace")
        assert token not in stderr
        assert not await process.stdout.read(), "stdout after bootstrap must be empty"


class SettingsTests(unittest.TestCase):
    def test_defaults_do_not_create_files_or_dirs(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "missing" / "config.json"
            snapshot = ReadOnlySettings(ROOT, path)
            self.assertEqual(snapshot.status, "missing_defaults")
            self.assertFalse(path.parent.exists())
            self.assertEqual(snapshot.policy.thinking_mode, "off")
            self.assertEqual(snapshot.policy.keep_alive, "30m")

    def test_existing_production_migration_is_in_memory_only(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text('{"model":"old-model","ollama":{"thinking_mode":"on","keep_alive":"5m"}}')
            before = path.read_bytes()
            snapshot = ReadOnlySettings(ROOT, path)
            self.assertEqual(snapshot.get("chat_model"), "old-model")
            self.assertEqual(snapshot.get("chat_model_mode"), "manual")
            self.assertEqual(snapshot.policy.think_payload_value, True)
            self.assertEqual(snapshot.policy.keep_alive, "5m")
            self.assertEqual(path.read_bytes(), before)
            for method, args in (("save", ()), ("set", ("chat_model", "oops")), ("update_many", ({},))):
                with self.assertRaises(AttributeError):
                    getattr(snapshot._snapshot, method)(*args)

    def test_corrupt_and_non_object_settings_never_repaired(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            for text in ("{bad", "[]", "null"):
                path.write_text(text)
                self.assertEqual(ReadOnlySettings(ROOT, path).status, "invalid_defaults")
                self.assertEqual(path.read_text(), text)

    def test_snapshot_is_immutable(self):
        with tempfile.TemporaryDirectory() as directory:
            snapshot = ReadOnlySettings(ROOT, Path(directory) / "settings.json").snapshot()
            with self.assertRaises(AttributeError):
                snapshot.revision = 22
            data = snapshot.get("ollama")
            data["thinking_mode"] = "on"
            self.assertEqual(snapshot.policy.thinking_mode, "off")

    def test_normalization_matches_actual_production_load(self):
        # Load the real declaration in the parent; run its normal constructor only
        # against disposable injected paths. This catches migration-order drift.
        fixtures = [{}, {"model": "legacy", "language": "zh"},
                    {"ollama": None, "services": {"docker": {}}, "openwebui": {}},
                    {"chat_model_mode": "bad", "chat_model": "manual-model"}]
        for fixture in fixtures:
            with self.subTest(fixture=fixture), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "settings.json"
                path.write_text(json.dumps(fixture))
                snapshot = ReadOnlySettings(ROOT, path)
                production = Settings(config_file=path)
                for key, value in production.data.items():
                    self.assertEqual(snapshot.get(key), value)

    def test_import_safety_no_ui_threads_network_writes_or_singletons(self):
        with tempfile.TemporaryDirectory() as directory:
            code = '''
import os, sys, threading
sys.path[:0] = [os.environ['TEST_SIDECAR'], os.environ['TEST_ROOT']]
def audit(event, args):
    if event in {'os.mkdir', 'subprocess.Popen', 'socket.connect'}:
        raise AssertionError(event)
    if event == 'open' and (isinstance(args[1], str) and any(c in args[1] for c in 'wax+') or isinstance(args[2], int) and args[2] & (os.O_WRONLY | os.O_RDWR | os.O_CREAT)):
        raise AssertionError('write')
sys.addaudithook(audit)
from production_sidecar.composition import ProductionComposition
c = ProductionComposition()
assert c.settings.status == 'missing_defaults'
assert len(threading.enumerate()) == 1
assert not any(n.startswith(('tkinter', 'customtkinter', 'widgets', 'modules.chat', 'modules.logger', 'modules.runtime_state', 'modules.service_manager')) for n in sys.modules)
from modules.settings import settings
assert settings._instance is None
assert not list(c.settings.config_file.parent.parent.glob('*'))
print('import-safe')
'''
            result = subprocess.run([sys.executable, "-B", "-c", code], cwd=directory,
                                    env={**os.environ, "TEST_ROOT": str(ROOT), "TEST_SIDECAR": str(SIDECAR),
                                         "AURORA_USER_DATA_DIR": directory}, capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr.decode())
            self.assertEqual(result.stdout.strip(), b"import-safe")


class CompositionTests(unittest.IsolatedAsyncioTestCase):
    async def test_fake_health_ready_get_only_no_settings_mutation(self):
        with tempfile.TemporaryDirectory() as directory, fake_ollama() as (host, calls):
            path = write_settings(directory, host)
            before = path.read_bytes()
            c = ProductionComposition(ROOT, path)
            result = await c.refresh()
            self.assertEqual(c.state, "READY")
            self.assertTrue(result["ollama"]["model_available"])
            self.assertEqual(calls, [("GET", "/api/tags")])
            self.assertEqual(path.read_bytes(), before)
            c.close()
            c.close()
            with self.assertRaisesRegex(RuntimeError, "BACKEND_CLOSED"):
                await c.refresh()

    async def test_unreachable_and_invalid_settings_degrade(self):
        with tempfile.TemporaryDirectory() as directory, socket.socket() as blocked:
            blocked.bind(("127.0.0.1", 0))
            path = write_settings(directory, f"http://127.0.0.1:{blocked.getsockname()[1]}")
            c = ProductionComposition(ROOT, path)
            result = await c.refresh()
            self.assertEqual(c.state, "DEGRADED")
            self.assertEqual(result["ollama"]["error_code"], "OLLAMA_UNAVAILABLE")

    async def test_invalid_host_secret_never_exposed_or_requested(self):
        with tempfile.TemporaryDirectory() as directory:
            path = write_settings(directory, "http://private-user:secret@localhost:11434/?token=secret")
            c = ProductionComposition(ROOT, path)
            result = await c.refresh()
            self.assertEqual(result["ollama"]["error_code"], "INVALID_HOST")
            self.assertNotIn("secret", json.dumps(result))

    async def test_invalid_ollama_payload_degrades(self):
        with tempfile.TemporaryDirectory() as directory, fake_ollama({"models": None}) as (host, _):
            c = ProductionComposition(ROOT, write_settings(directory, host))
            result = await c.refresh()
            self.assertEqual(result["ollama"]["error_code"], "INVALID_OLLAMA_RESPONSE")

    async def test_model_missing_degrades_without_auto_selecting(self):
        with tempfile.TemporaryDirectory() as directory, fake_ollama({"models": []}) as (host, _):
            c = ProductionComposition(ROOT, write_settings(directory, host))
            result = await c.refresh()
            self.assertTrue(result["ollama"]["reachable"])
            self.assertFalse(result["ollama"]["model_available"])
            self.assertEqual(c.state, "DEGRADED")

    async def test_corrupt_settings_still_composes_with_fake_health(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            path.write_text("{invalid")
            c = ProductionComposition(ROOT, path)
            fake = {"reachable": True, "host": "http://127.0.0.1:1", "configured_model": "fixture",
                    "model_available": True, "error_code": "", "probe_duration_ms": 0.0}
            with patch("production_sidecar.composition.OllamaHealth.probe", return_value=fake):
                result = await c.refresh()
            self.assertEqual(c.state, "DEGRADED")
            self.assertEqual(result["settings_status"], "invalid_defaults")
            self.assertEqual(path.read_text(), "{invalid")

    async def test_truncated_http_reply_is_degraded_not_startup_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            c = ProductionComposition(ROOT, write_settings(directory, "http://127.0.0.1:1"))
            with patch("urllib.request.OpenerDirector.open", side_effect=http.client.IncompleteRead(b"")):
                result = await c.refresh()
            self.assertEqual(result["ollama"]["error_code"], "INVALID_OLLAMA_RESPONSE")
            self.assertEqual(c.state, "DEGRADED")

    async def test_capabilities_inventory_not_rpc(self):
        with tempfile.TemporaryDirectory() as directory:
            c = ProductionComposition(ROOT, Path(directory) / "missing.json")
            caps = c.capabilities()
            self.assertTrue(all(caps["implementation"].values()))
            self.assertTrue(caps["voice"]["edge_tts"])
            self.assertTrue(caps["voice"]["cosyvoice_remote"])
            self.assertTrue(caps["chat_streaming"] and caps["chat_cancel"])
            self.assertFalse(any(caps[k] for k in ("memory", "knowledge", "rag")))
            self.assertTrue(caps["voice"]["ipc"])
            self.assertFalse(any(caps["voice"][k] for k in ("streaming_pcm", "cosyvoice_local")))


class ProcessTests(unittest.IsolatedAsyncioTestCase):
    async def exercise(self, directory, expected_state, old_token=None):
        async with child_sidecar(directory) as (process, bootstrap, token):
            uri = f"ws://127.0.0.1:{bootstrap['port']}"
            if old_token:
                with self.assertRaises(InvalidStatus):
                    async with connect(uri, additional_headers={"Authorization": f"Bearer {old_token}"}):
                        pass
            async with connect(uri, additional_headers={"Authorization": f"Bearer {token}"}) as ws:
                await ws.send(json.dumps(envelope("hello", client="aurora-desktop", supported_versions=[1])))
                ack = json.loads(await ws.recv())
                validate_message(ack)
                self.assertEqual(ack["payload"]["state"], expected_state)
                self.assertTrue(ack["payload"]["capabilities"]["chat_streaming"])
                await ws.send(json.dumps(envelope("health.request")))
                health = json.loads(await ws.recv())
                validate_message(health)
                self.assertEqual(health["payload"]["state"], expected_state)
                await ws.send(json.dumps(envelope("shutdown.request")))
                self.assertEqual(json.loads(await ws.recv())["type"], "shutdown.ack")
            await asyncio.wait_for(process.wait(), 4)
            self.assertEqual(process.returncode, 0)
        with socket.socket() as check:
            self.assertNotEqual(check.connect_ex(("127.0.0.1", bootstrap["port"])), 0)
        return bootstrap, token

    async def test_real_child_foreign_cwd_ready_restart_credentials_shutdown(self):
        with tempfile.TemporaryDirectory() as directory, fake_ollama() as (host, calls):
            path = write_settings(directory, host)
            before = path.read_bytes()
            first, token = await self.exercise(directory, "READY")
            second, next_token = await self.exercise(directory, "READY", token)
            for key in ("pid", "port", "sidecar_instance_id"):
                self.assertNotEqual(first[key], second[key])
            self.assertNotEqual(token, next_token)
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(set(calls), {("GET", "/api/tags")})

    async def test_real_child_offline_degraded_survives(self):
        with tempfile.TemporaryDirectory() as directory, socket.socket() as blocked:
            blocked.bind(("127.0.0.1", 0))
            write_settings(directory, f"http://127.0.0.1:{blocked.getsockname()[1]}")
            await self.exercise(directory, "DEGRADED")

    async def test_missing_dependency_has_no_bootstrap_and_stderr_failure(self):
        process = await asyncio.create_subprocess_exec(
            sys.executable, "-S", str(SIDECAR / "production_sidecar/server.py"),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            env={**os.environ, "PYTHONPATH": ""})
        out, err = await asyncio.wait_for(process.communicate(), 5)
        self.assertNotEqual(process.returncode, 0)
        self.assertEqual(out, b"")
        self.assertIn(b"ModuleNotFoundError", err)

    async def test_production_import_failure_never_publishes_fake_bootstrap(self):
        code = '''
import importlib.abc, runpy, sys
class MissingProductionPolicy(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, *args):
        if fullname == 'modules.ollama_request_policy':
            raise ImportError('production policy unavailable')
sys.meta_path.insert(0, MissingProductionPolicy())
runpy.run_path(sys.argv[1], run_name='__main__')
'''
        process = await asyncio.create_subprocess_exec(
            sys.executable, "-c", code, str(SIDECAR / "production_sidecar/server.py"),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        out, err = await asyncio.wait_for(process.communicate(), 5)
        self.assertNotEqual(process.returncode, 0)
        self.assertEqual(out, b"")
        self.assertIn(b"production policy unavailable", err)


if __name__ == "__main__":
    unittest.main()
