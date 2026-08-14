from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from odysseus.ci import CIWatcher
from odysseus.store import RunStore


class FakeBridge:
    def __init__(self, values):  # noqa: ANN001
        self.values = list(values)

    def checks(self, _url, _path):  # noqa: ANN001
        return self.values.pop(0)


class FakeActions:
    def __init__(self, store: RunStore) -> None:
        self.store = store
        self.prompts: list[str] = []

    def resume(self, run_id: str, prompt: str):  # noqa: ANN201
        self.prompts.append(prompt)
        return self.store.update(run_id, status="queued")


class CIWatcherTests(unittest.TestCase):
    def test_failed_ci_resumes_original_run_then_records_green(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / "project"
            project.mkdir()
            store = RunStore(root / "state")
            store.update_config({"ci": {"watch": True, "auto_resume": True, "max_attempts": 2, "poll_seconds": 5}})
            run = store.create({"task": "Repair CI", "project_path": str(project)})
            store.update(run["id"], status="pr_created", pull_request_url="https://github.com/acme/repo/pull/1")
            actions = FakeActions(store)
            bridge = FakeBridge(
                [
                    {"status": "failed", "checks": [{"name": "tests", "bucket": "fail"}], "summary": "1 failed", "logs": "AssertionError"},
                    {"status": "passed", "checks": [{"name": "tests", "bucket": "pass"}], "summary": "1 passed", "logs": ""},
                ]
            )
            watcher = CIWatcher(store, actions, bridge=bridge, poll_seconds=5)

            watcher.poll_once(force=True)

            repairing = store.get(run["id"])
            self.assertEqual(repairing["status"], "queued")
            self.assertTrue(repairing["ci_retry_active"])
            self.assertIn("AssertionError", actions.prompts[0])
            store.update(run["id"], status="pr_created", ci_retry_active=False)
            watcher.poll_once(force=True)
            finished = store.get(run["id"])
            self.assertEqual(finished["ci"]["status"], "passed")
            self.assertIn("ci.retry_queued", [event["type"] for event in store.events(run["id"])])
            self.assertIn("ci.passed", [event["type"] for event in store.events(run["id"])])


if __name__ == "__main__":
    unittest.main()
