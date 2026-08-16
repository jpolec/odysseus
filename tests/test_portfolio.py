from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from odysseus.portfolio import engineering_portfolio
from odysseus.store import RunStore


def _iso(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


class PortfolioTests(unittest.TestCase):
    def test_windowed_metrics_keep_unknown_cost_and_sample_size_honest(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / "repo"
            project.mkdir()
            store = RunStore(root / "state")
            now = datetime.now(timezone.utc)

            delivered = store.create({"task": "Ship", "project_path": str(project), "lane": "codex"})
            store.update(
                delivered["id"],
                status="accepted",
                started_at=_iso(now - timedelta(minutes=12)),
                finished_at=_iso(now - timedelta(minutes=2)),
                delivery={"status": "applied"},
            )
            failed = store.create({"task": "Fail", "project_path": str(project), "lane": "claude"})
            store.update(
                failed["id"],
                status="failed",
                started_at=_iso(now - timedelta(minutes=5)),
                finished_at=_iso(now - timedelta(minutes=1)),
                last_error="GitHub CI failed",
            )

            result = engineering_portfolio(store, days=7)

            self.assertEqual(result["metrics"]["tasks_started"], 2)
            self.assertEqual(result["metrics"]["terminal_started"], 2)
            self.assertEqual(result["metrics"]["delivered"], 1)
            self.assertIsNone(result["metrics"]["median_cost_per_delivery_usd"])
            self.assertEqual(result["metrics"]["cost_coverage_deliveries"], 0)
            self.assertIsNone(result["metrics"]["engineer_hours_saved"])
            self.assertEqual(result["failures"], [{"reason": "CI failure", "count": 1}])
            self.assertEqual({row["agent"] for row in result["agents"]}, {"codex", "claude"})

    def test_corrective_operator_action_breaks_autonomous_delivery(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / "repo"
            project.mkdir()
            store = RunStore(root / "state")
            now = datetime.now(timezone.utc)
            run = store.create({"task": "Repair", "project_path": str(project)})
            store.append_event(run["id"], "review.sent_back", "user", {"feedback": "Fix regression"})
            store.update(
                run["id"],
                status="accepted",
                started_at=_iso(now - timedelta(minutes=8)),
                finished_at=_iso(now),
                delivery={"status": "applied"},
            )

            result = engineering_portfolio(store, days=7)

            self.assertEqual(result["metrics"]["autonomous_delivery_rate"], 0.0)
            self.assertEqual(result["metrics"]["first_pass_success_rate"], 0.0)
            self.assertEqual(result["metrics"]["human_interventions"], 1)


if __name__ == "__main__":
    unittest.main()
