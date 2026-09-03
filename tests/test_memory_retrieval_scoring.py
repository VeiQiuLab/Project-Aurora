"""Regression tests for deterministic Memory relevance and ranking."""

import unittest

from modules.memory_retrieval import build_memory_retrieval_config, retrieve_memories


def _memory(identifier, content, **overrides):
    item = {
        "id": identifier,
        "content": content,
        "type": "preference",
        "importance": "normal",
        "enabled": True,
        "metadata": {"state": "active", "confidence": 0.5},
    }
    item.update(overrides)
    return item


class MemoryRetrievalScoringTests(unittest.TestCase):
    def test_settings_are_resolved_for_production_retrieval(self):
        settings = {
            "memory.max_injection": "3",
            "memory.min_importance": "1",
            "memory.retrieval_threshold": "0.42",
            "memory.confidence_default": "0.6",
            "rag.memory_ranking_weights": {"relevance": 1.0},
        }

        config = build_memory_retrieval_config(settings)

        self.assertEqual(config["max_results"], 3)
        self.assertEqual(config["min_relevance"], 0.42)
        self.assertEqual(config["confidence_default"], 0.6)
        self.assertEqual(config["ranking_weights"], {"relevance": 1.0})

    def test_high_relevance_memory_is_retrieved(self):
        result = retrieve_memories(
            "python testing workflow",
            [_memory("hit", "My python testing workflow uses unittest")],
            enriched=True,
        )

        self.assertEqual(result[0]["id"], "hit")
        self.assertGreaterEqual(result[0]["relevance_score"], 0.9)

    def test_generic_single_overlap_is_filtered(self):
        memories = [_memory("generic", "This project should continue next week")]
        self.assertEqual(retrieve_memories("please continue this project", memories), [])

    def test_protected_generic_chinese_queries_do_not_retrieve(self):
        memories = [_memory("generic", "\u4f60\u597d\uff0c\u8fd9\u4e2a\u9879\u76ee\u53ef\u4ee5\u7ee7\u7eed\uff0c\u7136\u540e\u8ba8\u8bba\u4e3a\u4ec0\u4e48\u6548\u679c\u600e\u4e48\u6837")]
        for query in ("\u4f60\u597d", "\u7136\u540e\u5462", "\u8fd9\u4e2a\u600e\u4e48\u6837", "\u4e3a\u4ec0\u4e48", "\u53ef\u4ee5\u5417", "\u7ee7\u7eed"):
            with self.subTest(query=query):
                self.assertEqual(retrieve_memories(query, memories), [])

    def test_only_enabled_active_and_legacy_memories_are_retrieved(self):
        memories = [
            _memory("active", "aurora memory retrieval"),
            _memory("disabled", "aurora memory retrieval", enabled=False),
            _memory("superseded", "aurora memory retrieval", metadata={"state": "superseded"}),
            _memory("archived", "aurora memory retrieval", metadata={"state": "archived"}),
            {"id": "legacy", "content": "aurora memory retrieval", "importance": "normal"},
        ]

        result = retrieve_memories("aurora memory retrieval", memories, max_results=10)

        self.assertEqual({item["id"] for item in result}, {"active", "legacy"})

    def test_relevance_outweighs_importance(self):
        memories = [
            _memory("relevant", "python testing workflow", importance="low"),
            _memory("important", "python gardening notes", importance="high"),
        ]

        result = retrieve_memories(
            "python testing workflow", memories, max_results=10, enriched=True, min_relevance=0.30
        )

        self.assertEqual([item["id"] for item in result], ["relevant", "important"])

    def test_freshness_breaks_near_equal_relevance_lightly(self):
        memories = [
            _memory("old", "python testing workflow", updated_time="2020-01-01T00:00:00+00:00"),
            _memory("new", "python testing workflow", updated_time="2099-01-01T00:00:00+00:00"),
        ]

        result = retrieve_memories("python testing workflow", memories, enriched=True)

        self.assertEqual([item["id"] for item in result], ["new", "old"])
        self.assertLess(result[1]["freshness_score"], result[0]["freshness_score"])

    def test_missing_metadata_uses_neutral_defaults(self):
        result = retrieve_memories(
            "local aurora",
            [{"id": "legacy", "content": "local aurora", "importance": "normal"}],
            enriched=True,
        )[0]

        self.assertEqual(result["confidence_score"], 0.5)
        self.assertEqual(result["freshness_score"], 0.5)

    def test_max_results_is_enforced(self):
        memories = [_memory(str(index), "aurora retrieval") for index in range(5)]
        self.assertEqual(len(retrieve_memories("aurora retrieval", memories, max_results=2)), 2)

    def test_chinese_and_existing_ui_aliases_remain_compatible(self):
        memories = [_memory("zh", "\u7528\u6237\u504f\u597d\u6df1\u8272 UI \u98ce\u683c")]
        result = retrieve_memories("\u6211\u559c\u6b22\u6df1\u8272\u754c\u9762\u8bbe\u8ba1", memories)
        self.assertEqual(result[0]["id"], "zh")

    def test_enriched_diagnostics_include_all_scores(self):
        result = retrieve_memories(
            "aurora retrieval",
            [_memory("scores", "aurora retrieval")],
            enriched=True,
        )[0]

        for field in (
            "relevance_score", "confidence_score", "importance_score", "freshness_score", "final_score"
        ):
            self.assertIn(field, result)
            self.assertIn(field, result["score_details"])
            self.assertGreaterEqual(result[field], 0.0)
            self.assertLessEqual(result[field], 1.0)


if __name__ == "__main__":
    unittest.main()
