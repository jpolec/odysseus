from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from odysseus.state import verify_state
from odysseus.store import RUN_SCHEMA_VERSION, RunStore


class StateVerificationTests(unittest.TestCase):
    def test_valid_state_scans_run_and_event_journal(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "repo"
            project.mkdir()
            store = RunStore(Path(temp) / "state")
            run = store.create({"task": "verify me", "project_path": str(project)})

            result = verify_state(store.root)

            self.assertTrue(result["valid"], result["errors"])
            self.assertEqual(result["runs"], 1)
            self.assertGreaterEqual(result["events"], 1)
            self.assertEqual(run["schema_version"], RUN_SCHEMA_VERSION)

    def test_corrupt_json_and_ndjson_are_never_silently_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "runs").mkdir()
            (root / "events").mkdir()
            (root / "runs" / "broken.json").write_text("{", encoding="utf-8")
            (root / "events" / "broken.ndjson").write_text("not-json\n", encoding="utf-8")

            result = verify_state(root)

            self.assertFalse(result["valid"])
            self.assertEqual(len(result["errors"]), 2)

    def test_newer_run_schema_is_rejected_before_migration(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "repo"
            project.mkdir()
            root = Path(temp) / "state"
            store = RunStore(root)
            run = store.create({"task": "future", "project_path": str(project)})
            path = store.runs_dir / f"{run['id']}.json"
            value = json.loads(path.read_text(encoding="utf-8"))
            value["schema_version"] = RUN_SCHEMA_VERSION + 1
            path.write_text(json.dumps(value), encoding="utf-8")

            self.assertFalse(verify_state(root)["valid"])
            with self.assertRaisesRegex(RuntimeError, "supports up to"):
                RunStore(root)


if __name__ == "__main__":
    unittest.main()
