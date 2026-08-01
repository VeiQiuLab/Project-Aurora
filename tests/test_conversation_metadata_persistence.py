"""Tests for conversation metadata namespace persistence."""

import tempfile
import unittest
from pathlib import Path

from modules.conversation import ConversationManager


class ConversationMetadataPersistenceTests(unittest.TestCase):
    def make_manager(self):
        return ConversationManager(Path(tempfile.mkdtemp()))

    def test_save_metadata_uses_namespace(self):
        manager = self.make_manager()
        conversation = manager.save(
            None,
            "qwen3:8b",
            [{"role": "user", "content": "Hello"}],
            metadata={"existing": {"keep": True}},
        )

        updated = manager.save_metadata(
            conversation["id"],
            "conversation_intelligence",
            {"summary": "Hello", "topics": []},
        )

        self.assertEqual(
            updated["metadata"]["conversation_intelligence"],
            {"summary": "Hello", "topics": []},
        )
        self.assertEqual(updated["metadata"]["existing"], {"keep": True})

    def test_save_conversation_intelligence_wrapper(self):
        manager = self.make_manager()
        conversation = manager.save(
            None,
            "qwen3:8b",
            [{"role": "user", "content": "Summarize this."}],
        )
        analysis = {
            "summary": "Summarize this.",
            "topics": [{"topic": "summarize", "confidence": 0.5}],
            "important_events": [],
            "memory_signals": [],
            "analysis_version": "conversation_intelligence_v1",
            "analyzed_time": "2026-08-01T00:00:00+00:00",
        }

        updated = manager.save_conversation_intelligence(conversation["id"], analysis)

        self.assertEqual(updated["metadata"]["conversation_intelligence"], analysis)

    def test_metadata_update_does_not_change_messages(self):
        manager = self.make_manager()
        messages = [
            {"role": "user", "content": "First"},
            {"role": "assistant", "content": "Second"},
        ]
        conversation = manager.save(None, "model", messages, title="Chat")

        updated = manager.save_metadata(
            conversation["id"],
            "conversation_intelligence",
            {"summary": "First"},
        )

        self.assertEqual(updated["messages"], messages)
        self.assertEqual(updated["title"], "Chat")
        self.assertEqual(updated["model"], "model")

    def test_namespace_update_replaces_only_that_namespace(self):
        manager = self.make_manager()
        conversation = manager.save(
            None,
            "model",
            [{"role": "user", "content": "Hello"}],
            metadata={
                "conversation_intelligence": {"summary": "old"},
                "custom": {"value": 1},
            },
        )

        updated = manager.save_metadata(
            conversation["id"],
            "conversation_intelligence",
            {"summary": "new"},
        )

        self.assertEqual(updated["metadata"]["conversation_intelligence"], {"summary": "new"})
        self.assertEqual(updated["metadata"]["custom"], {"value": 1})

    def test_invalid_payload_becomes_empty_namespace(self):
        manager = self.make_manager()
        conversation = manager.save(
            None,
            "model",
            [{"role": "user", "content": "Hello"}],
        )

        updated = manager.save_metadata(conversation["id"], "conversation_intelligence", None)

        self.assertEqual(updated["metadata"]["conversation_intelligence"], {})


if __name__ == "__main__":
    unittest.main()
