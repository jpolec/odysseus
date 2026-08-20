"""Durable per-run worker leases with monotonically increasing fencing epochs."""

from __future__ import annotations

import datetime as dt
import os
import socket
import uuid
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import Any, Iterator, Mapping

from .events import now_iso


WORKER_LEASE_FORMAT = "odysseus-worker-lease-v1"
DEFAULT_WORKER_LEASE_TTL_SECONDS = 60


class StaleWorkerLease(RuntimeError):
    """A worker tried to mutate a run after its lease expired or was replaced."""


@dataclass(frozen=True, slots=True)
class WorkerLeaseToken:
    run_id: str
    lease_id: str
    epoch: int
    worker_id: str


_ACTIVE_WORKER_LEASE: ContextVar[WorkerLeaseToken | None] = ContextVar(
    "odysseus_active_worker_lease", default=None
)


def _timestamp(value: str) -> float:
    try:
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except (AttributeError, ValueError):
        return 0.0


def _iso_after(seconds: int, *, at: dt.datetime | None = None) -> str:
    current = at or dt.datetime.now(dt.timezone.utc)
    return (
        (current + dt.timedelta(seconds=max(1, int(seconds))))
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def new_worker_lease(
    run_id: str,
    *,
    worker_id: str,
    previous: Mapping[str, Any] | None = None,
    stream_version_at_claim: int,
    ttl_seconds: int = DEFAULT_WORKER_LEASE_TTL_SECONDS,
) -> dict[str, Any]:
    prior = previous if isinstance(previous, Mapping) else {}
    acquired_at = now_iso()
    return {
        "format": WORKER_LEASE_FORMAT,
        "lease_id": str(uuid.uuid4()),
        "run_id": str(run_id),
        "worker_id": str(worker_id),
        "worker_host": socket.gethostname(),
        "worker_pid": os.getpid(),
        "epoch": max(0, int(prior.get("epoch") or 0)) + 1,
        "stream_version_at_claim": max(0, int(stream_version_at_claim)),
        "acquired_at": acquired_at,
        "heartbeat_at": acquired_at,
        "expires_at": _iso_after(ttl_seconds),
        "ttl_seconds": max(1, int(ttl_seconds)),
        "active": True,
        "released_at": "",
        "release_reason": "",
    }


def lease_token(run: Mapping[str, Any]) -> WorkerLeaseToken:
    lease = run.get("worker_lease") if isinstance(run.get("worker_lease"), Mapping) else {}
    if not lease or not lease.get("active"):
        raise StaleWorkerLease(f"run {run.get('id', '')} does not have an active worker lease")
    return WorkerLeaseToken(
        run_id=str(run.get("id") or ""),
        lease_id=str(lease.get("lease_id") or ""),
        epoch=int(lease.get("epoch") or 0),
        worker_id=str(lease.get("worker_id") or ""),
    )


def lease_expired(lease: Mapping[str, Any], *, at: dt.datetime | None = None) -> bool:
    if not lease.get("active"):
        return True
    current = (at or dt.datetime.now(dt.timezone.utc)).timestamp()
    return _timestamp(str(lease.get("expires_at") or "")) <= current


def lease_owner_live(lease: Mapping[str, Any], *, at: dt.datetime | None = None) -> bool:
    """Treat a valid remote lease as live and verify a same-host owner PID."""

    if lease_expired(lease, at=at):
        return False
    if str(lease.get("worker_host") or "") != socket.gethostname():
        return True
    try:
        pid = int(lease.get("worker_pid") or 0)
        if pid <= 0:
            return False
        os.kill(pid, 0)
        return True
    except PermissionError:
        return True
    except (OSError, TypeError, ValueError):
        return False


def active_worker_lease() -> WorkerLeaseToken | None:
    return _ACTIVE_WORKER_LEASE.get()


@contextmanager
def worker_lease_scope(value: WorkerLeaseToken) -> Iterator[None]:
    token: Token[WorkerLeaseToken | None] = _ACTIVE_WORKER_LEASE.set(value)
    try:
        yield
    finally:
        _ACTIVE_WORKER_LEASE.reset(token)


@contextmanager
def suspend_worker_lease() -> Iterator[None]:
    """Enter an explicit control-plane operation that does not act as a worker."""

    token: Token[WorkerLeaseToken | None] = _ACTIVE_WORKER_LEASE.set(None)
    try:
        yield
    finally:
        _ACTIVE_WORKER_LEASE.reset(token)


def validate_and_renew_worker_lease(
    run: Mapping[str, Any],
    token: WorkerLeaseToken,
) -> dict[str, Any]:
    lease = run.get("worker_lease") if isinstance(run.get("worker_lease"), Mapping) else {}
    run_id = str(run.get("id") or "")
    reason = ""
    if token.run_id != run_id:
        reason = f"lease belongs to {token.run_id}, not {run_id}"
    elif not lease.get("active"):
        reason = "lease is no longer active"
    elif str(lease.get("lease_id") or "") != token.lease_id:
        reason = "lease was replaced"
    elif int(lease.get("epoch") or 0) != token.epoch:
        reason = "fencing epoch is stale"
    elif str(lease.get("worker_id") or "") != token.worker_id:
        reason = "worker identity does not match"
    elif lease_expired(lease):
        reason = "lease heartbeat TTL expired"
    if reason:
        raise StaleWorkerLease(
            f"worker {token.worker_id} cannot mutate run {run_id}: {reason} "
            f"(lease {token.lease_id}, epoch {token.epoch})"
        )
    renewed = dict(lease)
    renewed["heartbeat_at"] = now_iso()
    renewed["expires_at"] = _iso_after(int(lease.get("ttl_seconds") or DEFAULT_WORKER_LEASE_TTL_SECONDS))
    return renewed


def released_worker_lease(lease: Mapping[str, Any], reason: str) -> dict[str, Any]:
    value = dict(lease)
    value["active"] = False
    value["released_at"] = now_iso()
    value["release_reason"] = str(reason or "released")
    return value
