import unittest

from modules.knowledge import KnowledgeStore
from modules.memory_retrieval import retrieve_memories
from modules.rag_integration import run_rag_pipeline_with_fallback
from modules.retrieval import search_knowledge


class _VectorKnowledgeStore(KnowledgeStore):
    def __init__(self):
        pass

    def vector_search(self, query, provider=None, top_k=3, min_similarity=0.0, enabled_only=True, enriched=False):
        result = {
            "id": "doc-1",
            "score": 0.82,
            "record": {
                "id": "doc-1",
                "file_name": "guide.md",
                "content": "Local AI guide",
            },
        }
        if enriched:
            result["score_details"] = {
                "vector": 0.82,
                "keyword": None,
                "matched_terms": [],
                "importance": None,
                "confidence": None,
            }
            result["retrieval_method"] = "vector"
        return [result]

    def _read_vector_index(self):
        return {"items": [{"id": "doc-1"}]}


class RAGScorePropagationTests(unittest.TestCase):
    def test_knowledge_keyword_scores_and_terms_are_propagated(self):
        items = [{
            "id": "doc-1",
            "file_name": "guide.md",
            "file_type": "md",
            "status": "OK",
            "enabled": True,
            "content": "local AI guide",
        }]
        results = search_knowledge("local AI", items, enriched=True)
        self.assertEqual(results[0]["score_details"]["keyword"], 20)
        self.assertEqual(results[0]["score_details"]["matched_terms"], ["ai", "local"])
        self.assertEqual(results[0]["retrieval_method"], "keyword")

    def test_knowledge_vector_score_is_propagated(self):
        result = _VectorKnowledgeStore().retrieve("query", enriched=True)[0]
        self.assertEqual(result["score_details"]["vector"], 0.82)
        self.assertEqual(result["score_details"]["keyword"], None)

    def test_memory_scores_are_propagated(self):
        memories = [{
            "id": "memory-1",
            "content": "I like local AI projects",
            "type": "preference",
            "importance": "high",
            "metadata": {"confidence": 0.9},
        }]
        result = retrieve_memories("local AI", memories, enriched=True)[0]
        self.assertEqual(result["score_details"]["keyword"], 2)
        self.assertEqual(result["score_details"]["importance"], "high")
        self.assertEqual(result["score_details"]["confidence"], 0.9)

    def test_missing_confidence_is_not_invented(self):
        result = retrieve_memories(
            "local",
            [{"content": "local project", "importance": "normal"}],
            enriched=True,
        )[0]
        self.assertIsNone(result["score_details"]["confidence"])

    def test_legacy_retrieval_shape_is_unchanged_by_default(self):
        item = {
            "id": "doc-1",
            "file_name": "guide.md",
            "file_type": "md",
            "status": "OK",
            "enabled": True,
            "content": "local AI guide",
        }
        result = search_knowledge("local", [item])
        self.assertEqual(result, [item])
        self.assertNotIn("score_details", result[0])

    def test_rag_disabled_skips_enriched_processing(self):
        memory = [{"content": "local", "score_details": {"importance": "high"}}]
        result = run_rag_pipeline_with_fallback(memory, [], enabled=False)
        self.assertEqual(result["memory_results"], memory)
        self.assertEqual(result["diagnostics"]["trace"]["fallback_stage"], "disabled")

    def test_rank_score_uses_propagated_features(self):
        result = run_rag_pipeline_with_fallback(
            [{
                "id": "memory-1",
                "content": "local AI",
                "importance": "high",
                "metadata": {"confidence": 0.9},
                "score_details": {"keyword": 2, "importance": "high", "confidence": 0.9},
            }],
            [{
                "id": "doc-1",
                "content": "local AI guide",
                "score": 0.82,
                "score_details": {"vector": 0.82},
            }],
            enabled=True,
        )
        ranked = [item for section in result["sections"] for item in section.get("items", [])]
        self.assertTrue(ranked)
        self.assertTrue(any(item.get("rank_score", 0) > 0 for item in ranked))
        self.assertEqual(result["diagnostics"]["success"], True)


if __name__ == "__main__":
    unittest.main()
