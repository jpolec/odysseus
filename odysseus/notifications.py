"""Small dependency-free notification fan-out for attention-worthy events."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Mapping
from urllib import request

from .events import now_iso

if TYPE_CHECKING:
    from .store import RunStore


NOTIFY_EVENTS = frozenset(
    {
        "run.review_ready",
        "run.failed",
        "integration.conflict",
        "agent.question",
        "agent.permission_request",
        "agent.blocked",
        "agent.decision_required",
        "ci.failed",
        "ci.retry_exhausted",
        "ci.passed",
        "run.stalled",
        "run.budget_exceeded",
        "review.comment",
    }
)


class NotificationManager:
    def __init__(self, store: RunStore) -> None:
        self.store = store
        self.journal = Path(store.root) / "notifications.ndjson"
        self._lock = threading.Lock()

    def notify(
        self,
        run: Mapping[str, Any],
        event_type: str,
        data: Mapping[str, Any],
    ) -> None:
        if event_type not in NOTIFY_EVENTS:
            return
        destinations = self.store.config().get("notifications") or []
        if not isinstance(destinations, list):
            return
        for destination in destinations[:20]:
            if not isinstance(destination, dict) or not destination.get("url"):
                continue
            thread = threading.Thread(
                target=self._deliver,
                args=(dict(destination), dict(run), event_type, dict(data)),
                name="odysseus-notify",
                daemon=True,
            )
            thread.start()

    def _deliver(
        self,
        destination: dict[str, Any],
        run: dict[str, Any],
        event_type: str,
        data: dict[str, Any],
    ) -> None:
        kind = str(destination.get("type") or "webhook").lower()
        title = str(data.get("title") or run.get("title") or run.get("id") or "Odysseus")
        message = str(data.get("message") or data.get("question") or event_type)
        payload = {
            "source": "odysseus",
            "event": event_type,
            "run_id": run.get("id"),
            "epic_id": run.get("epic_id"),
            "project_id": run.get("project_id"),
            "title": title,
            "message": message,
            "status": run.get("status"),
            "created_at": now_iso(),
        }
        headers = {"User-Agent": "Odysseus/0.4"}
        if kind == "ntfy":
            body = message.encode("utf-8")
            headers.update({"Content-Type": "text/plain; charset=utf-8", "Title": title[:200]})
        elif kind == "slack":
            body = json.dumps({"text": f"*{title}*\n{message}\n`{event_type}`"}).encode("utf-8")
            headers["Content-Type"] = "application/json"
        else:
            body = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        error = ""
        delivered = False
        for delay in (0, 1, 3):
            if delay:
                time.sleep(delay)
            try:
                call = request.Request(str(destination["url"]), data=body, headers=headers, method="POST")
                with request.urlopen(call, timeout=8) as response:  # noqa: S310 - explicit operator config
                    if 200 <= int(response.status) < 300:
                        delivered = True
                        error = ""
                        break
                    error = f"HTTP {response.status}"
            except Exception as exc:  # notification boundary
                error = str(exc)
        self._record(
            {
                "ts": now_iso(),
                "event": event_type,
                "run_id": run.get("id"),
                "destination": str(destination.get("name") or kind),
                "delivered": delivered,
                "error": error[:1000],
            }
        )

    def _record(self, value: Mapping[str, Any]) -> None:
        line = json.dumps(dict(value), ensure_ascii=False, separators=(",", ":")) + "\n"
        with self._lock:
            with self.journal.open("a", encoding="utf-8") as handle:
                handle.write(line)
