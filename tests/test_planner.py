from __future__ import annotations

import hashlib
import tempfile
import unittest
from unittest import mock
from pathlib import Path

from odysseus.planner import EpicPlanner, PlanningFailed
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


class FailingPlannerRunner:
    def run(self, lane, worktree, prompt, **kwargs):  # noqa: ANN001
        return ProcessResult(1, "planner failed before returning a task graph", 0.1, session_id="failed-planner-thread")


class CompatibilityFallbackPlannerRunner:
    def __init__(self) -> None:
        self.lanes = []

    def run(self, lane, worktree, prompt, **kwargs):  # noqa: ANN001
        self.lanes.append(lane)
        if lane == "codex":
            return ProcessResult(1, "The selected model requires a newer version of Codex.", 0.1)
        return ProcessResult(
            0,
            'ODYSSEUS_PLAN: {"summary":"Recovered","tasks":['
            '{"task_key":"implement","title":"Implement","task":"Implement the ADR","depends_on":[]}]}',
            0.1,
            session_id="fallback-planner-thread",
        )


class VerbosePlannerRunner:
    def run(self, lane, worktree, prompt, **kwargs):  # noqa: ANN001
        kwargs["emit"](
            "agent.message",
            lane,
            {
                "text": 'ODYSSEUS_PLAN: {"summary":"Recovered from final message","tasks":['
                '{"task_key":"docs","title":"Docs","task":"Update docs","depends_on":[]}]}',
            },
        )
        return ProcessResult(
            0,
            'Earlier bounded output mentioning ODYSSEUS_PLAN: {"summary":',
            301.0,
            session_id="verbose-planner-thread",
        )


class PlannerTests(unittest.TestCase):
    def test_final_agent_message_survives_a_truncated_raw_planner_buffer(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / "project"
            project.mkdir()
            store = RunStore(root / "state")

            proposal = EpicPlanner(store, agent_runner=VerbosePlannerRunner()).plan(
                "Create a documentation plan",
                project,
                lane="claude",
            )

            self.assertEqual(proposal["status"], "proposed")
            self.assertEqual(proposal["plan"]["summary"], "Recovered from final message")
            self.assertEqual(proposal["planner_progress"]["state"], "draft_ready")

    def test_failed_attempt_can_recover_a_returned_draft_without_another_agent_run(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / "project"
            project.mkdir()
            store = RunStore(root / "state")
            failed = store.epics.create(
                {
                    "title": "Recover me",
                    "description": "Create docs",
                    "project_path": str(project),
                    "status": "planning_failed",
                }
            )
            store.epics.update(
                failed["id"],
                planner_error="raw output was truncated",
                planner_events=[
                    {
                        "type": "agent.message",
                        "source": "claude",
                        "data": {
                            "text": 'ODYSSEUS_PLAN: {"summary":"Recovered","tasks":['
                            '{"task_key":"docs","title":"Docs","task":"Update docs","depends_on":[]}]}',
                        },
                    }
                ],
            )
            planner = EpicPlanner(store, agent_runner=FailingPlannerRunner())

            recovered = planner.recover(failed["id"])

            self.assertEqual(recovered["status"], "proposed")
            self.assertEqual(recovered["plan"]["summary"], "Recovered")
            self.assertEqual(recovered["planner_progress"]["state"], "draft_recovered")
            self.assertEqual(len(recovered["planner_events"]), 1)

    def test_incompatible_planner_runtime_falls_back_to_an_installed_independent_lane(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / "project"
            project.mkdir()
            store = RunStore(root / "state")
            runner = CompatibilityFallbackPlannerRunner()
            planner = EpicPlanner(store, agent_runner=runner)

            with mock.patch("odysseus.planner.shutil.which", side_effect=lambda command: f"/bin/{command}" if command == "claude" else None):
                proposal = planner.plan("Implement the ADR", project, lane="codex")

            self.assertEqual(runner.lanes, ["codex", "claude"])
            self.assertEqual(proposal["status"], "proposed")
            self.assertEqual(proposal["planner_lane"], "claude")
            self.assertEqual(proposal["planner_requested_lane"], "codex")
            self.assertEqual(proposal["planner_fallback"]["reason"], "runtime_compatibility")
            self.assertIn("planner.route_fallback", {event["type"] for event in proposal["planner_events"]})

    def test_ordinary_planner_failure_is_not_hidden_by_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / "project"
            project.mkdir()
            store = RunStore(root / "state")
            runner = FailingPlannerRunner()
            planner = EpicPlanner(store, agent_runner=runner)

            with mock.patch("odysseus.planner.shutil.which", return_value="/bin/claude"):
                with self.assertRaises(PlanningFailed):
                    planner.plan("Implement the ADR", project, lane="codex")
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
                source_documents=[
                    {
                        "kind": "adr",
                        "path": "_ADR/0001-auth.md",
                        "title": "Authentication",
                        "status": "accepted",
                        "sha256": "abc123",
                        "bytes": 42,
                        "content": "# Authentication\n\nUse passkeys.",
                    }
                ],
            )

            self.assertEqual(proposal["status"], "proposed")
            self.assertEqual(proposal["plan_version"]["number"], 1)
            self.assertTrue(proposal["plan_version"]["sha256"])
            self.assertIn("read-only Planner role", runner.prompt)
            self.assertIn("_ADR/0001-auth.md", runner.prompt)
            self.assertIn("Use passkeys", runner.prompt)
            self.assertIn("[S1]", runner.prompt)
            self.assertIn("acceptance_criteria", runner.prompt)
            frozen = "# Authentication\n\nUse passkeys.".encode()
            self.assertEqual(proposal["source_documents"][0]["sha256"], hashlib.sha256(frozen).hexdigest())
            self.assertEqual(proposal["source_documents"][0]["bytes"], len(frozen))
            approved = planner.approve(proposal["id"])
            runs = {run["task_key"]: run for run in store.list()}
            self.assertEqual(approved["status"], "active")
            self.assertEqual(runs["schema"]["status"], "queued")
            self.assertEqual(runs["api"]["status"], "blocked")
            self.assertEqual(runs["api"]["depends_on"], [runs["schema"]["id"]])
            self.assertEqual(runs["schema"]["lane"], "codex")
            self.assertEqual(runs["schema"]["review_lane"], "claude")
            self.assertIn("architecture_decision", {item["kind"] for item in runs["schema"]["context_bundle"]})

    def test_invalid_or_unmarked_plan_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "ODYSSEUS_PLAN"):
            EpicPlanner.parse_proposal(
                ProcessResult(0, "plain text", 0.1),
                project_path="/tmp/project",
                default_lane="codex",
                default_review_lane="claude",
                default_checks=[],
            )

    def test_failed_planning_attempt_preserves_sources_and_can_be_repaired_manually(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / "project"
            project.mkdir()
            store = RunStore(root / "state")
            planner = EpicPlanner(store, agent_runner=FailingPlannerRunner())

            with self.assertRaises(PlanningFailed) as caught:
                planner.plan(
                    "Implement the decision",
                    project,
                    source_documents=[{"kind": "adr", "path": "ADR/0001.md", "title": "Decision", "content": "# Decision\n\nKeep the API stable."}],
                )

            failed = store.epics.get(caught.exception.epic_id)
            self.assertEqual(failed["status"], "planning_failed")
            self.assertEqual(failed["planner_session_id"], "failed-planner-thread")
            self.assertIn("Keep the API stable", failed["source_documents"][0]["content"])
            repaired = store.epics.save_plan(
                failed["id"],
                {
                    "summary": "Manual recovery draft",
                    "tasks": [
                        {
                            "task_key": "implement",
                            "title": "Implement decision",
                            "task": "Implement the frozen ADR without changing the public API.",
                            "outcome": "The ADR is implemented and the public API remains compatible.",
                            "depends_on": [],
                        }
                    ],
                },
            )
            self.assertEqual(repaired["status"], "proposed")
            self.assertEqual(len(repaired["plan"]["tasks"]), 1)


if __name__ == "__main__":
    unittest.main()
