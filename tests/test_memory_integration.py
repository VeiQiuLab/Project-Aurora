"""Integration tests for MemoryStore and Memory Intelligence."""

import tempfile
import unittest
from pathlib import Path

from modules.memory import MemoryStore


class MemoryIntelligenceIntegrationTests(unittest.TestCase):
    def make_store(self):
        return MemoryStore(Path(tempfile.mkdtemp()))

    def test_extract_candidates_returns_intelligence_fields(self):
        store = self.make_store()

        candidates = store.extract_candidates("I prefer concise release summaries.")

        self.assertEqual(len(candidates), 1)
        candidate = candidates[0]
        self.assertIn("category", candidate)
        self.assertIn("confidence", candidate)
        self.assertIn("risk", candidate)
        self.assertIn("explanation", candidate)

    def test_queue_candidates_preserves_intelligence_fields(self):
        store = self.make_store()

        queued = store.queue_candidates("I prefer concise release summaries.")

        self.assertEqual(len(queued), 1)
        candidate = queued[0]
        self.assertIn("category", candidate)
        self.assertIn("confidence", candidate)
        self.assertIn("risk", candidate)
        self.assertIn("explanation", candidate)

    def test_queue_candidates_passes_source_to_source_detail(self):
        store = self.make_store()

        queued = store.queue_candidates("I prefer concise release summaries.", source="mobile")

        self.assertEqual(queued[0]["source"], "mobile")
        self.assertEqual(queued[0]["source_detail"]["kind"], "mobile")

    def test_intelligence_importance_is_not_overwritten(self):
        store = self.make_store()

        def fake_extract(_messages_or_text, min_score=0.75, source="chat"):
            return [
                {
                    "type": "preference",
                    "content": "User prefers short answers.",
                    "score": 0.86,
                    "importance": "low",
                    "importance_score": 9.5,
                    "category": "communication_style",
                    "confidence": 0.9,
                    "risk": {"level": "low", "reasons": []},
                    "explanation": "test_candidate",
                    "source_detail": {"kind": source, "extractor": "test", "signals": []},
                }
            ]

        store.extract_candidates = fake_extract

        queued = store.queue_candidates("ignored")

        self.assertEqual(queued[0]["importance"], "low")
        self.assertEqual(queued[0]["importance_score"], 9.5)

    def test_legacy_candidate_still_works(self):
        store = self.make_store()

        def fake_extract(_messages_or_text, min_score=0.75, source="chat"):
            return [
                {
                    "type": "fact",
                    "content": "User works on Project Aurora.",
                    "score": 0.78,
                }
            ]

        store.extract_candidates = fake_extract

        queued = store.queue_candidates("ignored")

        self.assertEqual(len(queued), 1)
        self.assertEqual(queued[0]["type"], "fact")
        self.assertEqual(queued[0]["content"], "User works on Project Aurora.")
        self.assertIn("importance", queued[0])

    def test_queue_candidates_does_not_write_real_memories_file(self):
        root = Path(__file__).resolve().parent.parent
        memories_file = root / "data" / "memory" / "memories.json"
        before = memories_file.read_bytes() if memories_file.exists() else None

        store = self.make_store()
        store.queue_candidates("I prefer concise release summaries.")

        after = memories_file.read_bytes() if memories_file.exists() else None
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
