from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from odysseus.proof import production_proof, proof_markdown
from odysseus.store import RunStore


class ProductionProofTests(unittest.TestCase):
    def test_only_observed_release_runs_contribute_to_production_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / "repo"
            project.mkdir()
            store = RunStore(root / "state")
            observed = store.create(
                {
                    "task": "Ship it",
                    "project_path": str(project),
                    "release": "0.6.3",
                    "origin": "cli",
                    "evidence_class": "observed",
                }
            )
            store.update(
                observed["id"],
                status="accepted",
                started_at="2026-08-15T08:00:00Z",
                finished_at="2026-08-15T08:10:00Z",
                artifact_sha="abc123",
                ci={"status": "passed"},
            )
            store.append_event(observed["id"], "run.started", "odysseus", {})
            store.append_event(observed["id"], "system.recovered", "odysseus", {"message": "resumed"})
            store.append_event(observed["id"], "agent.output", "codex", {"message": "working"})
            store.append_event(observed["id"], "agent.cost", "codex", {"cost_usd": 2.5})
            store.append_event(observed["id"], "check.completed", "check", {"returncode": 0})
            store.append_event(observed["id"], "ci.failed", "github", {"message": "red"})
            store.append_event(observed["id"], "ci.passed", "github", {"message": "green"})
            store.append_event(observed["id"], "artifact.created", "git", {"artifact_sha": "abc123"})
            store.append_event(observed["id"], "review.accepted", "user", {})
            store.append_event(observed["id"], "run.accepted", "odysseus", {})
            item = store.attention.create({"type": "review", "run_id": observed["id"], "title": "Approve"})
            store.attention.respond(item["id"], "approve")
            store.append_event(
                observed["id"],
                "attention.answered",
                "user",
                {"attention_id": item["id"], "response": "approve"},
            )
            store.create(
                {
                    "task": "Tour only",
                    "project_path": str(project),
                    "release": "0.6.3",
                    "evidence_class": "demo",
                }
            )
            store.create(
                {
                    "task": "Other release",
                    "project_path": str(project),
                    "release": "0.6.2",
                    "evidence_class": "observed",
                }
            )

            proof = production_proof(store, release="0.6.3", minimum_runs=2)

            self.assertEqual(proof["metrics"]["autonomous_tasks"], 1)
            self.assertEqual(proof["metrics"]["accepted_changes"], 1)
            self.assertEqual(proof["metrics"]["median_task_duration_seconds"], 600.0)
            self.assertEqual(proof["metrics"]["ci_failures_repaired"], 1)
            self.assertEqual(proof["metrics"]["runs_resumed_after_crash"], 1)
            self.assertEqual(proof["metrics"]["human_interventions"], 2)
            self.assertEqual(proof["classifications"]["demo"], 1)
            self.assertFalse(proof["sample_sufficient"])
            self.assertEqual(len(proof["run_receipts"]), 1)
            self.assertNotIn(observed["id"], json.dumps(proof))
            self.assertNotIn(str(project), json.dumps(proof))
            self.assertEqual(
                proof["proof_sha256"],
                production_proof(store, release="0.6.3", minimum_runs=2)["proof_sha256"],
            )
            self.assertIn("below 2-run threshold", proof_markdown(proof))

    def test_new_runs_capture_versioned_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / "repo"
            project.mkdir()
            run = RunStore(root / "state").create(
                {"task": "Trace me", "project_path": str(project), "origin": "web"}
            )

            self.assertEqual(run["provenance"]["format"], "odysseus-run-provenance-v1")
            self.assertEqual(run["provenance"]["evidence_class"], "observed")
            self.assertEqual(run["provenance"]["origin"], "web")
            self.assertEqual(run["provenance"]["odysseus_version"], "0.6.4")

    def test_read_only_proof_does_not_backfill_legacy_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / "repo"
            project.mkdir()
            state = root / "state"
            store = RunStore(state)
            run = store.create({"task": "Legacy", "project_path": str(project)})
            path = store.runs_dir / f"{run['id']}.json"
            value = json.loads(path.read_text(encoding="utf-8"))
            value["schema_version"] = 8
            value.pop("provenance")
            path.write_text(json.dumps(value), encoding="utf-8")

            proof = production_proof(RunStore(state, migrate=False, readonly=True))

            persisted = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(persisted["schema_version"], 8)
            self.assertNotIn("provenance", persisted)
            self.assertEqual(proof["classifications"]["unclassified"], 1)
            self.assertEqual(proof["metrics"]["autonomous_tasks"], 0)

    def test_queued_or_manually_accepted_records_do_not_become_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / "repo"
            project.mkdir()
            store = RunStore(root / "state")
            queued = store.create({"task": "Only queued", "project_path": str(project), "release": "0.6.3"})
            fake = store.create({"task": "Edited snapshot", "project_path": str(project), "release": "0.6.3"})
            store.update(fake["id"], status="accepted", artifact_sha="not-enough")

            proof = production_proof(store, release="0.6.3", minimum_runs=1)

            self.assertEqual(proof["metrics"]["observed_tasks"], 2)
            self.assertEqual(proof["metrics"]["autonomous_tasks"], 0)
            self.assertEqual(proof["metrics"]["in_progress_tasks"], 1)
            self.assertEqual(proof["metrics"]["ineligible_terminal_tasks"], 1)
            self.assertFalse(proof["sample_sufficient"])

    def test_pr_is_not_acceptance_and_missing_cost_is_not_zero(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / "repo"
            project.mkdir()
            store = RunStore(root / "state")
            run = store.create({"task": "Open draft", "project_path": str(project), "release": "0.6.3"})
            store.update(
                run["id"],
                status="pr_created",
                started_at="2026-08-15T08:00:00Z",
                finished_at="2026-08-15T08:01:00Z",
                artifact_sha="draft123",
            )
            store.append_event(run["id"], "run.started", "odysseus", {})
            store.append_event(run["id"], "agent.output", "codex", {})
            store.append_event(run["id"], "evaluation.completed", "odysseus", {})
            store.append_event(run["id"], "artifact.created", "git", {"artifact_sha": "draft123"})
            store.append_event(run["id"], "pr.created", "git", {"url": "https://example.invalid/1"})

            proof = production_proof(store, release="0.6.3", minimum_runs=1)

            self.assertEqual(proof["metrics"]["autonomous_tasks"], 1)
            self.assertEqual(proof["metrics"]["pull_requests_opened"], 1)
            self.assertEqual(proof["metrics"]["accepted_changes"], 0)
            self.assertIsNone(proof["metrics"]["median_cost_usd"])
            self.assertIsNone(proof["metrics"]["total_cost_usd"])
            self.assertEqual(proof["metrics"]["cost_coverage_runs"], 0)

    def test_claim_hash_binds_threshold_and_complete_strict_journal(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / "repo"
            project.mkdir()
            store = RunStore(root / "state")
            run = store.create({"task": "Long journal", "project_path": str(project), "release": "0.6.3"})
            for number in range(1_100):
                store.append_event(run["id"], "agent.output", "codex", {"number": number})
            self.assertEqual(len(store.events(run["id"])), 1_000)
            self.assertGreater(len(store.events_strict(run["id"])), 1_000)
            one = production_proof(store, release="0.6.3", minimum_runs=1)
            two = production_proof(store, release="0.6.3", minimum_runs=2)
            self.assertNotEqual(one["proof_sha256"], two["proof_sha256"])

    def test_early_agent_failure_is_an_eligible_unsuccessful_attempt(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / "repo"
            project.mkdir()
            store = RunStore(root / "state")
            run = store.create({"task": "Crash early", "project_path": str(project), "release": "0.6.3"})
            store.update(
                run["id"],
                status="failed",
                started_at="2026-08-15T08:00:00Z",
                finished_at="2026-08-15T08:00:20Z",
            )
            store.append_event(run["id"], "run.started", "odysseus", {})
            store.append_event(run["id"], "agent.output", "codex", {"message": "started"})
            store.append_event(run["id"], "run.failed", "odysseus", {"message": "crashed"})

            proof = production_proof(store, release="0.6.3", minimum_runs=1)

            self.assertEqual(proof["metrics"]["autonomous_tasks"], 1)
            self.assertEqual(proof["metrics"]["accepted_changes"], 0)
            self.assertEqual(proof["metrics"]["acceptance_rate"], 0.0)

    def test_acceptance_requires_last_verifier_then_artifact_then_outcome(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / "repo"
            project.mkdir()
            store = RunStore(root / "state")
            run = store.create({"task": "Misordered", "project_path": str(project), "release": "0.6.3"})
            store.update(run["id"], status="accepted", artifact_sha="abc")
            store.append_event(run["id"], "run.started", "odysseus", {})
            store.append_event(run["id"], "agent.output", "codex", {})
            store.append_event(run["id"], "evaluation.completed", "odysseus", {})
            store.append_event(run["id"], "artifact.created", "git", {"artifact_sha": "abc"})
            store.append_event(run["id"], "evaluation.failed", "odysseus", {})
            store.append_event(run["id"], "run.accepted", "odysseus", {})

            proof = production_proof(store, release="0.6.3", minimum_runs=1)

            self.assertEqual(proof["metrics"]["autonomous_tasks"], 0)
            self.assertEqual(proof["eligibility_reasons"]["last_verifier_failed"], 1)

    def test_deleted_journal_event_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / "repo"
            project.mkdir()
            store = RunStore(root / "state")
            run = store.create({"task": "Gap", "project_path": str(project)})
            store.append_event(run["id"], "agent.output", "codex", {"number": 1})
            store.append_event(run["id"], "agent.output", "codex", {"number": 2})
            journal = store._events_path(run["id"])
            lines = journal.read_text(encoding="utf-8").splitlines()
            journal.write_text("\n".join([lines[0], *lines[2:]]) + "\n", encoding="utf-8")

            with self.assertRaisesRegex(RuntimeError, "non-contiguous"):
                store.events_strict(run["id"])

    def test_read_only_proof_does_not_change_state_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / "repo"
            project.mkdir()
            state = root / "state"
            store = RunStore(state)
            store.create({"task": "Observe without writes", "project_path": str(project)})

            def manifest() -> str:
                values = []
                for path in sorted(item for item in state.rglob("*") if item.is_file()):
                    values.append((str(path.relative_to(state)), hashlib.sha256(path.read_bytes()).hexdigest()))
                return hashlib.sha256(json.dumps(values).encode("utf-8")).hexdigest()

            before = manifest()
            production_proof(RunStore(state, migrate=False, readonly=True))
            self.assertEqual(manifest(), before)

    def test_recovery_requires_progress_after_last_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / "repo"
            project.mkdir()
            store = RunStore(root / "state")
            run = store.create({"task": "Recover twice", "project_path": str(project), "release": "0.6.3"})
            store.update(run["id"], status="failed")
            store.append_event(run["id"], "run.started", "odysseus", {})
            store.append_event(run["id"], "system.recovered", "odysseus", {})
            store.append_event(run["id"], "agent.output", "codex", {})
            store.append_event(run["id"], "system.recovered", "odysseus", {})
            store.append_event(run["id"], "run.failed", "odysseus", {})

            proof = production_proof(store, release="0.6.3", minimum_runs=1)

            self.assertEqual(proof["metrics"]["autonomous_tasks"], 1)
            self.assertEqual(proof["metrics"]["runs_resumed_after_crash"], 0)


if __name__ == "__main__":
    unittest.main()
