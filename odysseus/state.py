"""Strict, non-destructive verification for persisted Odysseus state."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from .events import EVENT_SCHEMA_VERSION
from .epics import EPIC_SCHEMA_VERSION
from .kernel import EventKernel, KernelIntegrityError
from .store import RUN_SCHEMA_VERSION
from .worker_leases import WORKER_LEASE_FORMAT


JSON_OBJECT_FILES = (
    "config.json",
    "projects.json",
    "attention.json",
    "inbox.json",
)
JSON_OBJECT_DIRS = (
    "commands",
    "runs",
    "epics",
    "project_profiles",
    "project_knowledge",
    "project_skill_policies",
)
NDJSON_DIRS = ("events",)
NDJSON_FILES = ("notifications.ndjson",)


def _json(path: Path, errors: list[str]) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        errors.append(f"{path}: cannot read: {exc}")
    except json.JSONDecodeError as exc:
        errors.append(f"{path}: invalid JSON at line {exc.lineno}, column {exc.colno}")
    return None


def _verify_object(path: Path, errors: list[str]) -> dict[str, Any] | None:
    value = _json(path, errors)
    if value is not None and not isinstance(value, dict):
        errors.append(f"{path}: expected a JSON object")
        return None
    return value if isinstance(value, dict) else None


def _verify_ndjson(path: Path, errors: list[str], counts: dict[str, int]) -> None:
    previous_seq = 0
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        errors.append(f"{path}: cannot read: {exc}")
        return
    for number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append(f"{path}:{number}: invalid NDJSON: {exc.msg}")
            continue
        if not isinstance(value, dict):
            errors.append(f"{path}:{number}: expected a JSON object")
            continue
        counts["events"] += 1
        if path.parent.name == "events":
            version = value.get("v")
            if not isinstance(version, int) or version < 1 or version > EVENT_SCHEMA_VERSION:
                errors.append(
                    f"{path}:{number}: unsupported event schema {version!r}; reader supports 1..{EVENT_SCHEMA_VERSION}"
                )
            if str(value.get("run_id") or "") != path.stem:
                errors.append(f"{path}:{number}: run_id does not match journal name")
            seq = value.get("seq")
            if not isinstance(seq, int) or seq != previous_seq + 1:
                errors.append(f"{path}:{number}: event seq must be a contiguous integer starting at 1")
            elif isinstance(seq, int):
                previous_seq = seq


def verify_state(root: Path | str) -> dict[str, Any]:
    """Scan every durable format without creating or migrating any files."""

    state_root = Path(root).expanduser()
    errors: list[str] = []
    counts = {
        "runs": 0,
        "events": 0,
        "epics": 0,
        "json_files": 0,
        "ndjson_files": 0,
        "streams": 0,
        "stream_events": 0,
        "checkpoints": 0,
        "legacy_runs": 0,
        "commands": 0,
        "worker_leases": 0,
    }
    warnings: list[str] = []
    if not state_root.exists():
        return {"valid": True, "root": str(state_root), "errors": [], "warnings": [], **counts}
    if not state_root.is_dir():
        return {"valid": False, "root": str(state_root), "errors": [f"{state_root}: not a directory"], "warnings": [], **counts}

    run_records: dict[str, dict[str, Any]] = {}

    for name in JSON_OBJECT_FILES:
        path = state_root / name
        if path.exists():
            counts["json_files"] += 1
            _verify_object(path, errors)

    for name in JSON_OBJECT_DIRS:
        directory = state_root / name
        if not directory.exists():
            continue
        if not directory.is_dir():
            errors.append(f"{directory}: expected a directory")
            continue
        for path in sorted(directory.glob("*.json")):
            counts["json_files"] += 1
            value = _verify_object(path, errors)
            if value is None:
                continue
            if name == "runs":
                counts["runs"] += 1
                run_records[path.stem] = value
                if str(value.get("id") or "") != path.stem:
                    errors.append(f"{path}: run id does not match file name")
                version = value.get("schema_version")
                if not isinstance(version, int) or version < 1 or version > RUN_SCHEMA_VERSION:
                    errors.append(
                        f"{path}: unsupported run schema {version!r}; reader supports 1..{RUN_SCHEMA_VERSION}"
                    )
                lease = value.get("worker_lease")
                if lease:
                    counts["worker_leases"] += 1
                    if not isinstance(lease, dict):
                        errors.append(f"{path}: worker_lease must be an object")
                    else:
                        if lease.get("format") != WORKER_LEASE_FORMAT:
                            errors.append(f"{path}: unsupported worker lease format")
                        if str(lease.get("run_id") or "") != path.stem:
                            errors.append(f"{path}: worker lease run id does not match file name")
                        if not str(lease.get("lease_id") or ""):
                            errors.append(f"{path}: worker lease id is required")
                        if not str(lease.get("worker_id") or ""):
                            errors.append(f"{path}: worker lease owner is required")
                        if not isinstance(lease.get("epoch"), int) or int(lease.get("epoch") or 0) < 1:
                            errors.append(f"{path}: worker lease epoch must be a positive integer")
                        if not isinstance(lease.get("stream_version_at_claim"), int) or int(
                            lease.get("stream_version_at_claim") or 0
                        ) < 1:
                            errors.append(f"{path}: worker lease claim stream version is invalid")
                        if not isinstance(lease.get("ttl_seconds"), int) or int(
                            lease.get("ttl_seconds") or 0
                        ) < 1:
                            errors.append(f"{path}: worker lease TTL must be a positive integer")
                        if not isinstance(lease.get("active"), bool):
                            errors.append(f"{path}: worker lease active flag must be boolean")
                        if (
                            not str(lease.get("acquired_at") or "")
                            or not str(lease.get("heartbeat_at") or "")
                            or not str(lease.get("expires_at") or "")
                        ):
                            errors.append(f"{path}: worker lease timestamps are incomplete")
                        if lease.get("active") and str(lease.get("released_at") or ""):
                            errors.append(f"{path}: active worker lease cannot have a release timestamp")
                        if lease.get("active") is False and (
                            not str(lease.get("released_at") or "")
                            or not str(lease.get("release_reason") or "")
                        ):
                            errors.append(f"{path}: released worker lease is missing release evidence")
            elif name == "epics":
                counts["epics"] += 1
                if str(value.get("id") or "") != path.stem:
                    errors.append(f"{path}: epic id does not match file name")
                version = value.get("schema_version")
                if not isinstance(version, int) or version < 1 or version > EPIC_SCHEMA_VERSION:
                    errors.append(
                        f"{path}: unsupported epic schema {version!r}; "
                        f"reader supports 1..{EPIC_SCHEMA_VERSION}"
                    )
            elif name == "commands":
                counts["commands"] += 1
                if value.get("format") != "odysseus-command-receipt-v1":
                    errors.append(f"{path}: unsupported command receipt format")
                command = value.get("command") if isinstance(value.get("command"), dict) else {}
                if command.get("format") != "odysseus-command-envelope-v1":
                    errors.append(f"{path}: invalid command envelope")
                if value.get("state") not in {"executing", "completed", "failed", "unknown"}:
                    errors.append(f"{path}: invalid command state")

    for name in NDJSON_DIRS:
        directory = state_root / name
        if not directory.exists():
            continue
        if not directory.is_dir():
            errors.append(f"{directory}: expected a directory")
            continue
        for path in sorted(directory.glob("*.ndjson")):
            counts["ndjson_files"] += 1
            _verify_ndjson(path, errors, counts)
    for name in NDJSON_FILES:
        path = state_root / name
        if path.exists():
            counts["ndjson_files"] += 1
            _verify_ndjson(path, errors, counts)

    kernel = EventKernel(state_root, readonly=True)
    canonical_started = time.monotonic()
    stream_names: set[str] = set()
    if kernel.streams_dir.exists():
        if not kernel.streams_dir.is_dir():
            errors.append(f"{kernel.streams_dir}: expected a directory")
        else:
            for path in sorted(kernel.streams_dir.glob("*.ndjson")):
                counts["streams"] += 1
                counts["ndjson_files"] += 1
                stream_names.add(path.stem)
                try:
                    events = kernel.read(path.stem)
                    counts["stream_events"] += len(events)
                    projection = run_records.get(path.stem)
                    if projection is None:
                        errors.append(f"{path}: canonical stream has no materialized run projection")
                        continue
                    result = kernel.verify_projection(path.stem, projection)
                    for message in result["errors"]:
                        errors.append(f"{path}: {message}")
                    if kernel.checkpoint_path(path.stem).exists():
                        counts["checkpoints"] += 1
                except (KernelIntegrityError, KeyError, RuntimeError) as exc:
                    errors.append(f"{path}: {exc}")
    for run_id in sorted(set(run_records) - stream_names):
        counts["legacy_runs"] += 1
        warnings.append(f"run:{run_id} has no canonical stream; open state with migration before relying on replay")

    canonical_elapsed = max(0.0, time.monotonic() - canonical_started)
    counts["canonical_verify_seconds"] = round(canonical_elapsed, 6)
    counts["replay_events_per_second"] = (
        round(counts["stream_events"] / canonical_elapsed, 2)
        if counts["stream_events"] and canonical_elapsed
        else None
    )

    return {"valid": not errors, "root": str(state_root), "errors": errors, "warnings": warnings, **counts}
