"""Tests for retrieval result normalization."""

import copy
import unittest

from modules.rag_results import normalize_result, normalize_results


class RagResultsTests(unittest.TestCase):
    def test_knowledge_result_normalization(self):
        result = normalize_result(
            {
                "id": "doc-1",
                "file_name": "guide.md",
                "source_path": "docs/guide.md",
                "content": "Knowledge content",
                "score": 0.91,
            },
            source_kind="knowledge",
            retrieval_method="vector",
        )

        self.assertEqual(result["source"]["kind"], "knowledge")
        self.assertEqual(result["source"]["file_name"], "guide.md")
        self.assertEqual(result["source"]["source_path"], "docs/guide.md")
        self.assertEqual(result["retrieval_method"], "vector")

    def test_memory_result_normalization(self):
        result = normalize_result(
            {
                "id": "mem-1",
                "memory_id": "mem-1",
                "type": "preference",
                "content": "Use concise explanations.",
            },
            source_kind="memory",
            retrieval_method="keyword",
        )

        self.assertEqual(result["source"]["kind"], "memory")
        self.assertEqual(result["source"]["memory_id"], "mem-1")
        self.assertEqual(result["retrieval_method"], "keyword")

    def test_empty_result(self):
        result = normalize_result({})

        self.assertEqual(result["id"], "")
        self.assertEqual(result["content"], "")
        self.assertEqual(result["score"], 0.0)
        self.assertEqual(result["source"]["kind"], "knowledge")
        self.assertIsNone(result["source"]["chunk_id"])
        self.assertEqual(normalize_results([]), [])

    def test_missing_metadata(self):
        result = normalize_result({"content": "Text"})

        self.assertEqual(result["metadata"], {})
        self.assertEqual(result["score_details"]["final"], None)

    def test_source_preservation(self):
        result = normalize_result(
            {
                "content": "Text",
                "source": {
                    "kind": "knowledge",
                    "file_name": "existing.md",
                    "custom": "keep",
                },
                "file_name": "fallback.md",
            }
        )

        self.assertEqual(result["source"]["file_name"], "existing.md")
        self.assertEqual(result["source"]["custom"], "keep")

    def test_score_preservation(self):
        result = normalize_result({"score": 0.73})

        self.assertEqual(result["score"], 0.73)

    def test_score_details_preservation(self):
        result = normalize_result(
            {
                "score_details": {
                    "vector": 0.8,
                    "final": 0.8,
                    "custom": "keep",
                }
            }
        )

        self.assertEqual(result["score_details"]["vector"], 0.8)
        self.assertEqual(result["score_details"]["final"], 0.8)
        self.assertEqual(result["score_details"]["keyword"], None)
        self.assertEqual(result["score_details"]["custom"], "keep")

    def test_unknown_fields_preserved(self):
        result = normalize_result({"content": "Text", "future_field": {"value": 1}})

        self.assertEqual(result["future_field"], {"value": 1})

    def test_input_not_mutated(self):
        original = {
            "content": "Text",
            "metadata": {"custom": {"value": 1}},
            "source": {"custom": "keep"},
            "score_details": {"vector": 0.5},
        }
        snapshot = copy.deepcopy(original)

        normalized = normalize_result(original)
        normalized["metadata"]["custom"]["value"] = 2
        normalized["source"]["custom"] = "changed"

        self.assertEqual(original, snapshot)

    def test_chunk_id_defaults_to_none(self):
        result = normalize_result({"file_name": "guide.md"})

        self.assertIsNone(result["source"]["chunk_id"])


if __name__ == "__main__":
    unittest.main()
