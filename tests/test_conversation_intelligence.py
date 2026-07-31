"""Unit tests for Conversation Intelligence core analysis."""

import copy
import unittest

from modules.conversation_intelligence import (
    ANALYSIS_VERSION,
    ConversationIntelligence,
    analyze_conversation,
)


REQUIRED_SCHEMA = {
    "summary",
    "topics",
    "important_events",
    "memory_signals",
    "message_count",
    "user_message_count",
    "assistant_message_count",
    "analysis_version",
    "analyzed_time",
}


class ConversationIntelligenceTests(unittest.TestCase):
    def test_empty_messages_return_complete_schema(self):
        result = analyze_conversation([])

        self.assertEqual(set(result.keys()), REQUIRED_SCHEMA)
        self.assertEqual(result["summary"], "")
        self.assertEqual(result["topics"], [])
        self.assertEqual(result["important_events"], [])
        self.assertEqual(result["memory_signals"], [])
        self.assertEqual(result["message_count"], 0)

    def test_normal_conversation_returns_summary_and_topics(self):
        result = analyze_conversation([
            {"role": "system", "content": "System prompt."},
            {"role": "user", "content": "Please review Project Aurora memory lifecycle."},
            {"role": "assistant", "content": "The lifecycle review is complete."},
        ])

        self.assertIn("Project Aurora memory lifecycle", result["summary"])
        self.assertGreaterEqual(len(result["topics"]), 1)
        self.assertEqual(result["message_count"], 2)
        self.assertEqual(result["user_message_count"], 1)
        self.assertEqual(result["assistant_message_count"], 1)

    def test_only_user_messages(self):
        result = analyze_conversation([
            {"role": "user", "content": "Implement conversation intelligence core."},
            {"role": "user", "content": "Keep it deterministic."},
        ])

        self.assertIn("Implement conversation intelligence core", result["summary"])
        self.assertEqual(result["user_message_count"], 2)
        self.assertEqual(result["assistant_message_count"], 0)

    def test_only_assistant_messages(self):
        result = analyze_conversation([
            {"role": "assistant", "content": "The analysis is ready."},
        ])

        self.assertEqual(result["summary"], "The analysis is ready.")
        self.assertEqual(result["user_message_count"], 0)
        self.assertEqual(result["assistant_message_count"], 1)

    def test_system_messages_ignored(self):
        result = analyze_conversation([
            {"role": "system", "content": "Hidden instruction."},
            {"role": "user", "content": "Visible user request."},
        ])

        self.assertNotIn("Hidden instruction", result["summary"])
        self.assertEqual(result["message_count"], 1)

    def test_invalid_messages_ignored(self):
        result = analyze_conversation([
            None,
            "bad",
            {"role": "user", "content": ""},
            {"role": "tool", "content": "ignored"},
            {"role": "assistant", "content": "Valid assistant message."},
        ])

        self.assertEqual(result["message_count"], 1)
        self.assertEqual(result["summary"], "Valid assistant message.")

    def test_long_summary_truncated(self):
        result = analyze_conversation(
            [{"role": "user", "content": "A" * 120}],
            max_summary_chars=20,
        )

        self.assertLessEqual(len(result["summary"]), 20)
        self.assertTrue(result["summary"].endswith("..."))

    def test_input_messages_not_mutated(self):
        messages = [
            {"role": "user", "content": "  Keep original spacing.  "},
            {"role": "assistant", "content": "Done."},
        ]
        original = copy.deepcopy(messages)

        analyze_conversation(messages)

        self.assertEqual(messages, original)

    def test_output_schema_complete(self):
        result = ConversationIntelligence().analyze([
            {"role": "user", "content": "Project Aurora release completed."},
        ])

        self.assertEqual(set(result.keys()), REQUIRED_SCHEMA)
        self.assertEqual(result["analysis_version"], ANALYSIS_VERSION)
        self.assertTrue(result["analyzed_time"])
        self.assertIsInstance(result["topics"], list)
        self.assertIsInstance(result["important_events"], list)
        self.assertIsInstance(result["memory_signals"], list)

    def test_important_event_detected_without_memory_write(self):
        result = analyze_conversation([
            {"role": "user", "content": "Phase C5-04.1 implemented conversation intelligence."},
        ])

        self.assertEqual(len(result["important_events"]), 1)
        self.assertEqual(result["important_events"][0]["importance"], "normal")
        self.assertEqual(result["memory_signals"], [])


if __name__ == "__main__":
    unittest.main()
