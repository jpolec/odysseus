"""Explainable offline routing from accepted Odysseus outcome history."""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from .events import now_iso


SUCCESS_STATUSES = frozenset({"accepted", "pr_created"})
TERMINAL_STATUSES = SUCCESS_STATUSES | frozenset({"failed", "cancelled"})
INTERVENTION_EVENTS = frozenset(
    {"agent.question", "agent.permission_request", "agent.blocked", "agent.decision_required", "run.attention"}
)
REVIEW_CORRECTION_EVENTS = frozenset({"review.sent_back", "review.comment"})
CI_REPAIR_EVENTS = frozenset({"ci.retry_queued", "ci.retry_pushed"})
CODE_SURFACES = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".html": "web",
    ".css": "web",
    ".md": "documentation",
    ".sh": "shell",
    ".json": "config",
    ".yml": "config",
    ".yaml": "config",
    ".toml": "config",
}


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _safe_float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _safe_bool(value: Any, default: bool = False) -> bool:
    """Parse configuration booleans without treating the string 'false' as true."""

    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off", ""}:
            return False
    return default


def _seconds(start: Any, end: Any) -> float | None:
    if not start or not end:
        return None
    try:
        left = datetime.fromisoformat(str(start).replace("Z", "+00:00"))
        right = datetime.fromisoformat(str(end).replace("Z", "+00:00"))
    except ValueError:
        return None
    return max(0.0, (right - left).total_seconds())


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return round(ordered[middle], 3)
    return round((ordered[middle - 1] + ordered[middle]) / 2, 3)


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9_.-]+", "-", value.lower()).strip("-")[:80] or "unknown"


def _tokens(value: str) -> set[str]:
    return {item for item in re.findall(r"[a-z0-9][a-z0-9+_.-]+", value.lower()) if len(item) > 2}


class OutcomeRouter:
    """Read-only scorer for agent/model choices.

    The router never inspects prompts or code by default, and it never mutates a
    task's lane. It produces offline/shadow recommendations with the evidence
    and counterfactual trade-offs needed for operator review.
    """

    def __init__(self, store: Any) -> None:
        self.store = store

    @staticmethod
    def default_config() -> dict[str, Any]:
        return {
            "mode": "shadow",
            "min_samples": 5,
            "drift_min_samples": 8,
            "drift_window": 20,
            "drift_success_drop": 0.25,
            "allow_prompt_features": False,
            "disabled": False,
            "pins": {},
            "overrides": {},
        }

    def _config(self) -> dict[str, Any]:
        raw = self.store.config().get("outcome_router")
        config = self.default_config()
        if isinstance(raw, dict):
            config.update(raw)
        config["mode"] = str(config.get("mode") or "shadow")
        config["min_samples"] = max(1, _safe_int(config.get("min_samples")) or 5)
        config["drift_min_samples"] = max(1, _safe_int(config.get("drift_min_samples")) or 8)
        config["drift_window"] = max(2, _safe_int(config.get("drift_window")) or 20)
        config["drift_success_drop"] = max(0.0, min(1.0, _safe_float(config.get("drift_success_drop")) or 0.25))
        config["allow_prompt_features"] = _safe_bool(config.get("allow_prompt_features"), False)
        config["disabled"] = _safe_bool(config.get("disabled"), False)
        config["pins"] = config["pins"] if isinstance(config.get("pins"), dict) else {}
        config["overrides"] = config["overrides"] if isinstance(config.get("overrides"), dict) else {}
        return config

    @staticmethod
    def _model_for(run: Mapping[str, Any], events: list[dict[str, Any]]) -> str:
        for event in events:
            data = event.get("data") if isinstance(event.get("data"), dict) else {}
            model = str(data.get("model") or "").strip()
            if model:
                return model[:120]
        lane = str(run.get("lane") or "unknown")
        return "local-cli" if lane in {"codex", "claude"} else lane

    @staticmethod
    def _surface_for(run: Mapping[str, Any]) -> str:
        files = run.get("artifact_files") if isinstance(run.get("artifact_files"), list) else []
        counts: dict[str, int] = {}
        for item in files:
            suffix = Path(str(item)).suffix.lower()
            surface = CODE_SURFACES.get(suffix)
            if surface:
                counts[surface] = counts.get(surface, 0) + 1
        if counts:
            return sorted(counts.items(), key=lambda item: (-item[1], item[0]))[0][0]
        selected = run.get("skills_selected") if isinstance(run.get("skills_selected"), list) else []
        names = {str(item.get("name") or "") for item in selected if isinstance(item, dict)}
        if "frontend-accessibility" in names:
            return "web"
        if "database-change" in names:
            return "database"
        if "documentation-maintenance" in names:
            return "documentation"
        return "unknown"

    @staticmethod
    def _task_class_for(run: Mapping[str, Any], *, allow_prompt_features: bool) -> str:
        role = str(run.get("role") or "implementer")
        origin = str((run.get("provenance") if isinstance(run.get("provenance"), dict) else {}).get("origin") or "")
        if allow_prompt_features:
            selected = run.get("skills_selected") if isinstance(run.get("skills_selected"), list) else []
            names = sorted(str(item.get("name") or "") for item in selected if isinstance(item, dict) and item.get("name"))
            if names:
                return _slug(names[0])
            tokens = _tokens(str(run.get("task") or "")[:500])
            for name, words in {
                "bugfix": {"fix", "bug", "repair", "broken", "failed"},
                "test": {"test", "coverage", "unittest", "pytest"},
                "docs": {"docs", "readme", "document"},
                "feature": {"build", "implement", "add", "create"},
            }.items():
                if tokens & words:
                    return name
        return _slug(f"{role}-{origin or 'api'}")

    def _features_for(self, run: Mapping[str, Any], events: list[dict[str, Any]], config: Mapping[str, Any]) -> dict[str, str]:
        return {
            "repository": str(run.get("project_id") or ""),
            "task_class": self._task_class_for(run, allow_prompt_features=_safe_bool(config.get("allow_prompt_features"))),
            "surface": self._surface_for(run) if _safe_bool(config.get("allow_prompt_features")) else "unknown",
            "agent": str(run.get("lane") or "unknown"),
            "model": self._model_for(run, events),
        }

    @staticmethod
    def _empty() -> dict[str, Any]:
        return {
            "samples": 0,
            "terminal_samples": 0,
            "successful": 0,
            "success_rate": None,
            "review_corrections": 0,
            "ci_repairs": 0,
            "human_interventions": 0,
            "median_latency_seconds": None,
            "observed_cost_samples": 0,
            "avg_cost_usd": None,
            "run_ids": [],
        }

    def _records(self, *, before: str = "") -> list[dict[str, Any]]:
        config = self._config()
        deleted = self._deleted_project_ids()
        records: list[dict[str, Any]] = []
        for run in sorted(self.store.list(), key=lambda item: str(item.get("created_at") or "")):
            if str(run.get("kind") or "task") != "task":
                continue
            if str(run.get("project_id") or "") in deleted:
                continue
            created_at = str(run.get("created_at") or "")
            if before and created_at >= before:
                continue
            provenance = run.get("provenance") if isinstance(run.get("provenance"), dict) else {}
            if provenance.get("evidence_class") != "observed":
                continue
            status = str(run.get("status") or "")
            if status not in TERMINAL_STATUSES:
                continue
            run_id = str(run.get("id") or "")
            try:
                events = self.store.events_strict(run_id)
            except RuntimeError:
                continue
            metrics = run.get("metrics") if isinstance(run.get("metrics"), dict) else {}
            event_types = [str(event.get("type") or "") for event in events]
            cost_observed = bool(metrics.get("cost_observed"))
            cost = _safe_float(metrics.get("cost_usd")) if cost_observed else None
            records.append(
                {
                    "run_id": run_id,
                    "created_at": created_at,
                    "status": status,
                    "features": self._features_for(run, events, config),
                    "success": status in SUCCESS_STATUSES,
                    "review_corrections": sum(1 for event_type in event_types if event_type in REVIEW_CORRECTION_EVENTS),
                    "ci_repairs": 1 if any(event_type in CI_REPAIR_EVENTS for event_type in event_types) else 0,
                    "human_interventions": sum(1 for event_type in event_types if event_type in INTERVENTION_EVENTS),
                    "latency_seconds": _seconds(run.get("started_at"), run.get("finished_at")),
                    "cost_usd": cost,
                }
            )
        return records

    @staticmethod
    def _summarize(records: list[dict[str, Any]]) -> dict[str, Any]:
        summary = OutcomeRouter._empty()
        costs: list[float] = []
        latencies: list[float] = []
        for record in records:
            summary["samples"] += 1
            summary["terminal_samples"] += 1
            summary["successful"] += 1 if record["success"] else 0
            summary["review_corrections"] += int(record["review_corrections"])
            summary["ci_repairs"] += int(record["ci_repairs"])
            summary["human_interventions"] += int(record["human_interventions"])
            summary["run_ids"].append(record["run_id"])
            if record.get("latency_seconds") is not None:
                latencies.append(float(record["latency_seconds"]))
            if record.get("cost_usd") is not None:
                costs.append(float(record["cost_usd"]))
        if summary["terminal_samples"]:
            summary["success_rate"] = round(summary["successful"] / summary["terminal_samples"], 3)
        summary["median_latency_seconds"] = _median(latencies)
        if costs:
            summary["observed_cost_samples"] = len(costs)
            summary["avg_cost_usd"] = round(sum(costs) / len(costs), 6)
        return summary

    @staticmethod
    def _model_breakdown(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        by_model: dict[str, list[dict[str, Any]]] = {}
        for record in records:
            features = record.get("features") if isinstance(record.get("features"), dict) else {}
            model = str(features.get("model") or "unknown")
            by_model.setdefault(model, []).append(record)
        return [
            {"model": model, **OutcomeRouter._summarize(values)}
            for model, values in sorted(by_model.items())
        ]

    @staticmethod
    def _score(summary: Mapping[str, Any]) -> float:
        success = float(summary.get("success_rate") or 0.0)
        interventions = float(summary.get("human_interventions") or 0) / max(1, int(summary.get("samples") or 0))
        corrections = float(summary.get("review_corrections") or 0) / max(1, int(summary.get("samples") or 0))
        repairs = float(summary.get("ci_repairs") or 0) / max(1, int(summary.get("samples") or 0))
        latency = float(summary.get("median_latency_seconds") or 0.0)
        cost = float(summary.get("avg_cost_usd") or 0.0)
        return round((success * 100.0) - (interventions * 4.0) - (corrections * 5.0) - (repairs * 3.0) - min(latency / 600.0, 10.0) - min(cost * 3.0, 10.0), 3)

    @staticmethod
    def _matches(record: Mapping[str, Any], features: Mapping[str, str], candidate: str) -> bool:
        observed = record.get("features") if isinstance(record.get("features"), dict) else {}
        matches = (
            observed.get("repository") == features.get("repository")
            and observed.get("task_class") == features.get("task_class")
            and observed.get("surface") == features.get("surface")
            and observed.get("agent") == candidate
        )
        requested_model = str(features.get("model") or "").strip()
        return matches and (not requested_model or observed.get("model") == requested_model)

    def recommend(
        self,
        project_id: str,
        *,
        task: str = "",
        operator_default: str = "",
        request: Mapping[str, Any] | None = None,
        before: str = "",
    ) -> dict[str, Any]:
        config = self._config()
        default_lane = operator_default or str(self.store.config().get("default_lane") or "codex")
        project = self.store.projects.get(project_id)
        request_run = {
            "kind": "task",
            "task": task,
            "project_id": project_id,
            "project_path": project.get("path"),
            "lane": default_lane,
            "role": str((request or {}).get("role") or "implementer"),
            "provenance": {"origin": str((request or {}).get("origin") or "api")},
            # Prompt-derived and caller-supplied content features are opt-in.
            # Structural role/origin remain available for the privacy-safe class.
            "skills_selected": ((request or {}).get("skills_selected") or []) if config["allow_prompt_features"] else [],
            "artifact_files": ((request or {}).get("artifact_files") or []) if config["allow_prompt_features"] else [],
        }
        features = self._features_for(request_run, [], config)
        # No model is constrained unless an operator explicitly opts into and
        # supplies that feature. Lane-level recommendations may still expose a
        # per-model breakdown, but they cannot borrow a different model's
        # sample floor for a model-specific request.
        features["model"] = ""
        if request and config["allow_prompt_features"]:
            for key in ("task_class", "surface", "model"):
                if str(request.get(key) or "").strip():
                    features[key] = _slug(str(request[key])) if key != "model" else str(request[key])[:120]
        policy_key = f"{project_id}:{features['task_class']}:{features['surface']}"
        if config["disabled"]:
            return self._fallback("disabled", default_lane, features, config)
        if policy_key in config["pins"]:
            lane = str(config["pins"][policy_key] or default_lane)
            result = self._fallback("pinned", default_lane, features, config)
            result["recommended_lane"] = lane
            result["policy"] = {"type": "pin", "key": policy_key, "message": "operator pin selected this lane"}
            return result
        if policy_key in config["overrides"]:
            lane = str(config["overrides"][policy_key] or default_lane)
            result = self._fallback("overridden", default_lane, features, config)
            result["recommended_lane"] = lane
            result["policy"] = {"type": "override", "key": policy_key, "message": "operator override selected this lane"}
            return result

        records = self._records(before=before)
        observed_agents = {str(record["features"].get("agent")) for record in records if isinstance(record.get("features"), dict)}
        configured = set(self.store.config().get("lanes", {}).keys()) if isinstance(self.store.config().get("lanes"), dict) else set()
        candidates = sorted({"codex", "claude", default_lane, *configured, *observed_agents})
        evidence = []
        for candidate in candidates:
            cohort = [record for record in records if self._matches(record, features, candidate)]
            summary = self._summarize(cohort)
            summary["agent"] = candidate
            summary["models"] = self._model_breakdown(cohort)
            summary["score"] = self._score(summary) if summary["samples"] >= config["min_samples"] else None
            evidence.append(summary)
        eligible = [item for item in evidence if int(item.get("samples") or 0) >= config["min_samples"]]
        if not eligible:
            result = self._fallback("insufficient_samples", default_lane, features, config)
            result["evidence"] = evidence
            return result
        ranked = sorted(eligible, key=lambda item: (float(item.get("score") or 0.0), str(item.get("agent") or "")), reverse=True)
        best = ranked[0]
        default_summary = next((item for item in evidence if item["agent"] == default_lane), self._empty() | {"agent": default_lane})
        result = {
            "algorithm": "outcome-router-v1",
            "mode": "shadow",
            "created_at": now_iso(),
            "operator_default": default_lane,
            "recommended_lane": str(best["agent"]),
            "applied_lane": default_lane,
            "autonomous_routing": False,
            "reason": "offline recommendation only; operator default retained",
            "features": features,
            "minimum_samples": config["min_samples"],
            "prompt_features_enabled": _safe_bool(config["allow_prompt_features"]),
            "evidence": evidence,
            "counterfactual": self._counterfactual(best, default_summary),
            "drift": self.detect_drift(project_id, agent=str(best["agent"])),
            "governance": "repository checks and policies remain deterministic and are not inferred by this router",
        }
        return result

    def _fallback(self, reason: str, default_lane: str, features: Mapping[str, str], config: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "algorithm": "outcome-router-v1",
            "mode": "shadow",
            "created_at": now_iso(),
            "operator_default": default_lane,
            "recommended_lane": default_lane,
            "applied_lane": default_lane,
            "autonomous_routing": False,
            "reason": reason,
            "features": dict(features),
            "minimum_samples": config["min_samples"],
            "prompt_features_enabled": _safe_bool(config["allow_prompt_features"]),
            "evidence": [],
            "counterfactual": {"message": "operator default retained; no eligible alternative was used"},
            "drift": [],
            "governance": "repository checks and policies remain deterministic and are not inferred by this router",
        }

    @staticmethod
    def _counterfactual(best: Mapping[str, Any], default: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "recommended_agent": best.get("agent"),
            "default_agent": default.get("agent"),
            "success_rate_delta": (
                round(float(best["success_rate"]) - float(default["success_rate"]), 3)
                if best.get("success_rate") is not None and default.get("success_rate") is not None
                else None
            ),
            "median_latency_seconds_delta": (
                round(float(best["median_latency_seconds"]) - float(default["median_latency_seconds"]), 3)
                if best.get("median_latency_seconds") is not None and default.get("median_latency_seconds") is not None
                else None
            ),
            "avg_cost_usd_delta": (
                round(float(best["avg_cost_usd"]) - float(default["avg_cost_usd"]), 6)
                if best.get("avg_cost_usd") is not None and default.get("avg_cost_usd") is not None
                else None
            ),
            "human_interventions_delta": int(best.get("human_interventions") or 0) - int(default.get("human_interventions") or 0),
            "review_corrections_delta": int(best.get("review_corrections") or 0) - int(default.get("review_corrections") or 0),
            "ci_repairs_delta": int(best.get("ci_repairs") or 0) - int(default.get("ci_repairs") or 0),
        }

    def detect_drift(self, project_id: str, *, agent: str = "") -> list[dict[str, Any]]:
        config = self._config()
        records = [
            record
            for record in self._records()
            if record["features"].get("repository") == project_id
            and (not agent or record["features"].get("agent") == agent)
        ]
        grouped: dict[str, list[dict[str, Any]]] = {}
        for record in records:
            key = str(record["features"].get("agent") or "unknown")
            grouped.setdefault(key, []).append(record)
        drift: list[dict[str, Any]] = []
        for key, values in sorted(grouped.items()):
            window = config["drift_window"]
            if len(values) < max(config["drift_min_samples"] * 2, window):
                continue
            baseline = values[:-window]
            recent = values[-window:]
            if len(baseline) < config["drift_min_samples"] or len(recent) < config["drift_min_samples"]:
                continue
            base_rate = sum(1 for item in baseline if item["success"]) / len(baseline)
            recent_rate = sum(1 for item in recent if item["success"]) / len(recent)
            drop = base_rate - recent_rate
            if drop >= config["drift_success_drop"]:
                drift.append(
                    {
                        "agent": key,
                        "baseline_success_rate": round(base_rate, 3),
                        "recent_success_rate": round(recent_rate, 3),
                        "drop": round(drop, 3),
                        "recent_samples": len(recent),
                        "baseline_samples": len(baseline),
                    }
                )
        return drift

    def backtest(self, project_id: str) -> dict[str, Any]:
        records = [record for record in self._records() if record["features"].get("repository") == project_id]
        decisions: list[dict[str, Any]] = []
        for record in records:
            recommendation = self.recommend(
                project_id,
                operator_default=str(record["features"].get("agent") or ""),
                request={
                    "role": "implementer",
                    "origin": "api",
                    "task_class": record["features"].get("task_class"),
                    "surface": record["features"].get("surface"),
                },
                before=str(record.get("created_at") or ""),
            )
            decisions.append(
                {
                    "run_id": record["run_id"],
                    "created_at": record["created_at"],
                    "actual_agent": record["features"].get("agent"),
                    "recommended_agent": recommendation["recommended_lane"],
                    "eligible": recommendation["reason"] not in {"insufficient_samples", "disabled"},
                    "success": record["success"],
                }
            )
        return {
            "algorithm": "outcome-router-v1",
            "project_id": project_id,
            "leakage_prevention": "each recommendation uses only runs created before the evaluated run",
            "decisions": decisions,
            "evaluated_runs": len(decisions),
        }

    def export(self, project_id: str = "") -> dict[str, Any]:
        records = [
            record
            for record in self._records()
            if not project_id or record["features"].get("repository") == project_id
        ]
        return {
            "format": "odysseus-outcome-router-export-v1",
            "exported_at": now_iso(),
            "project_id": project_id,
            "records": records,
            "content_features_included": bool(self._config().get("allow_prompt_features")),
        }

    def delete(self, project_id: str) -> dict[str, Any]:
        path = self.store.root / "outcome_router_deletions.ndjson"
        record = {"project_id": project_id, "deleted_at": now_iso(), "effect": "future exports and recommendations should exclude this repository after raw run deletion"}
        with self.store.locked():
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
        return record

    def _deleted_project_ids(self) -> set[str]:
        path = self.store.root / "outcome_router_deletions.ndjson"
        deleted: set[str] = set()
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return deleted
        for line in lines:
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict) and value.get("project_id"):
                deleted.add(str(value["project_id"]))
        return deleted
