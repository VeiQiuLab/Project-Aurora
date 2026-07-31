"""Tests for durable Memory metadata lifecycle state."""

import tempfile
import unittest
from pathlib import Path

from modules.memory import MemoryStore


class MemoryMetadataLifecycleTests(unittest.TestCase):
    def make_store(self):
        return MemoryStore(Path(tempfile.mkdtemp()))

    def create_memory_with_metadata(self, store):
        return store.create(
            "preference",
            "old",
            "normal",
            metadata={
                "category": "communication_style",
                "confidence": 0.9,
                "source_detail": {"kind": "chat"},
            },
        )

    def test_content_change_marks_metadata_stale(self):
        store = self.make_store()
        memory = self.create_memory_with_metadata(store)

        updated = store.update(memory["id"], "preference", "new", "normal")

        self.assertEqual(updated["metadata"]["confidence"], 0.9)
        self.assertTrue(updated["metadata"]["stale"])
        self.assertEqual(updated["metadata"]["stale_reason"], "memory_updated")
        self.assertTrue(updated["metadata"]["stale_time"])

    def test_type_change_marks_metadata_stale(self):
        store = self.make_store()
        memory = self.create_memory_with_metadata(store)

        updated = store.update(memory["id"], "fact", "old", "normal")

        self.assertTrue(updated["metadata"]["stale"])
        self.assertEqual(updated["metadata"]["stale_reason"], "memory_updated")

    def test_importance_change_does_not_mark_metadata_stale(self):
        store = self.make_store()
        memory = self.create_memory_with_metadata(store)

        updated = store.update(memory["id"], "preference", "old", "high")

        self.assertEqual(updated["importance"], "high")
        self.assertNotIn("stale", updated["metadata"])
        self.assertNotIn("stale_reason", updated["metadata"])
        self.assertNotIn("stale_time", updated["metadata"])

    def test_enabled_change_does_not_mark_metadata_stale(self):
        store = self.make_store()
        memory = self.create_memory_with_metadata(store)

        updated = store.set_enabled(memory["id"], False)

        self.assertFalse(updated["enabled"])
        self.assertNotIn("stale", updated["metadata"])
        self.assertNotIn("stale_reason", updated["metadata"])
        self.assertNotIn("stale_time", updated["metadata"])

    def test_old_memory_without_metadata_can_update(self):
        store = self.make_store()
        memory = store.create("fact", "old", "normal")

        updated = store.update(memory["id"], "fact", "new", "normal")

        self.assertEqual(updated["content"], "new")
        self.assertNotIn("metadata", updated)

    def test_metadata_fields_are_preserved_when_marked_stale(self):
        store = self.make_store()
        memory = self.create_memory_with_metadata(store)

        updated = store.update(memory["id"], "preference", "new", "normal")

        self.assertEqual(updated["metadata"]["category"], "communication_style")
        self.assertEqual(updated["metadata"]["confidence"], 0.9)
        self.assertEqual(updated["metadata"]["source_detail"], {"kind": "chat"})


if __name__ == "__main__":
    unittest.main()
