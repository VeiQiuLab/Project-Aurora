"""In-memory smoke test for the C5 module chain."""

import unittest

from modules.context_optimizer import optimize_context
from modules.conversation_intelligence import analyze_conversation
from modules.memory_intelligence import analyze_memory_candidates
from modules.rag_ranker import rank_results
from modules.rag_results import deduplicate_results, normalize_results


class CoreIntegrationTests(unittest.TestCase):
    def test_c5_core_flow_uses_only_in_memory_objects(self):
        messages = [{
            "role": "user",
            "content": "I like local AI projects",
        }]
        conversation = analyze_conversation(messages)
        self.assertTrue(conversation["analysis_version"])
        self.assertIn("summary", conversation)

        candidates = analyze_memory_candidates(
            messages,
            base_candidates=[{
                "type": "preference",
                "content": "User likes local AI projects.",
                "score": 0.9,
            }],
        )
        self.assertEqual(len(candidates), 1)
        self.assertIn("confidence", candidates[0])
        self.assertIn("risk", candidates[0])

        raw_results = [
            {
                "id": "doc-1",
                "content": "Local AI project guide",
                "score": 0.8,
                "source": {"kind": "knowledge", "file_name": "guide.md"},
                "score_details": {"vector": 0.8},
            },
            {
                "id": "mem-1",
                "content": "User likes local AI projects.",
                "source": {"kind": "memory"},
                "metadata": {"importance": "high", "confidence": 0.9},
            },
        ]
        normalized = normalize_results(raw_results)
        deduplicated = deduplicate_results(normalized)
        ranked = rank_results(deduplicated)
        optimized = optimize_context(
            [
                {
                    "name": "Knowledge",
                    "enabled": True,
                    "content": ranked[0]["content"],
                    "source": ranked[0]["source"],
                },
                {
                    "name": "Memory",
                    "enabled": True,
                    "content": ranked[-1]["content"],
                    "source": ranked[-1]["source"],
                },
            ],
            max_tokens=80,
        )

        self.assertEqual(len(optimized["sections"]), 2)
        self.assertIn("diagnostics", optimized)
        self.assertLessEqual(
            optimized["diagnostics"]["used_tokens"],
            optimized["diagnostics"]["max_tokens"],
        )


if __name__ == "__main__":
    unittest.main()
