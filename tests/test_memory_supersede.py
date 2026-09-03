import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from modules.memory import MemoryStore


class MemorySupersedeTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.store = MemoryStore(Path(self.directory.name) / "memories.json")

    def tearDown(self):
        self.directory.cleanup()

    def test_legacy_memory_defaults_to_active_state(self):
        self.store.file_path.write_text(
            '[{"id":"legacy","type":"preference","content":"User prefers concise replies.","importance":"normal"}]',
            encoding="utf-8",
        )
        memory = self.store.list_memories()[0]
        self.assertEqual(memory["metadata"]["state"], "active")

    def test_new_memory_defaults_to_active_state(self):
        memory = self.store.create("preference", "User prefers concise replies.")
        self.assertEqual(memory["metadata"]["state"], "active")
        self.assertIsNone(memory["metadata"]["supersedes"])

    def test_possible_update_candidate_references_active_memory(self):
        old = self.store.create("preference", "User prefers concise replies.")
        queued = self.store.queue_candidates("I prefer detailed replies.")
        self.assertEqual(len(queued), 1)
        relation = queued[0]["metadata"]["relation"]
        self.assertEqual(relation["type"], "possible_update")
        self.assertEqual(relation["target_memory_id"], old["id"])

    def test_duplicate_detection_checks_all_memories_before_relation_match(self):
        self.store.create(
            "fact",
            "The office timezone is UTC.",
            metadata={"category": "long_term_fact"},
        )
        self.store.create(
            "fact",
            "alpha beta gamma delta epsilon",
            metadata={"category": "long_term_fact"},
        )

        queued = self.store.queue_candidate_records([{
            "type": "fact",
            "content": "alpha beta gamma delta epsilon zeta",
            "category": "long_term_fact",
            "score": 0.9,
        }])

        self.assertEqual(queued, [])

    def test_possible_update_targets_the_most_similar_related_memory(self):
        self.store.create(
            "preference",
            "User prefers concise email replies.",
            metadata={"category": "communication_style"},
        )
        closest = self.store.create(
            "preference",
            "User prefers concise technical reports.",
            metadata={"category": "communication_style"},
        )

        candidate = self.store.queue_candidate_records([{
            "type": "preference",
            "content": "User prefers detailed technical reports.",
            "category": "communication_style",
            "score": 0.9,
        }])[0]

        self.assertEqual(candidate["metadata"]["relation"]["type"], "possible_update")
        self.assertEqual(candidate["metadata"]["relation"]["target_memory_id"], closest["id"])

    def test_approve_possible_update_supersedes_old_memory(self):
        old = self.store.create("preference", "User prefers concise replies.")
        candidate = self.store.queue_candidates("I prefer detailed replies.")[0]
        new = self.store.approve_candidate(candidate["id"])

        records = {item["id"]: item for item in self.store.list_memories()}
        old_after = records[old["id"]]
        new_after = records[new["id"]]
        approval_time = new_after["metadata"]["valid_from"]
        self.assertEqual(old_after["metadata"]["state"], "superseded")
        self.assertEqual(old_after["metadata"]["superseded_by"], new["id"])
        self.assertEqual(old_after["metadata"]["valid_until"], approval_time)
        self.assertEqual(new_after["metadata"]["state"], "active")
        self.assertEqual(new_after["metadata"]["supersedes"], old["id"])
        self.assertIsNone(new_after["metadata"]["superseded_by"])

    def test_possible_update_writes_memory_transaction_once(self):
        self.store.create("preference", "User prefers concise replies.")
        candidate = self.store.queue_candidates("I prefer detailed replies.")[0]

        with patch.object(self.store, "_write", wraps=self.store._write) as write:
            self.store.approve_candidate(candidate["id"])

        self.assertEqual(write.call_count, 1)

    def test_possible_conflict_does_not_supersede_existing_memory(self):
        old = self.store.create(
            "fact",
            "The deployment target is staging.",
            metadata={"category": "long_term_fact"},
        )
        candidate = self.store.queue_candidate_records([{
            "type": "fact",
            "content": "The deployment target is production.",
            "category": "long_term_fact",
            "score": 0.9,
        }])[0]

        self.assertEqual(candidate["metadata"]["relation"]["type"], "possible_conflict")
        saved = self.store.approve_candidate(candidate["id"])
        records = {item["id"]: item for item in self.store.list_memories()}

        self.assertEqual(records[old["id"]]["metadata"]["state"], "active")
        self.assertEqual(records[saved["id"]]["metadata"]["state"], "active")
        self.assertIsNone(records[saved["id"]]["metadata"]["supersedes"])

    def test_retrieval_ignores_superseded_and_archived(self):
        old = self.store.create("preference", "User prefers concise replies.")
        archived = self.store.create("preference", "User likes archived replies.", metadata={"state": "archived"})
        self.store.queue_candidates("I prefer detailed replies.")
        candidate = self.store.list_candidates()[0]
        self.store.approve_candidate(candidate["id"])

        results = self.store.retrieve("concise detailed replies", max_results=10)
        ids = {item["id"] for item in results}
        self.assertNotIn(old["id"], ids)
        self.assertNotIn(archived["id"], ids)

    def test_archive_retains_data_until_separate_delete(self):
        memory = self.store.create("fact", "Aurora keeps local Memory data.")

        archived = self.store.archive(memory["id"])

        self.assertEqual(archived["metadata"]["state"], "archived")
        self.assertTrue(archived["metadata"]["valid_until"])
        self.assertEqual(len(self.store.list_memories()), 1)
        self.assertEqual(self.store.retrieve("Aurora local Memory", max_results=10), [])

        self.store.delete(memory["id"])
        self.assertEqual(self.store.list_memories(), [])

    def test_archived_memory_can_be_restored_to_active(self):
        memory = self.store.create("fact", "Aurora keeps local Memory data.")
        self.store.archive(memory["id"])

        restored = self.store.restore(memory["id"])

        self.assertEqual(restored["metadata"]["state"], "active")
        self.assertIsNone(restored["metadata"]["valid_until"])
        self.assertTrue(restored["metadata"]["valid_from"])
        self.assertEqual(len(self.store.retrieve("Aurora local Memory", max_results=10)), 1)

    def test_duplicate_and_normal_approval_still_work(self):
        old = self.store.create("fact", "User works on Project Aurora.")
        self.assertEqual(self.store.queue_candidates("User works on Project Aurora."), [])
        candidate = self.store.queue_candidates("My name is Aurora.")[0]
        self.assertEqual(candidate["metadata"]["relation"]["type"], "new")
        saved = self.store.approve_candidate(candidate["id"])
        self.assertEqual(saved["content"], "is Aurora")
        self.assertEqual(len(self.store.list_memories()), 2)
        self.assertEqual(self.store.list_memories()[0]["id"], old["id"])

    def test_candidate_decision_cannot_be_changed_after_approval(self):
        candidate = self.store.queue_candidates("My name is Aurora.")[0]
        self.store.approve_candidate(candidate["id"])

        with self.assertRaises(ValueError):
            self.store.approve_candidate(candidate["id"])
        with self.assertRaises(ValueError):
            self.store.reject_candidate(candidate["id"])

    def test_candidate_decision_cannot_be_changed_after_rejection(self):
        candidate = self.store.queue_candidates("My name is Aurora.")[0]
        self.store.reject_candidate(candidate["id"])

        with self.assertRaises(ValueError):
            self.store.approve_candidate(candidate["id"])
        with self.assertRaises(ValueError):
            self.store.reject_candidate(candidate["id"])


if __name__ == "__main__":
    unittest.main()
