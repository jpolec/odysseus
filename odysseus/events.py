"""Normalized events shared by every Odysseus agent lane."""

from __future__ import annotations

import datetime as dt
from dataclasses import asdict, dataclass, field
from typing import Any, Mapping


EVENT_SCHEMA_VERSION = 1

EVENT_TYPES = frozenset(
    {
        "run.queued",
        "run.started",
        "run.status",
        "run.cancel_requested",
        "run.cancelled",
        "run.failed",
        "run.review_ready",
        "run.accepted",
        "worktree.creating",
        "worktree.ready",
        "worktree.dirty_base",
        "step.started",
        "step.completed",
        "step.failed",
        "agent.output",
        "agent.message",
        "agent.reasoning",
        "agent.session",
        "agent.tool.started",
        "agent.tool.completed",
        "agent.usage",
        "agent.cost",
        "agent.completed",
        "check.output",
        "check.completed",
        "workflow.retry",
        "review.sent_back",
        "review.accepted",
        "pr.creating",
        "pr.created",
        "pr.failed",
        "system.recovered",
        "session.adopted",
        "session.resumed",
        "session.takeover_ready",
        "inbox.created",
        "inbox.promoted",
    }
)


def now_iso() -> str:
    return (
        dt.datetime.now(dt.timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


@dataclass(frozen=True, slots=True)
class Event:
    """One append-only NDJSON record in a run history."""

    run_id: str
    type: str
    source: str
    data: Mapping[str, Any] = field(default_factory=dict)
    seq: int = 0
    ts: str = field(default_factory=now_iso)
    v: int = EVENT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.type not in EVENT_TYPES:
            raise ValueError(f"unknown Odysseus event type: {self.type}")
        if not self.run_id:
            raise ValueError("run_id is required")
        if not self.source:
            raise ValueError("event source is required")
        if self.seq < 0:
            raise ValueError("event seq cannot be negative")

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["data"] = dict(self.data)
        return value
