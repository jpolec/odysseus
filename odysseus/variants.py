"""Explicit opt-in variant orchestration and comparison helpers."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

from .worktrees import WorktreeManager


TERMINAL_VARIANT_STATUSES = frozenset(
    {"review", "failed", "cancelled", "accepted", "pr_created", "attention", "rejected"}
)

DEFAULT_PROMPT_STRATEGIES = (
    "Favor the smallest coherent change. Avoid broad refactors unless required.",
    "Favor explicit tests and regression boundaries. Keep behavior compatibility central.",
    "Favor maintainability and clear integration boundaries. Minimize future merge risk.",
)

METRIC_DIRECTIONS = {
    "failed_tests": "lower",
    "evidence": "higher",
    "cost": "lower",
    "latency": "lower",
    "attention": "lower",
    "risk": "lower",
    "blast_radius": "lower",
    "change_size": "lower",
}

RISK_VALUES = {"none": 0.0, "low": 1.0, "medium": 2.0, "high": 3.0}


@dataclass(frozen=True)
class Metric:
    value: float | None
    observed: bool
    source: str
    lower: float | None = None
    upper: float | None = None
    type: str = "number"

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "value": self.value,
            "observed": self.observed,
            "source": self.source,
            "lower": self.lower,
            "upper": self.upper,
        }


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _bounded_count(value: Any) -> int:
    count = _safe_int(value, 0)
    if count not in {2, 3}:
        raise ValueError("variants requires exactly 2 or 3 candidates")
    return count


def _float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _observed_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _metric(value: float | int | None, *, observed: bool, source: str) -> Metric:
    return Metric(float(value) if value is not None else None, bool(observed), source)


def _iso_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    raw = str(value)
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def _seconds_between(start: Any, end: Any) -> float | None:
    started = _iso_datetime(start)
    finished = _iso_datetime(end)
    if not started or not finished:
        return None
    return max(0.0, (finished - started).total_seconds())


def _prompt_hash(prompt: str) -> str:
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()


def normalize_variants_request(request: Mapping[str, Any], *, default_lane: str) -> dict[str, Any]:
    raw = request.get("variants") if isinstance(request.get("variants"), Mapping) else {}
    workflow = str(request.get("workflow") or "")
    enabled = bool(raw.get("enabled")) or workflow == "variants"
    if not enabled:
        return {"enabled": False}
    count = _bounded_count(raw.get("count") or request.get("variant_count") or 2)
    candidates = raw.get("candidates") if isinstance(raw.get("candidates"), list) else []
    base_lanes = raw.get("lanes") if isinstance(raw.get("lanes"), list) else []
    base_prompts = raw.get("prompts") if isinstance(raw.get("prompts"), list) else []
    values: list[dict[str, Any]] = []
    for index in range(count):
        source = candidates[index] if index < len(candidates) and isinstance(candidates[index], Mapping) else {}
        lane = str(source.get("lane") or (base_lanes[index] if index < len(base_lanes) else "") or default_lane)
        review_lane = str(source.get("review_lane") or raw.get("review_lane") or request.get("review_lane") or lane)
        prompt = str(source.get("prompt") or (base_prompts[index] if index < len(base_prompts) else "") or DEFAULT_PROMPT_STRATEGIES[index])
        title = str(source.get("title") or f"Variant {index + 1}")
        model = str(source.get("model") or raw.get("model") or "")
        values.append(
            {
                "id": f"v{index + 1}",
                "index": index + 1,
                "title": title[:100],
                "lane": lane,
                "review_lane": review_lane,
                "model": model,
                "prompt": prompt,
                "prompt_sha256": _prompt_hash(prompt),
            }
        )
    return {
        "enabled": True,
        "version": 1,
        "count": count,
        "candidates": values,
        "shared_budget": bool(raw.get("shared_budget", True)),
        "candidate_run_ids": [],
        "state": "not_started",
    }


def child_budgets(parent: Mapping[str, Any], count: int) -> dict[str, Any]:
    budgets = parent.get("budgets") if isinstance(parent.get("budgets"), Mapping) else {}
    child = dict(budgets)
    for key in ("max_tokens", "max_tool_calls"):
        value = _safe_int(child.get(key), 0)
        if value:
            child[key] = max(1, value // count)
    cost = _float(child.get("max_cost_usd"))
    if cost:
        child["max_cost_usd"] = round(cost / count, 8)
    return child


def changed_line_count(stat: str) -> int:
    total = 0
    for match in re.finditer(r"(\d+)\s+(?:insertion|deletion)", stat):
        total += int(match.group(1))
    return total


def _metric_cost(run: Mapping[str, Any]) -> float:
    metrics = run.get("metrics") if isinstance(run.get("metrics"), Mapping) else {}
    return round(_float(metrics.get("cost_usd")), 8)


def _cost_metric(run: Mapping[str, Any]) -> Metric:
    metrics = run.get("metrics") if isinstance(run.get("metrics"), Mapping) else {}
    observed = bool(metrics.get("cost_observed"))
    value = round(_float(metrics.get("cost_usd")), 8) if observed else None
    return _metric(value, observed=observed, source="metrics.cost_usd")


def _tests_summary(run: Mapping[str, Any]) -> dict[str, Any]:
    checks = run.get("check_results") if isinstance(run.get("check_results"), list) else []
    passed = sum(1 for item in checks if isinstance(item, Mapping) and int(item.get("returncode", 1)) == 0)
    failed = sum(1 for item in checks if isinstance(item, Mapping) and int(item.get("returncode", 1)) != 0)
    return {"passed": passed, "failed": failed, "total": len(checks)}


def _attention_count(run: Mapping[str, Any]) -> int:
    if run.get("status") in {"failed", "cancelled", "attention"}:
        return 1
    evaluation = run.get("evaluation") if isinstance(run.get("evaluation"), Mapping) else {}
    return 1 if evaluation and not evaluation.get("eligible") else 0


def _attention_metric(run: Mapping[str, Any]) -> Metric:
    status = str(run.get("status") or "")
    evaluation = run.get("evaluation") if isinstance(run.get("evaluation"), Mapping) else {}
    observed = status in {"failed", "cancelled", "attention"} or bool(evaluation)
    return _metric(_attention_count(run) if observed else None, observed=observed, source="status/evaluation")


def _evidence_metric(run: Mapping[str, Any], evaluation: Mapping[str, Any]) -> Metric:
    value = _observed_float(evaluation.get("confidence")) if evaluation else _observed_float(run.get("confidence"))
    return _metric(round(value, 4) if value is not None else None, observed=value is not None, source="evaluation.confidence")


def _risk_metric(run: Mapping[str, Any], tests: Mapping[str, Any], evidence: Metric) -> tuple[Metric, str]:
    status = str(run.get("status") or "")
    if status in {"failed", "cancelled", "attention"} or int(tests.get("failed") or 0) > 0:
        return _metric(RISK_VALUES["high"], observed=True, source="status/check_results"), "high"
    if evidence.observed and evidence.value is not None:
        risk = "medium" if evidence.value < 0.85 else "low"
        return _metric(RISK_VALUES[risk], observed=True, source="evaluation.confidence"), risk
    return _metric(None, observed=False, source="evaluation.confidence"), "unknown"


def _merge_risk_metric(merge_analysis: Mapping[str, Any]) -> Metric:
    raw = str(merge_analysis.get("risk") or "")
    if raw in RISK_VALUES:
        return _metric(RISK_VALUES[raw], observed=True, source="merge_analysis.risk")
    return _metric(None, observed=False, source="merge_analysis.risk")


def _change_metrics(diff: Mapping[str, Any], artifact_files: Sequence[Any]) -> tuple[dict[str, Any], Metric, Metric]:
    stat = str(diff.get("stat") or "")
    files = len([item for item in artifact_files if str(item)])
    changed_lines = changed_line_count(stat)
    observed = bool(stat.strip() or files)
    change_size = {
        "files": files,
        "changed_lines": changed_lines,
        "stat": stat[-12_000:],
    }
    return (
        change_size,
        _metric(changed_lines if observed else None, observed=observed, source="worktree.diff.stat"),
        _metric(files if observed else None, observed=observed, source="artifact_files"),
    )


def _latency_metric(run: Mapping[str, Any]) -> Metric:
    value = _seconds_between(run.get("started_at"), run.get("finished_at"))
    return _metric(round(value, 3) if value is not None else None, observed=value is not None, source="started_at/finished_at")


def candidate_report(run: Mapping[str, Any]) -> dict[str, Any]:
    diff = WorktreeManager.diff(run, limit=120_000)
    evaluation = run.get("evaluation") if isinstance(run.get("evaluation"), Mapping) else {}
    tests = _tests_summary(run)
    artifact_files = run.get("artifact_files") if isinstance(run.get("artifact_files"), list) else []
    change_size, change_metric, blast_metric = _change_metrics(diff, artifact_files)
    evidence_metric = _evidence_metric(run, evaluation)
    quality_score = evidence_metric.value if evidence_metric.observed and evidence_metric.value is not None else 0.0
    merge_analysis = run.get("merge_analysis") if isinstance(run.get("merge_analysis"), Mapping) else {}
    risk_metric, regression_risk = _risk_metric(run, tests, evidence_metric)
    metrics = {
        "failed_tests": _metric(tests["failed"], observed=True, source="check_results").to_dict(),
        "evidence": evidence_metric.to_dict(),
        "cost": _cost_metric(run).to_dict(),
        "latency": _latency_metric(run).to_dict(),
        "attention": _attention_metric(run).to_dict(),
        "risk": risk_metric.to_dict(),
        "blast_radius": blast_metric.to_dict(),
        "change_size": change_metric.to_dict(),
    }
    return {
        "run_id": str(run.get("id") or ""),
        "title": str(run.get("title") or ""),
        "status": str(run.get("status") or ""),
        "lane": str(run.get("lane") or ""),
        "review_lane": str(run.get("review_lane") or ""),
        "variant": dict(run.get("variant") or {}),
        "tests": tests,
        "code_quality": {
            "confidence": round(quality_score, 4),
            "decision": str(run.get("policy_decision") or ""),
            "review_status": str(run.get("review_status") or ""),
        },
        "regression_merge_risk": {
            "risk": regression_risk,
            "merge_risk": str(merge_analysis.get("risk") or "none"),
            "merge_risk_metric": _merge_risk_metric(merge_analysis).to_dict(),
        },
        "observed_cost": {
            "usd": _metric_cost(run),
            "observed": bool((run.get("metrics") or {}).get("cost_observed")) if isinstance(run.get("metrics"), Mapping) else False,
        },
        "unnecessary_change_size": change_size,
        "human_attention": {
            "count": _attention_count(run),
            "reason": str(run.get("last_error") or ""),
        },
        "artifact": {
            "sha": str(run.get("artifact_sha") or ""),
            "files": list(artifact_files),
            "created_at": run.get("artifact_created_at"),
            "worktree_path": str(run.get("worktree_path") or ""),
        },
        "provenance": dict(run.get("provenance") or {}),
        "metrics": metrics,
    }


def _dominates(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    left_metrics = left.get("metrics") if isinstance(left.get("metrics"), Mapping) else {}
    right_metrics = right.get("metrics") if isinstance(right.get("metrics"), Mapping) else {}
    strictly_better = False
    for name, direction in METRIC_DIRECTIONS.items():
        left_metric = left_metrics.get(name) if isinstance(left_metrics.get(name), Mapping) else {}
        right_metric = right_metrics.get(name) if isinstance(right_metrics.get(name), Mapping) else {}
        left_observed = bool(left_metric.get("observed"))
        right_observed = bool(right_metric.get("observed"))
        if right_observed and not left_observed:
            return False
        if not left_observed or not right_observed:
            continue
        left_value = _observed_float(left_metric.get("value"))
        right_value = _observed_float(right_metric.get("value"))
        if left_value is None or right_value is None:
            return False
        if direction == "higher":
            if left_value < right_value:
                return False
            strictly_better = strictly_better or left_value > right_value
        else:
            if left_value > right_value:
                return False
            strictly_better = strictly_better or left_value < right_value
    return strictly_better


def compare_candidates(parent: Mapping[str, Any], candidates: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    reports = [candidate_report(candidate) for candidate in candidates]
    frontier = [
        item["run_id"]
        for item in reports
        if not any(_dominates(other, item) for other in reports if other["run_id"] != item["run_id"])
    ]
    totals = {
        "cost_usd": round(sum(float(item["observed_cost"]["usd"]) for item in reports if item["observed_cost"]["observed"]), 8),
        "cost_observed": sum(1 for item in reports if item["metrics"]["cost"]["observed"]),
        "human_attention": sum(int(item["human_attention"]["count"]) for item in reports if item["metrics"]["attention"]["observed"]),
        "human_attention_observed": sum(1 for item in reports if item["metrics"]["attention"]["observed"]),
        "artifacts": sum(1 for item in reports if item["artifact"]["sha"]),
        "complete": sum(1 for item in reports if item["status"] in TERMINAL_VARIANT_STATUSES),
    }
    return {
        "version": 1,
        "parent_run_id": str(parent.get("id") or ""),
        "candidate_run_ids": [item["run_id"] for item in reports],
        "status": "ready",
        "summary": (
            "Variants are compared as a Pareto frontier. Odysseus did not select, apply, "
            "or merge a candidate; an operator must select, queue integration, or reject all."
        ),
        "pareto_frontier": frontier,
        "candidates": reports,
        "totals": totals,
    }
