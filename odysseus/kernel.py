"""Canonical event streams and deterministic run projections.

The operator-facing event journal remains a compact activity feed.  This
module owns the canonical state stream: every run projection change is appended
and fsynced here before the replaceable JSON projection is written.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any, Mapping

from .events import now_iso


EVENT_ENVELOPE_FORMAT = "odysseus-event-envelope-v2"
EVENT_ENVELOPE_SCHEMA_VERSION = 2
LEGACY_EVENT_ENVELOPE_FORMAT = "odysseus-event-envelope-v1"
GENESIS_HASH = "0" * 64
STREAM_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


class KernelIntegrityError(RuntimeError):
    """Raised when an immutable canonical stream cannot be trusted."""


class ConcurrencyConflict(RuntimeError):
    """Raised when a command targets a stale canonical stream version."""


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def envelope_hash(value: Mapping[str, Any]) -> str:
    material = {key: item for key, item in value.items() if key != "event_hash"}
    return sha256_json(material)


def projection_patch(previous: Mapping[str, Any], current: Mapping[str, Any], *, replace: bool = False) -> dict[str, Any]:
    if replace:
        return {"replace": dict(current)}
    changed = {
        key: value
        for key, value in current.items()
        if key not in previous or previous.get(key) != value
    }
    removed = sorted(key for key in previous if key not in current)
    return {"set": changed, "unset": removed}


def apply_projection_patch(previous: Mapping[str, Any], patch: Mapping[str, Any]) -> dict[str, Any]:
    replacement = patch.get("replace")
    if isinstance(replacement, Mapping):
        return dict(replacement)
    result = dict(previous)
    changed = patch.get("set")
    if isinstance(changed, Mapping):
        result.update(changed)
    removed = patch.get("unset")
    if isinstance(removed, list):
        for key in removed:
            result.pop(str(key), None)
    return result


class EventKernel:
    """Append-only, hash-chained canonical streams for run projections."""

    def __init__(self, root: Path | str, *, readonly: bool = False) -> None:
        self.root = Path(root).expanduser()
        self.readonly = readonly
        self.streams_dir = self.root / "streams"
        self.checkpoints_dir = self.root / "checkpoints" / "runs"
        self.runs_dir = self.root / "runs"
        if not readonly:
            self.streams_dir.mkdir(parents=True, exist_ok=True)
            self.checkpoints_dir.mkdir(parents=True, exist_ok=True)

    def _name(self, run_id: str) -> str:
        if not STREAM_NAME_RE.fullmatch(run_id):
            raise ValueError("invalid stream id")
        return run_id

    def stream_path(self, run_id: str) -> Path:
        return self.streams_dir / f"{self._name(run_id)}.ndjson"

    def checkpoint_path(self, run_id: str) -> Path:
        return self.checkpoints_dir / f"{self._name(run_id)}.json"

    def has_stream(self, run_id: str) -> bool:
        return self.stream_path(run_id).is_file()

    @staticmethod
    def _legacy_hash(previous_hash: str, value: Mapping[str, Any]) -> str:
        return hashlib.sha256(previous_hash.encode("ascii") + b"\n" + canonical_json(value)).hexdigest()

    @staticmethod
    def _upcast_v1(value: Mapping[str, Any]) -> dict[str, Any]:
        actor = value.get("actor")
        if not isinstance(actor, Mapping):
            actor = {"type": "system", "id": str(value.get("source") or "legacy")}
        return {
            **dict(value),
            "format": EVENT_ENVELOPE_FORMAT,
            "schema_version": EVENT_ENVELOPE_SCHEMA_VERSION,
            "actor": dict(actor),
            "command_id": str(value.get("command_id") or ""),
            "idempotency_key": str(value.get("idempotency_key") or ""),
            "correlation_id": str(value.get("correlation_id") or value.get("stream_id") or ""),
            "causation_id": str(value.get("causation_id") or ""),
            "upcasted_from_schema": 1,
        }

    def read(self, run_id: str) -> list[dict[str, Any]]:
        path = self.stream_path(run_id)
        if not path.exists():
            return []
        values: list[dict[str, Any]] = []
        previous_hash = GENESIS_HASH
        previous_version = 0
        event_ids: set[str] = set()
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            raise KernelIntegrityError(f"cannot read canonical stream: {path}: {exc}") from exc
        for number, line in enumerate(lines, 1):
            if not line.strip():
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError as exc:
                raise KernelIntegrityError(f"corrupt canonical stream: {path}:{number}") from exc
            if not isinstance(raw, dict):
                raise KernelIntegrityError(f"invalid canonical event: {path}:{number}")
            schema = raw.get("schema_version")
            if schema == 1 or raw.get("format") == LEGACY_EVENT_ENVELOPE_FORMAT:
                expected_hash = envelope_hash(raw)
                if raw.get("event_hash") and raw.get("event_hash") != expected_hash:
                    raise KernelIntegrityError(f"event hash mismatch: {path}:{number}")
                raw_hash = str(raw.get("event_hash") or self._legacy_hash(previous_hash, raw))
                value = self._upcast_v1(raw)
                value["event_hash"] = raw_hash
            elif schema == EVENT_ENVELOPE_SCHEMA_VERSION and raw.get("format") == EVENT_ENVELOPE_FORMAT:
                if raw.get("prev_event_hash") != previous_hash:
                    raise KernelIntegrityError(f"hash-chain mismatch: {path}:{number}")
                expected_hash = envelope_hash(raw)
                if raw.get("event_hash") != expected_hash:
                    raise KernelIntegrityError(f"event hash mismatch: {path}:{number}")
                value = dict(raw)
                raw_hash = expected_hash
            else:
                raise KernelIntegrityError(f"unsupported canonical event schema: {path}:{number}: {schema!r}")
            version = value.get("stream_version")
            if not isinstance(version, int) or version != previous_version + 1:
                raise KernelIntegrityError(f"non-contiguous stream version: {path}:{number}")
            if str(value.get("stream_id") or "") != f"run:{run_id}":
                raise KernelIntegrityError(f"stream id mismatch: {path}:{number}")
            event_id = str(value.get("event_id") or "")
            if not event_id or event_id in event_ids:
                raise KernelIntegrityError(f"missing or duplicate event id: {path}:{number}")
            payload = value.get("payload")
            if not isinstance(payload, dict) or not isinstance(payload.get("projection_patch"), dict):
                raise KernelIntegrityError(f"canonical event has no projection patch: {path}:{number}")
            event_ids.add(event_id)
            previous_version = version
            previous_hash = raw_hash
            values.append(value)
        return values

    @staticmethod
    def _replay_events(events: list[Mapping[str, Any]], *, until_event: int | None = None) -> dict[str, Any]:
        projection: dict[str, Any] = {}
        for event in events:
            version = int(event["stream_version"])
            if until_event is not None and version > until_event:
                break
            payload = event["payload"]
            projection = apply_projection_patch(projection, payload["projection_patch"])
            expected = str(payload.get("projection_sha256") or "")
            if expected and sha256_json(projection) != expected:
                stream_id = str(event.get("stream_id") or "unknown")
                raise KernelIntegrityError(f"projection hash mismatch after {stream_id}@{version}")
        return projection

    def replay(self, run_id: str, *, until_event: int | None = None) -> dict[str, Any]:
        return self._replay_events(self.read(run_id), until_event=until_event)

    @staticmethod
    def _tail_line(path: Path) -> bytes:
        with path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            position = handle.tell()
            buffer = b""
            while position > 0:
                size = min(65536, position)
                position -= size
                handle.seek(position)
                buffer = handle.read(size) + buffer
                stripped = buffer.rstrip(b"\r\n")
                boundary = max(stripped.rfind(b"\n"), stripped.rfind(b"\r"))
                if boundary >= 0:
                    return stripped[boundary + 1 :]
            return buffer.strip()

    def _append_context(self, run_id: str) -> tuple[dict[str, Any], str, int]:
        stream_path = self.stream_path(run_id)
        if not stream_path.exists():
            return {}, GENESIS_HASH, 0
        checkpoint_path = self.checkpoint_path(run_id)
        projection_path = self.runs_dir / f"{self._name(run_id)}.json"
        try:
            checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
            projection = json.loads(projection_path.read_text(encoding="utf-8"))
            tail = json.loads(self._tail_line(stream_path))
            if not isinstance(checkpoint, dict) or not isinstance(projection, dict) or not isinstance(tail, dict):
                raise ValueError("invalid append cache")
            if checkpoint.get("projection_sha256") != sha256_json(projection):
                raise ValueError("projection checkpoint mismatch")
            if tail.get("format") != EVENT_ENVELOPE_FORMAT or tail.get("schema_version") != EVENT_ENVELOPE_SCHEMA_VERSION:
                raise ValueError("tail requires full replay")
            if tail.get("event_hash") != envelope_hash(tail):
                raise ValueError("tail event hash mismatch")
            if (
                checkpoint.get("stream_version") != tail.get("stream_version")
                or checkpoint.get("event_hash") != tail.get("event_hash")
                or str(tail.get("stream_id") or "") != f"run:{run_id}"
            ):
                raise ValueError("tail checkpoint mismatch")
            return projection, str(tail["event_hash"]), int(tail["stream_version"])
        except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
            events = self.read(run_id)
            if not events:
                return {}, GENESIS_HASH, 0
            return self._replay_events(events), str(events[-1]["event_hash"]), int(events[-1]["stream_version"])

    def append_run(
        self,
        run_id: str,
        *,
        event_type: str,
        actor: str,
        projection: Mapping[str, Any],
        domain_event: Mapping[str, Any] | None = None,
        command_id: str = "",
        idempotency_key: str = "",
        causation_id: str = "",
        expected_version: int | None = None,
    ) -> dict[str, Any]:
        if self.readonly:
            raise RuntimeError("canonical kernel is read-only")
        previous_projection, previous_hash, previous_version = self._append_context(run_id)
        if expected_version is not None and previous_version != int(expected_version):
            raise ConcurrencyConflict(
                f"stream run:{run_id} is at version {previous_version}; expected {expected_version}"
            )
        stream_version = previous_version + 1
        event_id = str(uuid.uuid4())
        payload = {
            "projection_patch": projection_patch(previous_projection, projection, replace=not previous_version),
            "projection_sha256": sha256_json(projection),
            "domain_event": dict(domain_event) if isinstance(domain_event, Mapping) else None,
        }
        value: dict[str, Any] = {
            "format": EVENT_ENVELOPE_FORMAT,
            "schema_version": EVENT_ENVELOPE_SCHEMA_VERSION,
            "event_id": event_id,
            "stream_id": f"run:{run_id}",
            "stream_version": stream_version,
            "event_type": str(event_type),
            "command_id": command_id or str(uuid.uuid4()),
            "idempotency_key": str(idempotency_key),
            "correlation_id": f"run:{run_id}",
            "causation_id": str(causation_id),
            "actor": {"type": "system" if actor == "odysseus" else "actor", "id": str(actor)},
            "occurred_at": now_iso(),
            "payload": payload,
            "prev_event_hash": previous_hash,
        }
        value["event_hash"] = envelope_hash(value)
        path = self.stream_path(run_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line)
            handle.flush()
            os.fsync(handle.fileno())
        self.write_checkpoint(run_id, value, projection)
        return value

    def stream_version(self, run_id: str) -> int:
        events = self.read(run_id)
        return int(events[-1]["stream_version"]) if events else 0

    def write_checkpoint(self, run_id: str, event: Mapping[str, Any], projection: Mapping[str, Any]) -> None:
        if self.readonly:
            raise RuntimeError("canonical kernel is read-only")
        checkpoint = {
            "format": "odysseus-run-checkpoint-v1",
            "stream_id": f"run:{run_id}",
            "stream_version": int(event.get("stream_version") or 0),
            "event_hash": str(event.get("event_hash") or ""),
            "projection_sha256": sha256_json(projection),
            "updated_at": now_iso(),
        }
        self._atomic_json(self.checkpoint_path(run_id), checkpoint)

    def domain_events(self, run_id: str) -> list[dict[str, Any]]:
        values: list[dict[str, Any]] = []
        for event in self.read(run_id):
            domain = event.get("payload", {}).get("domain_event")
            if isinstance(domain, dict):
                values.append(domain)
        return values

    def verify_projection(self, run_id: str, projection: Mapping[str, Any]) -> dict[str, Any]:
        started = time.monotonic()
        events = self.read(run_id)
        replayed = self.replay(run_id)
        latest = events[-1] if events else {}
        checkpoint_path = self.checkpoint_path(run_id)
        checkpoint: dict[str, Any] = {}
        if checkpoint_path.exists():
            try:
                value = json.loads(checkpoint_path.read_text(encoding="utf-8"))
                checkpoint = value if isinstance(value, dict) else {}
            except (OSError, json.JSONDecodeError):
                checkpoint = {}
        errors: list[str] = []
        if replayed != dict(projection):
            errors.append("run projection differs from canonical replay")
        if events:
            if not checkpoint:
                errors.append("canonical stream checkpoint is missing or invalid")
            elif (
                checkpoint.get("stream_version") != latest.get("stream_version")
                or checkpoint.get("event_hash") != latest.get("event_hash")
                or checkpoint.get("projection_sha256") != sha256_json(replayed)
            ):
                errors.append("canonical checkpoint does not match stream tail")
        elapsed = max(0.0, time.monotonic() - started)
        return {
            "valid": not errors,
            "errors": errors,
            "stream_events": len(events),
            "stream_version": int(latest.get("stream_version") or 0),
            "event_hash": str(latest.get("event_hash") or ""),
            "projection_sha256": sha256_json(replayed),
            "elapsed_seconds": round(elapsed, 6),
        }

    def rebuild(self, run_id: str, *, dry_run: bool = False) -> dict[str, Any]:
        started = time.monotonic()
        events = self.read(run_id)
        if not events:
            raise KeyError(run_id)
        projection = self.replay(run_id)
        if not dry_run:
            if self.readonly:
                raise RuntimeError("canonical kernel is read-only")
            self._atomic_json(self.runs_dir / f"{self._name(run_id)}.json", projection)
            self.write_checkpoint(run_id, events[-1], projection)
        elapsed = max(0.0, time.monotonic() - started)
        return {
            "run_id": run_id,
            "stream_events": len(events),
            "stream_version": int(events[-1]["stream_version"]),
            "projection_sha256": sha256_json(projection),
            "elapsed_seconds": round(elapsed, 6),
            "events_per_second": round(len(events) / elapsed, 2) if elapsed else None,
            "dry_run": dry_run,
        }

    def rebuild_all(self, *, run_id: str = "", dry_run: bool = False) -> dict[str, Any]:
        names = [run_id] if run_id else sorted(path.stem for path in self.streams_dir.glob("*.ndjson"))
        started = time.monotonic()
        rebuilt = [self.rebuild(name, dry_run=dry_run) for name in names]
        elapsed = max(0.0, time.monotonic() - started)
        events = sum(int(item["stream_events"]) for item in rebuilt)
        return {
            "format": "odysseus-projection-rebuild-v1",
            "rebuilt": rebuilt,
            "runs": len(rebuilt),
            "events": events,
            "elapsed_seconds": round(elapsed, 6),
            "events_per_second": round(events / elapsed, 2) if elapsed else None,
            "dry_run": dry_run,
        }

    @staticmethod
    def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
