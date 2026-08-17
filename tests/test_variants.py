from __future__ import annotations

import unittest
from unittest import mock

from odysseus.variants import compare_candidates


def _run(
    run_id: str,
    *,
    confidence: float | None = 0.9,
    cost: float | None = 0.1,
    changed_lines: int = 1,
    files: int = 1,
    status: str = "review",
) -> dict:
    metrics = {"cost_usd": 0.0, "cost_observed": False}
    if cost is not None:
        metrics = {"cost_usd": cost, "cost_observed": True}
    evaluation = {}
    if confidence is not None:
        evaluation = {"confidence": confidence, "eligible": True}
    return {
        "id": run_id,
        "title": run_id,
        "status": status,
        "lane": run_id,
        "metrics": metrics,
        "evaluation": evaluation,
        "check_results": [{"command": "tests", "returncode": 0}],
        "artifact_files": [f"{run_id}-{index}.txt" for index in range(files)],
        "diff_stat": f" {run_id}.txt | {changed_lines} +\n 1 file changed, {changed_lines} insertion(+)\n",
        "started_at": "2026-08-17T10:00:00+00:00",
        "finished_at": "2026-08-17T10:00:10+00:00",
    }


class VariantsParetoTests(unittest.TestCase):
    def _compare(self, *runs: dict) -> dict:
        def diff(run, limit=120_000):  # noqa: ANN001, ARG001
            return {"patch": "", "stat": run.get("diff_stat", ""), "truncated": False, "untracked": []}

        with mock.patch("odysseus.variants.WorktreeManager.diff", side_effect=diff):
            return compare_candidates({"id": "parent"}, list(runs))

    def test_missing_cost_does_not_dominate_observed_cost(self) -> None:
        unknown_cost = _run("unknown-cost", cost=None, changed_lines=1)
        observed_cost = _run("observed-cost", cost=0.25, changed_lines=3)

        comparison = self._compare(unknown_cost, observed_cost)

        self.assertEqual(set(comparison["pareto_frontier"]), {"unknown-cost", "observed-cost"})
        by_id = {item["run_id"]: item for item in comparison["candidates"]}
        self.assertFalse(by_id["unknown-cost"]["metrics"]["cost"]["observed"])
        self.assertIsNone(by_id["unknown-cost"]["metrics"]["cost"]["value"])
        self.assertEqual(by_id["unknown-cost"]["observed_cost"], {"usd": 0.0, "observed": False})

    def test_missing_evidence_does_not_dominate_observed_evidence(self) -> None:
        unknown_evidence = _run("unknown-evidence", confidence=None, changed_lines=1)
        observed_evidence = _run("observed-evidence", confidence=0.45, changed_lines=3)

        comparison = self._compare(unknown_evidence, observed_evidence)

        self.assertEqual(set(comparison["pareto_frontier"]), {"unknown-evidence", "observed-evidence"})
        by_id = {item["run_id"]: item for item in comparison["candidates"]}
        self.assertFalse(by_id["unknown-evidence"]["metrics"]["evidence"]["observed"])
        self.assertIsNone(by_id["unknown-evidence"]["metrics"]["evidence"]["value"])
        self.assertEqual(by_id["unknown-evidence"]["code_quality"]["confidence"], 0.0)

    def test_missing_named_pareto_dimensions_serialize_as_unknown_metrics(self) -> None:
        comparison = self._compare(
            {
                "id": "unknown",
                "title": "unknown",
                "status": "review",
                "metrics": {"cost_usd": 0.0, "cost_observed": False},
                "check_results": [],
                "artifact_files": [],
            }
        )

        metrics = comparison["candidates"][0]["metrics"]
        for name in ("cost", "evidence", "latency", "attention", "risk", "blast_radius", "change_size"):
            with self.subTest(name=name):
                self.assertFalse(metrics[name]["observed"])
                self.assertIsNone(metrics[name]["value"])
                self.assertIsInstance(metrics[name]["source"], str)
                self.assertIsNone(metrics[name]["lower"])
                self.assertIsNone(metrics[name]["upper"])

    def test_observed_comparable_metrics_can_still_select_frontier(self) -> None:
        better = _run("better", confidence=0.95, cost=0.05, changed_lines=1)
        worse = _run("worse", confidence=0.9, cost=0.25, changed_lines=4)

        comparison = self._compare(better, worse)

        self.assertEqual(comparison["pareto_frontier"], ["better"])
        metric = comparison["candidates"][0]["metrics"]["cost"]
        self.assertEqual(
            set(metric),
            {"type", "value", "observed", "source", "lower", "upper"},
        )
        self.assertEqual(metric["type"], "number")
        self.assertIsNone(metric["lower"])
        self.assertIsNone(metric["upper"])


if __name__ == "__main__":
    unittest.main()
