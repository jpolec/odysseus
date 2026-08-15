"""Cross-process leases that keep state maintenance and serving exclusive."""

from __future__ import annotations

import json
import os
import secrets
import shutil
from pathlib import Path
from typing import Any

from .events import now_iso


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
