"""Multi-project registry and GitHub metadata discovery."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlparse

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


def repository_identity(remote: str) -> dict[str, str]:
    """Return a human-facing repository identity without touching the network."""
    value = remote.strip().removesuffix(".git").rstrip("/")
    if not value:
        return {"provider": "", "repository": "", "repository_name": ""}
    scp = re.match(r"(?:[^@]+@)?(?P<host>[^:]+):(?P<path>.+)$", value)
    if scp and "://" not in value:
        host = scp.group("host")
        path = scp.group("path").strip("/")
    else:
        parsed = urlparse(value)
        if parsed.scheme and parsed.netloc:
            host = (parsed.hostname or parsed.netloc).lower()
            path = parsed.path.strip("/")
        else:
            host = ""
            path = value.strip("/")
    name = path.rsplit("/", 1)[-1] if path else ""
    return {"provider": host, "repository": path, "repository_name": name}


def _enrich_project(record: Mapping[str, Any]) -> dict[str, Any]:
    value = dict(record)
    path = str(value.get("path") or "")
    folder_name = Path(path).name if path else ""
    identity = repository_identity(str(value.get("remote") or ""))
    stored_name = str(value.get("name") or "").strip()
    source = str(value.get("name_source") or "")
    if not source:
        source = "custom" if stored_name and stored_name != folder_name else "automatic"
    display_name = stored_name if source == "custom" else identity["repository_name"] or stored_name or folder_name or "project"
    legacy_git_repository = bool(value.get("branch") or value.get("remote"))
    if path and not legacy_git_repository:
        legacy_git_repository = (Path(path) / ".git").exists()
    value.update(
        {
            "name": display_name,
            "display_name": display_name,
            "name_source": source,
            "folder_name": folder_name,
            "repository": identity["repository"],
            "provider": identity["provider"],
            "git_repository": bool(value.get("git_repository")) if "git_repository" in value else legacy_git_repository,
        }
    )
    return value


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

    def _managed_worktree(self, record: Mapping[str, Any]) -> bool:
        try:
            Path(str(record.get("path") or "")).resolve().relative_to(self.store.worktrees_dir.resolve())
            return True
        except (ValueError, OSError):
            return False

    def list(self) -> list[dict[str, Any]]:
        with self.store.locked():
            values = [_enrich_project(item) for item in self._read().values() if not self._managed_worktree(item)]
        return sorted(values, key=lambda item: (str(item.get("display_name", "")).lower(), str(item.get("path", ""))))

    def get(self, identifier: str) -> dict[str, Any]:
        with self.store.locked():
            value = self._read().get(identifier)
        if not isinstance(value, dict):
            raise KeyError(identifier)
        return _enrich_project(value)

    def describe(self, path: Path | str) -> dict[str, Any]:
        """Describe a local Git repository without registering or modifying it."""
        resolved = Path(path).expanduser().resolve()
        if not resolved.is_dir():
            return {}
        repository = _git(resolved, "rev-parse", "--show-toplevel")
        if not repository:
            return {}
        resolved = Path(repository).resolve()
        remote = _git(resolved, "remote", "get-url", "origin")
        identity = repository_identity(remote)
        return _enrich_project(
            {
                "id": project_id(resolved),
                "name": identity["repository_name"] or resolved.name,
                "name_source": "automatic",
                "path": str(resolved),
                "remote": remote,
                "github_url": github_url(remote),
                "branch": _git(resolved, "branch", "--show-current"),
                "git_repository": True,
                "tags": [],
            }
        )

    def upsert(
        self,
        path: Path | str,
        changes: Mapping[str, Any] | None = None,
        *,
        require_git: bool = False,
    ) -> dict[str, Any]:
        resolved = Path(path).expanduser().resolve()
        if not resolved.is_dir():
            raise ValueError(f"project directory does not exist: {resolved}")
        repository = _git(resolved, "rev-parse", "--show-toplevel")
        if require_git and not repository:
            raise ValueError(f"not a Git repository: {resolved}")
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
            explicit_name = str(incoming.get("name") or "").strip()
            current_name = str(current.get("name") or "").strip()
            current_source = str(current.get("name_source") or "")
            if not current_source:
                current_source = "custom" if current_name and current_name != resolved.name else "automatic"
            identity = repository_identity(remote or str(current.get("remote") or ""))
            name_source = "custom" if explicit_name else current_source
            automatic_name = identity["repository_name"] or resolved.name
            name = explicit_name or (current_name if name_source == "custom" else automatic_name)
            record = {
                "id": identifier,
                "name": name,
                "name_source": name_source,
                "path": str(resolved),
                "folder_name": resolved.name,
                "repository": identity["repository"],
                "provider": identity["provider"],
                "git_repository": bool(repository),
                "tags": sorted(set(tag.strip() for tag in tags if tag.strip())),
                "remote": remote or str(current.get("remote") or ""),
                "github_url": github_url(remote) or str(current.get("github_url") or ""),
                "branch": branch or str(current.get("branch") or ""),
                "created_at": current.get("created_at") or stamp,
                "updated_at": stamp,
            }
            values[identifier] = record
            self.store._atomic_json(self.path, values)
        return _enrich_project(record)

    def remove(self, identifier: str) -> None:
        with self.store.locked():
            values = self._read()
            if identifier not in values:
                raise KeyError(identifier)
            del values[identifier]
            self.store._atomic_json(self.path, values)
