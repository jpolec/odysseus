from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from odysseus.planner import EpicPlanner
from odysseus.runners import ProcessResult
from odysseus.store import RunStore


class FakePlannerRunner:
    def run(self, lane, worktree, prompt, **kwargs):  # noqa: ANN001
        self.lane = lane
        self.worktree = worktree
        self.prompt = prompt
        return ProcessResult(
            0,
            'Inspected architecture.\nODYSSEUS_PLAN: {"summary":"Auth epic","tasks":['
            '{"task_key":"schema","title":"Schema","task":"Add schema","depends_on":[]},'
            '{"task_key":"api","title":"API","task":"Add API","depends_on":["schema"]}]}'
            ,
            0.1,
            session_id="planner-thread",
        )


class PlannerTests(unittest.TestCase):
    def test_planner_is_read_only_and_approval_materializes_blocked_dag(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / "project"
            project.mkdir()
            store = RunStore(root / "state")
            runner = FakePlannerRunner()
            planner = EpicPlanner(store, agent_runner=runner)

            proposal = planner.plan(
                "Implement authentication",
                project,
                lane="claude",
                default_task_lane="codex",
                default_review_lane="claude",
                checks=["python3 -m unittest"],
            )

            self.assertEqual(proposal["status"], "proposed")
            self.assertIn("read-only Planner role", runner.prompt)
            approved = planner.approve(proposal["id"])
            runs = {run["task_key"]: run for run in store.list()}
            self.assertEqual(approved["status"], "active")
            self.assertEqual(runs["schema"]["status"], "queued")
            self.assertEqual(runs["api"]["status"], "blocked")
            self.assertEqual(runs["api"]["depends_on"], [runs["schema"]["id"]])
            self.assertEqual(runs["schema"]["lane"], "codex")
            self.assertEqual(runs["schema"]["review_lane"], "claude")

    def test_invalid_or_unmarked_plan_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "ODYSSEUS_PLAN"):
            EpicPlanner.parse_proposal(
                ProcessResult(0, "plain text", 0.1),
                project_path="/tmp/project",
                default_lane="codex",
                default_review_lane="claude",
                default_checks=[],
            )


if __name__ == "__main__":
    unittest.main()
