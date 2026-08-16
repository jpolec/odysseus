"""Cross-project search over Odysseus' inspectable local state."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from .economics import outcome_economics

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
    economics = outcome_economics(store)
    totals = economics["totals"]
    tokens = sum(int(bucket.get("total_tokens") or 0) for bucket in totals["tokens"].values())
    runs = [run for run in store.list() if run.get("kind") == "task"]
    metrics = [run.get("metrics") if isinstance(run.get("metrics"), dict) else {} for run in runs]
    attention = store.attention.list()
    return {
        "runs": totals["tasks"],
        "successful_changes": totals["accepted_changes"],
        "success_rate": totals["acceptance_rate"],
        "tokens": tokens,
        "tokens_by_phase": totals["tokens"],
        "tool_calls": sum(int(item.get("tool_calls") or 0) for item in metrics),
        "cost_usd": totals["observed_model_cost_usd"],
        "cost_per_successful_change": totals["cost_per_accepted_change_usd"],
        "open_attention": sum(1 for item in attention if item.get("status") == "open"),
        "human_interventions": totals["human_interventions"],
        "human_interventions_per_successful_change": (
            round(totals["human_interventions"] / totals["accepted_changes"], 4)
            if totals["accepted_changes"]
            else None
        ),
        "ci_failures": sum(1 for run in runs if int((run.get("ci") or {}).get("attempt") or 0) > 0),
        "merge_risk_high": sum(1 for run in runs if (run.get("merge_analysis") or {}).get("risk") == "high"),
        "outcome_economics": economics,
    }
