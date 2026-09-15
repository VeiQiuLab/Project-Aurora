"""V4-3C conversation boundary tests; every test uses a disposable root."""
from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SIDECAR = Path(__file__).resolve().parents[1]
ROOT = SIDECAR.parents[2]
sys.path[:0] = [str(SIDECAR), str(ROOT)]

from production_sidecar.conversations import ConversationError, ConversationPersistence
from production_sidecar.composition import ProductionComposition
from production_sidecar.server import ProductionSidecar
from test_direct_chat import model_server
from test_production_sidecar import child_sidecar, envelope, validate_message, write_settings
from websockets.asyncio.client import connect


class PersistenceTests(unittest.TestCase):
    def test_list_is_metadata_only_sorted_and_does_not_rewrite(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            root.mkdir(exist_ok=True)
            manager = ConversationPersistence(root)
            manager.manager.save("older", "m", [{"role": "user", "content": "one"}], title="旧")
            manager.manager.save("newer", "m", [{"role": "assistant", "content": "two"}], title="新")
            (root / "broken.json").write_text("{broken", encoding="utf-8")
            before = {p.name: p.stat().st_mtime_ns for p in root.glob("*.json")}
            records = manager.list_metadata()
            self.assertEqual([item["conversation_id"] for item in records], ["newer", "older"])
            self.assertEqual(set(records[0]), {"conversation_id", "title", "created_at", "updated_at", "message_count", "model"})
            self.assertEqual(records[0]["message_count"], 1)
            self.assertEqual(before, {p.name: p.stat().st_mtime_ns for p in root.glob("*.json")})

    def test_get_order_roles_and_missing_or_traversal(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manager = ConversationPersistence(root)
            manager.manager.save("history", "m", [
                {"role": "system", "content": "system"},
                {"role": "user", "content": "first"},
                {"role": "tool", "content": "ignored"},
                {"role": "assistant", "content": "second"},
            ])
            self.assertEqual([m["role"] for m in manager.get("history")["messages"]], ["system", "user", "assistant"])
            with self.assertRaisesRegex(ConversationError, "not found"):
                manager.get("missing")
            with self.assertRaisesRegex(ConversationError, "Invalid conversation ID"):
                manager.get("../../outside")
            with self.assertRaisesRegex(ConversationError, "Invalid conversation ID"):
                manager.get("C:\\outside")

    def test_create_is_ephemeral_and_save_completed_materializes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manager = ConversationPersistence(root)
            created = manager.create()
            self.assertFalse((root / f"{created['conversation_id']}.json").exists())
            self.assertEqual(manager.history(created["conversation_id"]), [])
            saved = manager.save_completed(created["conversation_id"], "model", [
                {"role": "system", "content": "system"},
                {"role": "user", "content": "hello"},
                {"role": "assistant", "content": "world"},
            ])
            self.assertEqual(saved["message_count"], 3)
            self.assertEqual(manager.get(created["conversation_id"])["messages"][-1]["content"], "world")

    def test_unknown_history_id_is_not_treated_as_new(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = ConversationPersistence(Path(directory))
            with self.assertRaisesRegex(ConversationError, "not found"):
                manager.history("unknown")

    def test_save_does_not_import_intelligence_or_memory(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = ConversationPersistence(Path(directory))
            with patch.dict(sys.modules, {"modules.conversation_intelligence": None, "modules.memory": None}):
                manager.save_completed("safe", "m", [{"role": "user", "content": "u"}, {"role": "assistant", "content": "a"}])


class RpcTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_process_conversation_rpc_roundtrip(self):
        with tempfile.TemporaryDirectory() as directory:
            async with child_sidecar(directory) as (process, bootstrap, token):
                uri = f"ws://127.0.0.1:{bootstrap['port']}"
                async with connect(uri, additional_headers={"Authorization": f"Bearer {token}"}) as ws:
                    await ws.send(json.dumps(envelope("hello", "hello-rpc", client="aurora-desktop", supported_versions=[1])))
                    hello = json.loads(await ws.recv())
                    validate_message(hello)
                    await ws.send(json.dumps(envelope("conversation.list.request", "list-rpc")))
                    listed = json.loads(await ws.recv())
                    validate_message(listed)
                    self.assertEqual(listed["type"], "conversation.list.response")
                    self.assertEqual(listed["payload"]["conversations"], [])
                    await ws.send(json.dumps(envelope("conversation.create.request", "create-rpc")))
                    created = json.loads(await ws.recv())
                    validate_message(created)
                    self.assertEqual(created["type"], "conversation.create.response")
                    conversation_id = created["payload"]["conversation"]["conversation_id"]
                    await ws.send(json.dumps(envelope("conversation.get.request", "get-rpc", conversation_id=conversation_id)))
                    missing = json.loads(await ws.recv())
                    validate_message(missing)
                    self.assertEqual((missing["type"], missing["payload"]["code"]), ("error", "NOT_FOUND"))
                    await ws.send(json.dumps(envelope("shutdown.request", "shutdown-rpc")))
                    shutdown = json.loads(await ws.recv())
                    validate_message(shutdown)
                    self.assertEqual(shutdown["type"], "shutdown.ack")

    async def test_production_rpc_list_get_create_and_errors(self):
        with tempfile.TemporaryDirectory() as directory, model_server() as (host, _):
            root = Path(directory)
            composition = ProductionComposition(ROOT, write_settings(root, host), conversation_root=root / "conversations")
            sidecar = ProductionSidecar("token", composition)
            events = []

            async def send(connection, event):
                validate_message(event)
                events.append(event)

            sidecar.send = send
            connection = object()
            await sidecar.conversation_create(connection, {"request_id": "create-1", "payload": {}})
            created = events[-1]["payload"]["conversation"]
            self.assertEqual(created["message_count"], 0)
            await sidecar.conversation_list(connection, {"request_id": "list-1", "payload": {}})
            self.assertEqual(events[-1]["type"], "conversation.list.response")
            await sidecar.conversation_get(connection, {"request_id": "get-1", "payload": {"conversation_id": "missing"}})
            self.assertEqual(events[-1]["payload"]["code"], "NOT_FOUND")
            composition.close()

    async def test_completed_chat_uses_history_and_persists_only_completed_turn(self):
        with tempfile.TemporaryDirectory() as directory, model_server() as (host, calls):
            root = Path(directory)
            conversation_root = root / "conversations"
            persistence = ConversationPersistence(conversation_root)
            persistence.save_completed("history", "test-model", [
                {"role": "system", "content": "system"},
                {"role": "user", "content": "previous"},
                {"role": "assistant", "content": "answer"},
            ])
            composition = ProductionComposition(ROOT, write_settings(root, host,
                persona={"enabled": False}, knowledge={"enabled": False}, rag={"pipeline_enabled": False}),
                conversation_root=conversation_root)
            sidecar = ProductionSidecar("token", composition)
            events = []

            async def send(connection, event):
                validate_message(event)
                events.append(event)

            sidecar.send = send
            connection = object()
            message = {
                "request_id": "r-history", "session_id": "session", "generation_id": "g-history",
                "payload": {"conversation_id": "history", "input": "current"},
            }
            await sidecar.chat.start(connection, message)
            await asyncio.wait_for(sidecar.chat.active.task, 5)
            self.assertEqual(calls[0]["messages"], [
                {"role": "system", "content": "system"},
                {"role": "user", "content": "previous"},
                {"role": "assistant", "content": "answer"},
                {"role": "user", "content": "current"},
            ])
            saved = persistence.get("history")["messages"]
            self.assertEqual([item["content"] for item in saved][-2:], ["current", "你好，世界。"])
            self.assertEqual(events[-1]["payload"]["terminal_state"], "completed")
            composition.close()

    async def test_created_identity_accepts_first_turn_then_materializes(self):
        with tempfile.TemporaryDirectory() as directory, model_server() as (host, calls):
            root = Path(directory)
            conversation_root = root / "conversations"
            composition = ProductionComposition(ROOT, write_settings(root, host), conversation_root=conversation_root)
            sidecar = ProductionSidecar("token", composition)
            events = []

            async def send(connection, event):
                validate_message(event)
                events.append(event)

            sidecar.send = send
            connection = object()
            created = await asyncio.to_thread(composition.conversations.create)
            message = {
                "request_id": "r-created", "session_id": "session", "generation_id": "g-created",
                "payload": {"conversation_id": created["conversation_id"], "input": "first"},
            }
            await sidecar.chat.start(connection, message)
            await asyncio.wait_for(sidecar.chat.active.task, 5)
            saved = composition.conversations.get(created["conversation_id"])
            self.assertEqual([item["role"] for item in saved["messages"]], ["user", "assistant"])
            self.assertEqual(events[-1]["payload"]["terminal_state"], "completed")
            composition.close()

    async def test_cancelled_turn_does_not_materialize_or_save_partial_assistant(self):
        with tempfile.TemporaryDirectory() as directory, model_server("blocked") as (host, _):
            root = Path(directory)
            conversation_root = root / "conversations"
            composition = ProductionComposition(ROOT, write_settings(root, host), conversation_root=conversation_root)
            sidecar = ProductionSidecar("token", composition)
            sidecar.send = lambda connection, event: asyncio.sleep(0)
            created = await asyncio.to_thread(composition.conversations.create)
            message = {
                "request_id": "r-cancelled", "session_id": "session", "generation_id": "g-cancelled",
                "payload": {"conversation_id": created["conversation_id"], "input": "cancel me"},
            }
            await sidecar.chat.start(object(), message)
            run = sidecar.chat.active
            await asyncio.sleep(0.05)
            await sidecar.chat.cancel(run.connection, {
                "request_id": "cancel-cancelled", "session_id": "session", "generation_id": "g-cancelled",
                "payload": {"target_request_id": "r-cancelled"},
            })
            await asyncio.wait_for(run.task, 5)
            self.assertEqual(run.terminal, "cancelled")
            self.assertFalse((conversation_root / f"{created['conversation_id']}.json").exists())
            composition.close()

    async def test_failed_turn_does_not_persist_user_or_partial_assistant(self):
        with tempfile.TemporaryDirectory() as directory, model_server("incomplete") as (host, _):
            root = Path(directory)
            conversation_root = root / "conversations"
            composition = ProductionComposition(ROOT, write_settings(root, host), conversation_root=conversation_root)
            sidecar = ProductionSidecar("token", composition)
            sidecar.send = lambda connection, event: asyncio.sleep(0)
            created = await asyncio.to_thread(composition.conversations.create)
            message = {
                "request_id": "r-failed", "session_id": "session", "generation_id": "g-failed",
                "payload": {"conversation_id": created["conversation_id"], "input": "fail me"},
            }
            await sidecar.chat.start(object(), message)
            run = sidecar.chat.active
            await asyncio.wait_for(run.task, 5)
            self.assertEqual(run.terminal, "failed")
            self.assertFalse((conversation_root / f"{created['conversation_id']}.json").exists())
            composition.close()


if __name__ == "__main__":
    unittest.main()
