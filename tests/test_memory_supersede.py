import tempfile
import unittest
from pathlib import Path

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

    def test_duplicate_and_normal_approval_still_work(self):
        old = self.store.create("fact", "User works on Project Aurora.")
        self.assertEqual(self.store.queue_candidates("User works on Project Aurora."), [])
        candidate = self.store.queue_candidates("My name is Aurora.")[0]
        self.assertEqual(candidate["metadata"]["relation"]["type"], "new")
        saved = self.store.approve_candidate(candidate["id"])
        self.assertEqual(saved["content"], "is Aurora")
        self.assertEqual(len(self.store.list_memories()), 2)
        self.assertEqual(self.store.list_memories()[0]["id"], old["id"])


if __name__ == "__main__":
    unittest.main()
