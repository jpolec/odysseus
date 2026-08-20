from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from odysseus.failpoints import FAILPOINT_EXIT_CODE, InjectedFailure, reset_failpoints
from odysseus.store import RunStore
from odysseus.state import verify_state
from odysseus.worker_leases import StaleWorkerLease, lease_token, worker_lease_scope


class WorkerLeaseTests(unittest.TestCase):
    def _run(self, root: Path) -> tuple[RunStore, dict[str, object]]:
        project = root / "repo"
        project.mkdir()
        store = RunStore(root / "state")
        return store, store.create({"task": "Lease fixture", "project_path": str(project)})

    @staticmethod
    def _crash(state: Path, run_id: str, point: str, operation: str) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env["ODYSSEUS_FAILPOINT"] = point
        env["ODYSSEUS_FAILPOINT_MODE"] = "exit"
        script = (
            "import sys\n"
            "from pathlib import Path\n"
            "from odysseus.store import RunStore\n"
            "from odysseus.worker_leases import lease_token, worker_lease_scope\n"
            "state, run_id = Path(sys.argv[1]), sys.argv[2]\n"
            "store = RunStore(state)\n"
            f"{operation}\n"
        )
        return subprocess.run(
            [sys.executable, "-c", script, str(state), run_id],
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

    def test_claim_creates_durable_identity_ttl_and_fencing_epoch(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            store, run = self._run(Path(temp))

            claimed = store.claim(str(run["id"]), worker_id="worker-a", lease_seconds=90)

            self.assertIsNotNone(claimed)
            lease = claimed["worker_lease"]  # type: ignore[index]
            self.assertEqual(lease["format"], "odysseus-worker-lease-v1")
            self.assertEqual(lease["worker_id"], "worker-a")
            self.assertEqual(lease["epoch"], 1)
            self.assertEqual(lease["ttl_seconds"], 90)
            self.assertTrue(lease["active"])
            self.assertTrue(lease["lease_id"])
            self.assertGreaterEqual(lease["stream_version_at_claim"], 1)

    def test_concurrent_claims_produce_exactly_one_active_lease(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            store, run = self._run(Path(temp))
            run_id = str(run["id"])
            barrier = threading.Barrier(3)
            results: list[dict[str, object] | None] = []

            def claim(worker_id: str) -> None:
                contender = RunStore(store.root)
                barrier.wait()
                results.append(contender.claim(run_id, worker_id=worker_id))

            threads = [
                threading.Thread(target=claim, args=("worker-a",)),
                threading.Thread(target=claim, args=("worker-b",)),
            ]
            for thread in threads:
                thread.start()
            barrier.wait()
            for thread in threads:
                thread.join(timeout=5)

            winners = [result for result in results if result is not None]
            self.assertEqual(len(winners), 1)
            self.assertEqual(store.get(run_id)["worker_lease"]["lease_id"], winners[0]["worker_lease"]["lease_id"])

    def test_old_worker_cannot_mutate_after_expiry_and_takeover(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            store, run = self._run(Path(temp))
            run_id = str(run["id"])
            first = store.claim(run_id, worker_id="worker-a")
            self.assertIsNotNone(first)
            first_token = lease_token(first)  # type: ignore[arg-type]

            expired = dict(first["worker_lease"])  # type: ignore[index]
            expired["expires_at"] = "2000-01-01T00:00:00Z"
            store.update(run_id, worker_lease=expired)
            self.assertEqual(store.recover_interrupted(), [run_id])

            second = store.claim(run_id, worker_id="worker-b")
            self.assertIsNotNone(second)
            second_token = lease_token(second)  # type: ignore[arg-type]
            self.assertEqual(second_token.epoch, first_token.epoch + 1)

            with worker_lease_scope(first_token):
                with self.assertRaisesRegex(StaleWorkerLease, "lease was replaced|epoch is stale"):
                    store.update(run_id, feedback="zombie write")
                with self.assertRaisesRegex(StaleWorkerLease, "lease was replaced|epoch is stale"):
                    store.append_event(run_id, "agent.output", "worker-a", {"text": "late result"})

            with worker_lease_scope(second_token):
                updated = store.update(run_id, feedback="current worker write")
            self.assertEqual(updated["feedback"], "current worker write")
            self.assertEqual(updated["worker_lease"]["lease_id"], second_token.lease_id)

    def test_old_worker_cannot_release_successor_lease(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            store, run = self._run(Path(temp))
            run_id = str(run["id"])
            first = store.claim(run_id, worker_id="worker-a")
            first_token = lease_token(first)  # type: ignore[arg-type]
            expired = dict(first["worker_lease"])  # type: ignore[index]
            expired["expires_at"] = "2000-01-01T00:00:00Z"
            store.update(run_id, worker_lease=expired)
            store.recover_interrupted()
            second = store.claim(run_id, worker_id="worker-b")
            second_token = lease_token(second)  # type: ignore[arg-type]

            self.assertFalse(
                store.release_worker_lease(
                    run_id,
                    lease_id=first_token.lease_id,
                    epoch=first_token.epoch,
                    reason="late cleanup",
                )
            )
            self.assertTrue(store.get(run_id)["worker_lease"]["active"])
            self.assertEqual(store.get(run_id)["worker_lease"]["lease_id"], second_token.lease_id)

            self.assertTrue(
                store.release_worker_lease(
                    run_id,
                    lease_id=second_token.lease_id,
                    epoch=second_token.epoch,
                    reason="complete",
                )
            )
            self.assertFalse(store.get(run_id)["worker_lease"]["active"])

    def test_worker_token_cannot_mutate_another_run(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            store, first = self._run(root)
            second = store.create({"task": "Another run", "project_path": str(root / "repo")})
            claimed = store.claim(str(first["id"]), worker_id="worker-a")
            token = lease_token(claimed)  # type: ignore[arg-type]

            with worker_lease_scope(token):
                with self.assertRaisesRegex(StaleWorkerLease, "belongs to"):
                    store.update(str(second["id"]), feedback="cross-run write")

            self.assertEqual(store.get(str(second["id"]))["feedback"], "")

    def test_state_verification_rejects_a_corrupt_worker_lease(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            store, run = self._run(Path(temp))
            claimed = store.claim(str(run["id"]), worker_id="worker-a")
            self.assertIsNotNone(claimed)
            path = store.runs_dir / f"{run['id']}.json"
            value = json.loads(path.read_text(encoding="utf-8"))
            value["worker_lease"]["epoch"] = 0
            path.write_text(json.dumps(value), encoding="utf-8")

            result = verify_state(store.root)

            self.assertFalse(result["valid"])
            self.assertTrue(any("worker lease epoch" in error for error in result["errors"]))

    def test_claim_crash_recovers_and_next_owner_gets_a_new_epoch(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            store, run = self._run(Path(temp))
            run_id = str(run["id"])

            crashed = self._crash(
                store.root,
                run_id,
                "worker.claim.after_persist",
                "store.claim(run_id, worker_id='crashed-worker')",
            )

            self.assertEqual(crashed.returncode, FAILPOINT_EXIT_CODE, crashed.stderr)
            recovered_store = RunStore(store.root)
            self.assertEqual(recovered_store.recover_interrupted(), [run_id])
            recovered = recovered_store.get(run_id)
            self.assertEqual(recovered["status"], "queued")
            self.assertFalse(recovered["worker_lease"]["active"])
            successor = recovered_store.claim(run_id, worker_id="successor")
            self.assertEqual(successor["worker_lease"]["epoch"], 2)  # type: ignore[index]

    def test_canonical_fsync_crash_rebuilds_projection_and_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            store, run = self._run(Path(temp))
            run_id = str(run["id"])

            crashed = self._crash(
                store.root,
                run_id,
                "kernel.after_stream_fsync",
                "store.update(run_id, feedback='durable crash-window value')",
            )

            self.assertEqual(crashed.returncode, FAILPOINT_EXIT_CODE, crashed.stderr)
            recovered_store = RunStore(store.root)
            self.assertEqual(
                recovered_store.get(run_id)["feedback"],
                "durable crash-window value",
            )
            self.assertTrue(verify_state(recovered_store.root)["valid"])

    def test_heartbeat_crash_preserves_state_then_requeues(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            store, run = self._run(Path(temp))
            run_id = str(run["id"])
            operation = (
                "claimed = store.claim(run_id, worker_id='crashed-worker')\n"
                "token = lease_token(claimed)\n"
                "with worker_lease_scope(token):\n"
                "    store.update(run_id, feedback='persisted before heartbeat crash')"
            )

            crashed = self._crash(
                store.root,
                run_id,
                "worker.heartbeat.after_persist",
                operation,
            )

            self.assertEqual(crashed.returncode, FAILPOINT_EXIT_CODE, crashed.stderr)
            recovered_store = RunStore(store.root)
            self.assertEqual(
                recovered_store.get(run_id)["feedback"],
                "persisted before heartbeat crash",
            )
            self.assertEqual(recovered_store.recover_interrupted(), [run_id])
            self.assertEqual(recovered_store.get(run_id)["status"], "queued")

    def test_cancel_crash_finalizes_cancellation_instead_of_requeueing(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            store, run = self._run(Path(temp))
            run_id = str(run["id"])
            operation = (
                "store.claim(run_id, worker_id='crashed-worker')\n"
                "store.request_cancel(run_id)"
            )

            crashed = self._crash(
                store.root,
                run_id,
                "worker.cancel.after_intent",
                operation,
            )

            self.assertEqual(crashed.returncode, FAILPOINT_EXIT_CODE, crashed.stderr)
            recovered_store = RunStore(store.root)
            interrupted = recovered_store.get(run_id)
            self.assertEqual(interrupted["status"], "cancelling")
            self.assertTrue(interrupted["cancel_requested"])
            self.assertEqual(recovered_store.recover_interrupted(), [run_id])
            cancelled = recovered_store.get(run_id)
            self.assertEqual(cancelled["status"], "cancelled")
            self.assertFalse(cancelled["cancel_requested"])
            event_types = [event["type"] for event in recovered_store.events_strict(run_id)]
            self.assertIn("run.cancel_requested", event_types)
            self.assertIn("run.cancelled", event_types)

    def test_recovery_crash_does_not_repeat_the_logical_requeue(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            store, run = self._run(Path(temp))
            run_id = str(run["id"])
            claimed = store.claim(run_id, worker_id="worker-a")
            lease = dict(claimed["worker_lease"])  # type: ignore[index]
            lease["expires_at"] = "2000-01-01T00:00:00Z"
            store.update(run_id, worker_lease=lease)

            with mock.patch.dict(
                os.environ,
                {
                    "ODYSSEUS_FAILPOINT": "worker.recovery.after_projection",
                    "ODYSSEUS_FAILPOINT_MODE": "raise",
                },
                clear=False,
            ):
                reset_failpoints()
                with self.assertRaisesRegex(InjectedFailure, "worker.recovery.after_projection"):
                    store.recover_interrupted()

            reopened = RunStore(store.root)
            self.assertEqual(reopened.get(run_id)["status"], "queued")
            self.assertEqual(reopened.recover_interrupted(), [])
            recoveries = [
                event
                for event in reopened.events_strict(run_id)
                if event["type"] == "system.recovered"
            ]
            self.assertEqual(len(recoveries), 1)

    def test_recovery_rechecks_lease_under_lock_before_requeueing(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            store, run = self._run(Path(temp))
            run_id = str(run["id"])
            claimed = store.claim(run_id, worker_id="worker-a")
            stale_scan = json.loads(json.dumps(claimed))
            stale_scan["worker_lease"]["expires_at"] = "2000-01-01T00:00:00Z"

            with mock.patch.object(store, "list", return_value=[stale_scan]):
                self.assertEqual(store.recover_interrupted(), [])

            current = store.get(run_id)
            self.assertEqual(current["status"], "starting")
            self.assertTrue(current["worker_lease"]["active"])
            self.assertEqual(
                current["worker_lease"]["lease_id"],
                claimed["worker_lease"]["lease_id"],
            )

    def test_recovery_releases_stale_lease_without_reverting_review_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            store, run = self._run(Path(temp))
            run_id = str(run["id"])
            claimed = store.claim(run_id, worker_id="worker-a")
            token = lease_token(claimed)  # type: ignore[arg-type]
            with worker_lease_scope(token):
                store.transition(run_id, "review", event_type="run.review_ready")
            stale = dict(store.get(run_id)["worker_lease"])
            stale["expires_at"] = "2000-01-01T00:00:00Z"
            store.update(run_id, worker_lease=stale)

            self.assertEqual(store.recover_interrupted(), [run_id])

            recovered = store.get(run_id)
            self.assertEqual(recovered["status"], "review")
            self.assertFalse(recovered["worker_lease"]["active"])
            self.assertEqual(
                recovered["worker_lease"]["release_reason"],
                "recovered_after_terminal_projection",
            )


if __name__ == "__main__":
    unittest.main()
