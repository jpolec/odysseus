"""Durable JSON run store and append-only NDJSON event history."""

from __future__ import annotations

import fcntl
import json
import os
import re
import secrets
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping

from .events import Event, now_iso


RUN_ID_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
TERMINAL_STATUSES = frozenset({"accepted", "pr_created", "cancelled"})
ACTIVE_STATUSES = frozenset(
    {"starting", "running", "checking", "reviewing", "cancelling", "publishing"}
)
REVIEWABLE_STATUSES = frozenset({"review", "failed", "accepted"})
DEFAULT_CONFIG: dict[str, Any] = {
    "max_parallel": 2,
    "default_lane": "codex",
    "default_workflow": "agent-check-review",
    "max_retries": 2,
    "lanes": {},
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
        merged["max_parallel"] = max(1, int(merged.get("max_parallel", 2)))
        merged["max_retries"] = max(0, int(merged.get("max_retries", 2)))
        return merged

    def update_config(self, changes: Mapping[str, Any]) -> dict[str, Any]:
        allowed = {"max_parallel", "default_lane", "default_workflow", "max_retries", "lanes"}
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
        return value

    def list(self) -> list[dict[str, Any]]:
        runs: list[dict[str, Any]] = []
        for path in self.runs_dir.glob("*.json"):
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(value, dict):
                runs.append(value)
        return sorted(runs, key=lambda item: str(item.get("created_at", "")), reverse=True)

    def create(self, request: Mapping[str, Any]) -> dict[str, Any]:
        task = str(request.get("task", "")).strip()
        if not task:
            raise ValueError("task is required")
        project = Path(str(request.get("project_path", "."))).expanduser().resolve()
        if not project.is_dir():
            raise ValueError(f"project directory does not exist: {project}")
        config = self.config()
        stamp = now_iso()
        compact_stamp = stamp.replace("-", "").replace(":", "").replace("T", "-")[:15]
        title = str(request.get("title", "")).strip() or task.splitlines()[0][:100]
        run_id = f"{compact_stamp}-{_slug(title)}-{secrets.token_hex(2)}"
        checks = request.get("checks", [])
        if not isinstance(checks, list) or not all(isinstance(item, str) for item in checks):
            raise ValueError("checks must be a list of shell command strings")
        max_retries = int(request.get("max_retries", config["max_retries"]))
        run: dict[str, Any] = {
            "schema_version": 1,
            "id": run_id,
            "title": title,
            "task": task,
            "project_path": str(project),
            "lane": str(request.get("lane") or config["default_lane"]),
            "review_lane": str(request.get("review_lane") or request.get("lane") or config["default_lane"]),
            "workflow": str(request.get("workflow") or config["default_workflow"]),
            "checks": checks,
            "max_retries": max(0, max_retries),
            "status": "queued",
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
        }
        with self.locked():
            self._atomic_json(self._path(run_id), run)
        self.append_event(run_id, "run.queued", "odysseus", {"title": title})
        return self.get(run_id)

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
            self._atomic_json(self._path(run_id), run)
        return value

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
        if run.get("status") in TERMINAL_STATUSES:
            return run
        if run.get("status") in {"review", "failed"}:
            return run
        if run.get("status") == "queued":
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
