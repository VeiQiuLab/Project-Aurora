"""Tests for durable Memory metadata persistence."""

import json
import tempfile
import unittest
from pathlib import Path

from modules.memory import MemoryStore


class MemoryMetadataPersistenceTests(unittest.TestCase):
    def make_store(self):
        return MemoryStore(Path(tempfile.mkdtemp()))

    def test_approve_candidate_saves_metadata(self):
        store = self.make_store()
        queued = store.queue_candidates("I prefer concise release summaries.")

        memory = store.approve_candidate(queued[0]["id"])

        self.assertIn("metadata", memory)
        self.assertEqual(memory["metadata"]["category"], queued[0]["category"])
        self.assertEqual(memory["metadata"]["confidence"], queued[0]["confidence"])
        self.assertEqual(memory["metadata"]["risk"], queued[0]["risk"])

    def test_create_without_metadata_stays_compatible(self):
        store = self.make_store()

        memory = store.create("fact", "User works on Project Aurora.", "normal")

        self.assertEqual(memory["type"], "fact")
        self.assertEqual(memory["content"], "User works on Project Aurora.")
        self.assertEqual(memory["importance"], "normal")
        self.assertEqual(memory["metadata"]["state"], "active")

    def test_old_memory_shape_still_reads(self):
        store = self.make_store()
        old_memory = {
            "id": "old-memory",
            "type": "fact",
            "content": "Legacy memory.",
            "importance": "normal",
        }
        store.file_path.write_text(json.dumps([old_memory]), encoding="utf-8")

        memories = store.list_memories()

        self.assertEqual(len(memories), 1)
        self.assertEqual(memories[0]["id"], "old-memory")
        self.assertEqual(memories[0]["content"], "Legacy memory.")
        self.assertEqual(memories[0]["metadata"]["state"], "active")

    def test_update_preserves_metadata(self):
        store = self.make_store()
        metadata = {
            "category": "communication_style",
            "confidence": 0.9,
            "risk": {"level": "low", "reasons": []},
        }
        memory = store.create(
            "preference",
            "User prefers short answers.",
            "high",
            metadata=metadata,
        )

        updated = store.update(
            memory["id"],
            "preference",
            "User prefers concise answers.",
            "normal",
        )

        self.assertEqual(updated["content"], "User prefers concise answers.")
        self.assertEqual(updated["importance"], "normal")
        self.assertEqual(updated["metadata"]["category"], metadata["category"])
        self.assertEqual(updated["metadata"]["confidence"], metadata["confidence"])
        self.assertEqual(updated["metadata"]["risk"], metadata["risk"])
        self.assertTrue(updated["metadata"]["stale"])
        self.assertEqual(updated["metadata"]["stale_reason"], "memory_updated")

    def test_intelligence_importance_is_not_overwritten_on_approve(self):
        store = self.make_store()
        candidate = {
            "type": "fact",
            "content": "Low scoring candidate with Intelligence override.",
            "score": 0.2,
            "importance": "high",
            "importance_score": 9.5,
            "category": "long_term_fact",
            "confidence": 0.91,
            "risk": {"level": "low", "reasons": []},
        }

        saved = store.save_candidates([candidate], min_score=0)

        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0]["importance"], "high")
        self.assertEqual(saved[0]["metadata"]["importance_score"], 9.5)


if __name__ == "__main__":
    unittest.main()
