"""Cross-project search over Odysseus' inspectable local state."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .store import RunStore


def search(store: RunStore, query: str, *, limit: int = 100) -> list[dict[str, Any]]:
    needle = query.strip().lower()
    if not needle:
        return []
    results: list[dict[str, Any]] = []

    def add(value: dict[str, Any]) -> None:
        if len(results) < max(1, min(limit, 500)):
            results.append(value)

    for run in store.list():
        haystack = "\n".join(
            str(run.get(key) or "")
            for key in ("id", "title", "task", "status", "lane", "task_key", "review_summary", "last_error")
        ).lower()
        if needle in haystack:
            add(
                {
                    "kind": "run",
                    "id": run["id"],
                    "run_id": run["id"],
                    "title": run.get("title"),
                    "snippet": str(run.get("task") or run.get("last_error") or "")[:500],
                    "status": run.get("status"),
                    "project_id": run.get("project_id"),
                }
            )
        for event in reversed(store.events(str(run["id"]), limit=200)):
            encoded = json.dumps(event, ensure_ascii=False).lower()
            if needle not in encoded:
                continue
            add(
                {
                    "kind": "event",
                    "id": f"{run['id']}:{event.get('seq')}",
                    "run_id": run["id"],
                    "title": event.get("type"),
                    "snippet": str((event.get("data") or {}).get("message") or (event.get("data") or {}).get("text") or "")[:500],
                    "status": run.get("status"),
                    "project_id": run.get("project_id"),
                }
            )
            break
    collections = (
        ("project", store.projects.list()),
        ("epic", store.epics.list()),
        ("attention", store.attention.list()),
        ("inbox", store.inbox.list()),
    )
    for kind, values in collections:
        for item in values:
            if needle not in json.dumps(item, ensure_ascii=False).lower():
                continue
            add(
                {
                    "kind": kind,
                    "id": item.get("id"),
                    "run_id": item.get("run_id"),
                    "title": item.get("title") or item.get("name") or item.get("id"),
                    "snippet": str(item.get("message") or item.get("description") or item.get("task") or item.get("path") or "")[:500],
                    "status": item.get("status"),
                    "project_id": item.get("project_id") or item.get("id") if kind == "project" else item.get("project_id"),
                }
            )
    return results


def statistics(store: RunStore) -> dict[str, Any]:
    runs = [run for run in store.list() if run.get("kind") == "task"]
    successful = [run for run in runs if run.get("status") in {"accepted", "pr_created"}]
    metrics = [run.get("metrics") if isinstance(run.get("metrics"), dict) else {} for run in runs]
    tokens = sum(
        int(item.get("input_tokens") or 0)
        + int(item.get("output_tokens") or 0)
        + int(item.get("reasoning_output_tokens") or 0)
        for item in metrics
    )
    cost = round(sum(float(item.get("cost_usd") or 0.0) for item in metrics), 6)
    attention = store.attention.list()
    interventions = sum(1 for item in attention if item.get("status") in {"answered", "resolved"})
    return {
        "runs": len(runs),
        "successful_changes": len(successful),
        "success_rate": round(len(successful) / len(runs), 4) if runs else 0.0,
        "tokens": tokens,
        "tool_calls": sum(int(item.get("tool_calls") or 0) for item in metrics),
        "cost_usd": cost,
        "cost_per_successful_change": round(cost / len(successful), 6) if successful else None,
        "open_attention": sum(1 for item in attention if item.get("status") == "open"),
        "human_interventions": interventions,
        "human_interventions_per_successful_change": (
            round(interventions / len(successful), 4) if successful else None
        ),
        "ci_failures": sum(1 for run in runs if int((run.get("ci") or {}).get("attempt") or 0) > 0),
        "merge_risk_high": sum(1 for run in runs if (run.get("merge_analysis") or {}).get("risk") == "high"),
    }
