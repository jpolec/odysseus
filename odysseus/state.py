"""Strict, non-destructive verification for persisted Odysseus state."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .events import EVENT_SCHEMA_VERSION
from .store import RUN_SCHEMA_VERSION


JSON_OBJECT_FILES = (
    "config.json",
    "projects.json",
    "attention.json",
    "inbox.json",
)
JSON_OBJECT_DIRS = (
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
            if not isinstance(seq, int) or seq <= previous_seq:
                errors.append(f"{path}:{number}: event seq must be a strictly increasing integer")
            elif isinstance(seq, int):
                previous_seq = seq


def verify_state(root: Path | str) -> dict[str, Any]:
    """Scan every durable format without creating or migrating any files."""

    state_root = Path(root).expanduser()
    errors: list[str] = []
    counts = {"runs": 0, "events": 0, "epics": 0, "json_files": 0, "ndjson_files": 0}
    if not state_root.exists():
        return {"valid": True, "root": str(state_root), "errors": [], **counts}
    if not state_root.is_dir():
        return {"valid": False, "root": str(state_root), "errors": [f"{state_root}: not a directory"], **counts}

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
                if str(value.get("id") or "") != path.stem:
                    errors.append(f"{path}: run id does not match file name")
                version = value.get("schema_version")
                if not isinstance(version, int) or version < 1 or version > RUN_SCHEMA_VERSION:
                    errors.append(
                        f"{path}: unsupported run schema {version!r}; reader supports 1..{RUN_SCHEMA_VERSION}"
                    )
            elif name == "epics":
                counts["epics"] += 1
                if str(value.get("id") or "") != path.stem:
                    errors.append(f"{path}: epic id does not match file name")
                version = value.get("schema_version")
                if not isinstance(version, int) or version != 1:
                    errors.append(f"{path}: unsupported epic schema {version!r}; reader supports 1")

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

    return {"valid": not errors, "root": str(state_root), "errors": errors, **counts}
