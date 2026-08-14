from __future__ import annotations

import unittest

from odysseus.evaluation import EvaluationEngine, parse_review_evaluation


class EvaluationTests(unittest.TestCase):
    def test_structured_review_and_independent_lane_produce_explainable_confidence(self) -> None:
        run = {"lane": "codex", "review_lane": "claude"}
        summary = 'Everything is covered.\nODYSSEUS_EVALUATION: {"score": 0.95, "verdict": "pass", "findings": []}'

        result = EvaluationEngine.evaluate(
            run,
            [{"command": "tests", "returncode": 0}],
            summary,
        )

        self.assertGreaterEqual(result["confidence"], 0.9)
        self.assertTrue(result["eligible"])
        self.assertTrue(result["human_review_required"])
        self.assertEqual(result["decision"], "human_review")

    def test_required_verifier_and_failed_command_prevent_eligibility(self) -> None:
        result = EvaluationEngine.evaluate(
            {"lane": "codex", "review_lane": "codex"},
            [{"command": "tests", "returncode": 0}],
            "No material concerns.",
            verifier_results=[{"id": "security", "returncode": 1, "weight": 0.4}],
            policy={"required_evaluators": ["security", "browser"], "require_human_review": False},
        )

        self.assertFalse(result["eligible"])
        self.assertIn("security", result["failing_evaluators"])
        self.assertEqual(result["missing_evaluators"], ["browser"])
        self.assertTrue(result["human_review_required"])

    def test_unstructured_review_fallback_is_conservative(self) -> None:
        parsed = parse_review_evaluation("The implementation needs more investigation.")
        self.assertFalse(parsed["structured"])
        self.assertEqual(parsed["verdict"], "needs_review")


if __name__ == "__main__":
    unittest.main()
