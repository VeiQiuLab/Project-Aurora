"""Tests for the independent diagnostics foundation."""

import copy
import json
import unittest

from modules.diagnostics import Diagnostics, create_diagnostics


class DiagnosticsTests(unittest.TestCase):
    def test_default_diagnostics_creation(self):
        result = create_diagnostics()

        self.assertEqual(
            result,
            {
                "stage": "",
                "success": True,
                "reason": "",
                "warnings": [],
                "metrics": {},
                "trace": {},
            },
        )

    def test_custom_stage_name(self):
        result = create_diagnostics(stage="memory_analysis")

        self.assertEqual(result["stage"], "memory_analysis")

    def test_success_and_failure_states(self):
        self.assertTrue(create_diagnostics(success=True)["success"])
        failure = create_diagnostics(success=False, reason="analysis failed")

        self.assertFalse(failure["success"])
        self.assertEqual(failure["reason"], "analysis failed")

    def test_warnings_list_preserved(self):
        result = create_diagnostics(warnings=["low confidence", "stale source"])

        self.assertEqual(result["warnings"], ["low confidence", "stale source"])

    def test_metrics_preserved(self):
        result = create_diagnostics(metrics={"input_count": 20, "output_count": 5})

        self.assertEqual(result["metrics"], {"input_count": 20, "output_count": 5})

    def test_trace_preserved(self):
        result = create_diagnostics(trace={"source": "test", "request_id": "r-1"})

        self.assertEqual(result["trace"], {"source": "test", "request_id": "r-1"})

    def test_serialization_compatibility(self):
        result = Diagnostics.create(
            stage="ranking",
            metrics={"input_count": 2},
            trace={"method": "weighted"},
        )

        serialized = json.dumps(result, ensure_ascii=False)
        self.assertIsInstance(serialized, str)
        self.assertEqual(json.loads(serialized), result)

    def test_input_does_not_mutate(self):
        warnings = ["warning"]
        metrics = {"counts": {"input": 1}}
        trace = {"details": {"source": "test"}}
        snapshot = copy.deepcopy((warnings, metrics, trace))

        result = create_diagnostics(warnings=warnings, metrics=metrics, trace=trace)
        result["warnings"].append("changed")
        result["metrics"]["counts"]["input"] = 2
        result["trace"]["details"]["source"] = "changed"

        self.assertEqual((warnings, metrics, trace), snapshot)


if __name__ == "__main__":
    unittest.main()
