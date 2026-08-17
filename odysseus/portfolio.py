"""Portfolio-level engineering outcomes for the Odysseus lead dashboard."""

from __future__ import annotations

import copy
import threading
import weakref
from datetime import datetime, timedelta, timezone
from statistics import median
from typing import TYPE_CHECKING, Any, Mapping

if TYPE_CHECKING:
    from .store import RunStore


DELIVERED_STATUSES = frozenset({"applied", "pr_created", "integrated_applied", "integrated_pr_created"})
TERMINAL_STATUSES = frozenset({"accepted", "pr_created", "failed", "cancelled", "rejected"})
CORRECTIVE_USER_EVENTS = frozenset(
    {"attention.answered", "attention.resolved", "review.sent_back", "run.cancel_requested"}
)
RETRY_EVENTS = frozenset({"workflow.retry", "review.sent_back", "ci.retry_queued", "ci.retry_pushed"})

_PORTFOLIO_CACHE_LOCK = threading.Lock()
_PORTFOLIO_CACHE: weakref.WeakKeyDictionary[RunStore, dict[str, Any]] = weakref.WeakKeyDictionary()


def _time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _duration_minutes(run: Mapping[str, Any]) -> float | None:
    start = _time(run.get("started_at"))
    end = _time(run.get("finished_at") or run.get("artifact_created_at"))
    if not start or not end:
        return None
    return max(0.0, (end - start).total_seconds() / 60.0)


def _cost(run: Mapping[str, Any], events: list[dict[str, Any]]) -> float | None:
    metrics = run.get("metrics") if isinstance(run.get("metrics"), dict) else {}
    if metrics.get("cost_observed") is True:
        try:
            return max(0.0, float(metrics.get("cost_usd") or 0.0))
        except (TypeError, ValueError):
            return None
    observed = []
    for event in events:
        if event.get("type") != "agent.cost":
            continue
        try:
            observed.append(max(0.0, float((event.get("data") or {}).get("cost_usd"))))
        except (TypeError, ValueError):
            continue
    return round(sum(observed), 8) if observed else None


def _delivered(run: Mapping[str, Any]) -> bool:
    delivery = run.get("delivery") if isinstance(run.get("delivery"), dict) else {}
    return str(delivery.get("status") or "") in DELIVERED_STATUSES or str(run.get("status") or "") == "pr_created"


def _failure_reason(run: Mapping[str, Any]) -> str:
    delivery = run.get("delivery") if isinstance(run.get("delivery"), dict) else {}
    ci = run.get("ci") if isinstance(run.get("ci"), dict) else {}
    review = run.get("evaluation") if isinstance(run.get("evaluation"), dict) else {}
    text = " ".join(
        str(value or "").lower()
        for value in (run.get("last_error"), run.get("blocked_reason"), delivery.get("error"), ci.get("summary"))
    )
    if delivery.get("status") == "failed" or "conflict" in text or "preimage" in text:
        return "Integration conflict"
    if str(ci.get("status") or "") in {"failed", "failure", "error", "retry_exhausted", "timed_out"} or "github ci" in text:
        return "CI failure"
    if any(word in text for word in ("test", "check failed", "verification", "lint")):
        return "Checks or tests"
    if any(word in text for word in ("budget", "token", "credit", "quota", "stall", "timeout")):
        return "Budget or timeout"
    if str(run.get("status") or "") == "cancelled":
        return "Cancelled"
    if str(run.get("status") or "") == "blocked" or run.get("depends_on"):
        return "Dependency blocked"
    if review.get("passed") is False or "review" in text:
        return "Review finding"
    if any(word in text for word in ("agent", "process", "command", "exit", "python")):
        return "Agent or runtime"
    return "Unclassified"


def _rate(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def _portfolio_signature(store: RunStore, days: int) -> tuple[Any, ...]:
    def fingerprint(path: Any) -> tuple[str, int, int]:
        try:
            stat = path.stat()
            return (path.name, int(stat.st_mtime_ns), int(stat.st_size))
        except OSError:
            return (path.name, 0, 0)

    return (
        days,
        fingerprint(store.config_path),
        tuple(fingerprint(path) for path in sorted(store.runs_dir.glob("*.json"))),
    )


def engineering_portfolio(store: RunStore, *, days: int = 7) -> dict[str, Any]:
    """Return one cached projection per durable run-state generation.

    The first calculation validates the full relevant journals. Concurrent UI
    refreshes then reuse that auditable result until a run or portfolio setting
    changes, preventing open browser tabs from repeatedly rescanning journals.
    """

    window_days = max(1, min(int(days or 7), 365))
    signature = _portfolio_signature(store, window_days)
    with _PORTFOLIO_CACHE_LOCK:
        cached = _PORTFOLIO_CACHE.get(store)
        if cached and cached.get("signature") == signature:
            return copy.deepcopy(cached["payload"])
        payload = _engineering_portfolio_uncached(store, days=window_days)
        _PORTFOLIO_CACHE[store] = {"signature": signature, "payload": payload}
        return copy.deepcopy(payload)


def _engineering_portfolio_uncached(store: RunStore, *, days: int = 7) -> dict[str, Any]:
    """Return auditable, windowed lead metrics without inventing missing cost data."""

    window_days = max(1, min(int(days or 7), 365))
    generated_at = datetime.now(timezone.utc)
    window_start = generated_at - timedelta(days=window_days)
    all_tasks = [run for run in store.list() if str(run.get("kind") or "task") == "task"]
    window_runs = [run for run in all_tasks if (_time(run.get("created_at")) or datetime.min.replace(tzinfo=timezone.utc)) >= window_start]
    observed: list[tuple[dict[str, Any], list[dict[str, Any]]]] = []
    for run in window_runs:
        try:
            events = store.events_strict(str(run.get("id") or ""))
        except RuntimeError:
            events = store.events(str(run.get("id") or ""), limit=100_000)
        observed.append((run, events))

    started = [(run, events) for run, events in observed if run.get("started_at")]
    terminal = [(run, events) for run, events in started if str(run.get("status") or "") in TERMINAL_STATUSES]
    delivered = [(run, events) for run, events in started if _delivered(run)]
    autonomous = [
        (run, events)
        for run, events in delivered
        if not any(event.get("source") == "user" and event.get("type") in CORRECTIVE_USER_EVENTS for event in events)
    ]
    first_pass = [
        (run, events)
        for run, events in terminal
        if _delivered(run)
        and int(run.get("attempt") or 0) <= 1
        and not any(event.get("type") in RETRY_EVENTS for event in events)
    ]
    interventions = sum(
        1
        for _run, events in observed
        for event in events
        if event.get("source") == "user" and event.get("type") in CORRECTIVE_USER_EVENTS
    )
    durations = [value for run, _events in delivered if (value := _duration_minutes(run)) is not None]
    delivered_costs = [value for run, events in delivered if (value := _cost(run, events)) is not None]

    config = store.config().get("portfolio")
    config = config if isinstance(config, dict) else {}
    try:
        baseline_minutes = max(0.0, float(config.get("baseline_engineer_minutes_per_delivery") or 0.0))
    except (TypeError, ValueError):
        baseline_minutes = 0.0
    engineer_hours = round((len(delivered) * baseline_minutes) / 60.0, 1) if baseline_minutes else None

    current_blocked = [run for run in all_tasks if str(run.get("status") or "") in {"blocked", "failed", "attention"}]
    agents: dict[str, dict[str, Any]] = {}
    for run, events in started:
        lane = str(run.get("lane") or "unknown")
        bucket = agents.setdefault(
            lane,
            {"agent": lane, "started": 0, "delivered": 0, "first_pass": 0, "interventions": 0, "durations": [], "costs": []},
        )
        bucket["started"] += 1
        if _delivered(run):
            bucket["delivered"] += 1
            duration = _duration_minutes(run)
            cost = _cost(run, events)
            if duration is not None:
                bucket["durations"].append(duration)
            if cost is not None:
                bucket["costs"].append(cost)
            if int(run.get("attempt") or 0) <= 1 and not any(event.get("type") in RETRY_EVENTS for event in events):
                bucket["first_pass"] += 1
        bucket["interventions"] += sum(
            1 for event in events if event.get("source") == "user" and event.get("type") in CORRECTIVE_USER_EVENTS
        )
    agent_rows = []
    for bucket in agents.values():
        costs = bucket.pop("costs")
        lane_durations = bucket.pop("durations")
        agent_rows.append(
            {
                **bucket,
                "delivery_rate": _rate(bucket["delivered"], bucket["started"]),
                "first_pass_rate": _rate(bucket["first_pass"], bucket["delivered"]),
                "median_minutes": round(median(lane_durations), 1) if lane_durations else None,
                "median_cost_usd": round(median(costs), 4) if costs else None,
                "cost_coverage": len(costs),
            }
        )
    agent_rows.sort(key=lambda row: (-int(row["delivered"]), str(row["agent"])))

    failure_counts: dict[str, int] = {}
    for run, _events in observed:
        if str(run.get("status") or "") not in {"failed", "blocked", "cancelled"} and not (
            isinstance(run.get("delivery"), dict) and run["delivery"].get("status") == "failed"
        ):
            continue
        reason = _failure_reason(run)
        failure_counts[reason] = failure_counts.get(reason, 0) + 1
    failures = [
        {"reason": reason, "count": count}
        for reason, count in sorted(failure_counts.items(), key=lambda item: (-item[1], item[0]))
    ]

    return {
        "format": "odysseus-engineering-portfolio-v1",
        "generated_at": generated_at.isoformat().replace("+00:00", "Z"),
        "window": {"days": window_days, "starts_at": window_start.isoformat().replace("+00:00", "Z")},
        "metrics": {
            "tasks_started": len(started),
            "terminal_started": len(terminal),
            "delivered": len(delivered),
            "autonomous_delivery_rate": _rate(len(autonomous), len(delivered)),
            "first_pass_success_rate": _rate(len(first_pass), len(terminal)),
            "human_interventions": interventions,
            "median_minutes_per_delivery": round(median(durations), 1) if durations else None,
            "median_cost_per_delivery_usd": round(median(delivered_costs), 4) if delivered_costs else None,
            "cost_coverage_deliveries": len(delivered_costs),
            "engineer_hours_saved": engineer_hours,
            "engineer_hours_method": (
                f"{baseline_minutes:g} configured baseline minutes per delivery"
                if baseline_minutes
                else "not estimated; configure a baseline before claiming hours saved"
            ),
            "active_repositories": len({str(run.get("project_id") or "") for run, _events in started if run.get("project_id")}),
            "currently_blocked": len(current_blocked),
        },
        "definitions": {
            "autonomous_delivery_rate": "delivered changes with no corrective operator answer, resolution, cancellation, or send-back; final approval is allowed",
            "first_pass_success_rate": "terminal started tasks delivered without retry, CI repair, or send-back",
            "cost": "observed model cost only; missing cost remains unknown",
        },
        "agents": agent_rows,
        "failures": failures,
        "blocked": [
            {
                "run_id": str(run.get("id") or ""),
                "project_id": str(run.get("project_id") or ""),
                "title": str(run.get("title") or run.get("task") or "Task"),
                "status": str(run.get("status") or "unknown"),
                "reason": _failure_reason(run),
                "updated_at": str(run.get("updated_at") or ""),
            }
            for run in current_blocked[:20]
        ],
    }
