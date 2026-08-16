"""Honest, content-addressed evidence for real Odysseus runs."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import statistics as stats
from typing import TYPE_CHECKING, Any

from .events import now_iso

if TYPE_CHECKING:
    from .store import RunStore


EVIDENCE_CLASSES = ("observed", "demo", "test", "imported", "unclassified")
TERMINAL_ATTEMPT_STATUSES = frozenset({"accepted", "pr_created", "failed", "cancelled"})
AGENT_ACTIVITY_EVENTS = frozenset(
    {
        "agent.session",
        "agent.output",
        "agent.message",
        "agent.reasoning",
        "agent.tool.started",
        "agent.tool.completed",
        "agent.completed",
    }
)
VERIFIER_EVENTS = frozenset({"check.completed", "evaluation.completed", "evaluation.inconclusive", "evaluation.failed"})
OPERATOR_ACTION_EVENTS = frozenset(
    {
        "attention.answered",
        "attention.resolved",
        "review.accepted",
        "review.sent_back",
        "run.cancel_requested",
        "pr.creating",
    }
)
PROOF_FORMAT = "odysseus-production-proof-v2"
ELIGIBILITY_POLICY = (
    "observed task for the selected release; ordered run.started, agent activity, and "
    "terminal outcome; delivery also requires final verifier success then artifact then outcome"
)


def _timestamp(value: Any) -> dt.datetime | None:
    try:
        return dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _seconds(start: Any, end: Any) -> float | None:
    left, right = _timestamp(start), _timestamp(end)
    if left is None or right is None or right < left:
        return None
    return (right - left).total_seconds()


def _median(values: list[float]) -> float | None:
    return round(float(stats.median(values)), 3) if values else None


def _canonical_digest(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _indices(events: list[dict[str, Any]], event_types: frozenset[str]) -> list[int]:
    return [index for index, event in enumerate(events) if str(event.get("type") or "") in event_types]


def _outcome_indices(status: str, events: list[dict[str, Any]]) -> list[int]:
    expected = {
        "accepted": frozenset({"run.accepted"}),
        "pr_created": frozenset({"pr.created", "ci.retry_pushed"}),
        "failed": frozenset({"run.failed"}),
        "cancelled": frozenset({"run.cancelled"}),
    }
    return _indices(events, expected.get(status, frozenset()))


def _verifier_succeeded(event: dict[str, Any]) -> bool:
    if event.get("type") == "evaluation.completed":
        return True
    if event.get("type") != "check.completed":
        return False
    data = event.get("data") if isinstance(event.get("data"), dict) else {}
    if "returncode" in data:
        try:
            return int(data["returncode"]) == 0
        except (TypeError, ValueError):
            return False
    return data.get("passed") is True or data.get("eligible") is True or str(
        data.get("status") or ""
    ).lower() in {"ok", "pass", "passed", "success"}


def _eligible_attempt(run: dict[str, Any], events: list[dict[str, Any]]) -> tuple[bool, str]:
    status = str(run.get("status") or "")
    if status not in TERMINAL_ATTEMPT_STATUSES:
        return False, "not_terminal"
    started = _indices(events, frozenset({"run.started"}))
    if not started:
        return False, "missing_start"
    agent = [index for index in _indices(events, AGENT_ACTIVITY_EVENTS) if index > started[0]]
    if not agent:
        return False, "missing_agent_activity"
    last_agent = max(agent)
    if status in {"failed", "cancelled"}:
        outcome = [index for index in _outcome_indices(status, events) if index > last_agent]
        if not outcome:
            return False, "missing_terminal_outcome"
        return True, "eligible"
    verifier = [index for index in _indices(events, VERIFIER_EVENTS) if index > last_agent]
    if not verifier:
        return False, "missing_verifier"
    last_verifier = max(verifier)
    if not _verifier_succeeded(events[last_verifier]):
        return False, "last_verifier_failed"
    outcome = [index for index in _outcome_indices(status, events) if index > last_verifier]
    if not outcome:
        return False, "missing_terminal_outcome"
    first_outcome = min(outcome)
    artifacts = [
        index
        for index in _indices(events, frozenset({"artifact.created"}))
        if last_verifier < index < first_outcome
    ]
    if not artifacts or not run.get("artifact_sha"):
        return False, "missing_ordered_artifact"
    return True, "eligible"


def _accepted_change(run: dict[str, Any], events: list[dict[str, Any]]) -> bool:
    eligible, _reason = _eligible_attempt(run, events)
    return eligible and run.get("status") == "accepted"


def _reported_cost(events: list[dict[str, Any]]) -> float | None:
    values: list[float] = []
    for event in events:
        if event.get("type") != "agent.cost":
            continue
        try:
            values.append(float((event.get("data") or {}).get("cost_usd")))
        except (TypeError, ValueError):
            continue
    return round(sum(values), 6) if values else None


def _operator_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        event
        for event in events
        if event.get("source") == "user" and event.get("type") in OPERATOR_ACTION_EVENTS
    ]


def production_proof(
    store: RunStore,
    *,
    release: str = "",
    minimum_runs: int = 20,
) -> dict[str, Any]:
    """Aggregate verified, explicitly observed, terminal autonomous attempts."""

    minimum = max(1, int(minimum_runs))
    all_tasks = [run for run in store.list() if run.get("kind") == "task"]
    release_tasks = [
        run
        for run in all_tasks
        if not release
        or str(
            (run.get("provenance") if isinstance(run.get("provenance"), dict) else {}).get("release")
            or ""
        )
        == release
    ]
    classifications = {name: 0 for name in EVIDENCE_CLASSES}
    for run in release_tasks:
        provenance = run.get("provenance") if isinstance(run.get("provenance"), dict) else {}
        name = str(provenance.get("evidence_class") or "unclassified")
        classifications[name if name in classifications else "unclassified"] += 1

    observed = []
    events_by_run: dict[str, list[dict[str, Any]]] = {}
    eligibility_reasons: dict[str, int] = {}
    eligible: list[dict[str, Any]] = []
    for run in release_tasks:
        provenance = run.get("provenance") if isinstance(run.get("provenance"), dict) else {}
        if provenance.get("evidence_class") != "observed":
            continue
        observed.append(run)
        run_id = str(run["id"])
        events = store.events_strict(run_id)
        events_by_run[run_id] = events
        is_eligible, reason = _eligible_attempt(run, events)
        eligibility_reasons[reason] = eligibility_reasons.get(reason, 0) + 1
        if is_eligible:
            eligible.append(run)

    accepted = [run for run in eligible if _accepted_change(run, events_by_run[str(run["id"])])]
    durations = [
        value
        for run in eligible
        if (value := _seconds(run.get("started_at"), run.get("finished_at"))) is not None
    ]
    reported_costs = [
        value
        for run in eligible
        if (value := _reported_cost(events_by_run[str(run["id"])])) is not None
    ]
    total_reported_cost = round(sum(reported_costs), 6) if reported_costs else None
    eligible_ids = {str(run["id"]) for run in eligible}
    attention = [item for item in store.attention.list() if str(item.get("run_id") or "") in eligible_ids]
    answered_ids = {
        str((event.get("data") or {}).get("attention_id") or "")
        for run in eligible
        for event in events_by_run[str(run["id"])]
        if event.get("type") == "attention.answered" and event.get("source") == "user"
    }
    answered_attention = [
        item
        for item in attention
        if str(item.get("id") or "") in answered_ids
        and bool(str(item.get("response") or "").strip())
    ]
    response_seconds = [
        value
        for item in answered_attention
        if (value := _seconds(item.get("created_at"), item.get("resolved_at"))) is not None
    ]

    repaired_ci = 0
    recovered_to_completion = 0
    context_receipts = 0
    operator_actions = 0
    run_receipts: list[dict[str, Any]] = []
    for run in eligible:
        run_id = str(run["id"])
        events = events_by_run[run_id]
        types = [str(event.get("type") or "") for event in events]
        failed_indices = [index for index, event_type in enumerate(types) if event_type == "ci.failed"]
        passed_indices = [index for index, event_type in enumerate(types) if event_type == "ci.passed"]
        if (
            failed_indices
            and passed_indices
            and max(passed_indices) > max(failed_indices)
            and (run.get("ci") or {}).get("status") == "passed"
        ):
            repaired_ci += 1
        recovery_indices = [index for index, event_type in enumerate(types) if event_type == "system.recovered"]
        if recovery_indices:
            last_recovery = max(recovery_indices)
            later_activity = [
                index for index in _indices(events, AGENT_ACTIVITY_EVENTS) if index > last_recovery
            ]
            later_outcome = _outcome_indices(str(run.get("status") or ""), events)
            if later_activity and any(index > max(later_activity) for index in later_outcome):
                recovered_to_completion += 1
        if run.get("context_receipt"):
            context_receipts += 1
        user_events = _operator_events(events)
        operator_actions += len(user_events)
        run_attention = [
            item for item in attention if str(item.get("run_id") or "") == run_id
        ]
        provenance = run.get("provenance") if isinstance(run.get("provenance"), dict) else {}
        event_digest = _canonical_digest(events)
        receipt_source = {
            "format": "odysseus-run-proof-v2",
            "opaque_run_id": hashlib.sha256(run_id.encode("utf-8")).hexdigest(),
            "provenance": provenance,
            "status": str(run.get("status") or ""),
            "accepted_change": _accepted_change(run, events),
            "started_at": run.get("started_at"),
            "finished_at": run.get("finished_at"),
            "reported_cost_usd": _reported_cost(events),
            "artifact_sha": str(run.get("artifact_sha") or ""),
            "context_receipt": str((run.get("context_receipt") or {}).get("bundle_sha256") or ""),
            "run_snapshot_sha256": _canonical_digest(run),
            "attention_records_sha256": _canonical_digest(run_attention),
            "operator_events_sha256": _canonical_digest(user_events),
            "event_journal_sha256": event_digest,
            "event_count": len(events),
            "final_seq": int(events[-1]["seq"]) if events else 0,
        }
        receipt_sha = _canonical_digest(receipt_source)
        run_receipts.append(
            {
                "receipt_id": receipt_sha[:16],
                "sha256": receipt_sha,
                "event_journal_sha256": event_digest,
                "run_snapshot_sha256": receipt_source["run_snapshot_sha256"],
                "attention_records_sha256": receipt_source["attention_records_sha256"],
                "event_count": len(events),
                "final_seq": receipt_source["final_seq"],
                "outcome": receipt_source["status"],
                "accepted_change": receipt_source["accepted_change"],
            }
        )
    run_receipts.sort(key=lambda item: item["receipt_id"])

    cost_coverage = len(reported_costs) / len(eligible) if eligible else 0.0
    metrics = {
        "repositories": len(
            {str(run.get("project_id") or run.get("project_path") or "") for run in eligible}
        ),
        "observed_tasks": len(observed),
        "autonomous_tasks": len(eligible),
        "in_progress_tasks": sum(
            1 for run in observed if str(run.get("status") or "") not in TERMINAL_ATTEMPT_STATUSES
        ),
        "ineligible_terminal_tasks": len(observed) - len(eligible) - sum(
            1 for run in observed if str(run.get("status") or "") not in TERMINAL_ATTEMPT_STATUSES
        ),
        "accepted_changes": len(accepted),
        "pull_requests_opened": sum(
            1 for run in eligible if "pr.created" in [event.get("type") for event in events_by_run[str(run["id"])]]
        ),
        "acceptance_rate": round(len(accepted) / len(eligible), 4) if eligible else None,
        "median_task_duration_seconds": _median(durations),
        "median_cost_usd": _median(reported_costs),
        "total_cost_usd": total_reported_cost,
        "cost_coverage_runs": len(reported_costs),
        "cost_coverage_rate": round(cost_coverage, 4),
        "cost_per_accepted_change_usd": (
            round(total_reported_cost / len(accepted), 6)
            if total_reported_cost is not None and accepted and cost_coverage == 1.0
            else None
        ),
        "human_interventions": operator_actions,
        "needs_you_responses": len(answered_attention),
        "median_operator_response_latency_seconds": _median(response_seconds),
        "human_attention_per_accepted_change_seconds": (
            round(sum(response_seconds) / len(accepted), 3)
            if accepted and len(response_seconds) == len(answered_attention)
            else None
        ),
        "ci_failures_repaired": repaired_ci,
        "runs_resumed_after_crash": recovered_to_completion,
        "context_receipts": context_receipts,
    }
    sample_sufficient = len(eligible) >= minimum
    claim_payload = {
        "format": PROOF_FORMAT,
        "release": release or "all",
        "evidence_filter": "kind=task AND provenance.evidence_class=observed",
        "eligibility_policy": ELIGIBILITY_POLICY,
        "attention_measurement": (
            "explicit source=user actions; timing is Needs You open-to-answered latency, "
            "not active human work time"
        ),
        "classification_scope": "selected release" if release else "all releases",
        "classifications": classifications,
        "eligibility_reasons": eligibility_reasons,
        "minimum_runs": minimum,
        "sample_sufficient": sample_sufficient,
        "metrics": metrics,
        "run_receipts": run_receipts,
    }
    return {
        **claim_payload,
        "generated_at": now_iso(),
        "proof_sha256": _canonical_digest(claim_payload),
    }


def proof_markdown(proof: dict[str, Any]) -> str:
    metrics = proof["metrics"]

    def shown(value: Any, suffix: str = "") -> str:
        return "not observed" if value is None else f"{value}{suffix}"

    status = "sufficient" if proof["sample_sufficient"] else f"below {proof['minimum_runs']}-run threshold"
    acceptance = metrics["acceptance_rate"]
    acceptance_text = "not observed" if acceptance is None else f"{acceptance:.1%}"
    return "\n".join(
        [
            "# Odysseus Production Proof",
            "",
            f"Release: `{proof['release']}`  ",
            f"Evidence: verified terminal agent attempts only; sample is **{status}**.  ",
            f"Receipt: `{proof['proof_sha256']}`",
            "",
            "| Metric | Observed value |",
            "| --- | ---: |",
            f"| Repositories | {metrics['repositories']} |",
            f"| Observed tasks | {metrics['observed_tasks']} |",
            f"| Verified autonomous outcomes | {metrics['autonomous_tasks']} |",
            f"| In progress | {metrics['in_progress_tasks']} |",
            f"| Accepted changes | {metrics['accepted_changes']} |",
            f"| Pull requests opened | {metrics['pull_requests_opened']} |",
            f"| Acceptance rate | {acceptance_text} |",
            f"| Median task duration | {shown(metrics['median_task_duration_seconds'], ' s')} |",
            f"| Median reported cost | {shown(metrics['median_cost_usd'], ' USD')} |",
            f"| Cost coverage | {metrics['cost_coverage_runs']}/{metrics['autonomous_tasks']} runs |",
            f"| Explicit operator actions | {metrics['human_interventions']} |",
            f"| Needs You response latency / accepted change | {shown(metrics['human_attention_per_accepted_change_seconds'], ' s')} |",
            f"| CI failures repaired to final green | {metrics['ci_failures_repaired']} |",
            f"| Crash recoveries completed | {metrics['runs_resumed_after_crash']} |",
            f"| Context receipts | {metrics['context_receipts']} |",
            "",
            "An attempt counts only after ordered start, agent activity, and terminal outcome events.",
            "Delivery additionally requires final verifier success, then artifact creation, then outcome.",
            "Needs You timing is queue response latency, not active human work time.",
            "Demo, test, imported tmux, and legacy unclassified runs are excluded.",
            "",
        ]
    )
