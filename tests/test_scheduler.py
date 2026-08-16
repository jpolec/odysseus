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

    def test_apply_queues_pending_accepted_artifacts_for_integration_delivery(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = self._repo(root)
            store = RunStore(root / "state")
            scheduler = Scheduler(store, agent_runner=FakeAgentRunner(), check_runner=FlakyCheckRunner())
            actions = ReviewActions(store, scheduler)

            accepted_ids = []
            for title, filename, check in (
                ("Backend", "backend.txt", "python3 -m unittest"),
                ("Frontend", "frontend.txt", "git diff --check"),
            ):
                run = store.create(
                    {
                        "title": title,
                        "task": f"Create {filename}",
                        "project_path": str(repo),
                        "status": "review",
                        "checks": [check],
                    }
                )
                info = scheduler.worktrees.create(run, lambda *_: None)
                store.update(run["id"], **info)
                (Path(info["worktree_path"]) / filename).write_text(f"{filename}\n")
                accepted = actions.accept(run["id"])
                accepted_ids.append(accepted["id"])

            result = actions.apply(accepted_ids[0])
            integration = result["integration_run"]
            self.assertEqual(integration["status"], "queued")
            self.assertEqual(integration["depends_on"], accepted_ids)
            self.assertEqual(integration["task_key"], "integration-delivery")
            self.assertEqual(integration["checks"], ["python3 -m unittest", "git diff --check"])
            for run_id in accepted_ids:
                delivery = store.get(run_id)["delivery"]
                self.assertEqual(delivery["status"], "integration_queued")
                self.assertEqual(delivery["integration_run_id"], integration["id"])

            repeated = actions.apply(accepted_ids[1])
            self.assertNotIn("integration_run", repeated)
            queued = [run for run in store.list() if run.get("task_key") == "integration-delivery"]
            self.assertEqual(len(queued), 1)

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
