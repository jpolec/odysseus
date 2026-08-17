"""Durable follow-up inbox shared by projects and agent runs."""

from __future__ import annotations

import json
import re
import secrets
from pathlib import Path
from typing import Any, Mapping

from .events import now_iso


class Inbox:
    def __init__(self, store: Any) -> None:
        self.store = store
        self.path = store.root / "inbox.json"

    def _read(self) -> dict[str, dict[str, Any]]:
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            value = {}
        return value if isinstance(value, dict) else {}

    def list(self, *, status: str | None = None) -> list[dict[str, Any]]:
        with self.store.locked():
            values = list(self._read().values())
        if status:
            values = [item for item in values if item.get("status") == status]
        return sorted(values, key=lambda item: str(item.get("created_at", "")), reverse=True)

    def get(self, item_id: str) -> dict[str, Any]:
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", item_id):
            raise KeyError(item_id)
        with self.store.locked():
            value = self._read().get(item_id)
        if not isinstance(value, dict):
            raise KeyError(item_id)
        return value

    def create(self, request: Mapping[str, Any]) -> dict[str, Any]:
        title = str(request.get("title") or "").strip()
        task = str(request.get("task") or request.get("body") or "").strip()
        if not title:
            title = task.splitlines()[0][:100] if task else "Follow-up"
        if not task:
            task = title
        title = str(self.store.redaction.redact(title, boundary="inbox")[0])
        task = str(self.store.redaction.redact(task, boundary="inbox")[0])
        stamp = now_iso()
        item_id = f"followup-{stamp.replace(':', '').replace('-', '')[:15]}-{secrets.token_hex(2)}"
        record = {
            "id": item_id,
            "title": title,
            "task": task,
            "project_id": str(request.get("project_id") or ""),
            "project_path": str(request.get("project_path") or ""),
            "run_id": str(request.get("run_id") or ""),
            "source": str(request.get("source") or "human"),
            "priority": str(request.get("priority") or "normal"),
            "status": "open",
            "created_at": stamp,
            "updated_at": stamp,
        }
        with self.store.locked():
            values = self._read()
            values[item_id] = record
            self.store._atomic_json(self.path, values)
        return record

    def update(self, item_id: str, **changes: Any) -> dict[str, Any]:
        allowed = {"status", "priority", "title", "task"}
        if set(changes) - allowed:
            raise ValueError("unsupported inbox change")
        redacted_changes = self.store.redaction.redact(changes, boundary="inbox")[0]
        with self.store.locked():
            values = self._read()
            if item_id not in values:
                raise KeyError(item_id)
            values[item_id].update(redacted_changes if isinstance(redacted_changes, dict) else changes)
            values[item_id]["updated_at"] = now_iso()
            self.store._atomic_json(self.path, values)
            return dict(values[item_id])

    def ingest_agent_file(self, run: Mapping[str, Any], worktree: Path) -> list[dict[str, Any]]:
        """Import the intentionally small agent-to-operator handoff file."""
        path = worktree / ".odysseus-followups.json"
        if not path.is_file():
            return []
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"invalid {path.name}: {exc}") from exc
        finally:
            try:
                path.unlink()
            except OSError:
                pass
        if not isinstance(raw, list):
            raise ValueError(f"{path.name} must contain a JSON array")
        created: list[dict[str, Any]] = []
        for item in raw[:50]:
            if not isinstance(item, dict):
                continue
            created.append(
                self.create(
                    {
                        **item,
                        "project_id": run.get("project_id", ""),
                        "project_path": run.get("project_path", ""),
                        "run_id": run.get("id", ""),
                        "source": "agent",
                    }
                )
            )
        return created
