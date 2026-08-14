from __future__ import annotations

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
            with mock.patch.object(
                WorktreeManager,
                "draft_pr",
                return_value="https://github.com/example/project/pull/1",
            ):
                published = actions.draft_pr(run["id"])
            self.assertEqual(published["status"], "pr_created")
            self.assertEqual(published["pull_request_url"], "https://github.com/example/project/pull/1")

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


if __name__ == "__main__":
    unittest.main()
