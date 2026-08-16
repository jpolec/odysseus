from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from odysseus.economics import economics_csv, economics_ndjson, outcome_economics
from odysseus.store import RunStore


class OutcomeEconomicsTests(unittest.TestCase):
    def _store(self) -> tuple[tempfile.TemporaryDirectory[str], RunStore, Path]:
        temp = tempfile.TemporaryDirectory()
        root = Path(temp.name)
        project = root / "project"
        project.mkdir()
        return temp, RunStore(root / "state"), project

    def test_aggregates_by_outcome_phase_and_receipt_without_zeroing_unknown_cost(self) -> None:
        temp, store, project = self._store()
        with temp:
            accepted = store.create({"title": "Accepted billing fix", "task": "Fix billing", "project_path": str(project)})
            store.append_event(accepted["id"], "run.started", "odysseus", {})
            store.append_event(accepted["id"], "agent.usage", "codex", {"phase": "agent", "input_tokens": 100, "cached_input_tokens": 40, "output_tokens": 30})
            store.append_event(accepted["id"], "agent.usage", "claude", {"phase": "review", "input_tokens": 50, "output_tokens": 10})
            store.append_event(accepted["id"], "agent.cost", "codex", {"phase": "agent", "cost_usd": 1.25})
            store.append_event(accepted["id"], "check.completed", "check", {"returncode": 0, "duration_seconds": 12.5})
            store.append_event(accepted["id"], "artifact.created", "git", {"artifact_sha": "abc"})
            store.update(accepted["id"], status="accepted", artifact_sha="abc")
            store.append_event(accepted["id"], "review.accepted", "user", {})
            store.append_event(accepted["id"], "run.accepted", "odysseus", {})

            delivered = store.create({"title": "Delivered API", "task": "Ship API", "project_path": str(project), "status": "accepted"})
            store.append_event(delivered["id"], "run.started", "odysseus", {})
            store.append_event(delivered["id"], "agent.usage", "codex", {"phase": "agent", "input_tokens": 20, "output_tokens": 5, "resumed": True})
            store.append_event(delivered["id"], "workflow.retry", "odysseus", {"attempt": 1})
            store.append_event(delivered["id"], "agent.cost", "codex", {"cost_usd": 0.75})
            store.update(delivered["id"], delivery={**delivered["delivery"], "status": "applied"})

            unknown = store.create({"title": "Unknown cost", "task": "No price", "project_path": str(project), "status": "accepted"})
            store.append_event(unknown["id"], "run.started", "odysseus", {})
            store.append_event(unknown["id"], "agent.usage", "codex", {"phase": "ci_repair", "input_tokens": 7, "output_tokens": 3})

            result = outcome_economics(store, minimum_runs=2)
            totals = result["totals"]

            self.assertEqual(totals["accepted_changes"], 3)
            self.assertEqual(totals["delivered_changes"], 1)
            self.assertEqual(totals["tokens"]["implementer"]["total_tokens"], 130)
            self.assertEqual(totals["tokens"]["reviewer"]["total_tokens"], 60)
            self.assertEqual(totals["tokens"]["ci_repair"]["total_tokens"], 10)
            self.assertEqual(totals["tokens"]["retry"]["total_tokens"], 25)
            self.assertEqual(totals["observed_model_cost_usd"], 2.0)
            self.assertIsNone(totals["cost_per_accepted_change_usd"])
            self.assertEqual(totals["cost_per_delivered_change_usd"], 0.75)
            self.assertEqual(totals["tests_check_compute_duration_seconds"], 12.5)
            self.assertGreaterEqual(result["sample"]["sample_size"], 3)
            self.assertIsNone(result["expected_cost_per_successful_change_usd"])
            self.assertTrue(all(row["receipt_id"] for row in result["lead_view"]))
            self.assertTrue(result["metric_receipts"]["accepted_changes"])
            self.assertTrue(result["metric_receipts"]["tokens.implementer.total_tokens"])
            self.assertTrue(result["metric_receipts"]["tests_check_compute_duration_seconds"])
            self.assertTrue(all(row["task"].startswith("Task ") for row in result["lead_view"]))
            full = outcome_economics(store, minimum_runs=2, privacy="full")
            self.assertIn("Accepted billing fix", {row["task"] for row in full["lead_view"]})
            self.assertIn("receipt_id", economics_csv(result))
            self.assertIn(delivered["id"], economics_ndjson(result, view="operator"))

    def test_expected_cost_uses_terminal_attempt_cost_over_acceptance_rate(self) -> None:
        temp, store, project = self._store()
        with temp:
            for index, status in enumerate(("accepted", "failed"), 1):
                run = store.create({"title": f"Run {index}", "task": f"Run {index}", "project_path": str(project), "status": status})
                store.append_event(run["id"], "run.started", "odysseus", {})
                store.append_event(run["id"], "agent.cost", "codex", {"cost_usd": 2.0})

            result = outcome_economics(store, minimum_runs=2)

            self.assertEqual(result["totals"]["acceptance_rate"], 0.5)
            self.assertEqual(result["expected_cost_per_successful_change_usd"], 4.0)
            self.assertTrue(result["sample"]["sufficient"])


if __name__ == "__main__":
    unittest.main()
