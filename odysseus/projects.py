"""Multi-project registry and GitHub metadata discovery."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any, Mapping

from .events import now_iso


def project_id(path: Path | str) -> str:
    resolved = str(Path(path).expanduser().resolve())
    slug = re.sub(r"[^a-z0-9]+", "-", Path(resolved).name.lower()).strip("-") or "project"
    digest = hashlib.sha256(resolved.encode("utf-8")).hexdigest()[:10]
    return f"{slug[:32]}-{digest}"


def _git(path: Path, *args: str) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(path), *args],
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def github_url(remote: str) -> str:
    """Convert common GitHub remotes to a browser URL."""
    value = remote.strip().removesuffix(".git")
    match = re.match(r"git@github\.com:(.+)$", value)
    if match:
        return f"https://github.com/{match.group(1)}"
    match = re.match(r"ssh://git@github\.com/(.+)$", value)
    if match:
        return f"https://github.com/{match.group(1)}"
    return value if value.startswith("https://github.com/") else ""


class ProjectRegistry:
    def __init__(self, store: Any) -> None:
        self.store = store
        self.path = store.root / "projects.json"

    def _read(self) -> dict[str, dict[str, Any]]:
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            value = {}
        return value if isinstance(value, dict) else {}

    def list(self) -> list[dict[str, Any]]:
        with self.store.locked():
            values = list(self._read().values())
        return sorted(values, key=lambda item: (str(item.get("name", "")).lower(), str(item.get("path", ""))))

    def get(self, identifier: str) -> dict[str, Any]:
        with self.store.locked():
            value = self._read().get(identifier)
        if not isinstance(value, dict):
            raise KeyError(identifier)
        return value

    def upsert(self, path: Path | str, changes: Mapping[str, Any] | None = None) -> dict[str, Any]:
        resolved = Path(path).expanduser().resolve()
        if not resolved.is_dir():
            raise ValueError(f"project directory does not exist: {resolved}")
        repository = _git(resolved, "rev-parse", "--show-toplevel")
        if repository:
            resolved = Path(repository).resolve()
        identifier = project_id(resolved)
        stamp = now_iso()
        remote = _git(resolved, "remote", "get-url", "origin")
        branch = _git(resolved, "branch", "--show-current")
        incoming = dict(changes or {})
        with self.store.locked():
            values = self._read()
            current = values.get(identifier, {})
            tags = incoming.get("tags", current.get("tags", []))
            if not isinstance(tags, list) or not all(isinstance(item, str) for item in tags):
                raise ValueError("project tags must be a list of strings")
            record = {
                "id": identifier,
                "name": str(incoming.get("name") or current.get("name") or resolved.name),
                "path": str(resolved),
                "tags": sorted(set(tag.strip() for tag in tags if tag.strip())),
                "remote": remote or str(current.get("remote") or ""),
                "github_url": github_url(remote) or str(current.get("github_url") or ""),
                "branch": branch or str(current.get("branch") or ""),
                "created_at": current.get("created_at") or stamp,
                "updated_at": stamp,
            }
            values[identifier] = record
            self.store._atomic_json(self.path, values)
        return record

    def remove(self, identifier: str) -> None:
        with self.store.locked():
            values = self._read()
            if identifier not in values:
                raise KeyError(identifier)
            del values[identifier]
            self.store._atomic_json(self.path, values)
