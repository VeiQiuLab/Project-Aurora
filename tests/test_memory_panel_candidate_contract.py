"""Contract tests for the data rendered by the Memory candidate panel."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, call, patch

from modules.memory import MemoryStore
from widgets.components.memory_panel import MemoryPanel


class MemoryPanelCandidateContractTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.store = MemoryStore(Path(self.directory.name) / "memories.json")
        self.panel = MemoryPanel.__new__(MemoryPanel)
        self.panel.memory_store = self.store
        self.panel.t = lambda key: key

    def tearDown(self):
        self.directory.cleanup()

    def test_update_detail_contains_review_fields_and_existing_memory(self):
        previous = self.store.create(
            "preference",
            "User prefers concise replies.",
            metadata={"category": "communication_style"},
        )
        candidate = self.store.queue_candidate_records([{
            "type": "preference",
            "content": "User prefers detailed replies.",
            "category": "communication_style",
            "confidence": 0.88,
            "importance": "high",
            "importance_score": 0.9,
            "risk": {"level": "low", "reasons": []},
            "source": "conversation",
            "score": 0.9,
        }])[0]

        detail = self.panel._format_candidate_detail(candidate)

        self.assertEqual(candidate["metadata"]["relation"]["type"], "possible_update")
        self.assertEqual(candidate["metadata"]["relation"]["target_memory_id"], previous["id"])
        for expected in (
            "User prefers detailed replies.",
            "memory_type_preference",
            "communication_style",
            "0.88",
            "memory_importance_high",
            "low",
            "memory_relation_possible_update",
            "conversation",
            "User prefers concise replies.",
        ):
            self.assertIn(expected, detail)

    def test_conflict_detail_warns_without_changing_existing_memory(self):
        previous = self.store.create(
            "fact",
            "The deployment target is staging.",
            metadata={"category": "long_term_fact"},
        )
        candidate = self.store.queue_candidate_records([{
            "type": "fact",
            "content": "The deployment target is production.",
            "category": "long_term_fact",
            "confidence": 0.75,
            "importance": "normal",
            "importance_score": 0.5,
            "risk": {"level": "medium", "reasons": ["conflicting_fact"]},
            "score": 0.9,
        }])[0]

        detail = self.panel._format_candidate_detail(candidate)

        self.assertEqual(candidate["metadata"]["relation"]["type"], "possible_conflict")
        self.assertIn("memory_candidate_conflict_warning", detail)
        self.assertIn(previous["content"], detail)
        self.assertEqual(self.store.list_memories()[0]["metadata"]["state"], "active")

    def test_panel_uses_public_candidate_and_lifecycle_apis(self):
        for method_name in (
            "list_candidates",
            "approve_candidate",
            "reject_candidate",
            "archive",
            "delete",
        ):
            self.assertTrue(callable(getattr(self.store, method_name, None)), method_name)

    def test_candidate_refresh_uses_pending_only_and_renders_empty_state(self):
        rejected = self.store.queue_candidates("My name is Aurora.")[0]
        self.store.reject_candidate(rejected["id"])
        self.panel.candidates = []
        self.panel.selected_candidate_id = {"value": rejected["id"]}
        self.panel.candidate_box = Mock()
        self.panel.candidate_detail = Mock()
        self.panel.approve_candidate_button = Mock()
        self.panel.reject_candidate_button = Mock()

        self.panel.refresh_candidate_list()

        self.assertEqual(self.panel.candidates, [])
        self.assertIsNone(self.panel.selected_candidate_id["value"])
        self.panel.candidate_box.configure.assert_called_once_with(
            values=["memory_candidate_no_pending"]
        )
        self.panel.candidate_box.set.assert_called_once_with("memory_candidate_no_pending")
        self.panel.approve_candidate_button.configure.assert_called_once_with(state="disabled")
        self.panel.reject_candidate_button.configure.assert_called_once_with(state="disabled")

    def test_archive_action_keeps_success_status_visible_after_form_reset(self):
        memory = self.store.create("fact", "Aurora keeps local Memory data.")
        self.panel.records = [memory]
        self.panel.selected_id = {"value": memory["id"]}
        self.panel.status = Mock()
        self.panel.logger = Mock()
        self.panel.memory_search_entry = Mock()
        self.panel.memory_search_entry.get.return_value = ""
        self.panel.refresh_memory_list = Mock()

        def reset_form():
            self.panel.status.set_status("disabled", "")

        self.panel.clear_form = Mock(side_effect=reset_form)
        with patch(
            "widgets.components.memory_panel.messagebox.askyesno",
            return_value=True,
        ):
            self.panel.archive_memory()

        self.assertEqual(self.store.list_memories()[0]["metadata"]["state"], "archived")
        self.assertEqual(
            self.panel.status.set_status.call_args_list,
            [call("disabled", ""), call("warning", "memory_window_archived")],
        )


if __name__ == "__main__":
    unittest.main()
