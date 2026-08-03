import copy
import unittest

from modules.explainability import explain_rag_pipeline


class RAGExplainabilityTests(unittest.TestCase):
    def pipeline_result(self):
        return {
            "sections": [
                {
                    "name": "Knowledge",
                    "items": [{
                        "id": "doc-1",
                        "content": "hidden content",
                        "score": 0.8,
                        "rank_score": 0.7,
                        "source": {
                            "kind": "knowledge",
                            "id": "doc-1",
                            "file_name": "guide.md",
                            "source_path": "docs/guide.md",
                            "chunk_id": "chunk-1",
                        },
                        "ranking_details": {
                            "reason": "knowledge ranking: vector=0.800",
                            "vector": 0.8,
                        },
                    }],
                },
                {
                    "name": "Memory",
                    "items": [{
                        "id": "memory-1",
                        "score": 0.4,
                        "rank_score": 0.6,
                        "source": {"kind": "memory", "memory_id": "memory-1"},
                        "metadata": {
                            "conversation_id": "conversation-1",
                            "signal_type": "preference",
                        },
                        "ranking_details": {"reason": "memory ranking: importance=1.000"},
                    }],
                },
            ],
            "diagnostics": {
                "stage": "rag_pipeline",
                "success": True,
                "metrics": {
                    "normalized_count": 3,
                    "deduplicated_count": 2,
                    "ranked_count": 2,
                    "optimized_count": 2,
                },
                "trace": {"sections": ["Memory", "Knowledge"]},
            },
        }

    def test_rag_result_explanation_generation(self):
        result = explain_rag_pipeline(self.pipeline_result())
        self.assertEqual(result["explanation_version"], "explainability_v1")
        self.assertEqual(result["diagnostics"]["stage"], "rag_explainability")

    def test_knowledge_citation_creation(self):
        result = explain_rag_pipeline(self.pipeline_result())
        citation = next(item for item in result["sources"] if item["source_type"] == "knowledge")
        self.assertEqual(citation["source_id"], "doc-1")
        self.assertEqual(citation["chunk_id"], "chunk-1")

    def test_memory_citation_creation(self):
        result = explain_rag_pipeline(self.pipeline_result())
        citation = next(item for item in result["sources"] if item["source_type"] == "memory")
        self.assertEqual(citation["memory_id"], "memory-1")
        self.assertEqual(citation["conversation_id"], "conversation-1")

    def test_selected_optimized_sources_are_preserved(self):
        result = explain_rag_pipeline(self.pipeline_result())
        ids = {item.get("source_id") or item.get("memory_id") for item in result["sources"]}
        self.assertEqual(ids, {"doc-1", "memory-1"})
        self.assertNotIn("hidden content", str(result["sources"]))

    def test_ranking_details_are_preserved(self):
        result = explain_rag_pipeline(self.pipeline_result())
        factors = result["ranking_factors"]
        self.assertEqual(factors["Knowledge:0"]["score"], 0.8)
        self.assertEqual(factors["Knowledge:0"]["ranking_details"]["vector"], 0.8)

    def test_missing_source_warning(self):
        data = self.pipeline_result()
        data["sections"][0]["items"][0].pop("source")
        result = explain_rag_pipeline(data)
        self.assertIn("source_metadata_missing", result["warnings"])

    def test_missing_ranking_reason_warning(self):
        data = self.pipeline_result()
        data["sections"][0]["items"][0]["ranking_details"] = {"vector": 0.8}
        result = explain_rag_pipeline(data)
        self.assertIn("ranking_reason_unavailable", result["warnings"])

    def test_duplicate_trace_unavailable_warning(self):
        result = explain_rag_pipeline(self.pipeline_result())
        self.assertIn("duplicate_trace_unavailable", result["warnings"])

    def test_trimming_trace_unavailable_warning(self):
        result = explain_rag_pipeline(self.pipeline_result())
        self.assertIn("trimming_trace_unavailable", result["warnings"])

    def test_diagnostics_metrics_are_correct(self):
        result = explain_rag_pipeline(self.pipeline_result())
        metrics = result["diagnostics"]["metrics"]
        self.assertEqual(metrics["sources_count"], 2)
        self.assertEqual(metrics["selected_items"], 2)
        self.assertEqual(metrics["memory_refs"], 1)
        self.assertEqual(metrics["optimized_count"], 2)

    def test_input_is_not_mutated(self):
        data = self.pipeline_result()
        original = copy.deepcopy(data)
        explain_rag_pipeline(data)
        self.assertEqual(data, original)

    def test_invalid_input_is_safe(self):
        result = explain_rag_pipeline(None)
        self.assertEqual(result["sources"], [])
        self.assertFalse(result["diagnostics"]["success"])

    def test_explanation_failure_safety(self):
        result = explain_rag_pipeline({"sections": [object()]})
        self.assertIn("explanation_version", result)
        self.assertIsInstance(result["warnings"], list)


if __name__ == "__main__":
    unittest.main()
