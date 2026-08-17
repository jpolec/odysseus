"""Durable operator-attention queue shared across projects and runs."""

from __future__ import annotations

import json
import re
import secrets
from typing import Any, Mapping

from .events import now_iso


ATTENTION_TYPES = frozenset(
    {
        "review",
        "question",
        "permission_request",
        "blocked",
        "decision_required",
        "evaluation_failed",
        "evaluation_review",
        "ci_failed",
        "merge_conflict",
        "stalled",
        "budget",
        "review_comment",
    }
)
ATTENTION_PRIORITIES = frozenset({"low", "medium", "high", "critical"})


class AttentionQueue:
    """Small JSON queue containing only work that currently needs a human."""

    def __init__(self, store: Any) -> None:
        self.store = store
        self.path = store.root / "attention.json"

    def _read(self) -> dict[str, dict[str, Any]]:
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            value = {}
        return value if isinstance(value, dict) else {}

    def list(
        self,
        *,
        status: str | None = None,
        run_id: str | None = None,
    ) -> list[dict[str, Any]]:
        with self.store.locked():
            values = list(self._read().values())
        if status:
            values = [item for item in values if item.get("status") == status]
        if run_id:
            values = [item for item in values if item.get("run_id") == run_id]
        priority = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        return sorted(
            values,
            key=lambda item: (
                priority.get(str(item.get("priority")), 9),
                str(item.get("created_at", "")),
            ),
        )

    def get(self, item_id: str) -> dict[str, Any]:
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", item_id):
            raise KeyError(item_id)
        with self.store.locked():
            value = self._read().get(item_id)
        if not isinstance(value, dict):
            raise KeyError(item_id)
        return value

    def create(self, request: Mapping[str, Any]) -> dict[str, Any]:
        item_type = str(request.get("type") or "decision_required")
        if item_type not in ATTENTION_TYPES:
            raise ValueError(f"unsupported attention type: {item_type}")
        priority = str(request.get("priority") or "medium")
        if priority not in ATTENTION_PRIORITIES:
            raise ValueError(f"unsupported attention priority: {priority}")
        title = str(request.get("title") or "Operator decision required").strip()
        message = str(request.get("message") or "").strip()
        title = str(self.store.redaction.redact(title, boundary="attention")[0])
        message = str(self.store.redaction.redact(message, boundary="attention")[0])
        raw_options = request.get("options") or []
        if not isinstance(raw_options, list):
            raise ValueError("attention options must be a list")
        options: list[dict[str, str]] = []
        for index, option in enumerate(raw_options[:12]):
            if isinstance(option, str):
                value = option.strip()
                if value:
                    options.append(
                        {
                            "id": str(self.store.redaction.redact(value, boundary="attention")[0]),
                            "label": str(self.store.redaction.redact(value, boundary="attention")[0]),
                        }
                    )
            elif isinstance(option, dict):
                option_id = str(option.get("id") or option.get("value") or index + 1).strip()
                label = str(option.get("label") or option.get("description") or option_id).strip()
                if option_id and label:
                    options.append(
                        {
                            "id": str(self.store.redaction.redact(option_id, boundary="attention")[0]),
                            "label": str(self.store.redaction.redact(label, boundary="attention")[0]),
                        }
                    )
        stamp = now_iso()
        dedupe_key = str(request.get("dedupe_key") or "").strip()
        with self.store.locked():
            values = self._read()
            if dedupe_key:
                for existing in values.values():
                    if existing.get("dedupe_key") == dedupe_key and existing.get("status") == "open":
                        return dict(existing)
            item_id = f"attention-{stamp.replace(':', '').replace('-', '')[:15]}-{secrets.token_hex(2)}"
            record = {
                "id": item_id,
                "type": item_type,
                "priority": priority,
                "title": title,
                "message": message,
                "options": options,
                "data": self.store.redaction.redact(
                    request.get("data") if isinstance(request.get("data"), dict) else {},
                    boundary="attention",
                )[0],
                "run_id": str(request.get("run_id") or ""),
                "epic_id": str(request.get("epic_id") or ""),
                "project_id": str(request.get("project_id") or ""),
                "status": "open",
                "response": "",
                "resolution": "",
                "dedupe_key": dedupe_key,
                "created_at": stamp,
                "updated_at": stamp,
                "resolved_at": None,
            }
            values[item_id] = record
            self.store._atomic_json(self.path, values)
        return record

    def respond(self, item_id: str, response: str) -> dict[str, Any]:
        answer = str(self.store.redaction.redact(response.strip(), boundary="attention_response")[0])
        if not answer:
            raise ValueError("attention response is required")
        stamp = now_iso()
        with self.store.locked():
            values = self._read()
            if item_id not in values:
                raise KeyError(item_id)
            item = values[item_id]
            if item.get("status") != "open":
                raise ValueError("attention item is already resolved")
            item.update(
                {
                    "status": "answered",
                    "response": answer,
                    "resolution": "answered",
                    "updated_at": stamp,
                    "resolved_at": stamp,
                }
            )
            self.store._atomic_json(self.path, values)
            return dict(item)

    def resolve(self, item_id: str, resolution: str = "resolved") -> dict[str, Any]:
        stamp = now_iso()
        with self.store.locked():
            values = self._read()
            if item_id not in values:
                raise KeyError(item_id)
            item = values[item_id]
            item.update(
                {
                    "status": "resolved",
                    "resolution": resolution,
                    "updated_at": stamp,
                    "resolved_at": stamp,
                }
            )
            self.store._atomic_json(self.path, values)
            return dict(item)

    def resolve_for_run(self, run_id: str, *, resolution: str) -> list[str]:
        stamp = now_iso()
        changed: list[str] = []
        with self.store.locked():
            values = self._read()
            for item in values.values():
                if item.get("run_id") != run_id or item.get("status") != "open":
                    continue
                item.update(
                    {
                        "status": "resolved",
                        "resolution": resolution,
                        "updated_at": stamp,
                        "resolved_at": stamp,
                    }
                )
                changed.append(str(item["id"]))
            if changed:
                self.store._atomic_json(self.path, values)
        return changed
