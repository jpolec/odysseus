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
        "run.attention",
        "run.review_ready",
        "run.accepted",
        "run.heartbeat",
        "run.stalled",
        "run.budget_exceeded",
        "worktree.creating",
        "worktree.ready",
        "worktree.dirty_base",
        "artifact.created",
        "delivery.started",
        "delivery.applied",
        "delivery.failed",
        "integration.candidates_presented",
        "integration.disposition_recorded",
        "integration.queued",
        "integration.started",
        "integration.artifact_applied",
        "integration.completed",
        "integration.conflict",
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
        "agent.question",
        "agent.permission_request",
        "agent.blocked",
        "agent.decision_required",
        "check.output",
        "check.completed",
        "workflow.retry",
        "review.sent_back",
        "review.accepted",
        "review.comment",
        "pr.creating",
        "pr.created",
        "pr.failed",
        "ci.started",
        "ci.passed",
        "ci.failed",
        "ci.poll_failed",
        "ci.retry_queued",
        "ci.retry_pushed",
        "ci.retry_exhausted",
        "system.recovered",
        "session.adopted",
        "session.resumed",
        "session.takeover_ready",
        "inbox.created",
        "inbox.promoted",
        "attention.answered",
        "attention.resolved",
        "evaluation.started",
        "evaluation.completed",
        "evaluation.failed",
        "epic.created",
        "epic.proposed",
        "epic.activated",
        "epic.task_created",
        "epic.completed",
        "epic.failed",
        "dag.dependency_met",
        "dag.blocked",
        "dag.unblocked",
        "planner.started",
        "planner.completed",
        "planner.failed",
        "skill.selected",
        "skill.loaded",
        "context.receipt.created",
        "knowledge.selected",
        "environment.prepared",
        "environment.starting",
        "environment.started",
        "environment.setup_started",
        "environment.setup_completed",
        "environment.approved",
        "environment.rejected",
        "resource.reclaimed",
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
