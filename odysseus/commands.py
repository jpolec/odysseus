"""Durable, idempotent command envelopes shared by every control surface."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import socket
import tempfile
import threading
import uuid
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping

from .events import now_iso
from .redaction import DEFAULT_REDACTION_ENGINE


COMMAND_ENVELOPE_FORMAT = "odysseus-command-envelope-v1"
COMMAND_RECEIPT_FORMAT = "odysseus-command-receipt-v1"
COMMAND_SCHEMA_VERSION = 1
COMMAND_TYPE_RE = re.compile(r"^[a-z0-9][a-z0-9._:/-]{1,159}$")
COMMAND_ID_RE = re.compile(r"^[0-9a-f-]{36}$")


class CommandError(RuntimeError):
    """Base class for command-layer failures."""


class IdempotencyConflict(CommandError):
    """One idempotency key was reused for a different request."""


class CommandOutcomeUnknown(CommandError):
    """A previous process died after preparing or starting the command."""


@dataclass
class ActiveCommand:
    envelope: dict[str, Any]
    consumed_expected_streams: set[str] = field(default_factory=set)

    def kernel_metadata(self, run_id: str) -> dict[str, Any]:
        stream_id = f"run:{run_id}"
        expected: int | None = None
        if self.envelope.get("target_stream") == stream_id and stream_id not in self.consumed_expected_streams:
            raw = self.envelope.get("expected_version")
            expected = int(raw) if isinstance(raw, int) else None
            self.consumed_expected_streams.add(stream_id)
        return {
            "command_id": str(self.envelope["command_id"]),
            "idempotency_key": str(self.envelope["idempotency_key"]),
            "causation_id": str(self.envelope.get("causation_id") or ""),
            "expected_version": expected,
        }


_ACTIVE_COMMAND: ContextVar[ActiveCommand | None] = ContextVar("odysseus_active_command", default=None)


def activate_command(envelope: Mapping[str, Any]) -> Token[ActiveCommand | None]:
    return _ACTIVE_COMMAND.set(ActiveCommand(dict(envelope)))


def reset_command(token: Token[ActiveCommand | None]) -> None:
    _ACTIVE_COMMAND.reset(token)


def kernel_command_metadata(run_id: str) -> dict[str, Any]:
    active = _ACTIVE_COMMAND.get()
    return active.kernel_metadata(run_id) if active else {}


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def _request_hash(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


@dataclass
class CommandTicket:
    path: Path
    receipt: dict[str, Any]
    replayed: bool = False
    duplicate: bool = False
    token: Token[ActiveCommand | None] | None = None

    @property
    def envelope(self) -> dict[str, Any]:
        return dict(self.receipt["command"])

    @property
    def command_id(self) -> str:
        return str(self.receipt["command"]["command_id"])


@dataclass
class CommandExecution:
    result: Any
    receipt: dict[str, Any]
    duplicate: bool


class CommandBus:
    """At-most-once durable command execution with replayable results."""

    def __init__(self, root: Path | str, *, kernel: Any = None, readonly: bool = False) -> None:
        self.root = Path(root).expanduser()
        self.kernel = kernel
        self.readonly = readonly
        self.commands_dir = self.root / "commands"
        self.lock_path = self.root / "commands.lock"
        self._active: set[str] = set()
        self._active_lock = threading.Lock()
        if not readonly:
            self.commands_dir.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def _locked(self) -> Iterator[None]:
        if self.readonly:
            yield
            return
        self.root.mkdir(parents=True, exist_ok=True)
        with self.lock_path.open("a+") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    @staticmethod
    def _key_hash(actor: Mapping[str, Any], key: str) -> str:
        scope = f"{actor.get('type', 'user')}:{actor.get('id', 'operator')}:{key}"
        return hashlib.sha256(scope.encode("utf-8")).hexdigest()

    def _path(self, actor: Mapping[str, Any], key: str) -> Path:
        return self.commands_dir / f"{self._key_hash(actor, key)}.json"

    @staticmethod
    def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True, default=str)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass

    @staticmethod
    def _read(path: Path) -> dict[str, Any]:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CommandError(f"invalid command receipt: {path}") from exc
        if not isinstance(value, dict) or value.get("format") != COMMAND_RECEIPT_FORMAT:
            raise CommandError(f"invalid command receipt: {path}")
        return value

    @staticmethod
    def _owner_status(receipt: Mapping[str, Any]) -> str:
        """Return live, dead, or unknown without taking ownership of the command."""

        owner = receipt.get("owner") if isinstance(receipt.get("owner"), Mapping) else {}
        host = str(owner.get("host") or "")
        try:
            pid = int(owner.get("pid") or 0)
        except (TypeError, ValueError):
            return "unknown"
        if not host or host != socket.gethostname() or pid <= 0:
            return "unknown"
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return "dead"
        except PermissionError:
            return "live"
        return "live"

    def begin(
        self,
        command_type: str,
        payload: Mapping[str, Any] | None = None,
        *,
        idempotency_key: str = "",
        command_id: str = "",
        actor: Mapping[str, Any] | None = None,
        policy_context: Mapping[str, Any] | None = None,
        target_stream: str = "",
        expected_version: int | None = None,
        causation_id: str = "",
    ) -> CommandTicket:
        if self.readonly:
            raise CommandError("command bus is read-only")
        normalized_type = str(command_type).strip().lower()
        if not COMMAND_TYPE_RE.fullmatch(normalized_type):
            raise ValueError("invalid command type")
        key = str(idempotency_key or uuid.uuid4())
        if not key or len(key) > 200:
            raise ValueError("idempotency key must contain 1..200 characters")
        identifier = str(command_id or uuid.uuid4())
        if not COMMAND_ID_RE.fullmatch(identifier):
            raise ValueError("command id must be a UUID")
        actor_value = {
            "type": str((actor or {}).get("type") or "user"),
            "id": str((actor or {}).get("id") or "operator"),
        }
        redacted_payload, payload_receipt = DEFAULT_REDACTION_ENGINE.redact(payload or {}, boundary="command_payload")
        redacted_policy, policy_receipt = DEFAULT_REDACTION_ENGINE.redact(
            policy_context or {}, boundary="command_policy_context"
        )
        envelope = {
            "format": COMMAND_ENVELOPE_FORMAT,
            "schema_version": COMMAND_SCHEMA_VERSION,
            "command_id": identifier,
            "command_type": normalized_type,
            "idempotency_key": key,
            "target_stream": str(target_stream),
            "expected_version": expected_version,
            "actor": actor_value,
            "policy_context": redacted_policy,
            "payload": redacted_payload,
            "causation_id": str(causation_id),
            "requested_at": now_iso(),
        }
        request_material = {
            key_name: envelope[key_name]
            for key_name in (
                "command_type",
                "idempotency_key",
                "target_stream",
                "expected_version",
                "actor",
                "policy_context",
                "payload",
                "causation_id",
            )
        }
        digest = _request_hash(request_material)
        path = self._path(actor_value, key)
        with self._locked():
            if path.exists():
                existing = self._read(path)
                if existing.get("request_sha256") != digest:
                    raise IdempotencyConflict("idempotency key was already used for a different command")
                state = str(existing.get("state") or "unknown")
                if state in {"completed", "failed"}:
                    return CommandTicket(path, existing, replayed=True, duplicate=True)
                command = existing.get("command") if isinstance(existing.get("command"), dict) else {}
                existing_id = str(command.get("command_id") or "")
                with self._active_lock:
                    is_active = existing_id in self._active
                owner_status = self._owner_status(existing)
                if is_active or owner_status == "live":
                    raise CommandOutcomeUnknown(f"command {existing_id} is still executing")
                if owner_status == "unknown":
                    raise CommandOutcomeUnknown(
                        f"command {existing_id} may still be executing on another process or host; "
                        "its outcome was not changed and execution was not repeated"
                    )
                existing["state"] = "unknown"
                existing["finished_at"] = existing.get("finished_at") or now_iso()
                existing["error"] = {
                    "type": "process_interrupted",
                    "message": "previous process ended before the command result was committed; execution was not repeated",
                }
                self._atomic_json(path, existing)
                raise CommandOutcomeUnknown(
                    f"command {existing_id} has an unknown outcome; inspect its receipt before retrying with a new key"
                )
            receipt = {
                "format": COMMAND_RECEIPT_FORMAT,
                "schema_version": COMMAND_SCHEMA_VERSION,
                "state": "executing",
                "request_sha256": digest,
                "command": envelope,
                "started_at": now_iso(),
                "finished_at": "",
                "owner": {"host": socket.gethostname(), "pid": os.getpid()},
                "http_status": None,
                "result": None,
                "error": None,
                "redaction_receipts": [payload_receipt.to_dict(), policy_receipt.to_dict()],
            }
            self._atomic_json(path, receipt)
            with self._active_lock:
                self._active.add(identifier)
        return CommandTicket(path, receipt)

    def activate(self, ticket: CommandTicket) -> None:
        if ticket.replayed:
            return
        ticket.token = activate_command(ticket.envelope)

    def finish(self, ticket: CommandTicket, result: Any, *, http_status: int = 200) -> dict[str, Any]:
        if ticket.replayed:
            return ticket.receipt
        redacted_result, receipt = DEFAULT_REDACTION_ENGINE.redact(result, boundary="command_result")
        value = dict(ticket.receipt)
        value["state"] = "completed" if int(http_status) < 400 else "failed"
        value["result"] = redacted_result
        value["http_status"] = int(http_status)
        value["finished_at"] = now_iso()
        value["redaction_receipts"] = [*value.get("redaction_receipts", []), receipt.to_dict()]
        if int(http_status) >= 400:
            message = str(redacted_result.get("error") or "command failed") if isinstance(redacted_result, Mapping) else "command failed"
            value["error"] = {"type": "command_rejected", "message": message}
        with self._locked():
            self._atomic_json(ticket.path, value)
        self._deactivate(ticket)
        ticket.receipt = value
        return value

    def fail(self, ticket: CommandTicket, exc: BaseException) -> dict[str, Any]:
        if ticket.replayed:
            return ticket.receipt
        redacted, receipt = DEFAULT_REDACTION_ENGINE.redact(str(exc), boundary="command_error")
        value = dict(ticket.receipt)
        value.update(
            {
                "state": "failed",
                "finished_at": now_iso(),
                "error": {"type": type(exc).__name__, "message": str(redacted)},
            }
        )
        value["redaction_receipts"] = [*value.get("redaction_receipts", []), receipt.to_dict()]
        with self._locked():
            self._atomic_json(ticket.path, value)
        self._deactivate(ticket)
        ticket.receipt = value
        return value

    def _deactivate(self, ticket: CommandTicket) -> None:
        if ticket.token is not None:
            reset_command(ticket.token)
            ticket.token = None
        with self._active_lock:
            self._active.discard(ticket.command_id)

    def execute(self, command_type: str, payload: Mapping[str, Any], handler: Callable[[], Any], **options: Any) -> CommandExecution:
        ticket = self.begin(command_type, payload, **options)
        if ticket.replayed:
            if ticket.receipt.get("state") == "failed" and ticket.receipt.get("result") is None:
                error = ticket.receipt.get("error") if isinstance(ticket.receipt.get("error"), Mapping) else {}
                raise CommandError(str(error.get("message") or "command previously failed"))
            return CommandExecution(ticket.receipt.get("result"), ticket.receipt, True)
        self.activate(ticket)
        try:
            result = handler()
        except BaseException as exc:
            self.fail(ticket, exc)
            raise
        receipt = self.finish(ticket, result)
        return CommandExecution(result, receipt, False)

    def get(self, command_id: str) -> dict[str, Any]:
        identifier = str(command_id)
        if not COMMAND_ID_RE.fullmatch(identifier):
            raise KeyError(command_id)
        for path in sorted(self.commands_dir.glob("*.json")) if self.commands_dir.exists() else []:
            value = self._read(path)
            command = value.get("command") if isinstance(value.get("command"), dict) else {}
            if command.get("command_id") == identifier:
                return value
        raise KeyError(command_id)

    def list(self, *, limit: int = 100) -> list[dict[str, Any]]:
        values = [self._read(path) for path in self.commands_dir.glob("*.json")] if self.commands_dir.exists() else []
        values.sort(key=lambda item: str(item.get("started_at") or ""), reverse=True)
        return values[: max(1, min(int(limit), 1000))]
