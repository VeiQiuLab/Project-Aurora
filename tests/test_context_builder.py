"""Unit tests for the Context Builder core module."""

import unittest

from modules.context_builder import ContextBuilder


class ContextBuilderTests(unittest.TestCase):
    def test_context_sections_keep_expected_order(self):
        builder = ContextBuilder()

        sections = builder.build_context_sections(
            system_context="System rules",
            persona={"name": "Aurora", "style": "Concise"},
            memory_items=[{"id": "mem-1", "type": "preference", "content": "Use English."}],
            knowledge_items=[{"id": "doc-1", "file_name": "guide.md", "snippet": "Project guide."}],
            conversation_messages=[
                {"role": "system", "content": "Old system context"},
                {"role": "user", "content": "Previous request"},
                {"role": "assistant", "content": "Previous answer"},
            ],
            user_message="Current request",
        )

        self.assertEqual(
            [section["name"] for section in sections],
            [
                "System Context",
                "Persona",
                "Memory",
                "Knowledge",
                "Conversation Context",
                "Current User Message",
            ],
        )
        self.assertEqual(sections[0]["content"], "System rules")
        self.assertIn("Aurora", sections[1]["content"])
        self.assertIn("Use English.", sections[2]["content"])
        self.assertIn("Project guide.", sections[3]["content"])
        self.assertNotIn("Old system context", sections[4]["content"])
        self.assertEqual(sections[5]["content"], "Current request")

    def test_empty_inputs_return_normal_structure(self):
        builder = ContextBuilder()

        package = builder.build_prompt_package()

        self.assertEqual(len(package["sections"]), 6)
        self.assertEqual(package["sections"][0]["name"], "System Context")
        self.assertTrue(package["sections"][0]["enabled"])
        for section in package["sections"][1:]:
            self.assertFalse(section["enabled"])
            self.assertEqual(section["content"], "")
        self.assertEqual(len(package["messages"]), 1)
        self.assertEqual(package["messages"][0]["role"], "system")
        self.assertIsInstance(package["final_prompt"], str)

    def test_prompt_package_always_contains_required_fields(self):
        builder = ContextBuilder()

        package = builder.build_prompt_package(user_message="Hello")

        self.assertEqual(
            set(package.keys()),
            {"messages", "sections", "final_prompt", "diagnostics", "source_refs"},
        )
        self.assertIsInstance(package["messages"], list)
        self.assertIsInstance(package["sections"], list)
        self.assertIsInstance(package["final_prompt"], str)
        self.assertIsInstance(package["diagnostics"], dict)
        self.assertIsInstance(package["source_refs"], dict)
        self.assertEqual(package["messages"][-1], {"role": "user", "content": "Hello"})

    def test_metadata_and_source_refs_do_not_break_structure(self):
        builder = ContextBuilder(warning_tokens=1)

        package = builder.build_prompt_package(
            memory_items=[
                {
                    "id": "mem-1",
                    "type": "preference",
                    "content": "A durable preference with future metadata.",
                    "importance_score": 9.5,
                    "pinned": True,
                }
            ],
            knowledge_items=[
                {
                    "id": "doc-1",
                    "file_name": "architecture.md",
                    "snippet": "Architecture source text.",
                    "score": 0.91,
                    "source_path": "docs/ARCHITECTURE.md",
                }
            ],
            conversation_messages=[
                {"id": "msg-1", "role": "user", "content": "Earlier question"},
            ],
            user_message="Current question",
        )

        self.assertEqual(package["source_refs"]["memory_ids"], ["mem-1"])
        self.assertEqual(package["source_refs"]["knowledge_ids"], ["doc-1"])
        self.assertEqual(package["source_refs"]["conversation_message_ids"], ["msg-1"])
        self.assertIn("total_tokens", package["diagnostics"])
        self.assertIn("warning_reasons", package["diagnostics"])
        self.assertTrue(package["diagnostics"]["warning"])

    def test_import_context_builder(self):
        self.assertTrue(callable(ContextBuilder))


if __name__ == "__main__":
    unittest.main()
