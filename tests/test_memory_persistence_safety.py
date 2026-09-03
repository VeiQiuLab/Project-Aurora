import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from modules.memory import MemoryStore


class MemoryPersistenceSafetyTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.store = MemoryStore(Path(self.directory.name) / "memories.json")

    def tearDown(self):
        self.directory.cleanup()

    def test_atomic_replace_failure_keeps_original_memory_json(self):
        memory = self.store.create("fact", "Original Memory")
        original = self.store.file_path.read_bytes()

        with patch("modules.memory.os.replace", side_effect=OSError("replace failed")):
            with self.assertRaises(OSError):
                self.store.update(memory["id"], "fact", "Changed Memory")

        self.assertEqual(self.store.file_path.read_bytes(), original)
        self.assertEqual(self.store.list_memories()[0]["content"], "Original Memory")
        self.assertEqual(list(self.store.file_path.parent.glob("*.tmp")), [])

    def test_supersede_replace_failure_keeps_old_memory_active_and_candidate_pending(self):
        previous = self.store.create("preference", "User prefers concise replies.")
        candidate = self.store.queue_candidates("I prefer detailed replies.")[0]
        original = self.store.file_path.read_bytes()
        real_replace = os.replace

        def fail_primary_replace(source, destination):
            if Path(destination) == self.store.file_path:
                raise OSError("primary replace failed")
            return real_replace(source, destination)

        with patch("modules.memory.os.replace", side_effect=fail_primary_replace):
            with self.assertRaises(OSError):
                self.store.approve_candidate(candidate["id"])

        self.assertEqual(self.store.file_path.read_bytes(), original)
        memories = self.store.list_memories()
        self.assertEqual(len(memories), 1)
        self.assertEqual(memories[0]["id"], previous["id"])
        self.assertEqual(memories[0]["metadata"]["state"], "active")
        pending = self.store.list_candidates(status="pending")
        self.assertEqual([item["id"] for item in pending], [candidate["id"]])

    def test_candidate_replace_failure_keeps_original_candidate_json(self):
        candidate = self.store.queue_candidates("My name is Aurora.")[0]
        original = self.store.candidates_file.read_bytes()
        real_replace = os.replace

        def fail_primary_replace(source, destination):
            if Path(destination) == self.store.candidates_file:
                raise OSError("candidate replace failed")
            return real_replace(source, destination)

        with patch("modules.memory.os.replace", side_effect=fail_primary_replace):
            with self.assertRaises(OSError):
                self.store.reject_candidate(candidate["id"])

        self.assertEqual(self.store.candidates_file.read_bytes(), original)
        pending = self.store.list_candidates(status="pending")
        self.assertEqual([item["id"] for item in pending], [candidate["id"]])

    def test_candidate_status_write_failure_can_be_retried_without_duplicate_memory(self):
        previous = self.store.create("preference", "User prefers concise replies.")
        candidate = self.store.queue_candidates("I prefer detailed replies.")[0]

        with patch.object(self.store, "_write_candidates", side_effect=OSError("candidate write failed")):
            with self.assertRaises(OSError):
                self.store.approve_candidate(candidate["id"])

        committed = self.store.list_memories()
        self.assertEqual(len(committed), 2)
        self.assertEqual(
            next(item for item in committed if item["id"] == previous["id"])["metadata"]["state"],
            "superseded",
        )
        self.assertEqual(self.store.list_candidates(status="pending")[0]["id"], candidate["id"])

        self.store.approve_candidate(candidate["id"])

        self.assertEqual(len(self.store.list_memories()), 2)
        self.assertEqual(self.store.list_candidates(status="pending"), [])
        self.assertEqual(self.store.list_candidates(status="approved")[0]["id"], candidate["id"])

    def test_corrupt_memory_json_recovers_last_valid_backup(self):
        first = self.store.create("fact", "First valid Memory")
        self.store.create("fact", "Second valid Memory")
        self.store.file_path.write_text("{broken", encoding="utf-8")

        recovered = self.store.list_memories()

        self.assertEqual([item["id"] for item in recovered], [first["id"]])
        self.assertEqual(self.store.list_memories()[0]["content"], "First valid Memory")

    def test_non_object_memory_record_recovers_last_valid_backup(self):
        first = self.store.create("fact", "First valid Memory")
        self.store.create("fact", "Second valid Memory")
        self.store.file_path.write_text('["broken record"]', encoding="utf-8")

        recovered = self.store.list_memories()

        self.assertEqual([item["id"] for item in recovered], [first["id"]])

    def test_corrupt_memory_without_backup_is_not_overwritten(self):
        self.store.file_path.write_text("{broken", encoding="utf-8")

        with self.assertRaises(OSError):
            self.store.create("fact", "Do not overwrite")

        self.assertEqual(self.store.file_path.read_text(encoding="utf-8"), "{broken")

    def test_corrupt_candidate_json_recovers_last_valid_backup(self):
        candidate = self.store.queue_candidate_records([{
            "type": "fact",
            "content": "First pending candidate",
            "score": 0.9,
        }])[0]
        self.store.reject_candidate(candidate["id"])
        self.store.candidates_file.write_text("[broken", encoding="utf-8")

        recovered = self.store.list_candidates()

        self.assertEqual(len(recovered), 1)
        self.assertEqual(recovered[0]["id"], candidate["id"])
        self.assertEqual(recovered[0]["status"], "pending")

    def test_corrupt_candidate_without_backup_is_not_overwritten(self):
        self.store.candidates_file.write_text("[broken", encoding="utf-8")

        with self.assertRaises(OSError):
            self.store.queue_candidate_records([{
                "type": "fact",
                "content": "Do not overwrite",
                "score": 0.9,
            }])

        self.assertEqual(self.store.candidates_file.read_text(encoding="utf-8"), "[broken")


if __name__ == "__main__":
    unittest.main()
