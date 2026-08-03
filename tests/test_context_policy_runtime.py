import copy
import unittest
from unittest.mock import patch

from modules.explainability import explain_rag_result
from modules.rag_integration import run_rag_pipeline_with_fallback


class ContextPolicyRuntimeTests(unittest.TestCase):
    def runner(self, captured):
        def run(*, memory_results, knowledge_results, config):
            captured.append({
                "memory": copy.deepcopy(memory_results),
                "knowledge": copy.deepcopy(knowledge_results),
                "config": copy.deepcopy(config),
            })
            return {
                "sections": [
                    {"name": "Memory", "items": memory_results, "content": "memory", "enabled": True},
                    {"name": "Knowledge", "items": knowledge_results, "content": "knowledge", "enabled": True},
                ],
                "diagnostics": {
                    "stage": "rag_pipeline",
                    "success": True,
                    "metrics": {"optimized_count": len(memory_results) + len(knowledge_results)},
                    "trace": {},
                },
            }
        return run

    def test_adaptive_disabled_keeps_legacy_behavior(self):
        calls = []
        with patch("modules.rag_integration.build_context_policy") as policy:
            result = run_rag_pipeline_with_fallback(
                [{"id": "m1", "content": "memory"}],
                [{"id": "k1", "content": "knowledge"}],
                enabled=True,
                pipeline_runner=self.runner(calls),
            )
        policy.assert_not_called()
        self.assertIsNone(calls[0]["config"])
        self.assertTrue(result["diagnostics"]["metrics"]["adaptive_enabled"] is False)

    def test_adaptive_enabled_applies_policy_allocation(self):
        calls = []
        result = run_rag_pipeline_with_fallback(
            [{"id": "m1", "content": "memory"}],
            [{"id": "k1", "content": "knowledge"}],
            enabled=True,
            config={"context.adaptive_enabled": True, "max_tokens": 100},
            query="remember preference",
            available_context={"memory_count": 3, "knowledge_count": 1, "conversation_count": 0},
            pipeline_runner=self.runner(calls),
        )
        self.assertIn("section_budget", calls[0]["config"])
        self.assertGreater(calls[0]["config"]["section_budget"]["Memory"], calls[0]["config"]["section_budget"]["Knowledge"])
        self.assertEqual(result["diagnostics"]["trace"]["context_policy"]["selected_policy"], "adaptive")

    def test_policy_failure_falls_back(self):
        calls = []
        with patch("modules.rag_integration.build_context_policy", side_effect=RuntimeError("policy failed")):
            result = run_rag_pipeline_with_fallback(
                [], [], enabled=True,
                config={"context.adaptive_enabled": True},
                pipeline_runner=self.runner(calls),
            )
        self.assertTrue(result["diagnostics"]["metrics"]["fallback"])
        self.assertEqual(result["diagnostics"]["trace"]["context_policy"]["selected_policy"], "static_fallback")
        self.assertNotIn("section_budget", calls[0]["config"])

    def test_invalid_policy_output_falls_back(self):
        calls = []
        with patch("modules.rag_integration.build_context_policy", return_value={
            "memory_budget": -1,
            "knowledge_budget": 0,
            "conversation_budget": 0,
        }):
            result = run_rag_pipeline_with_fallback(
                [], [], enabled=True,
                config={"context.adaptive_enabled": True},
                pipeline_runner=self.runner(calls),
            )
        self.assertTrue(result["diagnostics"]["metrics"]["fallback"])

    def test_budget_validation(self):
        calls = []
        result = run_rag_pipeline_with_fallback(
            [], [], enabled=True,
            config={"context.adaptive_enabled": True, "max_tokens": 50},
            budget={"total_budget": 50, "reserved_output": 10},
            pipeline_runner=self.runner(calls),
        )
        section_budget = calls[0]["config"]["section_budget"]
        self.assertLessEqual(sum(section_budget.values()), 40)
        self.assertFalse(result["diagnostics"]["metrics"]["fallback"])

    def test_diagnostics_output(self):
        result = run_rag_pipeline_with_fallback(
            [], [], enabled=True,
            config={"context.adaptive_enabled": True},
            pipeline_runner=self.runner([]),
        )
        diagnostics = result["diagnostics"]
        self.assertIn("context_policy", diagnostics["trace"])
        self.assertIn("allocated_budget", diagnostics["metrics"])

    def test_explainability_can_read_policy_diagnostics(self):
        result = run_rag_pipeline_with_fallback(
            [{"id": "m1", "content": "memory"}], [], enabled=True,
            config={"context.adaptive_enabled": True},
            query="memory preference",
            pipeline_runner=self.runner([]),
        )
        explanation = explain_rag_result(
            {"source": {"kind": "memory", "memory_id": "m1"}, "ranking_details": {}},
            diagnostics=result["diagnostics"],
        )
        self.assertEqual(explanation["diagnostics"]["trace"]["context_policy"]["selected_policy"], "adaptive")

    def test_context_builder_interface_unchanged(self):
        result = run_rag_pipeline_with_fallback([], [], enabled=False)
        self.assertIn("sections", result)
        self.assertIn("memory_results", result)
        self.assertIn("knowledge_results", result)

    def test_original_retrieval_metadata_unchanged(self):
        memory = [{"id": "m1", "content": "memory", "metadata": {"keep": True}}]
        original = copy.deepcopy(memory)
        result = run_rag_pipeline_with_fallback(
            memory, [], enabled=True,
            config={"context.adaptive_enabled": True},
            pipeline_runner=self.runner([]),
        )
        self.assertEqual(memory, original)
        self.assertEqual(result["memory_results"], original)

    def test_no_prompt_format_changes(self):
        calls = []
        run_rag_pipeline_with_fallback([], [], enabled=True, pipeline_runner=self.runner(calls))
        self.assertNotIn("prompt", calls[0]["config"] or {})


if __name__ == "__main__":
    unittest.main()
