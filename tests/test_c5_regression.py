"""Regression coverage for completed C5 capabilities."""

import tempfile
import unittest
from pathlib import Path

from modules.context_optimizer import optimize_context
from modules.conversation import ConversationManager
from modules.conversation_intelligence import analyze_conversation
from modules.memory import MemoryStore
from modules.memory_intelligence import MemoryIntelligence
from modules.rag_ranker import rank_results
from modules.rag_results import deduplicate_results, normalize_result, normalize_results


class C5RegressionTests(unittest.TestCase):
    def test_memory_intelligence_candidate_contract(self):
        intelligence = MemoryIntelligence()
        self.assertIsInstance(intelligence, MemoryIntelligence)

        candidate = intelligence.analyze(
            "I prefer concise explanations.",
            base_candidates=[
                {
                    "type": "preference",
                    "content": "User prefers concise explanations.",
                    "score": 0.9,
                }
            ],
        )[0]

        for field in ("content", "confidence", "importance", "risk", "explanation"):
            self.assertIn(field, candidate)

    def test_memory_metadata_lifecycle_regression(self):
        store = MemoryStore(Path(tempfile.mkdtemp()))
        memory = store.create(
            "preference",
            "old",
            "normal",
            metadata={"confidence": 0.9},
        )

        content_updated = store.update(memory["id"], "preference", "new", "normal")
        self.assertTrue(content_updated["metadata"]["stale"])

        type_updated = store.update(memory["id"], "fact", "new", "normal")
        self.assertTrue(type_updated["metadata"]["stale"])

        importance_memory = store.create(
            "fact",
            "stable",
            "normal",
            metadata={"confidence": 0.9},
        )
        importance_updated = store.update(importance_memory["id"], "fact", "stable", "high")
        self.assertNotIn("stale", importance_updated["metadata"])

        enabled_memory = store.create(
            "fact",
            "enabled",
            "normal",
            metadata={"confidence": 0.9},
        )
        enabled_updated = store.set_enabled(enabled_memory["id"], False)
        self.assertFalse(enabled_updated["enabled"])
        self.assertNotIn("stale", enabled_updated["metadata"])

    def test_conversation_intelligence_contract(self):
        result = analyze_conversation([{"role": "user", "content": "test"}])

        for field in (
            "summary",
            "topics",
            "important_events",
            "memory_signals",
            "analysis_version",
            "analyzed_time",
        ):
            self.assertIn(field, result)

    def test_conversation_metadata_namespace(self):
        manager = ConversationManager(Path(tempfile.mkdtemp()))
        conversation = manager.save(
            None,
            "model",
            [{"role": "user", "content": "test"}],
        )
        analysis = analyze_conversation(conversation["messages"])

        updated = manager.save_conversation_intelligence(conversation["id"], analysis)

        self.assertEqual(updated["metadata"]["conversation_intelligence"], analysis)

    def test_rag_result_contract(self):
        knowledge = normalize_result(
            {
                "id": "doc-1",
                "content": "Knowledge",
                "source": {"kind": "knowledge", "file_name": "guide.md"},
                "metadata": {"custom": "keep"},
            }
        )
        memory = normalize_result(
            {
                "id": "mem-1",
                "content": "Memory",
                "source": {"kind": "memory"},
                "metadata": {"confidence": 0.9},
            }
        )
        normalized = normalize_results([knowledge, memory])

        self.assertEqual(normalized[0]["id"], "doc-1")
        self.assertEqual(normalized[0]["content"], "Knowledge")
        self.assertEqual(normalized[0]["source"]["kind"], "knowledge")
        self.assertEqual(normalized[0]["metadata"]["custom"], "keep")

    def test_rag_duplicate_ranking_and_optimizer_contract(self):
        results = [
            normalize_result({
                "id": "doc-1",
                "content": "Same knowledge",
                "score": 0.4,
                "source": {"kind": "knowledge", "content_hash": "same"},
                "score_details": {"vector": 0.4},
            }),
            normalize_result({
                "id": "doc-1",
                "content": "Same knowledge",
                "score": 0.8,
                "source": {"kind": "knowledge", "content_hash": "same"},
                "score_details": {"vector": 0.8},
            }),
            normalize_result({
                "id": "mem-1",
                "content": "Same knowledge",
                "source": {"kind": "memory"},
                "metadata": {"importance": "high", "confidence": 0.9},
            }),
        ]

        deduplicated = deduplicate_results(results)
        self.assertEqual(len(deduplicated), 2)
        ranked = rank_results(deduplicated)
        self.assertIn("rank_score", ranked[0])
        self.assertIn("ranking_details", ranked[0])

        optimized = optimize_context(
            [
                {"name": "Knowledge", "enabled": True, "content": ranked[0]["content"]},
                {"name": "Memory", "enabled": True, "content": ranked[-1]["content"]},
            ],
            max_tokens=20,
        )
        self.assertLessEqual(optimized["diagnostics"]["used_tokens"], 20)
        self.assertIn("diagnostics", optimized)


if __name__ == "__main__":
    unittest.main()
