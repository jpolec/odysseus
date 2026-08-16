from __future__ import annotations

import json
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from odysseus.runners import ProcessResult
from odysseus.scheduler import ReviewActions, Scheduler
from odysseus.store import RunStore
from odysseus.worktrees import WorktreeManager


def git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


class FakeAgentRunner:
    def __init__(self) -> None:
        self.implementations = 0
        self.reviews = 0

    def run(self, lane, worktree, prompt, *, review, emit, cancelled):  # noqa: ANN001
        if cancelled():
            return ProcessResult(130, "", 0, cancelled=True)
        if review:
            self.reviews += 1
            emit("agent.output", lane, {"text": "No material concerns.", "stream": "stdout"})
            return ProcessResult(0, "No material concerns.", 0.01)
        self.implementations += 1
        (worktree / "result.txt").write_text(f"attempt {self.implementations}\n")
        emit("agent.output", lane, {"text": "Implemented.", "stream": "stdout"})
        return ProcessResult(0, "Implemented.", 0.01)


class FlakyCheckRunner:
    def __init__(self) -> None:
        self.calls = 0

    def run(self, command, worktree, *, emit, cancelled):  # noqa: ANN001
        self.calls += 1
        returncode = 1 if self.calls == 1 else 0
        output = "fail once" if returncode else "ok"
        emit("check.output", "check", {"text": output, "stream": "stdout"})
        return ProcessResult(returncode, output, 0.01)


class BlockingAgentRunner:
    def __init__(self) -> None:
        self.started = threading.Event()

    def run(self, lane, worktree, prompt, *, review, emit, cancelled):  # noqa: ANN001
        self.started.set()
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and not cancelled():
            time.sleep(0.01)
        return ProcessResult(130, "stopped", 0.01, cancelled=True)


class ConflictResolvingAgentRunner:
    def __init__(self) -> None:
        self.implementation_prompt = ""
        self.implementations = 0
        self.reviews = 0

    def run(self, lane, worktree, prompt, *, review, emit, cancelled):  # noqa: ANN001
        if review:
            self.reviews += 1
            return ProcessResult(0, "No material concerns.", 0.01)
        self.implementations += 1
        self.implementation_prompt = prompt
        (worktree / "shared.txt").write_text("resolved\n")
        git(worktree, "add", "shared.txt")
        emit("agent.output", lane, {"text": "Resolved integration conflict.", "stream": "stdout"})
        return ProcessResult(0, "Resolved integration conflict.", 0.01)


class BudgetAgentRunner:
    def run(self, lane, worktree, prompt, *, review, emit, cancelled):  # noqa: ANN001
        emit(
            "agent.usage",
            lane,
            {"input_tokens": 60, "output_tokens": 10, "reasoning_output_tokens": 0},
        )
        stopped = cancelled()
        return ProcessResult(130 if stopped else 0, "budget", 0.01, cancelled=stopped)


class SchedulerTests(unittest.TestCase):
    @staticmethod
    def _repo(root: Path) -> Path:
        repo = root / "repo"
        repo.mkdir()
        git(repo, "init", "-b", "main")
        git(repo, "config", "user.name", "Odysseus Test")
        git(repo, "config", "user.email", "odysseus@example.test")
        (repo / "README.md").write_text("base\n")
        git(repo, "add", "README.md")
        git(repo, "commit", "-m", "base")
        return repo

    @staticmethod
    def _accepted_artifact(
        store: RunStore,
        scheduler: Scheduler,
        actions: ReviewActions,
        repo: Path,
        title: str,
        filename: str,
        *,
        check: str = "",
    ) -> dict:
        run = store.create(
            {
                "title": title,
                "task": f"Create {filename}",
                "project_path": str(repo),
                "status": "review",
                "checks": [check] if check else [],
            }
        )
        info = scheduler.worktrees.create(run, lambda *_: None)
        store.update(run["id"], **info)
        (Path(info["worktree_path"]) / filename).write_text(f"{filename}\n")
        return actions.accept(run["id"])

    def test_agent_check_review_retries_then_waits_for_human(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = self._repo(root)

            store = RunStore(root / "state")
            run = store.create(
                {
                    "task": "Create result.txt",
                    "project_path": str(repo),
                    "checks": ["fake-check"],
                    "max_retries": 2,
                }
            )
            agents = FakeAgentRunner()
            checks = FlakyCheckRunner()
            scheduler = Scheduler(store, agent_runner=agents, check_runner=checks, poll_seconds=0.02)
            scheduler.start()
            try:
                deadline = time.monotonic() + 8
                while time.monotonic() < deadline and store.get(run["id"])["status"] != "review":
                    time.sleep(0.03)
                finished = store.get(run["id"])
            finally:
                scheduler.stop()

            event_types = [event["type"] for event in store.events(run["id"])]
            self.assertEqual(finished["status"], "review")
            self.assertEqual(agents.implementations, 2)
            self.assertEqual(agents.reviews, 1)
            self.assertIn("workflow.retry", event_types)
            self.assertEqual(finished["check_results"][0]["returncode"], 0)

            actions = ReviewActions(store, scheduler)
            sent_back = actions.send_back(run["id"], "Make the output more explicit.")
            self.assertEqual(sent_back["status"], "queued")
            self.assertEqual(sent_back["event_seq"], finished["event_seq"] + 2)
            store.update(run["id"], status="review")
            accepted = actions.accept(run["id"])
            self.assertEqual(accepted["status"], "accepted")
            self.assertEqual(accepted["event_seq"], sent_back["event_seq"] + 3)
            self.assertTrue(accepted["artifact_sha"])
            self.assertEqual(accepted["delivery"]["status"], "not_applied")
            self.assertFalse((repo / "result.txt").exists())
            applied = actions.apply(run["id"])
            self.assertEqual(applied["delivery"]["status"], "applied")
            self.assertEqual((repo / "result.txt").read_text(), "attempt 2\n")
            self.assertIn("delivery.applied", [event["type"] for event in store.events(run["id"])])
            with mock.patch.object(
                WorktreeManager,
                "draft_pr",
                return_value="https://github.com/example/project/pull/1",
            ):
                published = actions.draft_pr(run["id"])
            self.assertEqual(published["status"], "pr_created")
            self.assertEqual(published["pull_request_url"], "https://github.com/example/project/pull/1")
            self.assertEqual(published["delivery"]["status"], "pr_created")

    def test_apply_keeps_single_artifact_delivery_backward_compatible_with_pending_backlog(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = self._repo(root)
            store = RunStore(root / "state")
            scheduler = Scheduler(store, agent_runner=FakeAgentRunner(), check_runner=FlakyCheckRunner())
            actions = ReviewActions(store, scheduler)

            first = self._accepted_artifact(store, scheduler, actions, repo, "Backend", "backend.txt")
            second = self._accepted_artifact(store, scheduler, actions, repo, "Frontend", "frontend.txt")

            result = actions.apply(first["id"])

            self.assertEqual(result["delivery"]["status"], "applied")
            self.assertNotIn("integration_run", result)
            self.assertEqual(store.get(second["id"])["delivery"]["status"], "not_applied")
            queued = [run for run in store.list() if run.get("task_key") == "integration-delivery"]
            self.assertEqual(queued, [])

    def test_integration_delivery_requires_explicit_disposition_for_current_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = self._repo(root)
            store = RunStore(root / "state")
            scheduler = Scheduler(store, agent_runner=FakeAgentRunner(), check_runner=FlakyCheckRunner())
            actions = ReviewActions(store, scheduler)

            accepted = [
                self._accepted_artifact(store, scheduler, actions, repo, "Backend", "backend.txt", check="python3 -m unittest"),
                self._accepted_artifact(store, scheduler, actions, repo, "Frontend", "frontend.txt", check="git diff --check"),
                self._accepted_artifact(store, scheduler, actions, repo, "Docs", "docs.txt"),
            ]
            accepted_ids = [run["id"] for run in accepted]
            preview = actions.integration_candidates(accepted_ids[0])
            candidate_ids = [item["id"] for item in preview["candidates"]]

            self.assertEqual(set(candidate_ids), set(accepted_ids))
            self.assertEqual(
                candidate_ids,
                [item["id"] for item in actions.integration_candidates(accepted_ids[0])["candidates"]],
            )
            with self.assertRaisesRegex(ValueError, "provide one disposition"):
                actions.create_integration_delivery(
                    accepted_ids[0],
                    {"dispositions": {accepted_ids[0]: "integrate_now", accepted_ids[1]: "integrate_now"}},
                )
            with self.assertRaisesRegex(ValueError, "at least two artifacts"):
                actions.create_integration_delivery(
                    accepted_ids[0],
                    {
                        "dispositions": {
                            accepted_ids[0]: {"decision": "integrate_now"},
                            accepted_ids[1]: {"decision": "keep_for_later"},
                            accepted_ids[2]: {"decision": "keep_for_later"},
                        }
                    },
                )
            self.assertTrue(
                all(store.get(run_id)["integration_disposition"]["state"] == "pending" for run_id in accepted_ids)
            )

            result = actions.create_integration_delivery(
                accepted_ids[0],
                {
                    "dispositions": {
                        accepted_ids[0]: {"decision": "integrate_now"},
                        accepted_ids[1]: {"decision": "integrate_now"},
                        accepted_ids[2]: {"decision": "keep_for_later", "reason": "wait for copy review"},
                    }
                },
            )
            integration = result["integration_run"]
            self.assertEqual(integration["status"], "queued")
            self.assertEqual(integration["depends_on"], [run_id for run_id in candidate_ids if run_id in accepted_ids[:2]])
            self.assertEqual(integration["task_key"], "integration-delivery")
            self.assertEqual(integration["checks"], ["python3 -m unittest", "git diff --check"])
            for run_id in accepted_ids[:2]:
                delivery = store.get(run_id)["delivery"]
                self.assertEqual(delivery["status"], "integration_queued")
                self.assertEqual(delivery["integration_run_id"], integration["id"])
                events = [event["type"] for event in store.events(run_id)]
                self.assertIn("integration.disposition_recorded", events)
            self.assertEqual(store.get(accepted_ids[2])["delivery"]["status"], "not_applied")
            self.assertEqual(store.get(accepted_ids[2])["integration_disposition"]["state"], "deferred")

    def test_superseded_and_delivered_artifacts_are_not_candidates_and_remain_inspectable(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = self._repo(root)
            store = RunStore(root / "state")
            scheduler = Scheduler(store, agent_runner=FakeAgentRunner(), check_runner=FlakyCheckRunner())
            actions = ReviewActions(store, scheduler)

            old_ui = self._accepted_artifact(store, scheduler, actions, repo, "Old UI", "ui-old.txt")
            backend = self._accepted_artifact(store, scheduler, actions, repo, "Backend", "backend.txt")
            api = self._accepted_artifact(store, scheduler, actions, repo, "API", "api.txt")
            newer = self._accepted_artifact(store, scheduler, actions, repo, "New UI", "ui-new.txt")

            actions.create_integration_delivery(
                old_ui["id"],
                {
                    "dispositions": {
                        old_ui["id"]: {"decision": "supersede", "superseded_by": newer["id"], "reason": "replaced by newer UI"},
                        backend["id"]: {"decision": "integrate_now"},
                        api["id"]: {"decision": "integrate_now"},
                        newer["id"]: {"decision": "keep_for_later"},
                    }
                },
            )

            superseded = store.get(old_ui["id"])
            self.assertEqual(superseded["status"], "accepted")
            self.assertEqual(superseded["integration_disposition"]["state"], "superseded")
            self.assertEqual(superseded["integration_disposition"]["superseded_by"], newer["id"])
            self.assertEqual(superseded["integration_disposition"]["reason"], "replaced by newer UI")

            preview = actions.integration_candidates(newer["id"])
            candidate_ids = [item["id"] for item in preview["candidates"]]
            self.assertNotIn(old_ui["id"], candidate_ids)
            self.assertNotIn(backend["id"], candidate_ids)
            self.assertNotIn(api["id"], candidate_ids)
            excluded = {item["run_id"]: item["reason"] for item in preview["excluded"]}
            self.assertEqual(excluded[old_ui["id"]], "superseded")
            self.assertEqual(excluded[backend["id"]], "already_delivered")

    def test_delivery_status_matrix_controls_integration_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = self._repo(root)
            store = RunStore(root / "state")
            scheduler = Scheduler(store, agent_runner=FakeAgentRunner(), check_runner=FlakyCheckRunner())
            actions = ReviewActions(store, scheduler)

            anchor = self._accepted_artifact(store, scheduler, actions, repo, "Anchor", "anchor.txt")
            cases = [
                ("Applied", "applied", False),
                ("Draft PR", "pr_created", False),
                ("Integrated applied", "integrated_applied", False),
                ("Integrated PR", "integrated_pr_created", False),
                ("Not applied", "not_applied", True),
                ("Integration queued", "integration_queued", False),
            ]
            expected_eligible = {anchor["id"]}
            expected_excluded: set[str] = set()
            for title, delivery_status, eligible in cases:
                run = self._accepted_artifact(store, scheduler, actions, repo, title, f"{title.lower().replace(' ', '-')}.txt")
                store.update(run["id"], delivery={**run["delivery"], "status": delivery_status})
                if eligible:
                    expected_eligible.add(run["id"])
                else:
                    expected_excluded.add(run["id"])

            preview = actions.integration_candidates(anchor["id"])
            candidate_ids = {item["id"] for item in preview["candidates"]}
            excluded = {item["run_id"]: item["reason"] for item in preview["excluded"]}

            self.assertEqual(expected_eligible, candidate_ids)
            for run_id in expected_excluded:
                self.assertEqual(excluded[run_id], "already_delivered")

    def test_integrated_delivery_statuses_do_not_duplicate_delivery_actions(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = self._repo(root)
            store = RunStore(root / "state")
            scheduler = Scheduler(store, agent_runner=FakeAgentRunner(), check_runner=FlakyCheckRunner())
            actions = ReviewActions(store, scheduler)

            for status in ("integrated_applied", "integrated_pr_created", "integration_queued"):
                run = self._accepted_artifact(store, scheduler, actions, repo, status, f"{status}.txt")
                store.update(run["id"], delivery={**run["delivery"], "status": status})
                before_events = [event["type"] for event in store.events(run["id"])]
                with mock.patch.object(WorktreeManager, "apply_to_repository") as apply_to_repository:
                    applied = actions.apply(run["id"])
                with mock.patch.object(WorktreeManager, "draft_pr") as draft_pr:
                    published = actions.draft_pr(run["id"])

                apply_to_repository.assert_not_called()
                draft_pr.assert_not_called()
                self.assertEqual(applied["delivery"]["status"], status)
                self.assertEqual(published["delivery"]["status"], status)
                self.assertEqual([event["type"] for event in store.events(run["id"])], before_events)

    def test_successful_integration_delivery_fans_out_source_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = self._repo(root)
            store = RunStore(root / "state")
            scheduler = Scheduler(store, agent_runner=FakeAgentRunner(), check_runner=FlakyCheckRunner())
            actions = ReviewActions(store, scheduler)

            backend = self._accepted_artifact(store, scheduler, actions, repo, "Backend", "backend.txt")
            api = self._accepted_artifact(store, scheduler, actions, repo, "API", "api.txt")
            integration = store.create(
                {
                    "title": "Integrate accepted artifacts",
                    "task": "Integrate",
                    "project_path": str(repo),
                    "status": "accepted",
                    "base_ref": "main",
                }
            )
            store.update(
                integration["id"],
                status="accepted",
                integration_sources=[
                    {"run_id": backend["id"], "artifact_sha": backend["artifact_sha"]},
                    {"run_id": api["id"], "artifact_sha": api["artifact_sha"]},
                ],
                integration_head="c" * 40,
                artifact_sha="d" * 40,
            )
            applied = {
                "status": "applied",
                "method": "local_merge",
                "target_branch": "main",
                "target_before_sha": "a" * 40,
                "target_after_sha": "b" * 40,
                "already_applied": False,
                "error": "",
            }
            with mock.patch.object(WorktreeManager, "apply_to_repository", return_value=applied):
                actions.apply(integration["id"])

            for source_id in (backend["id"], api["id"]):
                delivery = store.get(source_id)["delivery"]
                self.assertEqual(delivery["status"], "integrated_applied")
                self.assertEqual(delivery["method"], "integration_delivery")
                self.assertEqual(delivery["integration_run_id"], integration["id"])
                self.assertEqual(delivery["integration_head"], "c" * 40)
                self.assertEqual(delivery["target_after_sha"], "b" * 40)

    def test_existing_accepted_backlog_is_never_silently_folded_into_new_release(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = self._repo(root)
            store = RunStore(root / "state")
            scheduler = Scheduler(store, agent_runner=FakeAgentRunner(), check_runner=FlakyCheckRunner())
            actions = ReviewActions(store, scheduler)

            old_ui = self._accepted_artifact(store, scheduler, actions, repo, "Older UI artifact", "old-ui.txt")
            backend = self._accepted_artifact(store, scheduler, actions, repo, "Release backend", "backend.txt")
            api = self._accepted_artifact(store, scheduler, actions, repo, "Release API", "api.txt")

            result = actions.create_integration_delivery(
                backend["id"],
                {
                    "dispositions": {
                        old_ui["id"]: {"decision": "keep_for_later", "reason": "not part of this release"},
                        backend["id"]: {"decision": "integrate_now"},
                        api["id"]: {"decision": "integrate_now"},
                    }
                },
            )

            self.assertEqual(set(result["integration_run"]["depends_on"]), {backend["id"], api["id"]})
            self.assertNotIn(old_ui["id"], result["integration_run"]["depends_on"])
            self.assertEqual(store.get(old_ui["id"])["delivery"]["status"], "not_applied")
            self.assertEqual(store.get(old_ui["id"])["integration_disposition"]["state"], "deferred")

    def test_dependency_conflict_reaches_integration_agent_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = self._repo(root)
            (repo / "shared.txt").write_text("base\n")
            git(repo, "add", "shared.txt")
            git(repo, "commit", "-m", "add shared")
            store = RunStore(root / "state")
            manager = WorktreeManager(store.worktrees_dir)

            dependency_ids = []
            for title, content in (("Left", "left\n"), ("Right", "right\n")):
                run = store.create({"title": title, "task": title, "project_path": str(repo), "status": "review"})
                info = manager.create(run, lambda *_: None)
                run = store.update(run["id"], **info)
                (Path(info["worktree_path"]) / "shared.txt").write_text(content)
                artifact = manager.snapshot(run)
                store.update(run["id"], **artifact, status="accepted")
                dependency_ids.append(run["id"])

            integration = store.create(
                {
                    "title": "Integration",
                    "task": "Integrate accepted artifacts",
                    "project_path": str(repo),
                    "depends_on": dependency_ids,
                    "max_retries": 0,
                }
            )
            agents = ConflictResolvingAgentRunner()
            scheduler = Scheduler(store, agent_runner=agents, check_runner=FlakyCheckRunner(), poll_seconds=0.02)
            scheduler.start()
            try:
                deadline = time.monotonic() + 8
                while time.monotonic() < deadline and store.get(integration["id"])["status"] != "review":
                    time.sleep(0.03)
                finished = store.get(integration["id"])
            finally:
                scheduler.stop()

            self.assertEqual(finished["status"], "review")
            self.assertEqual(agents.implementations, 1)
            self.assertIn("Dependency artifact integration stopped with Git merge conflicts", agents.implementation_prompt)
            self.assertEqual(finished["integration_conflicts"][0]["conflicts"], ["shared.txt"])
            attention = store.attention.list(status="open", run_id=integration["id"])
            self.assertEqual(len([item for item in attention if item["type"] == "merge_conflict"]), 1)
            conflict_item = next(item for item in attention if item["type"] == "merge_conflict")
            self.assertEqual(conflict_item["data"]["conflicts"], ["shared.txt"])
            self.assertIn("preserved_branches", conflict_item["data"])
            self.assertEqual((Path(finished["worktree_path"]) / "shared.txt").read_text(), "resolved\n")
            self.assertIn("integration.completed", [event["type"] for event in store.events(integration["id"])])

    def test_untrusted_repo_commands_stop_before_agent_until_operator_approval(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = self._repo(root)
            (repo / ".odysseus.json").write_text(json.dumps({"checks": ["touch should-not-run"]}))
            git(repo, "add", ".odysseus.json")
            git(repo, "commit", "-m", "add untrusted config")
            store = RunStore(root / "state")
            run = store.create(
                {
                    "task": "Inspect safely",
                    "project_path": str(repo),
                    "environment": {"profile": "docker", "image": "agent:test"},
                    "untrusted_project": True,
                }
            )
            agents = FakeAgentRunner()
            checks = FlakyCheckRunner()
            scheduler = Scheduler(store, agent_runner=agents, check_runner=checks, poll_seconds=0.01)
            scheduler.environments.prepare = mock.Mock(
                return_value={
                    "version": "environment-plan-v1",
                    "profile": "docker",
                    "image": "agent:test",
                    "status": "ready",
                    "setup": [],
                }
            )
            scheduler.start()
            try:
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline and store.get(run["id"])["status"] != "attention":
                    time.sleep(0.02)
                gated = store.get(run["id"])
            finally:
                scheduler.stop()

            open_items = store.attention.list(status="open", run_id=run["id"])
            self.assertEqual(gated["status"], "attention")
            self.assertEqual(gated["environment"]["trust_status"], "pending")
            self.assertEqual(agents.implementations, 0)
            self.assertEqual(agents.reviews, 0)
            self.assertEqual(checks.calls, 0)
            self.assertEqual(open_items[0]["type"], "permission_request")
            self.assertIn("touch should-not-run", open_items[0]["message"])

            approved = ReviewActions(store, scheduler).answer_attention(open_items[0]["id"], "approve")
            self.assertEqual(approved["run"]["status"], "queued")
            self.assertTrue(approved["run"]["project_commands_approved"])

    def test_scheduler_shutdown_requeues_instead_of_cancelling(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = self._repo(root)
            store = RunStore(root / "state")
            run = store.create({"task": "Wait for shutdown", "project_path": str(repo)})
            agent = BlockingAgentRunner()
            scheduler = Scheduler(store, agent_runner=agent, poll_seconds=0.01)
            scheduler.start()
            self.assertTrue(agent.started.wait(timeout=5))

            scheduler.stop(timeout=5)

            recovered = store.get(run["id"])
            self.assertEqual(recovered["status"], "queued")
            self.assertEqual(store.events(run["id"])[-1]["type"], "system.recovered")

    def test_token_budget_stops_agent_and_creates_operator_attention(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = self._repo(root)
            store = RunStore(root / "state")
            run = store.create(
                {
                    "task": "Stay within budget",
                    "project_path": str(repo),
                    "budgets": {"max_tokens": 50, "stall_seconds": 0},
                }
            )
            scheduler = Scheduler(store, agent_runner=BudgetAgentRunner(), poll_seconds=0.01)
            scheduler.start()
            try:
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline and store.get(run["id"])["status"] != "failed":
                    time.sleep(0.02)
            finally:
                scheduler.stop()

            finished = store.get(run["id"])
            self.assertEqual(finished["budget_status"]["state"], "exceeded")
            self.assertIn("Token budget exceeded", finished["last_error"])
            self.assertEqual(
                store.attention.list(status="open", run_id=run["id"])[0]["type"],
                "budget",
            )

    def test_ignored_review_comment_records_explicit_operator_action(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = self._repo(root)
            store = RunStore(root / "state")
            run = store.create({"task": "Review comment", "project_path": str(repo)})
            store.update(run["id"], status="review")
            item = store.attention.create(
                {
                    "type": "review_comment",
                    "run_id": run["id"],
                    "title": "Review feedback",
                    "message": "Consider renaming this.",
                }
            )

            result = ReviewActions(store, Scheduler(store)).answer_attention(item["id"], "ignore")

            self.assertEqual(result["attention"]["status"], "resolved")
            events = store.events_strict(run["id"])
            self.assertEqual(events[-1]["type"], "attention.answered")
            self.assertEqual(events[-1]["source"], "user")


if __name__ == "__main__":
    unittest.main()
