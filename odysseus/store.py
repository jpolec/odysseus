"""Durable JSON run store and append-only NDJSON event history."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import secrets
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping

from .events import EVENT_SCHEMA_VERSION, EVENT_TYPES, Event, now_iso
from .environments import normalize_environment_request
from .failpoints import failpoint
from .attention import AttentionQueue
from .commands import CommandBus, kernel_command_metadata
from .epics import EpicStore, VALID_ROLES
from .inbox import Inbox
from .kernel import EventKernel, KernelIntegrityError
from .notifications import NotificationManager
from .outcome_router import OutcomeRouter
from .project_knowledge import ProjectKnowledge
from .projects import ProjectRegistry
from .redaction import DEFAULT_REDACTION_ENGINE
from .skills import SkillRegistry, VALID_TASK_MODES
from .variants import normalize_variants_request
from .worker_leases import (
    DEFAULT_WORKER_LEASE_TTL_SECONDS,
    active_worker_lease,
    lease_owner_live,
    new_worker_lease,
    released_worker_lease,
    validate_and_renew_worker_lease,
)


RUN_ID_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
TERMINAL_STATUSES = frozenset({"accepted", "pr_created", "cancelled", "rejected", "decided"})
ACTIVE_STATUSES = frozenset(
    {"starting", "running", "checking", "reviewing", "cancelling", "publishing"}
)
REVIEWABLE_STATUSES = frozenset({"review", "failed", "accepted", "attention"})
DEFAULT_CONFIG: dict[str, Any] = {
    "max_parallel": 2,
    "default_lane": "codex",
    "default_workflow": "agent-check-review",
    "max_retries": 2,
    "planner_lane": "",
    "review_lane": "",
    "assistant_models": {},
    "lanes": {},
    "budgets": {
        "timeout_seconds": 0,
        "stall_seconds": 900,
        "max_tokens": 0,
        "max_tool_calls": 0,
        "max_cost_usd": 0.0,
    },
    "ci": {
        "watch": True,
        "auto_resume": True,
        "max_attempts": 2,
        "poll_seconds": 30,
    },
    "notifications": [],
    "resource_retention_days": 14,
    "evaluation_policy": {
        "min_confidence": 0.85,
        "require_human_review": True,
        "required_evaluators": [],
    },
    "outcome_router": OutcomeRouter.default_config(),
    "portfolio": {"baseline_engineer_minutes_per_delivery": 0},
}


RUN_SCHEMA_VERSION = 16
ROUTE_OBSERVATION_FORMAT = "odysseus-route-observation-v1"
ROUTE_OBSERVATION_FEATURE_SCHEMA_VERSION = "outcome-router-features-v1"
ROUTE_OBSERVATION_POLICY_VERSION = "outcome-routing-policy-v1"
ROUTE_OBSERVATION_UTILITY_PROFILE_VERSION = "outcome-router-utility-v1"


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _run_defaults() -> dict[str, Any]:
    return {
        "epic_id": "",
        "task_key": "",
        "role": "implementer",
        "depends_on": [],
        "dependency_keys": [],
        "dependencies_met": [],
        "blocks": [],
        "block_keys": [],
        "parallelizable": True,
        "blocked_reason": "",
        "task_contract": {},
        "execution_profile": {},
        "estimate": {},
        "failure": {},
        "evaluation": {},
        "verifier_results": [],
        "confidence": None,
        "policy_decision": "human_review",
        "human_review_required": True,
        "pending_operator_response": "",
        "priority": 50,
        "artifact_sha": "",
        "artifact_files": [],
        "artifact_created_at": None,
        "delivery": {
            "status": "not_ready",
            "method": "",
            "target_branch": "",
            "target_before_sha": "",
            "target_after_sha": "",
            "delivered_at": None,
            "error": "",
        },
        "integration_sources": [],
        "integration_head": "",
        "integration_conflicts": [],
        "integration_disposition": {
            "state": "pending",
            "integration_run_id": "",
            "superseded_by": "",
            "reason": "",
            "decided_at": None,
        },
        "merge_analysis": {"risk": "none", "source_count": 0, "overlaps": [], "files": []},
        "ci": {
            "status": "not_started",
            "attempt": 0,
            "checks": [],
            "summary": "",
            "updated_at": None,
        },
        "ci_retry_active": False,
        "github_feedback_seen": [],
        "budgets": {},
        "budget_status": {"state": "within", "reason": ""},
        "stage": "queued",
        "stage_started_at": None,
        "last_heartbeat": None,
        "worker_lease": {},
        "skill_mode": "auto",
        "skills_requested": [],
        "skills_selected": [],
        "skill_context": [],
        "context_bundle": [],
        "context_receipt": {},
        "source_documents": [],
        "knowledge_selected": [],
        "skill_routing": {},
        "environment_request": {},
        "environment": {
            "version": "environment-plan-v1",
            "profile": "host",
            "status": "pending",
            "isolation": "none; host user permissions apply",
        },
        "untrusted_project": False,
        "project_commands_approved": False,
        "provenance": {
            "format": "odysseus-run-provenance-v1",
            "evidence_class": "unclassified",
            "origin": "legacy",
            "odysseus_version": "",
            "release": "",
            "observed_at": None,
        },
        "variants": {"enabled": False},
        "variant": {
            "parent_run_id": "",
            "index": 0,
            "title": "",
            "prompt_sha256": "",
            "model": "",
        },
        "variant_comparison": {},
        "variant_decision": {
            "decision": "",
            "selected_run_ids": [],
            "integration_run_id": "",
            "reason": "",
            "decided_at": None,
        },
        "outcome_routing": {},
        "route_observation": {},
        "redaction_receipt": {},
    }


def _selected_model_for(run: Mapping[str, Any]) -> str:
    metrics = run.get("metrics") if isinstance(run.get("metrics"), Mapping) else {}
    model = str(metrics.get("model") or "").strip()
    if model:
        return model[:120]
    variant = run.get("variant") if isinstance(run.get("variant"), Mapping) else {}
    model = str(variant.get("model") or "").strip()
    if model:
        return model[:120]
    profile = run.get("execution_profile") if isinstance(run.get("execution_profile"), Mapping) else {}
    model = str(profile.get("model") or "").strip()
    if model:
        return model[:120]
    lane = str(run.get("lane") or "")
    return "local-cli" if lane in {"codex", "claude"} else lane[:120]


def _route_selection_source(run: Mapping[str, Any], outcome_routing: Mapping[str, Any]) -> str:
    if not outcome_routing:
        return "operator"
    mode = str(outcome_routing.get("mode") or "shadow")
    if bool(outcome_routing.get("autonomous_routing")):
        return "outcome_router_auto"
    if mode == "automatic_fallback":
        return "outcome_router_fallback"
    recommended = str(outcome_routing.get("recommended_lane") or "")
    applied = str(outcome_routing.get("applied_lane") or run.get("lane") or "")
    if recommended and recommended != applied:
        return "operator_default_shadow_recommendation"
    return "operator"


def _route_result_for(run: Mapping[str, Any]) -> dict[str, Any]:
    status = str(run.get("status") or "")
    terminal = status in TERMINAL_STATUSES or status in {"failed", "review"}
    success = True if status in {"accepted", "pr_created"} else False if terminal else None
    return {
        "status": status,
        "terminal": terminal,
        "success": success,
        "policy_decision": str(run.get("policy_decision") or ""),
        "last_error": str(run.get("last_error") or "")[:1000],
    }


def _route_observation_for(run: Mapping[str, Any]) -> dict[str, Any]:
    if str(run.get("kind") or "task") != "task":
        return {}
    outcome_routing = run.get("outcome_routing") if isinstance(run.get("outcome_routing"), Mapping) else {}
    features = outcome_routing.get("features") if isinstance(outcome_routing.get("features"), Mapping) else {}
    metrics = run.get("metrics") if isinstance(run.get("metrics"), Mapping) else {}
    selected_skills = [
        {
            "name": str(skill.get("name") or ""),
            "policy": str(skill.get("policy") or ""),
            "reason": str(skill.get("reason") or ""),
            "sha256": str(skill.get("sha256") or ""),
        }
        for skill in (run.get("skills_selected") if isinstance(run.get("skills_selected"), list) else [])
        if isinstance(skill, Mapping) and str(skill.get("name") or "")
    ]
    tokens = {
        "input_tokens": _safe_int(metrics.get("input_tokens")),
        "cached_input_tokens": _safe_int(metrics.get("cached_input_tokens")),
        "output_tokens": _safe_int(metrics.get("output_tokens")),
        "reasoning_output_tokens": _safe_int(metrics.get("reasoning_output_tokens")),
    }
    tokens["total_tokens"] = tokens["input_tokens"] + tokens["output_tokens"] + tokens["reasoning_output_tokens"]
    cost_observed = bool(metrics.get("cost_observed"))
    try:
        cost_usd = round(float(metrics.get("cost_usd") or 0.0), 8) if cost_observed else None
    except (TypeError, ValueError):
        cost_usd = None
    return {
        "format": ROUTE_OBSERVATION_FORMAT,
        "task_class": str(features.get("task_class") or ""),
        "selected": {
            "agent": str(run.get("lane") or ""),
            "model": _selected_model_for(run),
            "skills": selected_skills,
        },
        "selection_source": _route_selection_source(run, outcome_routing),
        "selection_propensity": 1.0,
        "metadata_versions": {
            "advisor_version": str(outcome_routing.get("algorithm") or "outcome-router-v1"),
            "policy_version": ROUTE_OBSERVATION_POLICY_VERSION,
            "model_version": _selected_model_for(run),
            "feature_schema_version": ROUTE_OBSERVATION_FEATURE_SCHEMA_VERSION,
            "utility_profile_version": ROUTE_OBSERVATION_UTILITY_PROFILE_VERSION,
        },
        "timing": {
            "created_at": run.get("created_at"),
            "started_at": run.get("started_at"),
            "finished_at": run.get("finished_at"),
        },
        "tokens": tokens,
        "cost": {
            "observed": cost_observed,
            "usd": cost_usd,
            "source": "metrics.cost_usd" if cost_observed else "",
        },
        "result": _route_result_for(run),
        "upcast": {
            "source": "run.outcome_routing",
            "compatible_export_format": "odysseus-outcome-router-export-v1",
        },
    }


def default_state_root() -> Path:
    configured = os.environ.get("ODYSSEUS_HOME")
    return Path(configured).expanduser() if configured else Path.home() / ".odysseus"


def _slug(value: str, fallback: str = "task", limit: int = 36) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return (slug or fallback)[:limit].rstrip("-")


def _display_title(task: str, limit: int = 82) -> str:
    """Create a quiet navigation label while preserving the full task body."""

    lines = [re.sub(r"\s+", " ", line).strip() for line in task.splitlines() if line.strip()]
    first_line = lines[0] if lines else task
    if len(lines) > 1 and first_line.casefold() == lines[1].casefold():
        first_line = lines[1]
    value = re.sub(r"\s+", " ", first_line).strip().lstrip("-*# ")
    value = re.sub(
        r"^(?:please|could you|can you|prosz[eę]|czy mo[zż]esz|jeszcze|zobacz)\s*[:,—-]?\s*",
        "",
        value,
        flags=re.IGNORECASE,
    ).strip()
    value = re.split(r"\s+(?:np\.|e\.g\.|na przyk(?:ł|l)ad)\s*", value, maxsplit=1, flags=re.IGNORECASE)[0]
    value = re.sub(r"^(?:i teraz|a teraz|and now)\s+", "", value, flags=re.IGNORECASE).strip(" :,-–—")
    sentence = re.split(r"[.!?](?:\s|$)", value, maxsplit=1)[0].strip() or value
    if len(sentence) <= limit:
        return sentence
    clipped = sentence[:limit].rsplit(" ", 1)[0].rstrip(" ,:;-–—")
    return f"{clipped or sentence[: limit - 1]}…"


def _pid_alive(pid: Any) -> bool:
    try:
        number = int(pid)
        if number <= 0:
            return False
        os.kill(number, 0)
        return True
    except (OSError, TypeError, ValueError):
        return False


class RunStore:
    """Small, inspectable persistence layer safe across local processes."""

    def __init__(
        self,
        root: Path | str | None = None,
        *,
        migrate: bool = True,
        readonly: bool = False,
    ) -> None:
        self.root = Path(root).expanduser() if root is not None else default_state_root()
        self.readonly = readonly
        self.runs_dir = self.root / "runs"
        self.events_dir = self.root / "events"
        self.worktrees_dir = self.root / "worktrees"
        self._runtime_runs_signature: tuple[tuple[str, int, int], ...] | None = None
        self._runtime_runs_cache: list[dict[str, Any]] = []
        if not readonly:
            self.root.mkdir(parents=True, exist_ok=True)
            self.runs_dir.mkdir(exist_ok=True)
            self.events_dir.mkdir(exist_ok=True)
            self.worktrees_dir.mkdir(exist_ok=True)
        self.lock_path = self.root / ".store.lock"
        self.config_path = self.root / "config.json"
        if not readonly and not self.config_path.exists():
            self._atomic_json(self.config_path, DEFAULT_CONFIG)
        self.redaction = DEFAULT_REDACTION_ENGINE
        self.kernel = EventKernel(self.root, readonly=readonly)
        self.commands = CommandBus(self.root, kernel=self.kernel, readonly=readonly)
        self.projects = ProjectRegistry(self)
        self.knowledge = ProjectKnowledge(self)
        self.skills = SkillRegistry(self)
        self.inbox = Inbox(self)
        self.attention = AttentionQueue(self)
        self.epics = EpicStore(self)
        self.notifications = NotificationManager(self)
        self.outcome_router = OutcomeRouter(self)
        if migrate and not readonly:
            self._migrate_runs()

    def _migrate_runs(self) -> None:
        """Upgrade old snapshots in place while preserving append-only journals."""

        with self.locked():
            for stream in self.kernel.streams_dir.glob("*.ndjson"):
                path = self.runs_dir / f"{stream.stem}.json"
                if not path.exists():
                    self.kernel.rebuild(stream.stem)
            for path in self.runs_dir.glob("*.json"):
                canonical_events: list[dict[str, Any]] = []
                try:
                    disk_run = json.loads(path.read_text(encoding="utf-8"))
                except OSError as exc:
                    raise RuntimeError(f"cannot read run record: {path}") from exc
                except json.JSONDecodeError as exc:
                    if not self.kernel.has_stream(path.stem):
                        raise RuntimeError(f"corrupt run record: {path}") from exc
                    disk_run = {}
                if not isinstance(disk_run, dict):
                    raise RuntimeError(f"invalid run record: {path}")
                if self.kernel.has_stream(path.stem):
                    try:
                        canonical_events = self.kernel.read(path.stem)
                        run = self.kernel._replay_events(canonical_events)
                    except KernelIntegrityError as exc:
                        raise RuntimeError(f"invalid canonical stream for {path.stem}: {exc}") from exc
                    if not run:
                        raise RuntimeError(f"empty canonical stream for {path.stem}")
                else:
                    run = dict(disk_run)
                schema_version = _safe_int(run.get("schema_version"))
                if schema_version > RUN_SCHEMA_VERSION:
                    raise RuntimeError(
                        f"run record {path} uses schema {schema_version}; "
                        f"this Odysseus supports up to {RUN_SCHEMA_VERSION}"
                    )
                changed = False
                for key, value in _run_defaults().items():
                    if key not in run:
                        run[key] = value
                        changed = True
                if schema_version < RUN_SCHEMA_VERSION:
                    run["schema_version"] = RUN_SCHEMA_VERSION
                    changed = True
                observation = _route_observation_for(run)
                if observation and run.get("route_observation") != observation:
                    run["route_observation"] = observation
                    changed = True
                snapshot = self._redact_snapshot(run)
                if not self.kernel.has_stream(path.stem):
                    self.kernel.append_run(
                        path.stem,
                        event_type="projection.imported",
                        actor="migration",
                        projection=snapshot,
                    )
                elif changed:
                    canonical_events.append(
                        self.kernel.append_run(
                            path.stem,
                            event_type="projection.migrated",
                            actor="migration",
                            projection=snapshot,
                        )
                    )
                if snapshot != disk_run:
                    self._atomic_json(path, snapshot)
                if canonical_events:
                    # The checkpoint and JSON snapshot are replaceable caches.
                    # A crash after canonical stream fsync may leave either
                    # stale, so startup rebuilds both from the immutable tail.
                    self.kernel.write_checkpoint(path.stem, canonical_events[-1], snapshot)
                self._reconcile_domain_journal(path.stem)

    @contextmanager
    def locked(self) -> Iterator[None]:
        if self.readonly:
            if not self.lock_path.exists():
                yield
                return
            with self.lock_path.open("r") as lock:
                fcntl.flock(lock.fileno(), fcntl.LOCK_SH)
                try:
                    yield
                finally:
                    fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
            return
        with self.lock_path.open("a+") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    def _atomic_json(self, path: Path, value: Mapping[str, Any]) -> None:
        if self.readonly:
            raise RuntimeError("state is open read-only")
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_name, path)
        finally:
            try:
                os.unlink(tmp_name)
            except FileNotFoundError:
                pass

    def _persist_run(
        self,
        run: Mapping[str, Any],
        *,
        event_type: str,
        actor: str = "odysseus",
        domain_event: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        if self.readonly:
            raise RuntimeError("state is open read-only")
        run_id = str(run.get("id") or "")
        if not run_id:
            raise ValueError("run id is required")
        snapshot = self._redact_snapshot(run)
        self.kernel.append_run(
            run_id,
            event_type=event_type,
            actor=actor,
            projection=snapshot,
            domain_event=domain_event,
            **kernel_command_metadata(run_id),
        )
        self._atomic_json(self._path(run_id), snapshot)
        return snapshot

    def _reconcile_domain_journal(self, run_id: str) -> None:
        canonical = self.kernel.domain_events(run_id)
        if not canonical:
            return
        path = self._events_path(run_id)
        tail = 0
        if path.exists():
            try:
                for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                    if not line.strip():
                        continue
                    value = json.loads(line)
                    seq = value.get("seq") if isinstance(value, dict) else None
                    if not isinstance(seq, int) or seq != tail + 1:
                        raise RuntimeError(f"cannot reconcile non-contiguous event journal: {path}:{number}")
                    tail = seq
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"cannot reconcile corrupt event journal: {path}") from exc
        pending = sorted(
            (event for event in canonical if isinstance(event.get("seq"), int) and int(event["seq"]) > tail),
            key=lambda event: int(event["seq"]),
        )
        if not pending:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            for event in pending:
                if int(event["seq"]) != tail + 1:
                    raise RuntimeError(f"canonical event journal recovery has a gap for {run_id}")
                handle.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")
                tail += 1
            handle.flush()
            os.fsync(handle.fileno())

    def _redact_snapshot(self, run: Mapping[str, Any]) -> dict[str, Any]:
        previous = run.get("redaction_receipt") if isinstance(run.get("redaction_receipt"), dict) else {}
        previous_classes = previous.get("redacted_field_classes") if isinstance(previous, dict) else []
        if not isinstance(previous_classes, list):
            previous_classes = []
        value, receipt = self.redaction.redact(dict(run), boundary="run_snapshot")
        if not isinstance(value, dict):
            raise RuntimeError("redacted run snapshot must be an object")
        value["redaction_receipt"] = {
            **receipt.to_dict(),
            "redacted_field_classes": sorted(
                {
                    *receipt.redacted_field_classes,
                    *[str(item) for item in previous_classes if isinstance(item, str)],
                }
            ),
        }
        return value

    def _redact_event_record(self, event: Mapping[str, Any]) -> dict[str, Any]:
        previous = event.get("redaction_receipt") if isinstance(event.get("redaction_receipt"), dict) else {}
        previous_classes = previous.get("redacted_field_classes") if isinstance(previous, dict) else []
        if not isinstance(previous_classes, list):
            previous_classes = []
        value, receipt = self.redaction.redact(dict(event), boundary="event")
        if not isinstance(value, dict):
            raise RuntimeError("redacted event must be an object")
        value["redaction_receipt"] = {
            **receipt.to_dict(),
            "redacted_field_classes": sorted(
                {
                    *receipt.redacted_field_classes,
                    *[str(item) for item in previous_classes if isinstance(item, str)],
                }
            ),
        }
        return value

    def config(self) -> dict[str, Any]:
        with self.locked():
            try:
                value = json.loads(self.config_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                value = {}
        merged = dict(DEFAULT_CONFIG)
        if isinstance(value, dict):
            merged.update(value)
        merged["max_parallel"] = max(1, _safe_int(merged.get("max_parallel", 2)) or 2)
        merged["max_retries"] = max(0, _safe_int(merged.get("max_retries", 2)))
        merged["resource_retention_days"] = max(1, _safe_int(merged.get("resource_retention_days", 14)) or 14)
        ci = dict(DEFAULT_CONFIG["ci"])
        if isinstance(merged.get("ci"), dict):
            ci.update(merged["ci"])
        ci["max_attempts"] = max(0, _safe_int(ci.get("max_attempts", 2)))
        ci["poll_seconds"] = max(5, _safe_int(ci.get("poll_seconds", 30)) or 30)
        merged["ci"] = ci
        budgets = dict(DEFAULT_CONFIG["budgets"])
        if isinstance(merged.get("budgets"), dict):
            budgets.update(merged["budgets"])
        merged["budgets"] = budgets
        raw_models = merged.get("assistant_models")
        merged["assistant_models"] = {
            provider: str(model).strip()[:200]
            for provider, model in (raw_models.items() if isinstance(raw_models, dict) else [])
            if provider in {"openai", "anthropic"} and str(model).strip()
        }
        router = OutcomeRouter.default_config()
        if isinstance(merged.get("outcome_router"), dict):
            router.update(merged["outcome_router"])
        merged["outcome_router"] = router
        portfolio = dict(DEFAULT_CONFIG["portfolio"])
        if isinstance(merged.get("portfolio"), dict):
            portfolio.update(merged["portfolio"])
        merged["portfolio"] = portfolio
        return merged

    def update_config(self, changes: Mapping[str, Any]) -> dict[str, Any]:
        allowed = {
            "max_parallel",
            "default_lane",
            "default_workflow",
            "max_retries",
            "planner_lane",
            "review_lane",
            "assistant_models",
            "lanes",
            "evaluation_policy",
            "budgets",
            "ci",
            "notifications",
            "resource_retention_days",
            "outcome_router",
            "portfolio",
        }
        unknown = set(changes) - allowed
        if unknown:
            raise ValueError(f"unknown config keys: {', '.join(sorted(unknown))}")
        with self.locked():
            try:
                raw = json.loads(self.config_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                raw = {}
            value = dict(DEFAULT_CONFIG)
            if isinstance(raw, dict):
                value.update(raw)
            value.update(changes)
            self._atomic_json(self.config_path, value)
        return self.config()

    def _path(self, run_id: str) -> Path:
        if not RUN_ID_RE.fullmatch(run_id):
            raise ValueError("invalid run id")
        return self.runs_dir / f"{run_id}.json"

    def _events_path(self, run_id: str) -> Path:
        if not RUN_ID_RE.fullmatch(run_id):
            raise ValueError("invalid run id")
        return self.events_dir / f"{run_id}.ndjson"

    def get(self, run_id: str) -> dict[str, Any]:
        path = self._path(run_id)
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise KeyError(run_id) from exc
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"corrupt run record: {path}") from exc
        if not isinstance(value, dict):
            raise RuntimeError(f"invalid run record: {path}")
        for key, default in _run_defaults().items():
            value.setdefault(key, default)
        return self._redact_snapshot(value)

    def _list_records(self, *, redact: bool) -> list[dict[str, Any]]:
        runs: list[dict[str, Any]] = []
        for path in self.runs_dir.glob("*.json"):
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(value, dict):
                for key, default in _run_defaults().items():
                    value.setdefault(key, default)
                runs.append(self._redact_snapshot(value) if redact else value)
        return sorted(runs, key=lambda item: str(item.get("created_at", "")), reverse=True)

    def list(self) -> list[dict[str, Any]]:
        return self._list_records(redact=True)

    def runtime_runs(self) -> list[dict[str, Any]]:
        """Load persisted run state for the trusted scheduler without re-redacting it.

        The durable write boundary already redacts snapshots. Avoiding another
        recursive regex pass on every scheduler tick keeps an idle server idle;
        HTTP and CLI readers continue to use :meth:`list`.
        """

        signature: list[tuple[str, int, int]] = []
        for path in sorted(self.runs_dir.glob("*.json")):
            try:
                stat = path.stat()
                signature.append((path.name, int(stat.st_mtime_ns), int(stat.st_size)))
            except OSError:
                signature.append((path.name, 0, 0))
        current = tuple(signature)
        if current != self._runtime_runs_signature:
            self._runtime_runs_cache = self._list_records(redact=False)
            self._runtime_runs_signature = current
        return [dict(run) for run in self._runtime_runs_cache]

    def create(self, request: Mapping[str, Any]) -> dict[str, Any]:
        task = str(request.get("task", "")).strip()
        if not task:
            raise ValueError("task is required")
        task = str(self.redaction.redact(task, boundary="run_request")[0])
        project = Path(str(request.get("project_path", "."))).expanduser().resolve()
        if not project.is_dir():
            raise ValueError(f"project directory does not exist: {project}")
        project_record = self.projects.upsert(project)
        config = self.config()
        stamp = now_iso()
        compact_stamp = stamp.replace("-", "").replace(":", "").replace("T", "-")[:15]
        raw_title = request.get("title")
        explicit_title = str(raw_title).strip() if raw_title is not None else ""
        title = explicit_title or _display_title(task)
        title = str(self.redaction.redact(title, boundary="run_request")[0])
        run_id = f"{compact_stamp}-{_slug(title)}-{secrets.token_hex(2)}"
        checks = request.get("checks", [])
        if not isinstance(checks, list) or not all(isinstance(item, str) for item in checks):
            raise ValueError("checks must be a list of shell command strings")
        retries_value = request.get("max_retries")
        max_retries = config["max_retries"] if retries_value is None else _safe_int(retries_value)
        kind = str(request.get("kind") or "task")
        initial_status = str(request.get("status") or "queued")
        role = str(request.get("role") or "implementer")
        if role not in VALID_ROLES:
            raise ValueError("role must be planner, implementer, or reviewer")
        graph_lists: dict[str, list[str]] = {}
        for key in ("depends_on", "dependency_keys", "blocks", "block_keys"):
            raw = request.get(key) or []
            if not isinstance(raw, list) or not all(isinstance(item, str) for item in raw):
                raise ValueError(f"{key} must be a list of run ids or task keys")
            graph_lists[key] = list(dict.fromkeys(raw))
        raw_budgets = request.get("budgets") or {}
        if not isinstance(raw_budgets, dict):
            raise ValueError("budgets must be an object")
        budgets = dict(config.get("budgets") or {})
        budgets.update(raw_budgets)
        for key in ("timeout_seconds", "stall_seconds", "max_tokens", "max_tool_calls"):
            budgets[key] = max(0, _safe_int(budgets.get(key)))
        try:
            budgets["max_cost_usd"] = max(0.0, float(budgets.get("max_cost_usd") or 0.0))
        except (TypeError, ValueError) as exc:
            raise ValueError("max_cost_usd must be numeric") from exc
        priority = max(0, min(100, _safe_int(request.get("priority", 50))))
        skill_mode = str(request.get("skill_mode") or "auto")
        if skill_mode not in VALID_TASK_MODES:
            raise ValueError("skill mode must be auto, manual, or none")
        skills_requested = request.get("skills") or []
        if not isinstance(skills_requested, list) or not all(isinstance(item, str) for item in skills_requested):
            raise ValueError("skills must be a list of skill names")
        environment_request = normalize_environment_request(request.get("environment"))
        workflow = str(request.get("workflow") or config["default_workflow"])
        variants = normalize_variants_request(request, default_lane=str(request.get("lane") or config["default_lane"]))
        if workflow == "variants" and not variants.get("enabled"):
            raise ValueError("variants workflow requires explicit variants configuration")
        from . import __version__

        evidence_class = str(request.get("evidence_class") or "observed")
        if kind == "tmux" and "evidence_class" not in request:
            evidence_class = "imported"
        if evidence_class not in {"observed", "demo", "test", "imported", "unclassified"}:
            raise ValueError("evidence_class must be observed, demo, test, imported, or unclassified")
        origin = str(request.get("origin") or ("tmux" if kind == "tmux" else "api"))
        release = str(request.get("release") or os.environ.get("ODYSSEUS_RELEASE_TARGET") or __version__)
        selected_skills = self.skills.select(
            project_record,
            task,
            task_mode=skill_mode,
            requested=skills_requested,
        ) if kind != "tmux" else []
        selected_memory = self.knowledge.select_items(str(project_record["id"]), task) if kind != "tmux" else []
        skill_routing = self.skills.recommend(str(project_record["id"]), task) if kind != "tmux" and skill_mode == "auto" else {"algorithm": skill_mode, "recommendations": []}
        source_documents = request.get("source_documents") or []
        if not isinstance(source_documents, list) or not all(isinstance(item, dict) for item in source_documents):
            raise ValueError("source_documents must be a list of objects")
        context_bundle, context_receipt = self.knowledge.snapshot(
            project_record,
            task,
            selected_skills,
            selected_memory,
            source_documents,
        ) if kind != "tmux" else ([], {})
        requested_lane = str(request.get("lane") or config["default_lane"])
        outcome_routing = (
            self.outcome_router.recommend(
                str(project_record["id"]),
                task=task,
                operator_default=requested_lane,
                request={
                    "role": role,
                    "origin": origin,
                    "skills_selected": [
                        {"name": str(skill.get("name") or "")}
                        for skill in selected_skills
                        if isinstance(skill, dict)
                    ],
                },
            )
            if kind != "tmux"
            else {}
        )
        auto_route = request.get("auto_route") is True and kind != "tmux"
        if auto_route:
            recommendation_reason = str(outcome_routing.get("reason") or "")
            recommended_lane = str(outcome_routing.get("recommended_lane") or requested_lane)
            configured_lanes = config.get("lanes") if isinstance(config.get("lanes"), dict) else {}
            available_lanes = {"codex", "claude", *configured_lanes.keys()}
            eligible = recommendation_reason not in {"disabled", "insufficient_samples"} and recommended_lane in available_lanes
            selected_lane = recommended_lane if eligible else requested_lane
            outcome_routing = {
                **outcome_routing,
                "mode": "automatic" if eligible else "automatic_fallback",
                "applied_lane": selected_lane,
                "autonomous_routing": eligible,
                "recommendation_reason": recommendation_reason,
                "reason": (
                    f"auto selected {selected_lane} from eligible historical evidence"
                    if eligible
                    else f"auto fell back to {selected_lane}: {recommendation_reason or 'recommended lane unavailable'}"
                ),
            }
            requested_lane = selected_lane
        run: dict[str, Any] = {
            "schema_version": RUN_SCHEMA_VERSION,
            "id": run_id,
            "kind": kind,
            "title": title,
            "title_generated": not bool(explicit_title),
            "task": task,
            "project_path": str(project),
            "project_id": project_record["id"],
            "lane": requested_lane,
            "review_lane": str(request.get("review_lane") or requested_lane),
            "workflow": workflow,
            "checks": checks,
            "max_retries": max(0, max_retries),
            "status": initial_status,
            "created_at": stamp,
            "updated_at": stamp,
            "started_at": None,
            "finished_at": None,
            "base_ref": str(request.get("base_ref", "")),
            "base_sha": None,
            "branch": None,
            "worktree_path": None,
            "base_was_dirty": False,
            "attempt": 0,
            "review_cycle": 0,
            "feedback": "",
            "last_error": "",
            "check_results": [],
            "review_summary": "",
            "review_status": "pending",
            "pull_request_url": None,
            "worker_pid": None,
            "cancel_requested": False,
            "event_seq": 0,
            "agent_sessions": {},
            "agent_session_id": str(request.get("agent_session_id") or ""),
            "tmux_session": str(request.get("tmux_session") or ""),
            "tmux_target": str(request.get("tmux_target") or ""),
            "metrics": {
                "input_tokens": 0,
                "cached_input_tokens": 0,
                "output_tokens": 0,
                "reasoning_output_tokens": 0,
                "tool_calls": 0,
                "cost_usd": 0.0,
                "cost_observed": False,
                "session_usage": {},
            },
            **_run_defaults(),
            "epic_id": str(request.get("epic_id") or ""),
            "task_key": str(request.get("task_key") or ""),
            "role": role,
            "depends_on": graph_lists["depends_on"],
            "dependency_keys": graph_lists["dependency_keys"],
            "blocks": graph_lists["blocks"],
            "block_keys": graph_lists["block_keys"],
            "parallelizable": bool(request.get("parallelizable", True)),
            "blocked_reason": str(request.get("blocked_reason") or ""),
            "task_contract": {
                "outcome": str(request.get("outcome") or ""),
                "source_refs": list(request.get("source_refs") or []),
                "acceptance_criteria": list(request.get("acceptance_criteria") or []),
                "required_evidence": list(request.get("required_evidence") or []),
                "plan_version_id": str(request.get("plan_version_id") or ""),
                "plan_version_sha256": str(request.get("plan_version_sha256") or ""),
                "source_version_hashes": list(request.get("source_version_hashes") or []),
            },
            "execution_profile": dict(request.get("execution_profile") or {}),
            "estimate": dict(request.get("estimate") or {}),
            "priority": priority,
            "budgets": budgets,
            "skill_mode": skill_mode,
            "skills_requested": list(dict.fromkeys(skills_requested)),
            "skills_selected": [
                {key: skill[key] for key in ("name", "description", "scope", "relative_path", "sha256", "reason", "policy")}
                for skill in selected_skills
            ],
            "skill_context": [
                {key: skill[key] for key in ("name", "description", "scope", "relative_path", "sha256", "reason", "content")}
                for skill in selected_skills
            ],
            "context_bundle": context_bundle,
            "context_receipt": context_receipt,
            "source_documents": list(source_documents),
            "knowledge_selected": [
                {key: item.get(key) for key in ("id", "title", "triggers", "folders", "source", "reason")}
                for item in selected_memory
            ],
            "skill_routing": skill_routing,
            "environment_request": environment_request,
            "environment": {
                "version": "environment-plan-v1",
                "profile": str(environment_request.get("profile") or "project-default"),
                "status": "pending",
                "isolation": "not resolved",
            },
            "untrusted_project": bool(request.get("untrusted_project", False)),
            "project_commands_approved": False,
            "provenance": {
                "format": "odysseus-run-provenance-v1",
                "evidence_class": evidence_class,
                "origin": origin,
                "odysseus_version": __version__,
                "release": release,
                "observed_at": stamp,
            },
            "variants": variants,
            "variant": {
                "parent_run_id": str(request.get("variant_parent_id") or ""),
                "index": _safe_int(request.get("variant_index")),
                "title": str(request.get("variant_title") or ""),
                "prompt_sha256": str(request.get("variant_prompt_sha256") or ""),
                "model": str(request.get("variant_model") or ""),
            },
            "outcome_routing": outcome_routing,
        }
        run["route_observation"] = _route_observation_for(run)
        with self.locked():
            self._persist_run(run, event_type="run.created")
        if initial_status == "queued":
            self.append_event(run_id, "run.queued", "odysseus", {"title": title})
        if context_receipt:
            self.append_event(
                run_id,
                "context.receipt.created",
                "odysseus",
                {
                    "version": context_receipt["version"],
                    "bundle_sha256": context_receipt["bundle_sha256"],
                    "source_count": context_receipt["source_count"],
                },
            )
        for skill in selected_skills:
            self.append_event(
                run_id,
                "skill.selected",
                "odysseus",
                {"name": skill["name"], "sha256": skill["sha256"], "scope": skill["scope"], "reason": skill["reason"]},
            )
        for item in selected_memory:
            self.append_event(
                run_id,
                "knowledge.selected",
                "odysseus",
                {"id": item["id"], "title": item["title"], "reason": item["reason"]},
            )
        return self.get(run_id)

    def create_external(self, request: Mapping[str, Any]) -> dict[str, Any]:
        value = dict(request)
        value.setdefault("kind", "external")
        value.setdefault("status", "session")
        value.setdefault("workflow", "interactive")
        value.setdefault("checks", [])
        value.setdefault("skill_mode", "none")
        return self.create(value)

    def update(self, run_id: str, **changes: Any) -> dict[str, Any]:
        with self.locked():
            run = self.get(run_id)
            fenced = self._fence_worker_mutation(run)
            run.update(changes)
            run["updated_at"] = now_iso()
            run["route_observation"] = _route_observation_for(run)
            self._persist_run(run, event_type="state.changed")
            if fenced:
                failpoint("worker.heartbeat.after_persist")
        return run

    def mutate(self, run_id: str, change: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
        with self.locked():
            run = self.get(run_id)
            fenced = self._fence_worker_mutation(run)
            change(run)
            run["updated_at"] = now_iso()
            run["route_observation"] = _route_observation_for(run)
            self._persist_run(run, event_type="state.changed")
            if fenced:
                failpoint("worker.heartbeat.after_persist")
        return run

    def append_event(
        self,
        run_id: str,
        event_type: str,
        source: str,
        data: Mapping[str, Any] | None = None,
        *,
        projection_changes: Mapping[str, Any] | None = None,
        _projection_guard: Callable[[Mapping[str, Any]], bool] | None = None,
    ) -> dict[str, Any]:
        with self.locked():
            run = self.get(run_id)
            if _projection_guard is not None and not _projection_guard(run):
                return {}
            fenced = self._fence_worker_mutation(run)
            if projection_changes:
                run.update(dict(projection_changes))
            seq = int(run.get("event_seq", 0)) + 1
            redacted_data, redaction_receipt = self.redaction.redact(data or {}, boundary="event")
            event = Event(run_id=run_id, type=event_type, source=source, data=redacted_data, seq=seq)
            value = event.to_dict()
            value["redaction_receipt"] = redaction_receipt.to_dict()
            line = json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n"
            path = self._events_path(run_id)
            run["event_seq"] = seq
            run["updated_at"] = event.ts
            self._aggregate_event(run, event_type, redacted_data)
            run["route_observation"] = _route_observation_for(run)
            snapshot = self._redact_snapshot(run)
            self.kernel.append_run(
                run_id,
                event_type=event_type,
                actor=source,
                projection=snapshot,
                domain_event=value,
                **kernel_command_metadata(run_id),
            )
            with path.open("a", encoding="utf-8") as handle:
                handle.write(line)
                handle.flush()
                os.fsync(handle.fileno())
            self._atomic_json(self._path(run_id), snapshot)
            if fenced:
                failpoint("worker.heartbeat.after_persist")
        self._route_attention(run, event_type, redacted_data)
        self.notifications.notify(run, event_type, redacted_data)
        return value

    def _route_attention(
        self,
        run: Mapping[str, Any],
        event_type: str,
        data: Mapping[str, Any],
    ) -> None:
        """Project normalized exceptional events into the operator queue."""

        if event_type == "run.review_ready":
            # A task that reached review no longer needs earlier runtime
            # questions or permission prompts. Keep evaluation findings: they
            # remain relevant evidence for the review decision.
            self.attention.resolve_for_run(
                str(run["id"]),
                resolution="superseded_by_review",
                types=frozenset(
                    {
                        "question",
                        "permission_request",
                        "blocked",
                        "decision_required",
                        "stalled",
                        "budget",
                    }
                ),
            )

        mapping = {
            "run.review_ready": ("review", "medium", "Review ready"),
            "run.failed": ("blocked", "high", "Task failed"),
            "dag.blocked": ("blocked", "high", "Dependency blocked"),
            "evaluation.failed": ("evaluation_failed", "high", "Evaluation failed"),
            "evaluation.inconclusive": ("evaluation_review", "medium", "Evaluation needs review"),
            "agent.question": ("question", "medium", "Agent question"),
            "agent.permission_request": ("permission_request", "high", "Permission required"),
            "agent.blocked": ("blocked", "high", "Agent blocked"),
            "agent.decision_required": ("decision_required", "medium", "Decision required"),
            "integration.conflict": ("merge_conflict", "high", "Integration conflict"),
            "delivery.failed": ("delivery_failed", "high", "Local apply failed"),
            "ci.failed": ("ci_failed", "high", "CI failed"),
            "ci.retry_exhausted": ("ci_failed", "critical", "CI retry budget exhausted"),
            "run.stalled": ("stalled", "high", "Agent stalled"),
            "run.budget_exceeded": ("budget", "high", "Run budget exceeded"),
            "review.comment": ("review_comment", "medium", "Pull request feedback"),
        }
        if event_type in {"run.accepted", "pr.created", "run.cancelled", "ci.passed"}:
            self.attention.resolve_for_run(str(run["id"]), resolution=event_type)
            return
        if event_type == "dag.blocked" and not (
            data.get("failed_dependencies") or data.get("missing_dependencies")
        ):
            # Waiting on healthy predecessors is normal scheduler state, not a
            # reason to spend human attention.
            return
        if event_type not in mapping:
            return
        item_type, priority, fallback_title = mapping[event_type]
        title = str(data.get("title") or f"{fallback_title}: {run.get('title', run['id'])}")
        message = str(
            data.get("message")
            or data.get("question")
            or data.get("reason")
            or run.get("last_error")
            or "Operator action is required."
        )
        stable = json.dumps(
            {
                "run_id": run["id"],
                "type": item_type,
                "title": title,
                "message": message,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        self.attention.create(
            {
                "type": item_type,
                "priority": str(data.get("priority") or priority),
                "title": title,
                "message": message,
                "options": data.get("options") if isinstance(data.get("options"), list) else [],
                "run_id": str(run["id"]),
                "epic_id": str(run.get("epic_id") or ""),
                "project_id": str(run.get("project_id") or ""),
                "data": {
                    key: data.get(key)
                    for key in (
                        "conflicts",
                        "preserved_branches",
                        "dependency_run_id",
                        "artifact_sha",
                        "integration_head",
                        "failed_dependencies",
                        "missing_dependencies",
                    )
                    if data.get(key) not in (None, "", [])
                },
                "dedupe_key": hashlib.sha256(stable.encode("utf-8")).hexdigest(),
            }
        )

    @staticmethod
    def _aggregate_event(run: dict[str, Any], event_type: str, data: Mapping[str, Any]) -> None:
        if event_type == "step.started":
            run["stage"] = str(data.get("step") or "running")
            run["stage_started_at"] = now_iso()
        if event_type in {"run.heartbeat", "agent.output", "agent.message", "agent.reasoning", "agent.tool.started", "agent.tool.completed", "check.output"}:
            run["last_heartbeat"] = now_iso()
        if event_type == "agent.session":
            session_id = str(data.get("session_id") or "")
            if session_id:
                phase = str(data.get("phase") or "agent")
                sessions = run.setdefault("agent_sessions", {})
                if isinstance(sessions, dict):
                    sessions[phase] = session_id
                run["agent_session_id"] = session_id
            return
        metrics = run.setdefault("metrics", {})
        if not isinstance(metrics, dict):
            metrics = {}
            run["metrics"] = metrics
        if event_type == "agent.tool.started":
            metrics["tool_calls"] = _safe_int(metrics.get("tool_calls", 0)) + 1
            return
        if event_type == "agent.cost":
            try:
                previous_cost = float(metrics.get("cost_usd", 0.0) or 0.0)
                new_cost = float(data.get("cost_usd", 0.0) or 0.0)
            except (TypeError, ValueError):
                previous_cost, new_cost = 0.0, 0.0
            metrics["cost_usd"] = round(previous_cost + new_cost, 8)
            metrics["cost_observed"] = True
            return
        if event_type != "agent.usage":
            return
        keys = ("input_tokens", "cached_input_tokens", "output_tokens", "reasoning_output_tokens")
        values = {key: max(0, _safe_int(data.get(key, 0))) for key in keys}
        if data.get("cumulative"):
            session_id = str(data.get("session_id") or "unknown")
            usage_by_session = metrics.setdefault("session_usage", {})
            previous = usage_by_session.get(session_id, {}) if isinstance(usage_by_session, dict) else {}
            for key in keys:
                delta = max(0, values[key] - _safe_int(previous.get(key, 0)))
                metrics[key] = _safe_int(metrics.get(key, 0)) + delta
            if isinstance(usage_by_session, dict):
                usage_by_session[session_id] = values
            if data.get("model"):
                metrics["model"] = str(data.get("model") or "")[:120]
            return
        for key in keys:
            metrics[key] = _safe_int(metrics.get(key, 0)) + values[key]
        if data.get("model"):
            metrics["model"] = str(data.get("model") or "")[:120]

    def events(self, run_id: str, after: int = 0, limit: int = 1000) -> list[dict[str, Any]]:
        self.get(run_id)
        path = self._events_path(run_id)
        if not path.exists():
            return []
        values: list[dict[str, Any]] = []
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                try:
                    value = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if int(value.get("seq", 0)) > after:
                    values.append(self._redact_event_record(value))
                    if len(values) >= limit:
                        break
        return values

    def events_strict(self, run_id: str) -> list[dict[str, Any]]:
        """Read a complete event journal or fail instead of truncating/skipping evidence."""

        run = self.get(run_id)
        path = self._events_path(run_id)
        if not path.exists():
            if int(run.get("event_seq", 0) or 0):
                raise RuntimeError(f"missing event journal: {path}")
            return []
        values: list[dict[str, Any]] = []
        previous_seq = 0
        with path.open(encoding="utf-8") as handle:
            for number, line in enumerate(handle, 1):
                if not line.strip():
                    continue
                try:
                    value = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise RuntimeError(f"corrupt event journal: {path}:{number}") from exc
                if not isinstance(value, dict):
                    raise RuntimeError(f"invalid event journal record: {path}:{number}")
                version = value.get("v")
                if not isinstance(version, int) or version < 1 or version > EVENT_SCHEMA_VERSION:
                    raise RuntimeError(f"unsupported event schema: {path}:{number}")
                if value.get("type") not in EVENT_TYPES:
                    raise RuntimeError(f"unknown event type: {path}:{number}")
                if not isinstance(value.get("source"), str) or not value["source"]:
                    raise RuntimeError(f"invalid event source: {path}:{number}")
                if not isinstance(value.get("data"), dict):
                    raise RuntimeError(f"invalid event data: {path}:{number}")
                seq = value.get("seq")
                if not isinstance(seq, int) or seq != previous_seq + 1:
                    raise RuntimeError(f"non-contiguous event sequence: {path}:{number}")
                if str(value.get("run_id") or "") != run_id:
                    raise RuntimeError(f"event run id does not match journal: {path}:{number}")
                previous_seq = seq
                values.append(self._redact_event_record(value))
        if previous_seq != int(run.get("event_seq", 0) or 0):
            raise RuntimeError(
                f"event journal tail {previous_seq} does not match run sequence "
                f"{run.get('event_seq', 0)}: {path}"
            )
        return values

    def _fence_worker_mutation(self, run: dict[str, Any]) -> bool:
        token = active_worker_lease()
        if token is not None:
            run["worker_lease"] = validate_and_renew_worker_lease(run, token)
            return True
        return False

    def claim(
        self,
        run_id: str,
        max_parallel: int | None = None,
        *,
        worker_id: str = "",
        lease_seconds: int = DEFAULT_WORKER_LEASE_TTL_SECONDS,
    ) -> dict[str, Any] | None:
        with self.locked():
            run = self.get(run_id)
            if run.get("status") != "queued":
                return None
            if not self.epics.can_start(run):
                return None
            if max_parallel is not None:
                active = 0
                for path in self.runs_dir.glob("*.json"):
                    try:
                        candidate = json.loads(path.read_text(encoding="utf-8"))
                    except (OSError, json.JSONDecodeError):
                        continue
                    lease = candidate.get("worker_lease") if isinstance(candidate, dict) else {}
                    live = (
                        lease_owner_live(lease)
                        if isinstance(lease, Mapping) and lease
                        else _pid_alive(candidate.get("worker_pid")) if isinstance(candidate, dict) else False
                    )
                    if isinstance(candidate, dict) and candidate.get("status") in ACTIVE_STATUSES and live:
                        active += 1
                if active >= max(1, int(max_parallel)):
                    return None
            run["status"] = "starting"
            run["worker_pid"] = os.getpid()
            lease = new_worker_lease(
                run_id,
                worker_id=worker_id or f"local:{os.getpid()}",
                previous=run.get("worker_lease") if isinstance(run.get("worker_lease"), Mapping) else {},
                stream_version_at_claim=self.kernel.stream_version(run_id),
                ttl_seconds=lease_seconds,
            )
            run["worker_lease"] = lease
            run["cancel_requested"] = False
            run["started_at"] = run.get("started_at") or now_iso()
            run["updated_at"] = now_iso()
            run["route_observation"] = _route_observation_for(run)
            self._persist_run(run, event_type="worker.lease_acquired")
        failpoint("worker.claim.after_persist")
        self.append_event(
            run_id,
            "run.started",
            "odysseus",
            {
                "worker_pid": os.getpid(),
                "worker_id": lease["worker_id"],
                "lease_id": lease["lease_id"],
                "lease_epoch": lease["epoch"],
                "lease_expires_at": lease["expires_at"],
            },
        )
        failpoint("worker.claim.after_started_event")
        return self.get(run_id)

    def release_worker_lease(self, run_id: str, *, lease_id: str, epoch: int, reason: str) -> bool:
        """Release only the exact current lease; stale workers cannot release a successor."""

        with self.locked():
            run = self.get(run_id)
            lease = run.get("worker_lease") if isinstance(run.get("worker_lease"), Mapping) else {}
            if (
                not lease.get("active")
                or str(lease.get("lease_id") or "") != str(lease_id)
                or int(lease.get("epoch") or 0) != int(epoch)
            ):
                return False
            run["worker_lease"] = released_worker_lease(lease, reason)
            run["worker_pid"] = None
            run["updated_at"] = now_iso()
            self._persist_run(run, event_type="worker.lease_released")
        return True

    def transition(
        self,
        run_id: str,
        status: str,
        *,
        event_type: str = "run.status",
        source: str = "odysseus",
        data: Mapping[str, Any] | None = None,
        **changes: Any,
    ) -> dict[str, Any]:
        if status in TERMINAL_STATUSES or status in {"failed", "review"}:
            changes.setdefault("finished_at", now_iso())
        payload = {"status": status}
        payload.update(data or {})
        self.append_event(
            run_id,
            event_type,
            source,
            payload,
            projection_changes={"status": status, **changes},
        )
        return self.get(run_id)

    def request_cancel(self, run_id: str) -> dict[str, Any]:
        run = self.get(run_id)
        if run.get("kind") == "tmux":
            raise ValueError("interactive tmux sessions must be stopped or detached through tmux")
        if run.get("status") in TERMINAL_STATUSES:
            return run
        if run.get("status") in {"review", "failed", "accepted"}:
            return run
        if run.get("status") in {"queued", "blocked", "attention"}:
            self.append_event(
                run_id,
                "run.cancel_requested",
                "user",
                {},
                projection_changes={
                    "cancel_requested": True,
                    "status": "cancelling",
                    "worker_pid": None,
                },
            )
            failpoint("worker.cancel.after_intent")
            return self.transition(
                run_id,
                "cancelled",
                event_type="run.cancelled",
                cancel_requested=False,
                worker_pid=None,
            )
        self.append_event(
            run_id,
            "run.cancel_requested",
            "user",
            {},
            projection_changes={"cancel_requested": True, "status": "cancelling"},
        )
        failpoint("worker.cancel.after_intent")
        return self.get(run_id)

    def recover_interrupted(self) -> list[str]:
        recovered: list[str] = []
        for run in self.list():
            lease = run.get("worker_lease") if isinstance(run.get("worker_lease"), Mapping) else {}
            expected = {
                "status": str(run.get("status") or ""),
                "cancel_requested": bool(run.get("cancel_requested")),
                "lease_id": str(lease.get("lease_id") or ""),
                "lease_epoch": int(lease.get("epoch") or 0),
                "heartbeat_at": str(lease.get("heartbeat_at") or ""),
                "expires_at": str(lease.get("expires_at") or ""),
            }

            def still_recoverable(current: Mapping[str, Any]) -> bool:
                current_lease = (
                    current.get("worker_lease")
                    if isinstance(current.get("worker_lease"), Mapping)
                    else {}
                )
                return (
                    str(current.get("status") or "") == expected["status"]
                    and bool(current.get("cancel_requested")) == expected["cancel_requested"]
                    and str(current_lease.get("lease_id") or "") == expected["lease_id"]
                    and int(current_lease.get("epoch") or 0) == expected["lease_epoch"]
                    and str(current_lease.get("heartbeat_at") or "") == expected["heartbeat_at"]
                    and str(current_lease.get("expires_at") or "") == expected["expires_at"]
                    and not lease_owner_live(current_lease)
                )

            if (
                lease
                and lease.get("active")
                and not lease_owner_live(lease)
                and run.get("status") not in ACTIVE_STATUSES
            ):
                run_id = str(run["id"])
                event = self.append_event(
                    run_id,
                    "system.recovered",
                    "odysseus",
                    {
                        "previous_lease_id": str(lease.get("lease_id") or ""),
                        "previous_lease_epoch": int(lease.get("epoch") or 0),
                        "recovery_outcome": "stale_lease_released",
                        "preserved_status": str(run.get("status") or ""),
                    },
                    projection_changes={
                        "worker_lease": released_worker_lease(
                            lease, "recovered_after_terminal_projection"
                        ),
                        "worker_pid": None,
                    },
                    _projection_guard=still_recoverable,
                )
                if not event:
                    continue
                recovered.append(run_id)
                continue
            if run.get("status") not in ACTIVE_STATUSES:
                continue
            if (lease and lease_owner_live(lease)) or (not lease and _pid_alive(run.get("worker_pid"))):
                continue
            run_id = str(run["id"])
            cancellation = bool(run.get("cancel_requested")) or run.get("status") == "cancelling"
            changes: dict[str, Any] = {
                "status": "cancelled" if cancellation else "queued",
                "worker_pid": None,
                "cancel_requested": False,
                "last_error": (
                    "The previous worker stopped after cancellation was requested; cancellation was finalized."
                    if cancellation
                    else "The previous worker lease ended; the run was re-queued."
                ),
            }
            if cancellation:
                changes["finished_at"] = now_iso()
            if lease:
                changes["worker_lease"] = released_worker_lease(lease, "recovered_after_expiry_or_process_death")
            event = self.append_event(
                run_id,
                "run.cancelled" if cancellation else "system.recovered",
                "odysseus",
                {
                    "previous_lease_id": str(lease.get("lease_id") or ""),
                    "previous_lease_epoch": int(lease.get("epoch") or 0),
                    "recovery_outcome": "cancelled" if cancellation else "requeued",
                },
                projection_changes=changes,
                _projection_guard=still_recoverable,
            )
            if not event:
                continue
            failpoint("worker.recovery.after_projection")
            if cancellation:
                self.append_event(
                    run_id,
                    "system.recovered",
                    "odysseus",
                    {"reason": "cancellation_finalized_after_worker_loss"},
                )
            recovered.append(run_id)
        return recovered
