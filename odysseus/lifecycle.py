"""Cross-process leases that keep state maintenance and serving exclusive."""

from __future__ import annotations

import json
import os
import secrets
import shutil
import subprocess
from pathlib import Path
from typing import Any

from .delivery import is_delivered_delivery
from .events import now_iso


DEFAULT_RETENTION_DAYS = 14
RECLAIMABLE_STATUSES = frozenset({"cancelled", "completed", "pr_created"})
PROTECTED_RUNTIME_NAMES = frozenset({"server.lock", "maintenance.lock"})


def _pid_alive(value: Any) -> bool:
    try:
        pid = int(value)
        if pid <= 0:
            return False
        os.kill(pid, 0)
        return True
    except (OSError, TypeError, ValueError):
        return False


def _owner(path: Path) -> dict[str, Any]:
    try:
        value = json.loads((path / "owner.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        try:
            lines = (path / "owner").read_text(encoding="utf-8").splitlines()
            return {"pid": int(lines[0]), "token": lines[1] if len(lines) > 1 else ""}
        except (OSError, ValueError, IndexError):
            return {}
    return value if isinstance(value, dict) else {}


def _reclaim_stale(path: Path) -> bool:
    owner = _owner(path)
    if _pid_alive(owner.get("pid")):
        return False
    stale = path.with_name(f"{path.name}.stale-{os.getpid()}-{secrets.token_hex(3)}")
    try:
        os.replace(path, stale)
    except FileNotFoundError:
        return True
    except OSError:
        return False
    shutil.rmtree(stale, ignore_errors=True)
    return True


class ServerLease:
    """A durable PID/token lease held for the entire web/scheduler process."""

    def __init__(self, state_root: Path | str) -> None:
        self.runtime = Path(state_root).expanduser() / "runtime"
        self.server_lock = self.runtime / "server.lock"
        self.maintenance_lock = self.runtime / "maintenance.lock"
        self.token = secrets.token_hex(16)
        self.acquired = False

    def _write(self, **details: Any) -> None:
        value = {
            "format": "odysseus-server-lease-v1",
            "pid": os.getpid(),
            "token": self.token,
            "started_at": now_iso(),
            **details,
        }
        temporary = self.server_lock / f"owner.{os.getpid()}.json"
        temporary.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temporary, self.server_lock / "owner.json")

    def acquire(self) -> None:
        self.runtime.mkdir(parents=True, exist_ok=True)
        for _attempt in range(3):
            if self.maintenance_lock.exists():
                owner = _owner(self.maintenance_lock)
                if _pid_alive(owner.get("pid")):
                    raise RuntimeError("state maintenance is active; wait for install/update/rollback to finish")
                _reclaim_stale(self.maintenance_lock)
            try:
                self.server_lock.mkdir()
            except FileExistsError:
                owner = _owner(self.server_lock)
                if _pid_alive(owner.get("pid")):
                    raise RuntimeError(f"another Odysseus server is active (pid {owner.get('pid')})")
                if _reclaim_stale(self.server_lock):
                    continue
                raise RuntimeError("cannot reclaim a stale Odysseus server lease")
            self.acquired = True
            self._write()
            # Close the race with maintenance acquiring between our first
            # check and mkdir: a server never starts while maintenance owns it.
            if self.maintenance_lock.exists():
                self.release()
                raise RuntimeError("state maintenance started concurrently; retry after it finishes")
            return
        raise RuntimeError("cannot acquire the Odysseus server lease")

    def update(self, **details: Any) -> None:
        if self.acquired:
            self._write(**details)

    def release(self) -> None:
        if not self.acquired:
            return
        owner = _owner(self.server_lock)
        if owner.get("token") == self.token:
            shutil.rmtree(self.server_lock, ignore_errors=True)
        self.acquired = False


def _parse_epoch(value: Any) -> float:
    text = str(value or "").strip()
    if not text:
        return 0.0
    try:
        import datetime as dt

        return dt.datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def _directory_size(path: Path) -> int:
    total = 0
    try:
        if path.is_symlink():
            return 0
        if path.is_file():
            return path.stat().st_size
        for root, dirs, files in os.walk(path):
            root_path = Path(root)
            retained_dirs = []
            for name in dirs:
                child = root_path / name
                if child.is_symlink():
                    continue
                retained_dirs.append(name)
            dirs[:] = retained_dirs
            for name in files:
                child = root_path / name
                try:
                    if not child.is_symlink():
                        total += child.stat().st_size
                except OSError:
                    continue
    except OSError:
        return 0
    return total


def _under(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except (OSError, ValueError):
        return False


class ResourceLifecycle:
    """Inspect and reclaim retained worktree/runtime resources safely."""

    def __init__(self, store: Any) -> None:
        self.store = store
        self.root = Path(store.root)
        self.worktrees_root = Path(store.worktrees_dir)
        self.runtime_root = self.root / "runtime"

    def inspect(self, *, retention_days: int | None = None) -> dict[str, Any]:
        days = DEFAULT_RETENTION_DAYS if retention_days is None else max(0, int(retention_days))
        cutoff = self._cutoff(days)
        runs = self.store.list()
        worktrees = [self._worktree_record(run, cutoff) for run in runs if run.get("worktree_path")]
        runtimes = self._runtime_records(runs, cutoff)
        worktrees = [item for item in worktrees if item]
        reclaimable_worktrees = [item for item in worktrees if item["reclaimable"]]
        reclaimable_runtimes = [item for item in runtimes if item["reclaimable"]]
        return {
            "format": "odysseus-resources-v1",
            "state_root": str(self.root),
            "retention_days": days,
            "generated_at": now_iso(),
            "totals": {
                "worktree_bytes": sum(int(item["bytes"]) for item in worktrees),
                "runtime_bytes": sum(int(item["bytes"]) for item in runtimes),
                "bytes": sum(int(item["bytes"]) for item in worktrees + runtimes),
                "reclaimable_worktree_bytes": sum(int(item["bytes"]) for item in reclaimable_worktrees),
                "reclaimable_runtime_bytes": sum(int(item["bytes"]) for item in reclaimable_runtimes),
                "reclaimable_bytes": sum(int(item["bytes"]) for item in reclaimable_worktrees + reclaimable_runtimes),
                "worktrees": len(worktrees),
                "runtime_directories": len(runtimes),
                "reclaimable_worktrees": len(reclaimable_worktrees),
                "reclaimable_runtime_directories": len(reclaimable_runtimes),
            },
            "worktrees": worktrees,
            "runtime_directories": runtimes,
        }

    def reclaim(self, *, retention_days: int | None = None, force: bool = False) -> dict[str, Any]:
        before = self.inspect(retention_days=retention_days)
        candidates = {
            "worktrees": [item for item in before["worktrees"] if item["reclaimable"] or (force and item["force_reclaimable"])],
            "runtime_directories": [
                item for item in before["runtime_directories"] if item["reclaimable"] or (force and item["force_reclaimable"])
            ],
        }
        reclaimed: list[dict[str, Any]] = []
        errors: list[dict[str, str]] = []
        for item in candidates["worktrees"]:
            try:
                bytes_before = int(item.get("bytes") or 0)
                self._remove_worktree(item)
                self._mark_run_reclaimed(item)
                reclaimed.append({"kind": "worktree", "run_id": item["run_id"], "path": item["path"], "bytes": bytes_before})
            except RuntimeError as exc:
                errors.append({"kind": "worktree", "run_id": str(item.get("run_id") or ""), "path": str(item.get("path") or ""), "error": str(exc)})
        for item in candidates["runtime_directories"]:
            try:
                bytes_before = int(item.get("bytes") or 0)
                path = Path(str(item["path"]))
                if not _under(path, self.runtime_root):
                    raise RuntimeError("runtime directory is outside Odysseus state")
                shutil.rmtree(path, ignore_errors=False)
                reclaimed.append({"kind": "runtime", "run_id": item.get("run_id") or "", "path": item["path"], "bytes": bytes_before})
            except (OSError, RuntimeError) as exc:
                errors.append({"kind": "runtime", "run_id": str(item.get("run_id") or ""), "path": str(item.get("path") or ""), "error": str(exc)})
        after = self.inspect(retention_days=before["retention_days"])
        return {
            "format": "odysseus-reclaim-v1",
            "retention_days": before["retention_days"],
            "force": force,
            "reclaimed": reclaimed,
            "errors": errors,
            "reclaimed_bytes": sum(int(item["bytes"]) for item in reclaimed),
            "before": before["totals"],
            "after": after["totals"],
        }

    def _cutoff(self, days: int) -> float:
        import time

        return time.time() - (days * 86400)

    def _run_age_epoch(self, run: dict[str, Any]) -> float:
        candidates = (
            _parse_epoch(run.get("finished_at")),
            _parse_epoch((run.get("delivery") or {}).get("delivered_at") if isinstance(run.get("delivery"), dict) else ""),
            _parse_epoch(run.get("updated_at")),
            _parse_epoch(run.get("created_at")),
        )
        return next((value for value in candidates if value > 0), 0.0)

    def _run_reclaimable(self, run: dict[str, Any], cutoff: float) -> tuple[bool, bool, str]:
        status = str(run.get("status") or "")
        delivery = run.get("delivery") if isinstance(run.get("delivery"), dict) else {}
        delivered = is_delivered_delivery(delivery)
        terminal = status in RECLAIMABLE_STATUSES or delivered
        if not terminal:
            return False, False, f"kept for {status or 'unknown'} recovery or delivery"
        if _pid_alive(run.get("worker_pid")):
            return False, False, "worker process is still alive"
        if run.get("resource_reclaimed_at"):
            return False, False, "already reclaimed"
        epoch = self._run_age_epoch(run)
        age_ready = bool(epoch and epoch <= cutoff)
        if age_ready:
            return True, True, "past retention window"
        return False, True, "eligible when retention window expires"

    def _worktree_record(self, run: dict[str, Any], cutoff: float) -> dict[str, Any] | None:
        path = Path(str(run.get("worktree_path") or ""))
        if not path:
            return None
        exists = path.exists()
        reclaimable, force_reclaimable, reason = self._run_reclaimable(run, cutoff)
        if not exists:
            reclaimable = False
            force_reclaimable = False
            reason = "path is already absent"
        elif not _under(path, self.worktrees_root):
            reclaimable = False
            force_reclaimable = False
            reason = "path is outside managed worktrees"
        return {
            "run_id": str(run.get("id") or ""),
            "title": str(run.get("title") or ""),
            "status": str(run.get("status") or ""),
            "branch": str(run.get("branch") or ""),
            "path": str(path),
            "exists": exists,
            "bytes": _directory_size(path) if exists else 0,
            "updated_at": run.get("updated_at"),
            "reclaimable": reclaimable,
            "force_reclaimable": force_reclaimable,
            "reason": reason,
        }

    def _runtime_records(self, runs: list[dict[str, Any]], cutoff: float) -> list[dict[str, Any]]:
        by_id = {str(run.get("id") or ""): run for run in runs}
        records: list[dict[str, Any]] = []
        if not self.runtime_root.is_dir():
            return records
        for path in sorted(self.runtime_root.iterdir(), key=lambda item: item.name):
            if path.name in PROTECTED_RUNTIME_NAMES or not path.is_dir():
                continue
            run = by_id.get(path.name)
            if run:
                reclaimable, force_reclaimable, reason = self._run_reclaimable(run, cutoff)
                run_id = str(run.get("id") or "")
                status = str(run.get("status") or "")
                title = str(run.get("title") or "")
            else:
                run_id = ""
                status = "orphan"
                title = ""
                owner = _owner(path)
                active_owner = _pid_alive(owner.get("pid"))
                try:
                    stale = path.stat().st_mtime <= cutoff
                except OSError:
                    stale = False
                reclaimable = stale and not active_owner
                force_reclaimable = not active_owner
                reason = "orphan runtime directory has a live owner" if active_owner else "orphan runtime directory"
            records.append(
                {
                    "run_id": run_id,
                    "title": title,
                    "status": status,
                    "path": str(path),
                    "bytes": _directory_size(path),
                    "updated_at": run.get("updated_at") if run else None,
                    "reclaimable": reclaimable,
                    "force_reclaimable": force_reclaimable,
                    "reason": reason,
                }
            )
        return records

    def _remove_worktree(self, item: dict[str, Any]) -> None:
        path = Path(str(item["path"]))
        if not _under(path, self.worktrees_root):
            raise RuntimeError("worktree is outside managed worktrees")
        run = self.store.get(str(item["run_id"]))
        project = Path(str(run.get("project_path") or ""))
        removed_by_git = False
        if project.is_dir():
            result = subprocess.run(
                ["git", "-C", str(project), "worktree", "remove", "--force", str(path)],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            removed_by_git = result.returncode == 0 or not path.exists()
            if result.returncode != 0 and path.exists():
                raise RuntimeError((result.stderr or result.stdout or "git worktree remove failed").strip())
        if path.exists():
            if not removed_by_git and not (path / ".git").exists() and not (path / ".git").is_file():
                raise RuntimeError("refusing to remove a directory that does not look like a Git worktree")
            shutil.rmtree(path, ignore_errors=False)

    def _mark_run_reclaimed(self, item: dict[str, Any]) -> None:
        run_id = str(item["run_id"])
        self.store.update(
            run_id,
            worktree_path=None,
            resource_reclaimed_at=now_iso(),
            resource_reclaimed_bytes=int(item.get("bytes") or 0),
        )
        self.store.append_event(
            run_id,
            "resource.reclaimed",
            "odysseus",
            {
                "kind": "worktree",
                "path": str(item.get("path") or ""),
                "bytes": int(item.get("bytes") or 0),
                "branch_preserved": str(item.get("branch") or ""),
            },
        )
