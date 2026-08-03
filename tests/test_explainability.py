import unittest

from modules.explainability import (
    EXPLANATION_VERSION,
    build_citation,
    explain_memory,
    explain_rag_result,
)


class ExplainabilityTests(unittest.TestCase):
    def test_basic_explanation_generation(self):
        result = explain_rag_result({
            "id": "doc-1",
            "source": {"kind": "knowledge", "id": "doc-1", "file_name": "guide.md"},
            "ranking_details": {"reason": "knowledge ranking: keyword=0.8"},
        })
        self.assertEqual(result["explanation_version"], EXPLANATION_VERSION)
        self.assertEqual(result["reason"], "knowledge ranking: keyword=0.8")

    def test_knowledge_citation_creation(self):
        citation = build_citation({
            "id": "doc-1",
            "source": {
                "kind": "knowledge",
                "id": "doc-1",
                "file_name": "guide.md",
                "source_path": "docs/guide.md",
                "chunk_id": "chunk-2",
            },
        })
        self.assertEqual(citation, {
            "source_type": "knowledge",
            "source_id": "doc-1",
            "title": "guide.md",
            "location": "docs/guide.md",
            "chunk_id": "chunk-2",
        })

    def test_memory_provenance_citation(self):
        citation = build_citation({
            "id": "memory-1",
            "source": {"kind": "memory", "memory_id": "memory-1"},
            "metadata": {"conversation_id": "conversation-1", "signal_type": "preference"},
        })
        self.assertEqual(citation["source_type"], "memory")
        self.assertEqual(citation["conversation_id"], "conversation-1")
        self.assertEqual(citation["signal_type"], "preference")

    def test_ranking_details_are_preserved(self):
        details = {"reason": "selected", "vector": 0.8, "custom": "keep"}
        result = explain_rag_result({
            "source": {"kind": "knowledge", "id": "doc-1"},
            "ranking_details": details,
        })
        self.assertEqual(result["ranking_factors"], details)

    def test_missing_metadata_generates_warning(self):
        result = explain_memory({"id": "memory-1", "content": "fact"})
        self.assertIn("memory_metadata_missing", result["warnings"])
        self.assertIn("conversation_provenance_missing", result["warnings"])

    def test_missing_confidence_remains_none(self):
        result = explain_rag_result({"source": {"kind": "knowledge", "id": "doc-1"}})
        self.assertIsNone(result["confidence"])
        self.assertIn("confidence_unavailable", result["warnings"])

    def test_warning_and_diagnostics_output(self):
        result = explain_rag_result(
            {"source": {"kind": "knowledge", "id": "doc-1"}},
            diagnostics={
                "stage": "rag_pipeline",
                "success": True,
                "metrics": {"input_count": 2},
                "trace": {"fallback_stage": ""},
            },
        )
        self.assertEqual(result["diagnostics"]["stage"], "rag_pipeline")
        self.assertEqual(result["diagnostics"]["metrics"]["input_count"], 2)
        self.assertTrue(result["warnings"])

    def test_default_diagnostics_are_created(self):
        result = explain_rag_result({"source": {"kind": "knowledge", "id": "doc-1"}})
        self.assertEqual(result["diagnostics"]["stage"], "explainability")
        self.assertEqual(result["diagnostics"]["metrics"]["sources_count"], 1)

    def test_fallback_diagnostic_becomes_warning(self):
        result = explain_rag_result(
            {"source": {"kind": "knowledge", "id": "doc-1"}},
            diagnostics={"trace": {"fallback_stage": "ranking"}},
        )
        self.assertIn("fallback_used", result["warnings"])

    def test_input_is_not_mutated(self):
        source = {"kind": "knowledge", "id": "doc-1"}
        result = {"source": source, "ranking_details": {"reason": "selected"}}
        explain_rag_result(result)
        self.assertEqual(result, {"source": source, "ranking_details": {"reason": "selected"}})

    def test_invalid_input_is_safe(self):
        result = explain_memory(None)
        self.assertEqual(result["sources"], [])
        self.assertFalse(result["diagnostics"]["success"])
        self.assertIn("invalid_input", result["warnings"])

    def test_memory_evaluation_information_is_exposed(self):
        result = explain_memory({
            "id": "memory-1",
            "source": {"kind": "memory", "memory_id": "memory-1"},
            "metadata": {"conversation_id": "conversation-1", "confidence": 0.9},
            "importance": "high",
            "risk": {"level": "low", "reasons": []},
            "explanation": "User preference detected.",
            "status": "pending",
        })
        self.assertEqual(result["reason"], "User preference detected.")
        self.assertEqual(result["confidence"], 0.9)
        self.assertEqual(result["ranking_factors"]["status"], "pending")


if __name__ == "__main__":
    unittest.main()
