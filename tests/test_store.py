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


if __name__ == "__main__":
    unittest.main()
