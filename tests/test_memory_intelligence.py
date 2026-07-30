"""Unit tests for the Memory Intelligence core module."""

import unittest
from pathlib import Path

from modules.memory_intelligence import (
    MemoryIntelligence,
    analyze_memory_candidates,
)


class MemoryIntelligenceTests(unittest.TestCase):
    def test_normal_candidate_analysis(self):
        candidates = analyze_memory_candidates(
            "I prefer concise release summaries.",
            base_candidates=[
                {
                    "type": "preference",
                    "content": "User prefers concise release summaries.",
                    "score": 0.86,
                    "source": "rule",
                }
            ],
        )

        self.assertEqual(len(candidates), 1)
        candidate = candidates[0]
        self.assertEqual(candidate["type"], "preference")
        self.assertEqual(candidate["category"], "communication_style")
        self.assertGreaterEqual(candidate["confidence"], 0.8)
        self.assertIn(candidate["importance"], {"normal", "high"})
        self.assertEqual(candidate["risk"]["level"], "low")
        self.assertIsInstance(candidate["explanation"], str)

    def test_empty_input_returns_empty_list(self):
        self.assertEqual(MemoryIntelligence().analyze(""), [])
        self.assertEqual(MemoryIntelligence().analyze([], base_candidates=[]), [])

    def test_sensitive_information_is_high_risk(self):
        candidates = analyze_memory_candidates(
            "remember my api key",
            base_candidates=[
                {
                    "type": "instruction",
                    "content": "Remember that my api key is secret-token-123",
                    "score": 0.9,
                }
            ],
        )

        candidate = candidates[0]
        self.assertEqual(candidate["risk"]["level"], "high")
        self.assertIn("sensitive_information", candidate["risk"]["reasons"])
        self.assertTrue(candidate["blocked"])
        self.assertLessEqual(candidate["importance_score"], 2.0)

    def test_temporary_information_is_medium_risk(self):
        candidates = analyze_memory_candidates(
            "remember this for today",
            base_candidates=[
                {
                    "type": "instruction",
                    "content": "Remember this setting for today only.",
                    "score": 0.88,
                }
            ],
        )

        candidate = candidates[0]
        self.assertEqual(candidate["risk"]["level"], "medium")
        self.assertIn("temporary_information", candidate["risk"]["reasons"])
        self.assertLess(candidate["confidence"], 0.88)

    def test_low_confidence_candidate_stays_low_importance(self):
        candidates = analyze_memory_candidates(
            "maybe try this",
            base_candidates=[
                {
                    "type": "fact",
                    "content": "Maybe try this test setting.",
                    "score": 0.2,
                }
            ],
        )

        candidate = candidates[0]
        self.assertLess(candidate["confidence"], 0.2)
        self.assertEqual(candidate["importance"], "low")
        self.assertIn("low_quality_signal", candidate["risk"]["reasons"])

    def test_legacy_candidate_shape_is_preserved(self):
        legacy = {
            "type": "fact",
            "content": "User works on Project Aurora.",
            "score": 0.78,
            "custom_field": "keep-me",
        }

        candidates = analyze_memory_candidates("", base_candidates=[legacy])

        candidate = candidates[0]
        self.assertEqual(candidate["type"], "fact")
        self.assertEqual(candidate["content"], legacy["content"])
        self.assertEqual(candidate["score"], legacy["score"])
        self.assertEqual(candidate["custom_field"], "keep-me")
        self.assertIn("category", candidate)
        self.assertIn("confidence", candidate)
        self.assertIn("risk", candidate)

    def test_module_does_not_write_memory_files(self):
        root = Path(__file__).resolve().parent.parent
        targets = [
            root / "data" / "memory" / "memories.json",
            root / "data" / "memory" / "memory_candidates.json",
        ]
        before = {
            path: path.read_bytes() if path.exists() else None
            for path in targets
        }

        analyze_memory_candidates(
            "Please remember that I prefer short answers.",
            base_candidates=[
                {
                    "type": "preference",
                    "content": "User prefers short answers.",
                    "score": 0.86,
                }
            ],
        )

        after = {
            path: path.read_bytes() if path.exists() else None
            for path in targets
        }
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
