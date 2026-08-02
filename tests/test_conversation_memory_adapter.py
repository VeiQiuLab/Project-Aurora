import tempfile
import unittest
from pathlib import Path

from modules.conversation_memory_adapter import adapt_memory_signals


class ConversationMemoryAdapterTests(unittest.TestCase):
    def test_basic_signal_conversion(self):
        result = adapt_memory_signals([{"content": "Likes concise replies", "type": "preference"}])
        self.assertEqual(result["candidates"][0]["content"], "Likes concise replies")
        self.assertEqual(result["candidates"][0]["source"], "conversation")

    def test_source_metadata_injection(self):
        candidate = adapt_memory_signals([{"content": "Use Python", "type": "instruction"}])["candidates"][0]
        self.assertEqual(candidate["metadata"]["signal_type"], "instruction")
        self.assertEqual(candidate["metadata"]["conversation_id"], "")

    def test_conversation_id_preserved(self):
        candidate = adapt_memory_signals(
            [{"content": "Project Aurora is local", "type": "fact"}],
            conversation_id="conversation-1",
        )["candidates"][0]
        self.assertEqual(candidate["metadata"]["conversation_id"], "conversation-1")

    def test_importance_and_confidence_preserved(self):
        candidate = adapt_memory_signals([{
            "content": "Prefers concise replies",
            "type": "preference",
            "importance": "high",
            "confidence": 0.9,
        }])["candidates"][0]
        self.assertEqual(candidate["importance"], "high")
        self.assertEqual(candidate["confidence"], 0.9)

    def test_missing_optional_fields_are_not_created(self):
        candidate = adapt_memory_signals([{"content": "A fact", "type": "fact"}])["candidates"][0]
        self.assertNotIn("importance", candidate)
        self.assertNotIn("confidence", candidate)

    def test_empty_content_is_filtered(self):
        result = adapt_memory_signals([{"content": "  \n  ", "type": "fact"}])
        self.assertEqual(result["candidates"], [])
        self.assertEqual(result["diagnostics"]["metrics"]["filtered_invalid"], 1)

    def test_invalid_signals_are_filtered_without_crashing(self):
        result = adapt_memory_signals([None, "bad", {}, {"content": "x", "type": "unknown"}])
        self.assertEqual(result["candidates"], [])
        self.assertEqual(result["diagnostics"]["metrics"]["filtered_invalid"], 4)

    def test_same_batch_whitespace_duplicates_are_filtered(self):
        result = adapt_memory_signals([
            {"content": "Project   Aurora", "type": "fact"},
            {"content": "Project\nAurora", "type": "fact"},
        ])
        self.assertEqual(len(result["candidates"]), 1)
        self.assertEqual(result["diagnostics"]["metrics"]["filtered_duplicates"], 1)

    def test_diagnostics_are_correct(self):
        diagnostics = adapt_memory_signals([
            {"content": "A", "type": "fact"},
            {"content": "A", "type": "fact"},
            {"content": "", "type": "fact"},
        ])["diagnostics"]
        self.assertEqual(diagnostics["stage"], "conversation_memory_adapter")
        self.assertTrue(diagnostics["success"])
        self.assertEqual(diagnostics["metrics"], {
            "signals_input": 3,
            "candidates_created": 1,
            "filtered_invalid": 1,
            "filtered_duplicates": 1,
        })

    def test_malformed_input_returns_failure_diagnostics(self):
        result = adapt_memory_signals(None)
        self.assertEqual(result["candidates"], [])
        self.assertFalse(result["diagnostics"]["success"])

    def test_adapter_does_not_write_memory_storage(self):
        with tempfile.TemporaryDirectory() as directory:
            result = adapt_memory_signals(
                [{"content": "No storage", "type": "fact"}],
                conversation_id=str(Path(directory) / "conversation.json"),
            )
            self.assertEqual(len(result["candidates"]), 1)
            self.assertEqual(list(Path(directory).iterdir()), [])


if __name__ == "__main__":
    unittest.main()
