"""Tests for source-aware RAG result de-duplication."""

import copy
import unittest

from modules.rag_results import deduplicate_results, normalize_content


class RagDuplicateFilteringTests(unittest.TestCase):
    def test_knowledge_same_id_duplicate(self):
        results = [
            {"content": "First", "score": 0.4, "source": {"kind": "knowledge", "id": "doc-1"}},
            {"content": "Second", "score": 0.8, "source": {"kind": "knowledge", "id": "doc-1"}},
        ]

        filtered = deduplicate_results(results)

        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["content"], "Second")

    def test_knowledge_same_content_hash_duplicate(self):
        results = [
            {"content": "First", "source": {"kind": "knowledge", "content_hash": "hash-1"}},
            {"content": "Second", "source": {"kind": "knowledge", "content_hash": "hash-1"}},
        ]

        self.assertEqual(len(deduplicate_results(results)), 1)

    def test_memory_same_memory_id_duplicate(self):
        results = [
            {"content": "Old", "score": 0.2, "source": {"kind": "memory", "memory_id": "mem-1"}},
            {"content": "New", "score": 0.9, "source": {"kind": "memory", "memory_id": "mem-1"}},
        ]

        filtered = deduplicate_results(results)

        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["content"], "New")

    def test_whitespace_normalization_duplicate(self):
        self.assertEqual(normalize_content("  A\r\n B   C  "), "A B C")
        results = [
            {"content": "A\nB", "source": {"kind": "knowledge"}},
            {"content": " A  B ", "source": {"kind": "knowledge"}},
        ]

        self.assertEqual(len(deduplicate_results(results)), 1)

    def test_different_source_kind_is_preserved(self):
        results = [
            {"content": "Same", "source": {"kind": "knowledge", "id": "doc-1"}},
            {"content": "Same", "source": {"kind": "memory", "memory_id": "mem-1"}},
        ]

        self.assertEqual(len(deduplicate_results(results)), 2)

    def test_higher_score_is_kept(self):
        results = [
            {"content": "Low", "score": 0.1, "source": {"kind": "knowledge", "id": "doc-1"}},
            {"content": "High", "score": 0.9, "source": {"kind": "knowledge", "id": "doc-1"}},
        ]

        self.assertEqual(deduplicate_results(results)[0]["score"], 0.9)

    def test_source_completeness_breaks_score_tie(self):
        results = [
            {"content": "Short", "score": 0.5, "source": {"kind": "knowledge", "id": "doc-1"}},
            {
                "content": "Rich",
                "score": 0.5,
                "source": {
                    "kind": "knowledge",
                    "id": "doc-1",
                    "file_name": "guide.md",
                    "source_path": "docs/guide.md",
                },
            },
        ]

        self.assertEqual(deduplicate_results(results)[0]["content"], "Rich")

    def test_empty_input(self):
        self.assertEqual(deduplicate_results([]), [])
        self.assertEqual(deduplicate_results(None), [])

    def test_unknown_fields_are_preserved(self):
        result = {
            "content": "Text",
            "future_field": {"keep": True},
            "metadata": {"custom": "value"},
            "source": {"kind": "knowledge", "id": "doc-1"},
        }

        filtered = deduplicate_results([result])

        self.assertEqual(filtered[0]["future_field"], {"keep": True})
        self.assertEqual(filtered[0]["metadata"], {"custom": "value"})

    def test_input_is_not_mutated(self):
        results = [
            {
                "content": "Text",
                "metadata": {"custom": {"value": 1}},
                "source": {"kind": "knowledge"},
            }
        ]
        snapshot = copy.deepcopy(results)

        filtered = deduplicate_results(results)
        filtered[0]["metadata"]["custom"]["value"] = 2

        self.assertEqual(results, snapshot)


if __name__ == "__main__":
    unittest.main()
