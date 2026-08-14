from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from odysseus.store import RunStore


class StoreTests(unittest.TestCase):
    def test_run_and_events_are_durable_json_and_ndjson(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / "project"
            project.mkdir()
            store = RunStore(root / "state")
            run = store.create({"task": "Build the thing", "project_path": str(project)})
            store.append_event(run["id"], "step.started", "odysseus", {"step": "agent"})

            persisted = json.loads((store.runs_dir / f"{run['id']}.json").read_text())
            lines = (store.events_dir / f"{run['id']}.ndjson").read_text().splitlines()
            events = [json.loads(line) for line in lines]

            self.assertEqual(persisted["event_seq"], 2)
            self.assertEqual([event["seq"] for event in events], [1, 2])
            self.assertEqual(events[0]["type"], "run.queued")

    def test_persistent_config_updates_concurrency(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            store = RunStore(Path(temp) / "state")
            config = store.update_config({"max_parallel": 4})
            self.assertEqual(config["max_parallel"], 4)
            self.assertEqual(RunStore(store.root).config()["max_parallel"], 4)

    def test_claim_enforces_global_parallel_limit(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / "project"
            project.mkdir()
            store = RunStore(root / "state")
            first = store.create({"task": "First", "project_path": str(project)})
            second = store.create({"task": "Second", "project_path": str(project)})

            self.assertIsNotNone(store.claim(first["id"], max_parallel=1))
            self.assertIsNone(store.claim(second["id"], max_parallel=1))

    def test_queued_run_can_be_cancelled_without_a_worker(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / "project"
            project.mkdir()
            store = RunStore(root / "state")
            run = store.create({"task": "Cancel me", "project_path": str(project)})

            cancelled = store.request_cancel(run["id"])

            self.assertEqual(cancelled["status"], "cancelled")
            self.assertFalse(cancelled["cancel_requested"])
            self.assertEqual(store.events(run["id"])[-1]["type"], "run.cancelled")

    def test_projects_inbox_and_usage_are_aggregated(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / "project"
            project.mkdir()
            store = RunStore(root / "state")
            run = store.create({"task": "Measure", "project_path": str(project)})
            self.assertEqual(len(store.projects.list()), 1)
            item = store.inbox.create({"title": "Later", "task": "Do it", "project_path": str(project)})
            self.assertEqual(store.inbox.get(item["id"])["status"], "open")
            store.append_event(run["id"], "agent.session", "codex", {"phase": "agent", "session_id": "thread-1"})
            store.append_event(run["id"], "agent.tool.started", "codex", {"tool": "shell"})
            store.append_event(run["id"], "agent.usage", "codex", {"input_tokens": 100, "cached_input_tokens": 80, "output_tokens": 10})
            measured = store.get(run["id"])
            self.assertEqual(measured["agent_sessions"]["agent"], "thread-1")
            self.assertEqual(measured["metrics"]["input_tokens"], 100)
            self.assertEqual(measured["metrics"]["tool_calls"], 1)

    def test_redacted_vendor_usage_does_not_crash_the_run(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / "project"
            project.mkdir()
            store = RunStore(root / "state")
            run = store.create({"task": "Measure safely", "project_path": str(project)})
            store.append_event(
                run["id"],
                "agent.usage",
                "claude",
                {
                    "session_id": "thread-redacted",
                    "input_tokens": "[REDACTED]",
                    "cached_input_tokens": "[REDACTED]",
                    "output_tokens": "[REDACTED]",
                    "cumulative": True,
                },
            )
            self.assertEqual(store.get(run["id"])["metrics"]["input_tokens"], 0)

    def test_schema_two_snapshot_migrates_forward_without_rewriting_events(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / "project"
            project.mkdir()
            store = RunStore(root / "state")
            run = store.create({"task": "Old snapshot", "project_path": str(project)})
            path = store.runs_dir / f"{run['id']}.json"
            legacy = json.loads(path.read_text())
            legacy["schema_version"] = 2
            legacy.pop("depends_on")
            legacy.pop("evaluation")
            path.write_text(json.dumps(legacy))
            journal_before = (store.events_dir / f"{run['id']}.ndjson").read_text()

            migrated = RunStore(store.root).get(run["id"])

            self.assertEqual(migrated["schema_version"], 3)
            self.assertEqual(migrated["depends_on"], [])
            self.assertEqual(migrated["evaluation"], {})
            self.assertEqual(
                (store.events_dir / f"{run['id']}.ndjson").read_text(), journal_before
            )

    def test_adopted_session_is_not_scheduler_eligible(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / "project"
            project.mkdir()
            store = RunStore(root / "state")
            run = store.create_external({"task": "Interactive", "project_path": str(project), "kind": "tmux"})
            self.assertEqual(run["status"], "session")
            self.assertIsNone(store.claim(run["id"], max_parallel=1))


if __name__ == "__main__":
    unittest.main()
