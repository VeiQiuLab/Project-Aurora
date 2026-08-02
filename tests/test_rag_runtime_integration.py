"""Tests for the optional runtime RAG integration adapter."""

import copy
import unittest

from modules.rag_integration import run_rag_pipeline_with_fallback


class RagRuntimeIntegrationTests(unittest.TestCase):
    def memory(self):
        return {
            "id": "mem-1",
            "content": "Memory content",
            "metadata": {"confidence": 0.9},
            "source": {"kind": "memory"},
        }

    def knowledge(self):
        return {
            "id": "doc-1",
            "content": "Knowledge content",
            "metadata": {"custom": "keep"},
            "source": {"kind": "knowledge", "file_name": "guide.md"},
        }

    def test_disabled_keeps_legacy_results_and_does_not_call_pipeline(self):
        calls = []
        result = run_rag_pipeline_with_fallback(
            [self.memory()],
            [self.knowledge()],
            enabled=False,
            pipeline_runner=lambda **_kwargs: calls.append(True),
        )

        self.assertEqual(calls, [])
        self.assertEqual(result["memory_results"][0]["id"], "mem-1")
        self.assertFalse(result["diagnostics"]["metrics"]["pipeline_enabled"])

    def test_enabled_calls_pipeline_and_returns_sections(self):
        def runner(**_kwargs):
            return {
                "sections": [
                    {"name": "Memory", "enabled": True, "content": "Optimized memory", "items": [self.memory()]},
                    {"name": "Knowledge", "enabled": True, "content": "Optimized knowledge", "items": [self.knowledge()]},
                ],
                "diagnostics": {
                    "stage": "rag_pipeline",
                    "success": True,
                    "warnings": [],
                    "metrics": {"optimized_count": 2},
                    "trace": {"enabled_stages": {"ranking": True}},
                },
            }

        result = run_rag_pipeline_with_fallback(
            [self.memory()],
            [self.knowledge()],
            enabled=True,
            pipeline_runner=runner,
        )

        self.assertEqual(result["diagnostics"]["stage"], "rag_runtime_integration")
        self.assertTrue(result["diagnostics"]["success"])
        self.assertEqual(result["sections"][0]["content"], "Optimized memory")
        self.assertEqual(result["diagnostics"]["metrics"]["optimized_count"], 2)

    def test_pipeline_failure_falls_back_without_raising(self):
        original_memory = [self.memory()]
        original_knowledge = [self.knowledge()]
        result = run_rag_pipeline_with_fallback(
            original_memory,
            original_knowledge,
            enabled=True,
            pipeline_runner=lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("pipeline failed")),
        )

        self.assertFalse(result["diagnostics"]["success"])
        self.assertEqual(result["diagnostics"]["trace"]["fallback_stage"], "pipeline")
        self.assertEqual(result["memory_results"], original_memory)
        self.assertEqual(result["knowledge_results"], original_knowledge)

    def test_diagnostics_contains_runtime_metrics(self):
        result = run_rag_pipeline_with_fallback(
            [self.memory()],
            [self.knowledge()],
            enabled=False,
        )

        diagnostics = result["diagnostics"]
        self.assertEqual(
            set(diagnostics),
            {"stage", "success", "reason", "warnings", "metrics", "trace"},
        )
        self.assertEqual(diagnostics["metrics"]["memory_input"], 1)
        self.assertEqual(diagnostics["metrics"]["knowledge_input"], 1)
        self.assertIn("elapsed_ms", diagnostics["trace"])

    def test_original_metadata_and_input_are_preserved(self):
        memory = [self.memory()]
        knowledge = [self.knowledge()]
        snapshot = copy.deepcopy((memory, knowledge))

        result = run_rag_pipeline_with_fallback(memory, knowledge, enabled=False)
        result["memory_results"][0]["metadata"]["confidence"] = 0.1

        self.assertEqual((memory, knowledge), snapshot)
        self.assertEqual(result["knowledge_results"][0]["metadata"]["custom"], "keep")


if __name__ == "__main__":
    unittest.main()
