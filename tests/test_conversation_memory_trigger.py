import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from modules.conversation import ConversationManager, schedule_conversation_intelligence
from modules.memory import MemoryStore


class ImmediateThread:
    def __init__(self, *, target, daemon=False):
        self.target = target
        self.daemon = daemon
        self.started = False

    def start(self):
        self.started = True
        self.target()


class Logger:
    def __init__(self):
        self.errors = []

    def error(self, message):
        self.errors.append(str(message))


class ConversationMemoryTriggerTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.manager = ConversationManager(Path(self.directory.name) / "conversations")
        self.store = MemoryStore(Path(self.directory.name) / "memories.json")
        self.messages = [
            {"role": "user", "content": "I prefer concise replies."},
            {"role": "assistant", "content": "Understood."},
        ]

    def tearDown(self):
        self.directory.cleanup()

    def _save(self):
        return self.manager.save(None, "model", self.messages)

    def _analysis(self, signals=None):
        return {
            "summary": "Conversation summary",
            "memory_signals": signals if signals is not None else [
                {"content": "User prefers concise replies", "type": "preference"}
            ],
            "message_count": 2,
            "analysis_version": "conversation_intelligence_v1",
            "analyzed_time": "2026-08-02T00:00:00+00:00",
        }

    def _schedule(self, conversation, analysis, **kwargs):
        return schedule_conversation_intelligence(
            self.manager,
            conversation["id"],
            conversation["messages"],
            expected_updated_time=conversation["updated_time"],
            analyzer=lambda _messages: analysis,
            thread_factory=ImmediateThread,
            memory_store=self.store,
            **kwargs,
        )

    def test_successful_analysis_triggers_pending_candidates(self):
        conversation = self._save()
        self._schedule(conversation, self._analysis())
        self.assertEqual(len(self.store.list_candidates()), 1)
        self.assertEqual(self.store.list_candidates()[0]["status"], "pending")

    def test_empty_signals_skip(self):
        conversation = self._save()
        self._schedule(conversation, self._analysis([]))
        self.assertEqual(self.store.list_candidates(), [])

    def test_short_conversation_skip(self):
        conversation = self.manager.save(None, "model", [{"role": "user", "content": "One"}])
        self._schedule(conversation, self._analysis())
        self.assertEqual(self.store.list_candidates(), [])

    def test_duplicate_fingerprint_skip(self):
        conversation = self._save()
        self._schedule(conversation, self._analysis())
        first = self.store.list_candidates()
        saved = self.manager.load(conversation["id"])
        schedule_conversation_intelligence(
            self.manager,
            conversation["id"],
            saved["messages"],
            expected_updated_time=saved["updated_time"],
            analyzer=lambda _messages: self._analysis(),
            thread_factory=ImmediateThread,
            memory_store=self.store,
        )
        self.assertEqual(len(self.store.list_candidates()), len(first))

    def test_stale_analysis_skip(self):
        conversation = self._save()
        self.manager.save(
            conversation["id"],
            "model",
            self.messages + [{"role": "user", "content": "new"}],
            created_at=conversation["created_at"],
        )
        self._schedule(conversation, self._analysis())
        self.assertEqual(self.store.list_candidates(), [])

    def test_adapter_failure_isolated(self):
        conversation = self._save()
        logger = Logger()
        with patch(
            "modules.conversation_memory_adapter.adapt_memory_signals",
            side_effect=RuntimeError("adapter failed"),
        ):
            self._schedule(conversation, self._analysis(), logger=logger)
        self.assertEqual(self.manager.load(conversation["id"])["messages"], self.messages)
        self.assertEqual(self.store.list_candidates(), [])
        self.assertTrue(logger.errors)

    def test_memory_intelligence_failure_isolated(self):
        conversation = self._save()
        with patch(
            "modules.memory_intelligence.analyze_memory_candidates",
            side_effect=RuntimeError("intelligence failed"),
        ):
            self._schedule(conversation, self._analysis())
        candidate = self.store.list_candidates()[0]
        self.assertEqual(candidate["evaluation_status"], "unevaluated")
        self.assertEqual(self.store.list_memories(), [])

    def test_pending_storage_failure_isolated(self):
        conversation = self._save()
        with patch.object(self.store, "queue_candidate_records", side_effect=OSError("storage failed")):
            self._schedule(conversation, self._analysis())
        self.assertEqual(self.manager.load(conversation["id"])["messages"], self.messages)
        self.assertEqual(self.store.list_memories(), [])
        self.assertNotIn("conversation_memory_trigger", self.manager.load(conversation["id"])["metadata"])

    def test_chat_save_and_durable_memory_are_unaffected(self):
        conversation = self._save()
        self._schedule(conversation, self._analysis())
        self.assertEqual(self.manager.load(conversation["id"])["messages"], self.messages)
        self.assertEqual(self.store.list_memories(), [])

    def test_trigger_marker_is_written_after_success(self):
        conversation = self._save()
        self._schedule(conversation, self._analysis())
        marker = self.manager.load(conversation["id"])["metadata"]["conversation_memory_trigger"]
        self.assertTrue(marker["source_fingerprint"])
        self.assertEqual(marker["candidate_count"], 1)


if __name__ == "__main__":
    unittest.main()
