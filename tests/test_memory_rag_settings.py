"""Tests for Memory/RAG settings defaults and validation."""

import json
from pathlib import Path
import unittest

from modules.settings_controller import SettingsController


class _SettingsStore:
    def update_many(self, _values, save=False):
        return save


class MemoryRagSettingsTests(unittest.TestCase):
    def test_default_config_enables_alpha_pipeline_with_adaptive_off(self):
        path = Path(__file__).parents[1] / "config" / "default_settings.json"
        config = json.loads(path.read_text(encoding="utf-8"))

        self.assertTrue(config["rag"]["pipeline_enabled"])
        self.assertEqual(config["memory"]["retrieval_threshold"], 0.35)
        self.assertEqual(config["rag"]["context_budget"], 4000)
        self.assertEqual(config["rag"]["memory_ranking_weights"]["relevance"], 0.7)
        self.assertFalse(config["context"]["adaptive_enabled"])

    def test_memory_and_rag_numbers_are_normalized(self):
        controller = SettingsController(_SettingsStore())
        valid, values, errors = controller.validate({
            "memory.retrieval_threshold": "0.4",
            "memory.confidence_default": "0.6",
            "rag.context_budget": "2048",
            "rag.reserved_output": "128",
        })

        self.assertTrue(valid, errors)
        self.assertEqual(values["memory.retrieval_threshold"], 0.4)
        self.assertEqual(values["rag.context_budget"], 2048)

    def test_probability_settings_reject_values_above_one(self):
        controller = SettingsController(_SettingsStore())
        valid, _values, errors = controller.validate({"memory.retrieval_threshold": "1.1"})

        self.assertFalse(valid)
        self.assertIn("Value too large: memory.retrieval_threshold", errors)


if __name__ == "__main__":
    unittest.main()
