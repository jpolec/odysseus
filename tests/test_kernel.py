from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from odysseus.events import now_iso
from odysseus.kernel import (
    EVENT_ENVELOPE_FORMAT,
    EVENT_ENVELOPE_SCHEMA_VERSION,
    GENESIS_HASH,
    LEGACY_EVENT_ENVELOPE_FORMAT,
    EventKernel,
    KernelIntegrityError,
    envelope_hash,
    sha256_json,
)
from odysseus.state import verify_state
from odysseus.store import RunStore


class EventKernelTests(unittest.TestCase):
    def _store(self, root: Path) -> tuple[RunStore, dict[str, object]]:
        project = root / "repo"
        project.mkdir()
        store = RunStore(root / "state")
        run = store.create({"task": "Canonical replay fixture", "project_path": str(project)})
        return store, run

    def test_stream_is_hash_chained_and_replays_exact_projection(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            store, run = self._store(Path(temp))
            store.update(run["id"], feedback="continue safely")

            events = store.kernel.read(run["id"])
            persisted = json.loads((store.runs_dir / f"{run['id']}.json").read_text(encoding="utf-8"))

            self.assertGreaterEqual(len(events), 2)
            self.assertEqual(events[0]["format"], EVENT_ENVELOPE_FORMAT)
            self.assertEqual(events[0]["schema_version"], EVENT_ENVELOPE_SCHEMA_VERSION)
            self.assertEqual(events[0]["prev_event_hash"], GENESIS_HASH)
            for previous, current in zip(events, events[1:]):
                self.assertEqual(current["prev_event_hash"], previous["event_hash"])
                self.assertEqual(current["stream_version"], previous["stream_version"] + 1)
            self.assertEqual(store.kernel.replay(run["id"]), persisted)
            verification = store.kernel.verify_projection(run["id"], persisted)
            self.assertTrue(verification["valid"])
            state = verify_state(store.root)
            self.assertGreater(state["replay_events_per_second"], 0)

    def test_deleted_projection_rebuilds_bit_for_bit_from_stream(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            store, run = self._store(Path(temp))
            store.transition(run["id"], "failed", event_type="run.failed", last_error="fixture")
            path = store.runs_dir / f"{run['id']}.json"
            expected = path.read_bytes()
            path.unlink()

            result = store.kernel.rebuild(run["id"])

            self.assertEqual(path.read_bytes(), expected)
            self.assertGreater(result["events_per_second"], 0)

    def test_replay_until_event_returns_historical_projection(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            store, run = self._store(Path(temp))
            first = store.kernel.replay(run["id"], until_event=1)
            store.update(run["id"], feedback="later value")
            current = store.kernel.replay(run["id"])

            self.assertEqual(first["feedback"], "")
            self.assertEqual(current["feedback"], "later value")

    def test_process_death_after_stream_fsync_recovers_projection(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            store, run = self._store(root)
            projection = store.get(run["id"])
            projection.update({"status": "failed", "last_error": "crash window", "updated_at": now_iso()})
            store.kernel.append_run(
                run["id"],
                event_type="fault.after_stream_fsync",
                actor="test",
                projection=store._redact_snapshot(projection),
            )

            recovered = RunStore(root / "state").get(run["id"])

            self.assertEqual(recovered["status"], "failed")
            self.assertEqual(recovered["last_error"], "crash window")
            self.assertTrue(verify_state(root / "state")["valid"])

    def test_tampering_breaks_hash_chain_and_state_verification(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            store, run = self._store(Path(temp))
            path = store.kernel.stream_path(run["id"])
            lines = path.read_text(encoding="utf-8").splitlines()
            value = json.loads(lines[0])
            value["payload"]["projection_patch"]["replace"]["title"] = "tampered"
            lines[0] = json.dumps(value, sort_keys=True, separators=(",", ":"))
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")

            with self.assertRaisesRegex(KernelIntegrityError, "hash mismatch"):
                store.kernel.replay(run["id"])
            self.assertFalse(verify_state(store.root)["valid"])

    def test_deleted_middle_event_breaks_stream_continuity(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            store, run = self._store(Path(temp))
            store.update(run["id"], feedback="one")
            store.update(run["id"], feedback="two")
            path = store.kernel.stream_path(run["id"])
            lines = path.read_text(encoding="utf-8").splitlines()
            self.assertGreaterEqual(len(lines), 4)
            path.write_text("\n".join([lines[0], *lines[2:]]) + "\n", encoding="utf-8")

            with self.assertRaisesRegex(KernelIntegrityError, "hash-chain|stream version"):
                store.kernel.replay(run["id"])

    def test_crash_before_domain_journal_and_snapshot_is_reconciled(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            store, run = self._store(root)
            projection = store.get(run["id"])
            sequence = int(projection["event_seq"]) + 1
            domain_event = {
                "v": 1,
                "run_id": run["id"],
                "type": "agent.output",
                "source": "codex",
                "data": {"text": "durable before crash"},
                "seq": sequence,
                "ts": now_iso(),
                "redaction_receipt": {
                    "ruleset_version": "odysseus-redaction-v1",
                    "boundary": "event",
                    "redacted_field_classes": [],
                },
            }
            projection.update({"event_seq": sequence, "updated_at": domain_event["ts"]})
            store.kernel.append_run(
                run["id"],
                event_type="agent.output",
                actor="codex",
                projection=store._redact_snapshot(projection),
                domain_event=domain_event,
            )

            recovered_store = RunStore(root / "state")
            recovered = recovered_store.get(run["id"])
            events = recovered_store.events_strict(run["id"])

            self.assertEqual(recovered["event_seq"], sequence)
            self.assertEqual(events[-1]["seq"], sequence)
            self.assertEqual(events[-1]["data"]["text"], "durable before crash")

    def test_v1_envelope_upcasts_without_rewriting_historical_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            kernel = EventKernel(Path(temp) / "state")
            projection = {"id": "legacy", "status": "queued"}
            value = {
                "format": LEGACY_EVENT_ENVELOPE_FORMAT,
                "schema_version": 1,
                "event_id": "legacy-event-1",
                "stream_id": "run:legacy",
                "stream_version": 1,
                "event_type": "projection.imported",
                "actor": {"type": "system", "id": "migration"},
                "occurred_at": now_iso(),
                "payload": {
                    "projection_patch": {"replace": projection},
                    "projection_sha256": sha256_json(projection),
                    "domain_event": None,
                },
                "prev_event_hash": GENESIS_HASH,
            }
            value["event_hash"] = envelope_hash(value)
            path = kernel.stream_path("legacy")
            path.write_text(json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
            original = path.read_bytes()

            event = kernel.read("legacy")[0]

            self.assertEqual(event["schema_version"], EVENT_ENVELOPE_SCHEMA_VERSION)
            self.assertEqual(event["upcasted_from_schema"], 1)
            self.assertEqual(kernel.replay("legacy"), projection)
            self.assertEqual(path.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
