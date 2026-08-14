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

from .events import Event, now_iso
from .attention import AttentionQueue
from .epics import EpicStore, VALID_ROLES
from .inbox import Inbox
from .notifications import NotificationManager
from .project_knowledge import ProjectKnowledge
from .projects import ProjectRegistry


RUN_ID_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
TERMINAL_STATUSES = frozenset({"accepted", "pr_created", "cancelled"})
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
    "evaluation_policy": {
        "min_confidence": 0.85,
        "require_human_review": True,
        "required_evaluators": [],
    },
}


RUN_SCHEMA_VERSION = 4


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
        "integration_sources": [],
        "integration_head": "",
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
    }


def default_state_root() -> Path:
    configured = os.environ.get("ODYSSEUS_HOME")
    return Path(configured).expanduser() if configured else Path.home() / ".odysseus"


def _slug(value: str, fallback: str = "task", limit: int = 36) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return (slug or fallback)[:limit].rstrip("-")


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

    def __init__(self, root: Path | str | None = None) -> None:
        self.root = Path(root).expanduser() if root is not None else default_state_root()
        self.runs_dir = self.root / "runs"
        self.events_dir = self.root / "events"
        self.worktrees_dir = self.root / "worktrees"
        self.root.mkdir(parents=True, exist_ok=True)
        self.runs_dir.mkdir(exist_ok=True)
        self.events_dir.mkdir(exist_ok=True)
        self.worktrees_dir.mkdir(exist_ok=True)
        self.lock_path = self.root / ".store.lock"
        self.config_path = self.root / "config.json"
        if not self.config_path.exists():
            self._atomic_json(self.config_path, DEFAULT_CONFIG)
        self.projects = ProjectRegistry(self)
        self.knowledge = ProjectKnowledge(self)
        self.inbox = Inbox(self)
        self.attention = AttentionQueue(self)
        self.epics = EpicStore(self)
        self.notifications = NotificationManager(self)
        self._migrate_runs()

    def _migrate_runs(self) -> None:
        """Upgrade old snapshots in place while preserving append-only journals."""

        with self.locked():
            for path in self.runs_dir.glob("*.json"):
                try:
                    run = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                if not isinstance(run, dict):
                    continue
                changed = False
                for key, value in _run_defaults().items():
                    if key not in run:
                        run[key] = value
                        changed = True
                if _safe_int(run.get("schema_version")) < RUN_SCHEMA_VERSION:
                    run["schema_version"] = RUN_SCHEMA_VERSION
                    changed = True
                if changed:
                    self._atomic_json(path, run)

    @contextmanager
    def locked(self) -> Iterator[None]:
        with self.lock_path.open("a+") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    @staticmethod
    def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
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
        return merged

    def update_config(self, changes: Mapping[str, Any]) -> dict[str, Any]:
        allowed = {
            "max_parallel",
            "default_lane",
            "default_workflow",
            "max_retries",
            "planner_lane",
            "review_lane",
            "lanes",
            "evaluation_policy",
            "budgets",
            "ci",
            "notifications",
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
        return value

    def list(self) -> list[dict[str, Any]]:
        runs: list[dict[str, Any]] = []
        for path in self.runs_dir.glob("*.json"):
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(value, dict):
                for key, default in _run_defaults().items():
                    value.setdefault(key, default)
                runs.append(value)
        return sorted(runs, key=lambda item: str(item.get("created_at", "")), reverse=True)

    def create(self, request: Mapping[str, Any]) -> dict[str, Any]:
        task = str(request.get("task", "")).strip()
        if not task:
            raise ValueError("task is required")
        project = Path(str(request.get("project_path", "."))).expanduser().resolve()
        if not project.is_dir():
            raise ValueError(f"project directory does not exist: {project}")
        project_record = self.projects.upsert(project)
        config = self.config()
        stamp = now_iso()
        compact_stamp = stamp.replace("-", "").replace(":", "").replace("T", "-")[:15]
        title = str(request.get("title", "")).strip() or task.splitlines()[0][:100]
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
        run: dict[str, Any] = {
            "schema_version": RUN_SCHEMA_VERSION,
            "id": run_id,
            "kind": kind,
            "title": title,
            "task": task,
            "project_path": str(project),
            "project_id": project_record["id"],
            "lane": str(request.get("lane") or config["default_lane"]),
            "review_lane": str(request.get("review_lane") or request.get("lane") or config["default_lane"]),
            "workflow": str(request.get("workflow") or config["default_workflow"]),
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
            "priority": priority,
            "budgets": budgets,
        }
        with self.locked():
            self._atomic_json(self._path(run_id), run)
        if initial_status == "queued":
            self.append_event(run_id, "run.queued", "odysseus", {"title": title})
        return self.get(run_id)

    def create_external(self, request: Mapping[str, Any]) -> dict[str, Any]:
        value = dict(request)
        value.setdefault("kind", "external")
        value.setdefault("status", "session")
        value.setdefault("workflow", "interactive")
        value.setdefault("checks", [])
        return self.create(value)

    def update(self, run_id: str, **changes: Any) -> dict[str, Any]:
        with self.locked():
            run = self.get(run_id)
            run.update(changes)
            run["updated_at"] = now_iso()
            self._atomic_json(self._path(run_id), run)
        return run

    def mutate(self, run_id: str, change: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
        with self.locked():
            run = self.get(run_id)
            change(run)
            run["updated_at"] = now_iso()
            self._atomic_json(self._path(run_id), run)
        return run

    def append_event(
        self,
        run_id: str,
        event_type: str,
        source: str,
        data: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        with self.locked():
            run = self.get(run_id)
            seq = int(run.get("event_seq", 0)) + 1
            event = Event(run_id=run_id, type=event_type, source=source, data=data or {}, seq=seq)
            value = event.to_dict()
            line = json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n"
            path = self._events_path(run_id)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(line)
                handle.flush()
                os.fsync(handle.fileno())
            run["event_seq"] = seq
            run["updated_at"] = event.ts
            self._aggregate_event(run, event_type, data or {})
            self._atomic_json(self._path(run_id), run)
        self._route_attention(run, event_type, data or {})
        self.notifications.notify(run, event_type, data or {})
        return value

    def _route_attention(
        self,
        run: Mapping[str, Any],
        event_type: str,
        data: Mapping[str, Any],
    ) -> None:
        """Project normalized exceptional events into the operator queue."""

        mapping = {
            "run.review_ready": ("review", "medium", "Review ready"),
            "run.failed": ("blocked", "high", "Task failed"),
            "dag.blocked": ("blocked", "high", "Dependency blocked"),
            "evaluation.failed": ("evaluation_failed", "high", "Evaluation failed"),
            "agent.question": ("question", "medium", "Agent question"),
            "agent.permission_request": ("permission_request", "high", "Permission required"),
            "agent.blocked": ("blocked", "high", "Agent blocked"),
            "agent.decision_required": ("decision_required", "medium", "Decision required"),
            "integration.conflict": ("merge_conflict", "high", "Integration conflict"),
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
            return
        for key in keys:
            metrics[key] = _safe_int(metrics.get(key, 0)) + values[key]

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
                    values.append(value)
                    if len(values) >= limit:
                        break
        return values

    def claim(self, run_id: str, max_parallel: int | None = None) -> dict[str, Any] | None:
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
                    if (
                        isinstance(candidate, dict)
                        and candidate.get("status") in ACTIVE_STATUSES
                        and _pid_alive(candidate.get("worker_pid"))
                    ):
                        active += 1
                if active >= max(1, int(max_parallel)):
                    return None
            run["status"] = "starting"
            run["worker_pid"] = os.getpid()
            run["cancel_requested"] = False
            run["started_at"] = run.get("started_at") or now_iso()
            run["updated_at"] = now_iso()
            self._atomic_json(self._path(run_id), run)
        self.append_event(run_id, "run.started", "odysseus", {"worker_pid": os.getpid()})
        return self.get(run_id)

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
        self.update(run_id, status=status, **changes)
        payload = {"status": status}
        payload.update(data or {})
        self.append_event(run_id, event_type, source, payload)
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
            self.update(
                run_id,
                cancel_requested=False,
                status="cancelled",
                finished_at=now_iso(),
                worker_pid=None,
            )
            self.append_event(run_id, "run.cancel_requested", "user", {})
            self.append_event(run_id, "run.cancelled", "odysseus", {"status": "cancelled"})
            return self.get(run_id)
        self.update(run_id, cancel_requested=True, status="cancelling")
        self.append_event(run_id, "run.cancel_requested", "user", {})
        return self.get(run_id)

    def recover_interrupted(self) -> list[str]:
        recovered: list[str] = []
        for run in self.list():
            if run.get("status") not in ACTIVE_STATUSES:
                continue
            if _pid_alive(run.get("worker_pid")):
                continue
            run_id = str(run["id"])
            self.update(
                run_id,
                status="queued",
                worker_pid=None,
                cancel_requested=False,
                last_error="The previous Odysseus process stopped; the run was re-queued.",
            )
            self.append_event(run_id, "system.recovered", "odysseus", {})
            recovered.append(run_id)
        return recovered
