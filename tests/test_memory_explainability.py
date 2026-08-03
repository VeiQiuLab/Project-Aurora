import copy
import unittest

from modules.explainability import explain_memory


class MemoryExplainabilityTests(unittest.TestCase):
    def memory(self):
        return {
            "id": "memory-1",
            "content": "private content omitted from explanation",
            "source": "conversation",
            "metadata": {
                "conversation_id": "conversation-1",
                "signal_type": "preference",
            },
            "confidence": 0.92,
            "importance": "high",
            "importance_score": 9.0,
            "risk": {"level": "low", "reasons": []},
            "explanation": "Stable user preference detected.",
            "status": "pending",
            "created_time": "2026-08-03T00:00:00+00:00",
            "updated_time": "2026-08-03T00:00:00+00:00",
        }

    def test_memory_explanation_generation(self):
        result = explain_memory(self.memory())
        self.assertEqual(result["explanation_version"], "explainability_v1")
        self.assertEqual(result["reason"], "Stable user preference detected.")

    def test_candidate_explanation_generation(self):
        candidate = self.memory()
        candidate["status"] = "pending"
        result = explain_memory(candidate)
        self.assertEqual(result["ranking_factors"]["status"], "pending")

    def test_conversation_provenance_citation(self):
        result = explain_memory(self.memory())
        self.assertEqual(result["sources"][0]["source_type"], "memory")
        self.assertEqual(result["sources"][0]["memory_id"], "memory-1")
        self.assertEqual(result["sources"][0]["conversation_id"], "conversation-1")

    def test_signal_type_is_preserved(self):
        result = explain_memory(self.memory())
        self.assertEqual(result["sources"][0]["signal_type"], "preference")

    def test_confidence_is_preserved(self):
        result = explain_memory(self.memory())
        self.assertEqual(result["confidence"], 0.92)

    def test_importance_is_preserved(self):
        result = explain_memory(self.memory())
        self.assertEqual(result["ranking_factors"]["importance"], "high")
        self.assertEqual(result["ranking_factors"]["importance_score"], 9.0)

    def test_risk_is_preserved(self):
        result = explain_memory(self.memory())
        self.assertEqual(result["ranking_factors"]["risk"]["level"], "low")

    def test_missing_metadata_warning(self):
        memory = self.memory()
        memory.pop("metadata")
        result = explain_memory(memory)
        self.assertIn("memory_metadata_missing", result["warnings"])
        self.assertIn("conversation_provenance_missing", result["warnings"])

    def test_missing_approval_history_warning(self):
        result = explain_memory(self.memory())
        self.assertIn("approval_history_unavailable", result["warnings"])

    def test_diagnostics_are_memory_specific(self):
        result = explain_memory(self.memory())
        self.assertEqual(result["diagnostics"]["stage"], "memory_explainability")
        self.assertEqual(result["diagnostics"]["metrics"]["memory_refs"], 1)
        self.assertGreater(result["diagnostics"]["metrics"]["warnings"], 0)

    def test_input_is_not_mutated(self):
        memory = self.memory()
        original = copy.deepcopy(memory)
        explain_memory(memory)
        self.assertEqual(memory, original)

    def test_invalid_input_is_safe(self):
        result = explain_memory(None)
        self.assertEqual(result["sources"], [])
        self.assertFalse(result["diagnostics"]["success"])
        self.assertIn("invalid_input", result["warnings"])


if __name__ == "__main__":
    unittest.main()
