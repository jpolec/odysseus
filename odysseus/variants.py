"""Explicit opt-in variant orchestration and comparison helpers."""

from __future__ import annotations

import hashlib
import json
import re
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


def candidate_report(run: Mapping[str, Any]) -> dict[str, Any]:
    diff = WorktreeManager.diff(run, limit=120_000)
    evaluation = run.get("evaluation") if isinstance(run.get("evaluation"), Mapping) else {}
    tests = _tests_summary(run)
    artifact_files = run.get("artifact_files") if isinstance(run.get("artifact_files"), list) else []
    stat = str(diff.get("stat") or "")
    change_size = {
        "files": len([item for item in artifact_files if str(item)]),
        "changed_lines": changed_line_count(stat),
        "stat": stat[-12_000:],
    }
    quality_score = _float(evaluation.get("confidence")) if evaluation else 0.0
    merge_analysis = run.get("merge_analysis") if isinstance(run.get("merge_analysis"), Mapping) else {}
    regression_risk = "high" if tests["failed"] or run.get("status") in {"failed", "cancelled", "attention"} else "medium" if quality_score < 0.85 else "low"
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
    }


def _dominates(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    left_tests = left["tests"]["failed"]
    right_tests = right["tests"]["failed"]
    left_quality = float(left["code_quality"]["confidence"])
    right_quality = float(right["code_quality"]["confidence"])
    left_cost = float(left["observed_cost"]["usd"])
    right_cost = float(right["observed_cost"]["usd"])
    left_size = int(left["unnecessary_change_size"]["changed_lines"])
    right_size = int(right["unnecessary_change_size"]["changed_lines"])
    left_attention = int(left["human_attention"]["count"])
    right_attention = int(right["human_attention"]["count"])
    better_or_equal = (
        left_tests <= right_tests
        and left_quality >= right_quality
        and left_cost <= right_cost
        and left_size <= right_size
        and left_attention <= right_attention
    )
    strictly_better = (
        left_tests < right_tests
        or left_quality > right_quality
        or left_cost < right_cost
        or left_size < right_size
        or left_attention < right_attention
    )
    return better_or_equal and strictly_better


def compare_candidates(parent: Mapping[str, Any], candidates: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    reports = [candidate_report(candidate) for candidate in candidates]
    frontier = [
        item["run_id"]
        for item in reports
        if not any(_dominates(other, item) for other in reports if other["run_id"] != item["run_id"])
    ]
    totals = {
        "cost_usd": round(sum(float(item["observed_cost"]["usd"]) for item in reports), 8),
        "human_attention": sum(int(item["human_attention"]["count"]) for item in reports),
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
