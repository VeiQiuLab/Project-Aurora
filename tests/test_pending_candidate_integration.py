import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from modules.conversation_memory_adapter import queue_conversation_memory_candidates
from modules.memory import MemoryStore


class PendingCandidateIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = MemoryStore(Path(self.temp_dir.name) / "memories.json")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_adapter_candidate_enters_pending_queue(self):
        result = queue_conversation_memory_candidates(
            self.store,
            [{"content": "User likes concise replies", "type": "preference"}],
            conversation_id="conversation-1",
        )
        self.assertEqual(len(result["candidates"]), 1)
        self.assertEqual(self.store.list_candidates()[0]["status"], "pending")

    def test_memory_intelligence_evaluation_runs(self):
        result = queue_conversation_memory_candidates(
            self.store,
            [{"content": "User prefers concise replies", "type": "preference"}],
        )
        candidate = result["candidates"][0]
        self.assertEqual(candidate["evaluation_status"], "evaluated")
        self.assertIn("confidence", candidate)
        self.assertIn("risk", candidate)

    def test_durable_memory_is_not_created_automatically(self):
        queue_conversation_memory_candidates(
            self.store,
            [{"content": "Project Aurora is local", "type": "fact"}],
        )
        self.assertEqual(self.store.list_memories(), [])
        self.assertTrue(self.store.candidates_file.exists())

    def test_metadata_is_preserved_until_approval(self):
        result = queue_conversation_memory_candidates(
            self.store,
            [{"content": "Uses local AI", "type": "fact"}],
            conversation_id="conversation-7",
        )
        candidate = result["candidates"][0]
        self.assertEqual(candidate["metadata"]["conversation_id"], "conversation-7")
        self.assertEqual(candidate["metadata"]["signal_type"], "fact")

        memory = self.store.approve_candidate(candidate["id"])
        self.assertEqual(memory["metadata"]["conversation_id"], "conversation-7")
        self.assertEqual(memory["metadata"]["signal_type"], "fact")

    def test_evaluation_failure_is_isolated(self):
        with patch(
            "modules.memory_intelligence.analyze_memory_candidates",
            side_effect=RuntimeError("evaluation unavailable"),
        ):
            result = queue_conversation_memory_candidates(
                self.store,
                [{"content": "A reviewable fact", "type": "fact"}],
            )
        self.assertTrue(result["diagnostics"]["success"])
        self.assertEqual(result["diagnostics"]["metrics"]["unevaluated"], 1)
        self.assertEqual(result["candidates"][0]["evaluation_status"], "unevaluated")
        self.assertEqual(self.store.list_memories(), [])

    def test_pending_storage_failure_is_isolated(self):
        with patch.object(self.store, "queue_candidate_records", side_effect=OSError("disk full")):
            result = queue_conversation_memory_candidates(
                self.store,
                [{"content": "A fact", "type": "fact"}],
            )
        self.assertFalse(result["diagnostics"]["success"])
        self.assertEqual(self.store.list_memories(), [])

    def test_approval_path_still_works(self):
        result = queue_conversation_memory_candidates(
            self.store,
            [{"content": "Project Aurora is local", "type": "fact", "importance": "high"}],
        )
        memory = self.store.approve_candidate(result["candidates"][0]["id"])
        self.assertEqual(memory["content"], "Project Aurora is local")
        self.assertEqual(len(self.store.list_memories()), 1)

    def test_existing_lifecycle_remains_unchanged(self):
        result = queue_conversation_memory_candidates(
            self.store,
            [{"content": "User likes concise replies", "type": "preference"}],
        )
        candidate = result["candidates"][0]
        self.store.reject_candidate(candidate["id"])
        self.assertEqual(self.store.list_candidates()[0]["status"], "rejected")

    def test_diagnostics_metrics_are_correct(self):
        result = queue_conversation_memory_candidates(
            self.store,
            [
                {"content": "A fact", "type": "fact"},
                {"content": "A fact", "type": "fact"},
            ],
        )
        metrics = result["diagnostics"]["metrics"]
        self.assertEqual(metrics["signals_input"], 2)
        self.assertEqual(metrics["candidates_created"], 1)
        self.assertEqual(metrics["evaluated"], 1)
        self.assertEqual(metrics["stored_pending"], 1)

    def test_candidate_file_contains_pending_only(self):
        queue_conversation_memory_candidates(
            self.store,
            [{"content": "A fact", "type": "fact"}],
        )
        payload = json.loads(self.store.candidates_file.read_text(encoding="utf-8"))
        self.assertEqual(payload[0]["status"], "pending")
        self.assertEqual(self.store.file_path.exists(), False)


if __name__ == "__main__":
    unittest.main()
