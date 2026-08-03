import unittest
from unittest.mock import patch

from modules.context_policy import ContextPolicy, build_context_policy


class ContextPolicyTests(unittest.TestCase):
    def context(self, adaptive=False):
        return {
            "query": "Project Aurora",
            "conversation_state": {"message_count": 4},
            "available_context": {
                "memory_count": 2,
                "knowledge_count": 3,
                "conversation_count": 4,
            },
            "budget": {"total_budget": 1000, "reserved_output": 100},
            "adaptive_enabled": adaptive,
        }

    def test_static_policy_output(self):
        result = build_context_policy(self.context())
        self.assertEqual(result["priority_order"], ["memory", "knowledge", "conversation"])
        self.assertEqual(result["diagnostics"]["metrics"]["adaptive_enabled"], False)

    def test_adaptive_disabled_behavior(self):
        first = build_context_policy(self.context())
        second = build_context_policy({**self.context(), "query": "memory preference", "adaptive_enabled": False})
        self.assertEqual(first["memory_budget"], second["memory_budget"])
        self.assertEqual(first["knowledge_budget"], second["knowledge_budget"])

    def test_adaptive_enabled_behavior(self):
        result = build_context_policy(self.context(adaptive=True))
        self.assertTrue(result["diagnostics"]["metrics"]["adaptive_enabled"])
        self.assertIn("adaptive", result["policy_reason"])

    def test_budget_limit_validation(self):
        result = build_context_policy(self.context())
        allocated = sum(result[name] for name in ("memory_budget", "knowledge_budget", "conversation_budget"))
        self.assertLessEqual(allocated, 1000)
        self.assertEqual(allocated, 900)

    def test_negative_budget_handling(self):
        context = self.context()
        context["budget"]["total_budget"] = -50
        result = build_context_policy(context)
        self.assertEqual(sum(result[name] for name in ("memory_budget", "knowledge_budget", "conversation_budget")), 0)
        self.assertIn("invalid_total_budget", result["diagnostics"]["warnings"])

    def test_empty_context_handling(self):
        result = build_context_policy({"budget": {"total_budget": 400}})
        self.assertEqual(result["memory_budget"], 160)
        self.assertEqual(result["knowledge_budget"], 160)
        self.assertEqual(result["conversation_budget"], 80)

    def test_memory_heavy_scenario(self):
        context = self.context(adaptive=True)
        context["query"] = "remember my preference"
        context["available_context"] = {"memory_count": 8, "knowledge_count": 1, "conversation_count": 2}
        result = build_context_policy(context)
        self.assertGreater(result["memory_budget"], result["knowledge_budget"])
        self.assertIn("memory", result["priority_order"])

    def test_knowledge_heavy_scenario(self):
        context = self.context(adaptive=True)
        context["query"] = "find the document source"
        context["available_context"] = {"memory_count": 1, "knowledge_count": 8, "conversation_count": 2}
        result = build_context_policy(context)
        self.assertGreater(result["knowledge_budget"], result["memory_budget"])

    def test_long_conversation_scenario(self):
        context = self.context(adaptive=True)
        context["conversation_state"]["message_count"] = 20
        result = build_context_policy(context)
        self.assertLessEqual(result["conversation_budget"], result["memory_budget"])
        self.assertIn("long conversation", result["policy_reason"])

    def test_diagnostics_output(self):
        result = build_context_policy(self.context())
        diagnostics = result["diagnostics"]
        self.assertEqual(diagnostics["stage"], "context_policy")
        self.assertEqual(diagnostics["metrics"]["total_budget"], 1000)
        self.assertEqual(diagnostics["metrics"]["allocated_budget"], 900)
        self.assertIn("selected_policy", diagnostics["trace"])

    def test_deterministic_output(self):
        context = self.context(adaptive=True)
        self.assertEqual(build_context_policy(context), build_context_policy(context))

    def test_failure_fallback(self):
        policy = ContextPolicy()
        with patch.object(policy, "_budget_values", side_effect=RuntimeError("bad policy")):
            result = policy.decide(self.context(adaptive=True))
        self.assertTrue(result["diagnostics"]["metrics"]["fallback"])
        self.assertEqual(result["memory_budget"], 0)


if __name__ == "__main__":
    unittest.main()
