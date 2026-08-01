"""Tests for conversation intelligence pipeline scheduling."""

import sys
import tempfile
import unittest
from pathlib import Path

from modules.conversation import (
    ConversationManager,
    schedule_conversation_intelligence,
)


class ImmediateThread:
    def __init__(self, *, target, daemon=False):
        self.target = target
        self.daemon = daemon
        self.started = False

    def start(self):
        self.started = True
        self.target()


class RecordingLogger:
    def __init__(self):
        self.errors = []

    def error(self, message):
        self.errors.append(str(message))


class ConversationIntelligencePipelineTests(unittest.TestCase):
    def make_manager(self):
        return ConversationManager(Path(tempfile.mkdtemp()))

    def test_save_success_triggers_analysis_scheduling(self):
        manager = self.make_manager()
        conversation = manager.save(
            None,
            "model",
            [{"role": "user", "content": "Analyze this."}],
        )
        calls = []

        def analyzer(messages):
            calls.append(messages)
            return {"summary": "Analyze this."}

        thread = schedule_conversation_intelligence(
            manager,
            conversation["id"],
            conversation["messages"],
            expected_updated_time=conversation["updated_time"],
            analyzer=analyzer,
            thread_factory=ImmediateThread,
        )

        self.assertTrue(thread.started)
        self.assertEqual(len(calls), 1)

    def test_analysis_result_saved_to_metadata_namespace(self):
        manager = self.make_manager()
        conversation = manager.save(
            None,
            "model",
            [{"role": "user", "content": "Summarize this."}],
        )

        schedule_conversation_intelligence(
            manager,
            conversation["id"],
            conversation["messages"],
            expected_updated_time=conversation["updated_time"],
            analyzer=lambda _messages: {"summary": "Summarize this."},
            thread_factory=ImmediateThread,
        )

        updated = manager.load(conversation["id"])
        self.assertEqual(
            updated["metadata"]["conversation_intelligence"],
            {"summary": "Summarize this."},
        )

    def test_existing_metadata_preserved(self):
        manager = self.make_manager()
        conversation = manager.save(
            None,
            "model",
            [{"role": "user", "content": "Hello"}],
            metadata={"custom": {"keep": True}},
        )

        schedule_conversation_intelligence(
            manager,
            conversation["id"],
            conversation["messages"],
            expected_updated_time=conversation["updated_time"],
            analyzer=lambda _messages: {"summary": "Hello"},
            thread_factory=ImmediateThread,
        )

        updated = manager.load(conversation["id"])
        self.assertEqual(updated["metadata"]["custom"], {"keep": True})
        self.assertEqual(updated["metadata"]["conversation_intelligence"], {"summary": "Hello"})

    def test_analysis_failure_does_not_break_saved_conversation(self):
        manager = self.make_manager()
        logger = RecordingLogger()
        conversation = manager.save(
            None,
            "model",
            [{"role": "user", "content": "Hello"}],
        )

        def analyzer(_messages):
            raise RuntimeError("analysis failed")

        schedule_conversation_intelligence(
            manager,
            conversation["id"],
            conversation["messages"],
            expected_updated_time=conversation["updated_time"],
            logger=logger,
            analyzer=analyzer,
            thread_factory=ImmediateThread,
        )

        saved = manager.load(conversation["id"])
        self.assertEqual(saved["messages"], conversation["messages"])
        self.assertNotIn("conversation_intelligence", saved["metadata"])
        self.assertTrue(any("analysis failed" in message for message in logger.errors))

    def test_stale_analysis_does_not_overwrite_newer_conversation(self):
        manager = self.make_manager()
        conversation = manager.save(
            None,
            "model",
            [{"role": "user", "content": "old"}],
        )
        manager.save(
            conversation["id"],
            "model",
            [
                {"role": "user", "content": "new"},
                {"role": "assistant", "content": "new response"},
            ],
            title=conversation["title"],
            created_at=conversation["created_at"],
            metadata={"conversation_intelligence": {"summary": "new"}},
        )

        schedule_conversation_intelligence(
            manager,
            conversation["id"],
            conversation["messages"],
            expected_updated_time=conversation["updated_time"],
            analyzer=lambda _messages: {"summary": "old"},
            thread_factory=ImmediateThread,
        )

        updated = manager.load(conversation["id"])
        self.assertEqual(updated["metadata"]["conversation_intelligence"], {"summary": "new"})

    def test_memory_pipeline_not_called(self):
        manager = self.make_manager()
        conversation = manager.save(
            None,
            "model",
            [{"role": "user", "content": "Hello"}],
        )
        memory_module_loaded = "modules.memory" in sys.modules

        schedule_conversation_intelligence(
            manager,
            conversation["id"],
            conversation["messages"],
            expected_updated_time=conversation["updated_time"],
            analyzer=lambda _messages: {"summary": "Hello"},
            thread_factory=ImmediateThread,
        )

        self.assertEqual("modules.memory" in sys.modules, memory_module_loaded)


if __name__ == "__main__":
    unittest.main()
