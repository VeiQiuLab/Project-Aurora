"""Tests for the independent RAG ranking layer."""

import copy
import unittest

from modules.rag_ranker import RAGRanker, normalize_score, rank_results


class RagRankerTests(unittest.TestCase):
    def test_score_normalization(self):
        self.assertEqual(normalize_score(0.75, "vector"), 0.75)
        self.assertEqual(normalize_score(1.0, "confidence"), 1.0)
        self.assertGreater(normalize_score(10, "keyword"), 0.0)
        self.assertEqual(normalize_score("high", "importance"), 1.0)

    def test_score_normalization_is_bounded(self):
        self.assertEqual(normalize_score(2.0, "vector"), 1.0)
        self.assertEqual(normalize_score(-1.0, "freshness"), 0.0)
        self.assertEqual(normalize_score("invalid", "keyword"), 0.0)

    def test_knowledge_ranking_details(self):
        result = rank_results(
            [{
                "id": "doc-1",
                "score": 0.8,
                "retrieval_method": "vector",
                "source": {"kind": "knowledge"},
                "score_details": {"vector": 0.8, "keyword": 0.2},
            }],
            section="knowledge",
        )[0]

        self.assertIn("rank_score", result)
        self.assertIn("ranking_details", result)
        self.assertEqual(result["ranking_details"]["section"], "knowledge")
        self.assertIn("vector=", result["ranking_details"]["reason"])

    def test_memory_section_uses_importance_and_confidence(self):
        result = rank_results(
            [{
                "content": "Memory",
                "source": {"kind": "memory"},
                "metadata": {"importance": "high", "confidence": 0.9},
            }]
        )[0]

        details = result["ranking_details"]
        self.assertEqual(details["section"], "memory")
        self.assertEqual(details["importance"], 1.0)
        self.assertEqual(details["confidence"], 0.9)

    def test_results_are_sorted_stably(self):
        results = [
            {"id": "low", "score": 0.2, "source": {"kind": "knowledge"}},
            {"id": "high", "score": 0.9, "source": {"kind": "knowledge"}},
        ]

        ranked = rank_results(results, section="knowledge")

        self.assertEqual(ranked[0]["id"], "high")

    def test_custom_weights(self):
        result = RAGRanker().rank_result(
            {
                "score_details": {"vector": 0.2, "keyword": 0.9},
                "source": {"kind": "knowledge"},
            },
            section="knowledge",
            weights={"vector": 0.0, "keyword": 1.0},
        )

        self.assertAlmostEqual(result["rank_score"], normalize_score(0.9, "keyword"))

    def test_original_score_details_are_preserved(self):
        result = {
            "score": 0.7,
            "score_details": {"vector": 0.7, "custom": "keep"},
            "metadata": {"custom": "value"},
            "source": {"kind": "knowledge"},
        }

        ranked = rank_results([result])[0]

        self.assertEqual(ranked["score"], 0.7)
        self.assertEqual(ranked["score_details"]["custom"], "keep")
        self.assertEqual(ranked["metadata"], {"custom": "value"})

    def test_input_is_not_mutated(self):
        results = [{
            "score": 0.5,
            "score_details": {"vector": 0.5},
            "source": {"kind": "knowledge"},
        }]
        snapshot = copy.deepcopy(results)

        ranked = rank_results(results)
        ranked[0]["ranking_details"]["section"] = "changed"

        self.assertEqual(results, snapshot)

    def test_empty_input(self):
        self.assertEqual(rank_results([]), [])
        self.assertEqual(rank_results(None), [])


if __name__ == "__main__":
    unittest.main()
