from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from odysseus.epics import CycleError
from odysseus.store import RunStore


class EpicTests(unittest.TestCase):
    def _store(self, root: Path) -> tuple[RunStore, Path]:
        project = root / "project"
        project.mkdir()
        return RunStore(root / "state"), project

    def test_validated_dag_queues_roots_and_unblocks_dependants(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            store, project = self._store(Path(temp))
            epic = store.epics.create({"title": "Ship auth", "project_path": str(project)})
            mapping = store.epics.create_task_batch(
                epic["id"],
                [
                    {"task_key": "schema", "task": "Change schema"},
                    {"task_key": "api", "task": "Build API", "depends_on": ["schema"]},
                    {"task_key": "ui", "task": "Build UI", "depends_on": ["schema"]},
                    {
                        "task_key": "integration",
                        "task": "Integrate",
                        "depends_on": ["api", "ui"],
                        "parallelizable": False,
                    },
                ],
            )

            self.assertEqual(store.get(mapping["schema"])["status"], "queued")
            self.assertEqual(store.get(mapping["api"])["status"], "blocked")
            self.assertEqual(store.attention.list(status="open"), [])
            self.assertIsNone(store.claim(mapping["api"], max_parallel=4))

            store.update(mapping["schema"], status="accepted")
            unblocked = store.epics.refresh_dag(epic["id"])
            self.assertCountEqual(unblocked, [mapping["api"], mapping["ui"]])
            self.assertEqual(store.get(mapping["api"])["dependencies_met"], [mapping["schema"]])

    def test_failed_dependency_becomes_operator_attention(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            store, project = self._store(Path(temp))
            epic = store.epics.create({"title": "Failure", "project_path": str(project)})
            mapping = store.epics.create_task_batch(
                epic["id"],
                [
                    {"task_key": "root", "task": "Root"},
                    {"task_key": "child", "task": "Child", "depends_on": ["root"]},
                ],
            )
            store.update(mapping["root"], status="failed")
            store.epics.refresh_dag(epic["id"])
            items = store.attention.list(status="open", run_id=mapping["child"])
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0]["type"], "blocked")

    def test_cycle_is_rejected_before_any_run_is_created(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            store, project = self._store(Path(temp))
            epic = store.epics.create({"title": "Bad graph", "project_path": str(project)})
            with self.assertRaises(CycleError):
                store.epics.create_task_batch(
                    epic["id"],
                    [
                        {"task_key": "a", "task": "A", "depends_on": ["b"]},
                        {"task_key": "b", "task": "B", "depends_on": ["a"]},
                    ],
                )
            self.assertEqual(store.list(), [])

    def test_nonparallel_task_waits_for_active_sibling(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            store, project = self._store(Path(temp))
            epic = store.epics.create({"title": "Serialized", "project_path": str(project)})
            mapping = store.epics.create_task_batch(
                epic["id"],
                [
                    {"task_key": "first", "task": "First"},
                    {"task_key": "second", "task": "Second", "parallelizable": False},
                ],
            )
            self.assertIsNotNone(store.claim(mapping["first"], max_parallel=4))
            self.assertIsNone(store.claim(mapping["second"], max_parallel=4))

    def test_refresh_all_reuses_the_scheduler_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            store, project = self._store(Path(temp))
            epic = store.epics.create({"title": "Snapshot", "project_path": str(project)})
            store.epics.create_task_batch(
                epic["id"],
                [{"task_key": "root", "task": "Root"}],
            )
            runs = store.runtime_runs()

            with patch.object(store, "get", side_effect=AssertionError("unexpected run reload")):
                self.assertEqual(store.epics.refresh_all(runs=runs), [])

    def test_legacy_epic_tasks_remain_unclassified(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            store, project = self._store(Path(temp))
            epic = store.epics.create({"title": "Legacy", "project_path": str(project)})
            path = store.epics._path(epic["id"])
            legacy = json.loads(path.read_text(encoding="utf-8"))
            legacy["schema_version"] = 1
            legacy.pop("evidence_class")
            legacy.pop("release")
            path.write_text(json.dumps(legacy), encoding="utf-8")

            loaded = store.epics.get(epic["id"])
            mapping = store.epics.create_task_batch(
                epic["id"], [{"task_key": "old", "task": "Materialize old plan"}]
            )

            self.assertEqual(loaded["evidence_class"], "unclassified")
            self.assertEqual(store.get(mapping["old"])["provenance"]["evidence_class"], "unclassified")


if __name__ == "__main__":
    unittest.main()
