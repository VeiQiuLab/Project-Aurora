from __future__ import annotations

import asyncio
import ast
import os
import subprocess
import json
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from contextlib import nullcontext
from unittest.mock import Mock

SIDECAR = Path(__file__).resolve().parents[1]
ROOT = SIDECAR.parents[2]
sys.path[:0] = [str(SIDECAR), str(ROOT)]

from production_sidecar.composition import ProductionComposition
from production_sidecar.context import ContextCancelled, ContextPreparationError
from production_sidecar.direct_chat import ChatRequest, DirectChatAdapter
from production_sidecar.server import ProductionSidecar
from test_direct_chat import model_server, request
from test_production_sidecar import envelope, validate_message, write_settings


def legacy_context(composition, prompt, history):
    """Compile only the actual pure/closure functions, never import GUI main."""
    import production_sidecar.context as api
    from modules.retrieval import retrieval_summary
    names = {"build_conversation_context", "context_warning_tokens", "build_context_package",
             "build_memory_context", "prepare_chat_prompt_context"}
    tree = ast.parse((ROOT / "main.py").read_text(encoding="utf-8"))
    functions = [node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name in names]
    assert len(functions) == len(names)
    namespace = {**vars(api), "settings": composition.settings, "logger": Mock(), "nullcontext": nullcontext,
                 "memory_store": composition.context.memory, "persona_store": composition.context.persona,
                 "knowledge_store": composition.context.knowledge, "retrieval_summary": retrieval_summary}
    exec(compile(ast.Module(body=functions, type_ignores=[]), str(ROOT / "main.py"), "exec"), namespace)
    return namespace["prepare_chat_prompt_context"](prompt, history)["system_context"]


def _write_sources(root: Path, *, persona=True, memory=True, knowledge=True):
    if memory:
        (root / "memory").mkdir(parents=True, exist_ok=True)
        (root / "memory" / "memories.json").write_text(json.dumps([{
            "id": "memory-1", "type": "preference", "content": "用户偏好简洁的黑白界面",
            "created_time": "2026-01-01T00:00:00Z", "updated_time": "2026-01-01T00:00:00Z",
            "importance": "high", "enabled": True, "metadata": {"state": "active"},
        }], ensure_ascii=False), encoding="utf-8")
    if persona:
        (root / "persona").mkdir(parents=True, exist_ok=True)
        (root / "persona" / "persona.json").write_text(json.dumps({
            "name": "Aurora Test", "description": "合成测试角色", "style": "简洁",
            "rules": ["保持清晰"], "last_loaded_time": "never", "last_updated_time": "never",
        }, ensure_ascii=False), encoding="utf-8")
    if knowledge:
        knowledge_root = root / "knowledge"
        files = knowledge_root / "files"
        files.mkdir(parents=True, exist_ok=True)
        stored = files / "knowledge-1.md"
        content = "黑白界面的文档说明"
        stored.write_text(content, encoding="utf-8")
        (knowledge_root / "metadata.json").write_text(json.dumps([{
            "id": "knowledge-1", "file_name": "design.md", "file_type": "md",
            "stored_name": stored.name, "file_size": len(content.encode("utf-8")),
            "added_time": "2026-01-01 00:00:00", "updated_time": "2026-01-01 00:00:00",
            "enabled": True, "content": content,
        }], ensure_ascii=False), encoding="utf-8")


class ContextPreparationTests(unittest.TestCase):
    def _composition(self, root, *, persona=True, knowledge=True, rag=False):
        path = write_settings(root, "http://127.0.0.1:1",
                              persona={"enabled": persona},
                              knowledge={"enabled": knowledge, "max_results": 3},
                              rag={"pipeline_enabled": rag})
        return ProductionComposition(ROOT, path, context_root=Path(root),
                                     conversation_root=Path(root) / "conversations")

    def test_headless_context_uses_real_apis_and_preserves_order(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _write_sources(root)
            composition = self._composition(root)
            snapshot = composition.context.prepare("黑白界面", [{"role": "user", "content": "上一句"}])
            self.assertIn("You are Aurora", snapshot.system_context)
            self.assertIn("Persona:", snapshot.system_context)
            self.assertIn("- [preference] 用户偏好简洁的黑白界面", snapshot.system_context)
            self.assertIn("- Source: design.md", snapshot.system_context)
            self.assertLess(snapshot.system_context.index("Persona:"), snapshot.system_context.index("[preference]"))
            self.assertLess(snapshot.system_context.index("[preference]"), snapshot.system_context.index("Source: design.md"))
            self.assertEqual(snapshot.diagnostics["history_message_count"], 1)
            self.assertTrue(snapshot.diagnostics["memory_enabled"])
            self.assertTrue(snapshot.diagnostics["persona_enabled"])
            self.assertTrue(snapshot.diagnostics["knowledge_enabled"])
            self.assertFalse(snapshot.diagnostics["rag_enabled"])
            self.assertIsNone(snapshot.diagnostics["rag_ms"])
            self.assertGreaterEqual(snapshot.diagnostics["context_total_ms"], 0)
            composition.close()

    def test_actual_legacy_prompt_parity_with_and_without_rag(self):
        for rag in (False, True):
            with self.subTest(rag=rag), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                _write_sources(root)
                composition = self._composition(root, rag=rag)
                history = [{"role": "user", "content": "之前"}, {"role": "assistant", "content": "之前的回答"}]
                expected = legacy_context(composition, "黑白界面", history)
                snapshot = composition.context.prepare("黑白界面", history, generation_id="g", conversation_id="c")
                self.assertEqual(snapshot.system_context, expected)
                self.assertEqual(snapshot.generation_id, "g")
                self.assertEqual(snapshot.conversation_id, "c")
                with self.assertRaises(TypeError):
                    snapshot.diagnostics["memory_ms"] = 99
                self.assertNotIn("黑白", repr(snapshot))
                adapter = DirectChatAdapter(composition)
                actual = adapter.prepare_context(history, snapshot).snapshot()
                legacy_session = adapter.prepare_context(history)
                legacy_session.set_system_context(expected)
                self.assertEqual(actual, legacy_session.snapshot())
                composition.close()

    def test_missing_and_corrupt_persona_use_production_default_without_write(self):
        for body in (None, "{broken", "{}"):
            with self.subTest(body=body), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                composition = self._composition(root, knowledge=False)
                path = root / "persona" / "persona.json"
                if body is not None:
                    path.parent.mkdir()
                    path.write_text(body, encoding="utf-8")
                before = path.read_bytes() if path.exists() else None
                expected = legacy_context(composition, "请求", [])
                self.assertEqual(composition.context.prepare("请求").system_context, expected)
                self.assertEqual(path.read_bytes() if path.exists() else None, before)
                composition.close()

    def test_record_disabled_memory_and_disabled_sources_never_retrieve(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _write_sources(root)
            memory_path = root / "memory" / "memories.json"
            data = json.loads(memory_path.read_text(encoding="utf-8"))
            data[0]["enabled"] = False
            memory_path.write_text(json.dumps(data), encoding="utf-8")
            composition = self._composition(root, persona=False, knowledge=False, rag=False)
            with patch.object(composition.context.persona, "load", side_effect=AssertionError("disabled")), \
                 patch.object(composition.context.knowledge, "retrieve", side_effect=AssertionError("disabled")), \
                 patch("production_sidecar.context.run_configured_rag_pipeline", side_effect=AssertionError("disabled")):
                snapshot = composition.context.prepare("黑白界面")
            self.assertEqual(snapshot.system_context, "")
            self.assertEqual(snapshot.diagnostics["memory_item_count"], 0)
            composition.close()

    def test_vector_unavailable_and_rag_failure_keep_production_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _write_sources(root)
            composition = self._composition(root, rag=True)
            # A valid synthetic index activates the real vector search branch.
            writable = type(composition.context.knowledge)(root / "knowledge")
            writable.save_vector("knowledge-1", [1.0, 0.0], "fixture")
            with patch("production_sidecar.context.OllamaEmbeddingProvider.embed_text", side_effect=OSError("private")), \
                 patch("modules.rag_integration.run_rag_pipeline", side_effect=ValueError("private")):
                snapshot = composition.context.prepare("黑白界面")
            self.assertIn("design.md", snapshot.system_context)
            self.assertEqual(snapshot.diagnostics["context_error_stage"], "rag")
            self.assertNotIn("private", str(dict(snapshot.diagnostics)))
            composition.close()

    def test_subprocess_import_construct_is_headless_and_side_effect_free(self):
        with tempfile.TemporaryDirectory() as directory:
            code = '''
import sys
from pathlib import Path
from production_sidecar.composition import ProductionComposition
c = ProductionComposition(context_root=Path(sys.argv[1]))
c.context.prepare("synthetic")
assert not any(n in sys.modules for n in ("tkinter", "main", "widgets", "modules.memory_intelligence", "modules.conversation_intelligence"))
from modules.settings import settings
assert settings._instance is None
assert not list(Path(sys.argv[1]).rglob("*.json"))
c.close()
'''
            result = subprocess.run([sys.executable, "-c", code, directory], cwd=ROOT,
                env={**os.environ, "PYTHONPATH": str(SIDECAR) + os.pathsep + str(ROOT),
                     "AURORA_USER_DATA_DIR": directory, "PYTHONDONTWRITEBYTECODE": "1"},
                capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_disabled_sources_are_skipped_and_no_context_baseline_is_empty(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            composition = self._composition(root, persona=False, knowledge=False, rag=False)
            snapshot = composition.context.prepare("普通请求")
            self.assertEqual(snapshot.system_context, "")
            self.assertFalse(snapshot.diagnostics["persona_enabled"])
            self.assertFalse(snapshot.diagnostics["knowledge_enabled"])
            self.assertFalse(snapshot.diagnostics["rag_enabled"])
            self.assertIsNone(snapshot.diagnostics["persona_ms"])
            self.assertIsNone(snapshot.diagnostics["knowledge_ms"])
            self.assertIsNone(snapshot.diagnostics["rag_ms"])
            composition.close()

    def test_rag_enabled_uses_existing_pipeline_and_reports_count(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _write_sources(root, persona=False, knowledge=False, memory=False)
            composition = self._composition(root, persona=False, knowledge=False, rag=True)
            result = {
                "sections": [{"name": "Memory", "content": "optimized", "items": [{"id": "m"}]}],
                "diagnostics": {"success": True},
            }
            with patch("production_sidecar.context.run_configured_rag_pipeline", return_value=result) as runner:
                snapshot = composition.context.prepare("请求", [{"role": "assistant", "content": "旧答复"}])
            runner.assert_called_once()
            self.assertEqual(snapshot.diagnostics["rag_result_count"], 1)
            self.assertIsNotNone(snapshot.diagnostics["rag_ms"])
            self.assertIn("optimized", snapshot.system_context)
            composition.close()

    def test_context_cancelled_at_boundary(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            composition = self._composition(root, persona=False, knowledge=False, rag=False)
            stop = threading.Event()
            stop.set()
            with self.assertRaises(ContextCancelled):
                composition.context.prepare("请求", stop_event=stop)
            composition.close()

    def test_source_failure_is_bounded_to_safe_context_stage(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            composition = self._composition(root, persona=False, knowledge=False, rag=False)
            with patch.object(composition.context.memory, "list_memories", side_effect=OSError("private detail")):
                with self.assertRaises(ContextPreparationError) as raised:
                    composition.context.prepare("请求")
            self.assertEqual(raised.exception.stage, "memory")
            self.assertNotIn("private detail", str(raised.exception))
            composition.close()

    def test_read_only_sources_do_not_write(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _write_sources(root)
            files = [root / "memory" / "memories.json", root / "persona" / "persona.json",
                     root / "knowledge" / "metadata.json"]
            before = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in files}
            composition = self._composition(root)
            composition.context.prepare("黑白界面")
            after = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in files}
            self.assertEqual(before, after)
            composition.close()

    def test_current_turn_appended_once_without_deleting_identical_historical_turn(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            composition = self._composition(root, persona=False, knowledge=False, rag=False)
            adapter = DirectChatAdapter(composition)
            captured = {}

            def fake_stream_chat(model, prompt, session, on_chunk, stop_event, **kwargs):
                session.add_user(prompt)
                captured["messages"] = session.snapshot()
                kwargs["raw_line_observer"]({"done": True})
                return "done"

            adapter.api["stream_chat"] = fake_stream_chat
            request = ChatRequest("r", "s", "g", "same", history=({"role": "user", "content": "same"},))
            handle = adapter.new_handle(threading.Event(), {})
            adapter.stream(request, "model", handle, lambda chunk: None)
            users = [item for item in captured["messages"] if item["role"] == "user"]
            self.assertEqual(users, [{"role": "user", "content": "same"}] * 2)
            composition.close()


class ContextCancellationIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_cancel_at_every_context_stage_prevents_model_and_save(self):
        for stage in ("memory", "persona", "knowledge", "rag", "prompt_assembly"):
            with self.subTest(stage=stage), tempfile.TemporaryDirectory() as directory, model_server() as (host, calls):
                import production_sidecar.context as api
                root = Path(directory)
                _write_sources(root)
                path = write_settings(root, host, rag={"pipeline_enabled": True})
                composition = ProductionComposition(ROOT, path, context_root=root, conversation_root=root / "conversations")
                sidecar = ProductionSidecar("token", composition)
                events = []

                async def send(connection, event):
                    validate_message(event)
                    events.append(event)

                sidecar.send = send
                created = composition.conversations.create()
                target, attribute = {
                    "memory": (api, "retrieve_memories"),
                    "persona": (composition.context.persona, "load"),
                    "knowledge": (composition.context.knowledge, "retrieve"),
                    "rag": (api, "run_configured_rag_pipeline"),
                    "prompt_assembly": (api.ContextBuilder, "build_from_formatted_context"),
                }[stage]
                original = getattr(target, attribute)
                entered, release = threading.Event(), threading.Event()

                def blocked(*args, **kwargs):
                    result = original(*args, **kwargs)
                    entered.set()
                    if not release.wait(3):
                        raise TimeoutError("test stage release")
                    return result

                connection = object()
                message = request(stage)
                message["payload"]["conversation_id"] = created["conversation_id"]
                with patch.object(target, attribute, blocked):
                    try:
                        await sidecar.chat.start(connection, message)
                        run = sidecar.chat.active
                        self.assertTrue(await asyncio.to_thread(entered.wait, 2))
                        # Health/IPC remains live while a disk/CPU source is blocked.
                        self.assertEqual((await asyncio.wait_for(composition.refresh(), 1))["ollama"]["reachable"], True)
                        cancellation = envelope("chat.cancel.request", "cancel", target_request_id=message["request_id"])
                        cancellation.update(session_id="session", generation_id=message["generation_id"])
                        await asyncio.wait_for(sidecar.chat.cancel(connection, cancellation), 1)
                        self.assertIs(sidecar.chat.active, run)
                        self.assertFalse(run.task.done())
                    finally:
                        release.set()
                    await asyncio.wait_for(run.task, 3)
                self.assertEqual(run.terminal, "cancelled")
                self.assertEqual(calls, [])
                self.assertTrue(events[-1]["payload"]["diagnostics"]["worker_exited"])
                self.assertIsNotNone(events[-1]["payload"]["diagnostics"]["context_total_ms"])
                self.assertEqual(list((root / "conversations").glob("*.json")), [])
                # N+1 begins only after N really exited, and reuses a clean context.
                await sidecar.chat.start(connection, request(stage + "-next"))
                await asyncio.wait_for(sidecar.chat.active.task, 3)
                self.assertEqual(events[-1]["payload"]["terminal_state"], "completed")
                self.assertEqual(len(calls), 1)
                await sidecar.chat.close()
                composition.close()

    async def test_async_task_cancel_joins_actual_context_thread_before_reuse(self):
        with tempfile.TemporaryDirectory() as directory, model_server() as (host, calls):
            root = Path(directory)
            composition = ProductionComposition(ROOT, write_settings(root, host),
                context_root=root, conversation_root=root / "conversations")
            sidecar = ProductionSidecar("token", composition)
            events = []
            async def send(connection, event):
                events.append(event)
            sidecar.send = send
            entered, release, exited = threading.Event(), threading.Event(), threading.Event()
            def slow(prompt, history, stop_event, **identity):
                entered.set()
                try:
                    if not release.wait(3):
                        raise TimeoutError("test release")
                    raise ContextCancelled()
                finally:
                    exited.set()
            with patch.object(composition.context, "prepare", slow):
                try:
                    await sidecar.chat.start(object(), request())
                    run = sidecar.chat.active
                    self.assertTrue(await asyncio.to_thread(entered.wait, 2))
                    run.task.cancel()
                    await asyncio.sleep(.03)
                    self.assertIs(sidecar.chat.active, run)
                    self.assertFalse(run.task.done())
                finally:
                    release.set()
                await asyncio.wait_for(run.task, 2)
            self.assertTrue(exited.is_set())
            self.assertEqual(run.terminal, "cancelled")
            self.assertEqual(calls, [])
            self.assertIsNone(sidecar.chat.active)
            composition.close()

    async def test_context_is_ephemeral_and_completed_history_only_is_saved(self):
        with tempfile.TemporaryDirectory() as directory, model_server() as (host, calls):
            root = Path(directory)
            _write_sources(root)
            path = write_settings(root, host)
            sources = list(root.rglob("*"))
            before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in sources if p.is_file()}
            composition = ProductionComposition(ROOT, path, context_root=root, conversation_root=root / "conversations")
            sidecar = ProductionSidecar("token", composition)
            events = []
            async def send(connection, event):
                validate_message(event)
                events.append(event)
            sidecar.send = send
            created = composition.conversations.create()
            for index in ("one", "two"):
                message = request(index)
                message["payload"].update(conversation_id=created["conversation_id"], input="黑白界面")
                await sidecar.chat.start(object(), message)
                await asyncio.wait_for(sidecar.chat.active.task, 5)
                self.assertEqual(events[-1]["payload"]["terminal_state"], "completed")
            saved = composition.conversations.get(created["conversation_id"])
            self.assertEqual(saved["title"], "New Conversation")
            self.assertEqual(len([m for m in saved["messages"] if m["role"] == "user"]), 2)
            self.assertEqual(len([m for m in calls[1]["messages"] if m["role"] == "user"]), 2)
            self.assertIn("合成测试角色", calls[1]["messages"][0]["content"])
            for private in ("合成测试角色", "用户偏好简洁", "Source: design.md"):
                self.assertNotIn(private, json.dumps(saved, ensure_ascii=False))
                self.assertNotIn(private, json.dumps(events, ensure_ascii=False))
            self.assertEqual(before, {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in before})
            self.assertFalse((root / "memory" / "memory_candidates.json").exists())
            self.assertFalse(any(p.is_file() and p not in before and "conversations" not in p.parts for p in root.rglob("*")))
            composition.close()

    async def test_cancel_during_context_prevents_ollama_entry(self):
        with tempfile.TemporaryDirectory() as directory, model_server() as (host, calls):
            root = Path(directory)
            path = write_settings(root, host, persona={"enabled": False},
                                  knowledge={"enabled": False}, rag={"pipeline_enabled": False})
            composition = ProductionComposition(ROOT, path, context_root=root,
                                                conversation_root=root / "conversations")
            sidecar = ProductionSidecar("token", composition)
            events = []
            entered = threading.Event()

            async def send(connection, event):
                validate_message(event)
                events.append(event)

            sidecar.send = send

            def slow_context(prompt, history, stop_event, **identity):
                entered.set()
                while not stop_event.is_set():
                    time.sleep(0.005)
                raise ContextCancelled()

            composition.context.prepare = slow_context
            connection = object()
            await sidecar.chat.start(connection, request())
            run = sidecar.chat.active
            await asyncio.to_thread(entered.wait, 2)
            cancellation = envelope("chat.cancel.request", "cancel-1", target_request_id="r1")
            cancellation.update(session_id="session", generation_id="g1")
            await sidecar.chat.cancel(connection, cancellation)
            await asyncio.wait_for(run.task, 2)
            self.assertEqual(run.terminal, "cancelled")
            self.assertEqual(calls, [])
            self.assertEqual(events[-1]["payload"]["terminal_state"], "cancelled")
            composition.close()
