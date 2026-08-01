"""Tests for the independent context optimizer."""

import copy
import unittest

from modules.context_optimizer import ContextOptimizer, optimize_context


class ContextOptimizerTests(unittest.TestCase):
    def test_token_budget(self):
        result = optimize_context(
            [{"name": "Knowledge", "enabled": True, "content": "x" * 400}],
            max_tokens=20,
        )

        self.assertLessEqual(result["diagnostics"]["used_tokens"], 20)
        self.assertTrue(result["diagnostics"]["truncated"])

    def test_priority_keeps_system_before_knowledge(self):
        result = optimize_context(
            [
                {"name": "Knowledge", "enabled": True, "content": "k" * 200},
                {"name": "System Context", "enabled": True, "content": "system rules"},
            ],
            max_tokens=8,
        )

        sections = {item["name"]: item for item in result["sections"]}
        self.assertTrue(sections["System Context"]["content"])
        self.assertIn("System Context", result["diagnostics"]["sections"][1]["name"])

    def test_long_conversation_keeps_recent_messages(self):
        result = optimize_context(
            [{
                "name": "Conversation Context",
                "enabled": True,
                "content": "",
                "messages": [
                    {"role": "user", "content": "old message"},
                    {"role": "assistant", "content": "recent message"},
                ],
            }],
            max_tokens=6,
        )

        content = result["sections"][0]["content"]
        self.assertIn("recent message", content)

    def test_empty_context(self):
        result = optimize_context([], max_tokens=20)

        self.assertEqual(result["sections"], [])
        self.assertEqual(result["diagnostics"]["used_tokens"], 0)
        self.assertFalse(result["diagnostics"]["truncated"])

    def test_no_truncation(self):
        sections = [{"name": "Memory", "enabled": True, "content": "Short memory"}]

        result = optimize_context(sections, max_tokens=100)

        self.assertEqual(result["sections"][0]["content"], "Short memory")
        self.assertFalse(result["diagnostics"]["truncated"])

    def test_section_budget(self):
        result = optimize_context(
            [{"name": "Knowledge", "enabled": True, "content": "k" * 200}],
            max_tokens=100,
            budget={"Knowledge": 5},
        )

        self.assertLessEqual(result["diagnostics"]["used_tokens"], 5)

    def test_input_is_not_mutated(self):
        sections = [{
            "name": "Memory",
            "enabled": True,
            "content": "Memory text",
            "metadata": {"custom": {"value": 1}},
        }]
        snapshot = copy.deepcopy(sections)

        result = ContextOptimizer().optimize_context(sections, max_tokens=2)
        result["sections"][0]["metadata"]["custom"]["value"] = 2

        self.assertEqual(sections, snapshot)

    def test_diagnostics_include_section_details(self):
        result = optimize_context(
            [{"name": "Persona", "enabled": True, "content": "Persona"}],
            max_tokens=20,
        )

        diagnostic = result["diagnostics"]["sections"][0]
        self.assertEqual(diagnostic["name"], "Persona")
        self.assertIn("tokens", diagnostic)
        self.assertIn("original_tokens", diagnostic)


if __name__ == "__main__":
    unittest.main()
