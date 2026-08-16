"""Outcome economics aggregated from accepted and delivered Odysseus changes."""

from __future__ import annotations

import csv
import hashlib
import io
import json
from typing import TYPE_CHECKING, Any, Iterable, Mapping

if TYPE_CHECKING:
    from .store import RunStore


DELIVERED_STATUSES = frozenset({"applied", "pr_created", "integrated_applied", "integrated_pr_created"})
TERMINAL_STATUSES = frozenset({"accepted", "pr_created", "failed", "cancelled"})
TOKEN_KEYS = ("input_tokens", "cached_input_tokens", "output_tokens", "reasoning_output_tokens")
PHASES = ("implementer", "reviewer", "ci_repair", "retry")
SAMPLE_MINIMUM = 20


def _safe_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _safe_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


def _digest(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _receipt(run: Mapping[str, Any], events: list[dict[str, Any]]) -> dict[str, Any]:
    public = {
        "run_id": str(run.get("id") or ""),
        "event_count": len(events),
        "final_seq": int(events[-1].get("seq") or 0) if events else 0,
        "event_journal_sha256": _digest(events),
        "run_snapshot_sha256": _digest(run),
    }
    sha = _digest(public)
    return {"receipt_id": sha[:16], "sha256": sha, **public}


def _phase(raw: Any, event_type: str, data: Mapping[str, Any]) -> str:
    value = str(raw or data.get("phase") or "").lower()
    if value in {"review", "evaluator"}:
        return "reviewer"
    if value in {"ci", "ci_repair", "ci-repair"} or event_type.startswith("ci."):
        return "ci_repair"
    if value in {"retry", "resume"} or data.get("resumed"):
        return "retry"
    return "implementer"


def _delivered(run: Mapping[str, Any]) -> bool:
    delivery = run.get("delivery") if isinstance(run.get("delivery"), dict) else {}
    return str(delivery.get("status") or "") in DELIVERED_STATUSES


def _cost(metrics: Mapping[str, Any], events: list[dict[str, Any]]) -> float | None:
    if metrics.get("cost_observed") is True:
        return round(_safe_float(metrics.get("cost_usd")) or 0.0, 8)
    values: list[float] = []
    for event in events:
        if event.get("type") != "agent.cost":
            continue
        value = _safe_float((event.get("data") or {}).get("cost_usd"))
        if value is not None:
            values.append(value)
    return round(sum(values), 8) if values else None


def _known_sum(values: Iterable[float | None]) -> float | None:
    observed = [value for value in values if value is not None]
    return round(sum(observed), 6) if observed else None


def _complete_average(costs: list[float | None], denominator: int) -> float | None:
    if denominator <= 0 or len(costs) != denominator or any(value is None for value in costs):
        return None
    return round(sum(float(value) for value in costs) / denominator, 6)


def outcome_economics(store: RunStore, *, minimum_runs: int = SAMPLE_MINIMUM, privacy: str = "redacted") -> dict[str, Any]:
    """Aggregate economics around accepted and delivered changes.

    Expected cost per successful change is:
    ``known observed model cost for terminal attempts / known-cost terminal attempts / acceptance_rate``.
    It is reported only when every terminal attempt has observed cost and the sample is not empty.
    Missing model prices or emitted cost stay ``None`` so callers can render Unknown, never zero.
    """

    minimum = max(1, int(minimum_runs or SAMPLE_MINIMUM))
    include_private = privacy == "full"
    runs = [run for run in store.list() if run.get("kind") == "task"]
    attention = store.attention.list()
    attention_by_run: dict[str, list[dict[str, Any]]] = {}
    for item in attention:
        attention_by_run.setdefault(str(item.get("run_id") or ""), []).append(item)

    totals = {
        "tasks": len(runs),
        "terminal_attempts": 0,
        "accepted_changes": 0,
        "delivered_changes": 0,
        "tokens": {phase: {key: 0 for key in TOKEN_KEYS} | {"total_tokens": 0} for phase in PHASES},
        "observed_model_cost_usd": None,
        "tests_check_compute_duration_seconds": 0.0,
        "retry_rate": None,
        "human_interventions": 0,
        "acceptance_rate": None,
        "delivery_rate": None,
        "cost_per_accepted_change_usd": None,
        "cost_per_delivered_change_usd": None,
    }
    cost_values: list[float | None] = []
    accepted_costs: list[float | None] = []
    delivered_costs: list[float | None] = []
    terminal_costs: list[float | None] = []
    retry_attempts = 0
    run_receipts: list[dict[str, Any]] = []
    lead_rows: list[dict[str, Any]] = []
    operator_rows: list[dict[str, Any]] = []
    metric_receipts: dict[str, set[str]] = {
        "tasks": set(),
        "terminal_attempts": set(),
        "accepted_changes": set(),
        "delivered_changes": set(),
        "observed_model_cost_usd": set(),
        "tests_check_compute_duration_seconds": set(),
        "retry_rate": set(),
        "human_interventions": set(),
        "acceptance_rate": set(),
        "delivery_rate": set(),
        "cost_per_accepted_change_usd": set(),
        "cost_per_delivered_change_usd": set(),
        "expected_cost_per_successful_change_usd": set(),
    }
    for phase in PHASES:
        for key in (*TOKEN_KEYS, "total_tokens"):
            metric_receipts[f"tokens.{phase}.{key}"] = set()

    for run in runs:
        run_id = str(run.get("id") or "")
        events = store.events(run_id, limit=100_000)
        receipt = _receipt(run, events)
        run_receipts.append(receipt)
        receipt_id = str(receipt["receipt_id"])
        metric_receipts["tasks"].add(receipt_id)
        metric_receipts["retry_rate"].add(receipt_id)
        metrics = run.get("metrics") if isinstance(run.get("metrics"), dict) else {}
        run_cost = _cost(metrics, events)
        cost_values.append(run_cost)
        terminal = str(run.get("status") or "") in TERMINAL_STATUSES
        accepted = str(run.get("status") or "") in {"accepted", "pr_created"}
        delivered = _delivered(run)
        if terminal:
            totals["terminal_attempts"] += 1
            terminal_costs.append(run_cost)
            for key in ("terminal_attempts", "acceptance_rate", "expected_cost_per_successful_change_usd"):
                metric_receipts[key].add(receipt_id)
        if accepted:
            totals["accepted_changes"] += 1
            accepted_costs.append(run_cost)
            for key in ("accepted_changes", "delivery_rate", "cost_per_accepted_change_usd"):
                metric_receipts[key].add(receipt_id)
        if delivered:
            totals["delivered_changes"] += 1
            delivered_costs.append(run_cost)
            for key in ("delivered_changes", "cost_per_delivered_change_usd"):
                metric_receipts[key].add(receipt_id)
        if run_cost is not None:
            metric_receipts["observed_model_cost_usd"].add(receipt_id)
        if int(run.get("attempt") or 0) > 0 or any(event.get("type") in {"workflow.retry", "review.sent_back", "ci.retry_queued", "ci.retry_pushed"} for event in events):
            retry_attempts += 1
        for event in events:
            data = event.get("data") if isinstance(event.get("data"), dict) else {}
            if event.get("type") == "agent.usage":
                phase = _phase(None, str(event.get("type") or ""), data)
                bucket = totals["tokens"][phase]
                for key in TOKEN_KEYS:
                    current = _safe_int(data.get(key))
                    bucket[key] += current
                    if current:
                        metric_receipts[f"tokens.{phase}.{key}"].add(receipt_id)
                current_total = _safe_int(data.get("input_tokens")) + _safe_int(data.get("output_tokens")) + _safe_int(data.get("reasoning_output_tokens"))
                bucket["total_tokens"] += current_total
                if current_total:
                    metric_receipts[f"tokens.{phase}.total_tokens"].add(receipt_id)
            if event.get("type") == "check.completed":
                totals["tests_check_compute_duration_seconds"] += _safe_float(data.get("duration_seconds")) or 0.0
                metric_receipts["tests_check_compute_duration_seconds"].add(receipt_id)
        interventions = sum(1 for item in attention_by_run.get(run_id, []) if item.get("status") in {"answered", "resolved"})
        interventions += sum(1 for event in events if event.get("source") == "user" and event.get("type") in {"attention.answered", "attention.resolved", "review.accepted", "review.sent_back", "run.cancel_requested", "pr.creating"})
        totals["human_interventions"] += interventions
        if interventions:
            metric_receipts["human_interventions"].add(receipt_id)
        risk = str((run.get("merge_analysis") if isinstance(run.get("merge_analysis"), dict) else {}).get("risk") or "none")
        eta = (run.get("economics") or {}).get("eta") if isinstance(run.get("economics"), dict) else None
        eta_sample = _safe_int((eta or {}).get("sample_size") if isinstance(eta, dict) else 0)
        lead_rows.append(
            {
                "run_id": run_id,
                "receipt_id": receipt_id,
                "task": str(run.get("title") or run.get("task") or "") if include_private else f"Task {receipt_id}",
                "state": str(run.get("status") or "unknown"),
                "risk": risk,
                "observed_cost_usd": run_cost,
                "eta": eta.get("value") if isinstance(eta, dict) and eta_sample >= minimum else None,
                "eta_sample_size": eta_sample if isinstance(eta, dict) else 0,
            }
        )
        operator_rows.append(
            {
                **lead_rows[-1],
                "lane": str(run.get("lane") or ""),
                "review_lane": str(run.get("review_lane") or ""),
                "attempt": int(run.get("attempt") or 0),
                "max_retries": int(run.get("max_retries") or 0),
                "checks": len(run.get("check_results") or []),
                "ci_status": str((run.get("ci") if isinstance(run.get("ci"), dict) else {}).get("status") or "not_started"),
                "human_interventions": interventions,
                "event_count": receipt["event_count"],
                "final_seq": receipt["final_seq"],
            }
        )

    observed_total = _known_sum(cost_values)
    totals["observed_model_cost_usd"] = observed_total
    totals["tests_check_compute_duration_seconds"] = round(float(totals["tests_check_compute_duration_seconds"]), 3)
    totals["acceptance_rate"] = round(totals["accepted_changes"] / totals["terminal_attempts"], 4) if totals["terminal_attempts"] else None
    totals["delivery_rate"] = round(totals["delivered_changes"] / totals["accepted_changes"], 4) if totals["accepted_changes"] else None
    totals["retry_rate"] = round(retry_attempts / len(runs), 4) if runs else None
    totals["cost_per_accepted_change_usd"] = _complete_average(accepted_costs, totals["accepted_changes"])
    totals["cost_per_delivered_change_usd"] = _complete_average(delivered_costs, totals["delivered_changes"])
    expected = None
    if terminal_costs and len(terminal_costs) == totals["terminal_attempts"] and all(value is not None for value in terminal_costs) and totals["acceptance_rate"]:
        expected = round((sum(float(value) for value in terminal_costs) / totals["terminal_attempts"]) / totals["acceptance_rate"], 6)
    sample_size = totals["terminal_attempts"]
    metric_receipt_ids = {key: sorted(values) for key, values in sorted(metric_receipts.items())}
    return {
        "format": "odysseus-outcome-economics-v1",
        "privacy": "full" if include_private else "redacted",
        "sample": {
            "minimum_runs": minimum,
            "sample_size": sample_size,
            "sufficient": sample_size >= minimum,
            "cost_coverage_runs": sum(1 for value in terminal_costs if value is not None),
        },
        "formula": {
            "expected_cost_per_successful_change_usd": "avg(observed_model_cost_usd per terminal attempt) / acceptance_rate; Unknown unless every terminal attempt has observed model cost",
            "cost_per_accepted_change_usd": "sum(observed model cost for accepted changes) / accepted_changes; Unknown if any accepted change has Unknown cost",
            "cost_per_delivered_change_usd": "sum(observed model cost for delivered changes) / delivered_changes; Unknown if any delivered change has Unknown cost",
        },
        "totals": totals,
        "lead_view": lead_rows,
        "operator_view": operator_rows,
        "run_receipts": sorted(run_receipts, key=lambda item: item["receipt_id"]),
        "metric_receipts": metric_receipt_ids,
        "expected_cost_per_successful_change_usd": expected,
    }


def economics_csv(economics: Mapping[str, Any], view: str = "lead") -> str:
    rows = economics.get("operator_view") if view == "operator" else economics.get("lead_view")
    rows = rows if isinstance(rows, list) else []
    fields = list(rows[0].keys()) if rows else ["run_id", "receipt_id", "task", "state", "risk", "observed_cost_usd", "eta", "eta_sample_size"]
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue()


def economics_ndjson(economics: Mapping[str, Any], view: str = "lead") -> str:
    rows = economics.get("operator_view") if view == "operator" else economics.get("lead_view")
    rows = rows if isinstance(rows, list) else []
    return "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows)
