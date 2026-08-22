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
            epic = store.epics.create(
                {
                    "title": "Legacy",
                    "project_path": str(project),
                    "source_documents": [{"kind": "adr", "path": "legacy.md", "content": "Legacy rule."}],
                }
            )
            path = store.epics._path(epic["id"])
            legacy = json.loads(path.read_text(encoding="utf-8"))
            legacy["schema_version"] = 1
            legacy.pop("evidence_class")
            legacy.pop("release")
            path.write_text(json.dumps(legacy), encoding="utf-8")

            reopened = RunStore(Path(temp) / "state")
            loaded = reopened.epics.get(epic["id"])
            mapping = reopened.epics.create_task_batch(
                epic["id"], [{"task_key": "old", "task": "Materialize old plan"}]
            )

            self.assertEqual(loaded["evidence_class"], "unclassified")
            self.assertEqual(reopened.get(mapping["old"])["provenance"]["evidence_class"], "unclassified")

            persisted = json.loads(reopened.epics._path(epic["id"]).read_text(encoding="utf-8"))
            self.assertEqual(persisted["schema_version"], 4)
            self.assertEqual(persisted["source_documents"][0]["sections"][0]["ref"], "S1")

    def test_versioned_contract_maps_source_changes_only_to_affected_tasks(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            store, project = self._store(Path(temp))
            source = project / "decision.md"
            source.write_text("Keep password login.\n\nAdd passkeys.\n", encoding="utf-8")
            epic = store.epics.create(
                {
                    "title": "Passkeys",
                    "project_path": str(project),
                    "source_documents": [{"kind": "adr", "path": "decision.md", "content": source.read_text()}],
                }
            )
            first = store.epics.save_plan(
                epic["id"],
                {
                    "summary": "Versioned passkey contract",
                    "tasks": [
                        {
                            "task_key": "password",
                            "title": "Preserve password login",
                            "task": "Keep password login unchanged",
                            "source_refs": ["S1"],
                        },
                        {
                            "task_key": "passkeys",
                            "title": "Add passkeys",
                            "task": "Implement passkeys",
                            "source_refs": ["S2"],
                            "acceptance_criteria": ["Passkey sign-in works"],
                            "required_evidence": ["Browser flow passes"],
                            "execution_profile": {
                                "mode": "override",
                                "harness": "claude",
                                "model": "claude-test",
                                "skills": ["security-review"],
                                "review_lane": "codex",
                            },
                            "estimate": {"cost_usd_min": 2, "cost_usd_max": 5, "confidence": "low", "basis": "small cohort"},
                        },
                    ],
                },
            )
            second = store.epics.save_plan(first["id"], first["plan"])
            self.assertEqual(first["plan_version"]["number"], 1)
            self.assertEqual(second["plan_version"]["number"], 2)
            self.assertEqual(len(second["plan_history"]), 1)

            source.write_text("Keep password login exactly as today.\n\nAdd passkeys.\n", encoding="utf-8")
            impact = store.epics.source_impact(epic["id"])
            self.assertEqual(impact["changed_refs"], ["S1"])
            self.assertEqual(impact["affected_task_keys"], ["password"])

            source.write_text("Keep password login.\n\nAdd passkeys with recovery.\n", encoding="utf-8")
            impact = store.epics.source_impact(epic["id"])
            self.assertEqual(impact["changed_refs"], ["S2"])
            self.assertEqual(impact["affected_task_keys"], ["passkeys"])

            source.write_text("Keep password login.\n\nAdd passkeys.\n\nDocument rollout.\n", encoding="utf-8")
            impact = store.epics.source_impact(epic["id"])
            self.assertEqual(impact["status"], "changed")
            self.assertEqual(impact["affected_task_keys"], [])
            self.assertFalse(impact["requires_reapproval"])

            refreshed = store.epics.refresh_local_sources(epic["id"])
            self.assertEqual(store.epics.source_impact(epic["id"])["status"], "current")
            third = store.epics.save_plan(epic["id"], refreshed["plan"])
            self.assertNotEqual(third["plan_version"]["source_hashes"], second["plan_version"]["source_hashes"])
            self.assertNotEqual(third["plan_version"]["sha256"], second["plan_version"]["sha256"])
            mapping = store.epics.create_task_batch(epic["id"], third["plan"]["tasks"])
            run = store.get(mapping["passkeys"])
            self.assertEqual(run["task_contract"]["source_refs"], ["S2"])
            self.assertEqual(run["task_contract"]["plan_version_sha256"], third["plan_version"]["sha256"])
            self.assertEqual(run["execution_profile"]["skills"], ["security-review"])
            self.assertEqual(run["lane"], "claude")
            self.assertEqual(run["review_lane"], "codex")
            self.assertEqual(run["execution_profile"]["model"], "claude-test")
            self.assertEqual(run["estimate"]["cost_usd_max"], 5.0)


if __name__ == "__main__":
    unittest.main()
