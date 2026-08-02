"""Tests for the independent RAG pipeline core."""

import copy
import unittest
from unittest.mock import patch

from modules.rag_pipeline import RAGPipeline, run_rag_pipeline


class RagPipelineTests(unittest.TestCase):
    def knowledge(self, content="Knowledge", item_id="doc-1"):
        return {
            "id": item_id,
            "content": content,
            "score": 0.8,
            "source": {"kind": "knowledge", "file_name": "guide.md"},
            "metadata": {"custom": "keep"},
            "score_details": {"vector": 0.8},
        }

    def memory(self, content="Memory", item_id="mem-1"):
        return {
            "id": item_id,
            "content": content,
            "source": {"kind": "memory"},
            "metadata": {"importance": "high", "confidence": 0.9},
        }

    def test_empty_input(self):
        result = run_rag_pipeline()

        self.assertEqual(len(result["sections"]), 2)
        self.assertFalse(result["diagnostics"]["success"] is False)
        self.assertEqual(result["diagnostics"]["metrics"]["normalized_count"], 0)

    def test_memory_only(self):
        result = run_rag_pipeline(memory_results=[self.memory()])

        self.assertEqual(result["diagnostics"]["metrics"]["memory_input"], 1)
        self.assertEqual(result["sections"][0]["items"][0]["source"]["kind"], "memory")

    def test_knowledge_only(self):
        result = run_rag_pipeline(knowledge_results=[self.knowledge()])

        self.assertEqual(result["diagnostics"]["metrics"]["knowledge_input"], 1)
        self.assertEqual(result["sections"][1]["items"][0]["source"]["kind"], "knowledge")

    def test_mixed_memory_and_knowledge(self):
        result = run_rag_pipeline(
            memory_results=[self.memory()],
            knowledge_results=[self.knowledge()],
        )

        self.assertEqual(len(result["sections"]), 2)
        self.assertEqual(result["diagnostics"]["metrics"]["ranked_count"], 2)

    def test_pipeline_calls_core_stages(self):
        with patch("modules.rag_pipeline.normalize_results", wraps=lambda items, **_kwargs: items) as normalize, \
                patch("modules.rag_pipeline.deduplicate_results", side_effect=lambda items: items) as dedup, \
                patch("modules.rag_pipeline.rank_results", side_effect=lambda items, **_kwargs: items) as rank, \
                patch("modules.rag_pipeline.optimize_context", side_effect=lambda sections, **_kwargs: {"sections": sections}) as optimize:
            run_rag_pipeline(memory_results=[self.memory()], knowledge_results=[self.knowledge()])

        self.assertEqual(normalize.call_count, 2)
        self.assertEqual(dedup.call_count, 2)
        self.assertEqual(rank.call_count, 2)
        self.assertEqual(optimize.call_count, 1)

    def test_normalization_failure_falls_back(self):
        with patch("modules.rag_pipeline.normalize_results", side_effect=RuntimeError("normalize")):
            result = run_rag_pipeline(memory_results=[self.memory()])

        self.assertFalse(result["diagnostics"]["success"])
        self.assertEqual(result["diagnostics"]["trace"]["fallback_stage"], "normalization")
        self.assertTrue(result["diagnostics"]["warnings"])

    def test_deduplication_failure_falls_back(self):
        with patch("modules.rag_pipeline.deduplicate_results", side_effect=RuntimeError("dedup")):
            result = run_rag_pipeline(memory_results=[self.memory()])

        self.assertFalse(result["diagnostics"]["success"])
        self.assertEqual(result["diagnostics"]["trace"]["fallback_stage"], "deduplication")
        self.assertEqual(result["diagnostics"]["metrics"]["deduplicated_count"], 1)

    def test_ranking_failure_falls_back(self):
        with patch("modules.rag_pipeline.rank_results", side_effect=RuntimeError("rank")):
            result = run_rag_pipeline(knowledge_results=[self.knowledge()])

        self.assertFalse(result["diagnostics"]["success"])
        self.assertEqual(result["diagnostics"]["trace"]["fallback_stage"], "ranking")
        self.assertEqual(result["sections"][1]["items"][0]["id"], "doc-1")

    def test_optimization_failure_falls_back(self):
        with patch("modules.rag_pipeline.optimize_context", side_effect=RuntimeError("optimize")):
            result = run_rag_pipeline(memory_results=[self.memory()])

        self.assertFalse(result["diagnostics"]["success"])
        self.assertEqual(result["diagnostics"]["trace"]["fallback_stage"], "optimization")
        self.assertEqual(result["sections"][0]["items"][0]["id"], "mem-1")

    def test_diagnostics_schema_and_metrics(self):
        result = run_rag_pipeline(
            memory_results=[self.memory()],
            knowledge_results=[self.knowledge()],
        )
        diagnostics = result["diagnostics"]

        self.assertEqual(
            set(diagnostics),
            {"stage", "success", "reason", "warnings", "metrics", "trace"},
        )
        self.assertEqual(diagnostics["stage"], "rag_pipeline")
        self.assertEqual(diagnostics["metrics"]["normalized_count"], 2)

    def test_config_can_disable_stages(self):
        result = run_rag_pipeline(
            memory_results=[self.memory()],
            config={
                "enable_dedup": False,
                "enable_ranking": False,
                "enable_optimization": False,
            },
        )

        self.assertEqual(result["diagnostics"]["trace"]["enabled_stages"]["dedup"], False)
        self.assertEqual(result["sections"][0]["items"][0]["id"], "mem-1")

    def test_inputs_and_metadata_are_preserved(self):
        inputs = [self.memory()]
        snapshot = copy.deepcopy(inputs)

        result = run_rag_pipeline(memory_results=inputs)
        result["sections"][0]["items"][0]["metadata"]["importance"] = "low"

        self.assertEqual(inputs, snapshot)
        self.assertEqual(result["sections"][0]["items"][0]["metadata"]["confidence"], 0.9)

    def test_pipeline_class_matches_helper(self):
        result = RAGPipeline().run(knowledge_results=[self.knowledge()])

        self.assertEqual(result["diagnostics"]["stage"], "rag_pipeline")


if __name__ == "__main__":
    unittest.main()
