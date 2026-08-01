"""Tests for normalized retrieval source tracking."""

import copy
import unittest

from modules.rag_results import normalize_result


class RagSourceTrackingTests(unittest.TestCase):
    def test_memory_id_maps_to_source_memory_id(self):
        result = normalize_result({"id": "mem-1", "content": "Memory"}, source_kind="memory")

        self.assertEqual(result["source"]["memory_id"], "mem-1")
        self.assertEqual(result["source"]["id"], "mem-1")

    def test_knowledge_source_fields_are_preserved(self):
        result = normalize_result(
            {
                "id": "doc-1",
                "file_name": "guide.md",
                "source_path": "docs/guide.md",
                "content": "Knowledge",
            },
            source_kind="knowledge",
        )

        source = result["source"]
        self.assertEqual(source["file_name"], "guide.md")
        self.assertEqual(source["source_path"], "docs/guide.md")
        self.assertEqual(source["name"], "guide.md")
        self.assertEqual(source["path"], "docs/guide.md")

    def test_content_hash_is_preserved(self):
        result = normalize_result({"content_hash": "hash-1"})

        self.assertEqual(result["source"]["content_hash"], "hash-1")

    def test_embedding_updated_time_is_preserved(self):
        result = normalize_result({"embedding_updated_time": "2026-08-01 12:00:00"})

        self.assertEqual(
            result["source"]["embedding_updated_time"],
            "2026-08-01 12:00:00",
        )

    def test_score_details_are_preserved(self):
        result = normalize_result(
            {
                "retrieval_method": "keyword",
                "score_details": {
                    "method": "keyword",
                    "keyword": 20.0,
                    "matched_terms": ["context", "memory"],
                    "custom": "keep",
                },
            }
        )

        details = result["score_details"]
        self.assertEqual(details["method"], "keyword")
        self.assertEqual(details["keyword"], 20.0)
        self.assertEqual(details["matched_terms"], ["context", "memory"])
        self.assertEqual(details["custom"], "keep")

    def test_matched_terms_default_is_empty(self):
        result = normalize_result({})

        self.assertEqual(result["score_details"]["matched_terms"], [])

    def test_missing_source_fields_have_defaults(self):
        source = normalize_result({})["source"]

        self.assertEqual(source["kind"], "knowledge")
        self.assertEqual(source["name"], "")
        self.assertEqual(source["path"], "")
        self.assertEqual(source["id"], "")
        self.assertEqual(source["file_name"], "")
        self.assertEqual(source["source_path"], "")
        self.assertEqual(source["memory_id"], "")
        self.assertEqual(source["content_hash"], "")
        self.assertEqual(source["timestamp"], "")
        self.assertIsNone(source["chunk_id"])

    def test_unknown_fields_are_preserved(self):
        result = normalize_result(
            {
                "future_field": {"value": 1},
                "source": {"future_source_field": "keep"},
                "score_details": {"future_score_field": "keep"},
            }
        )

        self.assertEqual(result["future_field"], {"value": 1})
        self.assertEqual(result["source"]["future_source_field"], "keep")
        self.assertEqual(result["score_details"]["future_score_field"], "keep")

    def test_input_is_not_mutated(self):
        original = {
            "id": "mem-1",
            "source": {"custom": {"value": 1}},
            "score_details": {"matched_terms": ["term"]},
        }
        snapshot = copy.deepcopy(original)

        normalized = normalize_result(original, source_kind="memory")
        normalized["source"]["custom"]["value"] = 2
        normalized["score_details"]["matched_terms"].append("changed")

        self.assertEqual(original, snapshot)

    def test_legacy_result_remains_compatible(self):
        result = normalize_result(
            {
                "id": "doc-1",
                "content": "Legacy content",
                "score": 4,
            }
        )

        self.assertEqual(result["id"], "doc-1")
        self.assertEqual(result["content"], "Legacy content")
        self.assertEqual(result["score"], 4)
        self.assertEqual(result["source"]["kind"], "knowledge")


if __name__ == "__main__":
    unittest.main()
