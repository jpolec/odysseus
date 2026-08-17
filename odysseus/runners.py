"""Agent and check process adapters emitting one normalized event protocol."""

from __future__ import annotations

import json
import os
import queue
import shlex
import signal
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .environments import wrap_command
from .redaction import DEFAULT_REDACTION_ENGINE, USAGE_COUNTER_KEYS


Emit = Callable[[str, str, Mapping[str, Any]], None]
Cancelled = Callable[[], bool]
ATTENTION_MARKER = "ODYSSEUS_ATTENTION:"


def _safe_int(value: Any) -> int:
    """Treat missing, redacted, and vendor-specific counters as zero."""

    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


@dataclass(slots=True)
class ProcessResult:
    returncode: int
    output: str
    duration_seconds: float
    cancelled: bool = False
    session_id: str = ""
    stop_reason: str = ""


def _extract_text(value: Any) -> str:
    """Best-effort text extraction without coupling the store to vendor schemas."""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts = [_extract_text(item) for item in value]
        return "\n".join(part for part in parts if part)
    if not isinstance(value, dict):
        return ""
    for key in ("text", "result", "message", "output_text"):
        if key in value:
            text = _extract_text(value[key])
            if text:
                return text
    for key in ("item", "content", "delta", "error"):
        if key in value:
            text = _extract_text(value[key])
            if text:
                return text
    return ""


def _sanitize(value: Any, *, key: str = "") -> Any:
    if isinstance(value, str):
        redacted, _receipt = DEFAULT_REDACTION_ENGINE.redact(value, boundary="runner")
        return str(redacted)[:20_000]
    if isinstance(value, list):
        return [_sanitize(item) for item in value[:100]]
    if isinstance(value, dict):
        if key and key.lower() in USAGE_COUNTER_KEYS:
            return value
        redacted, _receipt = DEFAULT_REDACTION_ENGINE.redact(value, boundary="runner")
        if isinstance(redacted, dict):
            return {str(item_key): _sanitize(item_value, key=str(item_key)) for item_key, item_value in list(redacted.items())[:100]}
        return redacted
    if key and key.lower() in USAGE_COUNTER_KEYS:
        return value
    if key:
        redacted, _receipt = DEFAULT_REDACTION_ENGINE.redact({key: value}, boundary="runner")
        if isinstance(redacted, dict):
            return redacted.get(key)
    return value


def _redact_values(value: Any, sensitive_values: Sequence[str]) -> Any:
    """Remove exact runtime credentials even when they do not match a token pattern."""

    secrets = [item for item in sensitive_values if len(item) >= 4]
    engine = DEFAULT_REDACTION_ENGINE if not secrets else DEFAULT_REDACTION_ENGINE.__class__(exact_values=secrets)
    if isinstance(value, str):
        redacted, _receipt = engine.redact(value, boundary="runner")
        return redacted
    if isinstance(value, list):
        return [_redact_values(item, secrets) for item in value]
    if isinstance(value, dict):
        redacted, _receipt = engine.redact(value, boundary="runner")
        return redacted
    return value


def _execution_secrets(execution: Mapping[str, Any] | None) -> list[str]:
    if not execution:
        return []
    return [
        value
        for name in execution.get("credential_env_names") or []
        if (value := os.environ.get(str(name))) is not None
    ]


def _attention_from_text(text: str) -> tuple[str, dict[str, Any]] | None:
    """Read an explicit agent-to-operator handoff from a final message."""

    payload = ""
    for line in reversed(text.splitlines()):
        if ATTENTION_MARKER in line:
            payload = line.split(ATTENTION_MARKER, 1)[1].strip()
            break
    if not payload:
        return None
    try:
        value = json.loads(payload)
    except json.JSONDecodeError:
        return None
    if not isinstance(value, dict):
        return None
    kind = str(value.get("type") or "decision_required")
    event_type = {
        "question": "agent.question",
        "permission_request": "agent.permission_request",
        "blocked": "agent.blocked",
        "decision_required": "agent.decision_required",
    }.get(kind, "agent.decision_required")
    options = value.get("options") if isinstance(value.get("options"), list) else []
    return event_type, {
        "attention_type": kind,
        "title": str(value.get("title") or "Operator decision required")[:500],
        "message": str(value.get("message") or value.get("question") or "")[:20_000],
        "options": options[:12],
        "priority": str(value.get("priority") or "medium"),
    }


class AgentRunner:
    def __init__(self, lanes: Mapping[str, Any] | None = None) -> None:
        self.lanes = dict(lanes or {})

    def command(
        self,
        lane: str,
        worktree: Path,
        prompt: str,
        *,
        review: bool,
        resume_session_id: str = "",
    ) -> list[str]:
        if lane == "codex":
            sandbox = "read-only" if review else "workspace-write"
            if resume_session_id:
                return [
                    "codex",
                    "exec",
                    "--json",
                    "--color",
                    "never",
                    "-C",
                    str(worktree),
                    "--sandbox",
                    sandbox,
                    "resume",
                    resume_session_id,
                    prompt,
                ]
            return [
                "codex",
                "exec",
                "--json",
                "--color",
                "never",
                "-C",
                str(worktree),
                "--sandbox",
                sandbox,
                prompt,
            ]
        if lane == "claude":
            permission_mode = "plan" if review else "acceptEdits"
            command = [
                "claude",
                "-p",
                "--output-format",
                "stream-json",
                "--verbose",
                "--permission-mode",
                permission_mode,
            ]
            if resume_session_id:
                command.extend(["--resume", resume_session_id])
            command.append(prompt)
            return command

        configured = self.lanes.get(lane)
        if isinstance(configured, dict):
            configured = configured.get("command")
        if isinstance(configured, str):
            args = shlex.split(configured)
        elif isinstance(configured, list) and all(isinstance(item, str) for item in configured):
            args = list(configured)
        else:
            raise ValueError(
                f"unknown lane {lane!r}; configure it in $ODYSSEUS_HOME/config.json"
            )
        replaced = [item.replace("{worktree}", str(worktree)).replace("{prompt}", prompt) for item in args]
        if not any("{prompt}" in item for item in args):
            replaced.append(prompt)
        return replaced

    def run(
        self,
        lane: str,
        worktree: Path,
        prompt: str,
        *,
        review: bool,
        emit: Emit,
        cancelled: Cancelled,
        resume_session_id: str = "",
        phase: str = "agent",
        timeout_seconds: float = 0,
        stall_seconds: float = 0,
        execution: Mapping[str, Any] | None = None,
    ) -> ProcessResult:
        args = self.command(
            lane,
            worktree,
            prompt,
            review=review,
            resume_session_id=resume_session_id,
        )
        host_args, cwd, process_env = wrap_command(execution, args, worktree, phase=phase)
        return _stream_process(
            host_args,
            cwd=cwd,
            source=lane,
            event_type="agent.output",
            emit=emit,
            cancelled=cancelled,
            parse_json=True,
            phase=phase,
            resumed=bool(resume_session_id),
            timeout_seconds=timeout_seconds,
            stall_seconds=stall_seconds,
            process_env=process_env,
            redact_values=_execution_secrets(execution),
        )


class CheckRunner:
    def run(
        self,
        command: str,
        worktree: Path,
        *,
        emit: Emit,
        cancelled: Cancelled,
        execution: Mapping[str, Any] | None = None,
        phase: str = "check",
    ) -> ProcessResult:
        # A login shell can rewrite PATH (notably through macOS path_helper),
        # selecting /usr/bin/python3 even when the server and `doctor` found a
        # newer Homebrew/pyenv interpreter. Checks should use the exact host
        # environment captured by wrap_command instead of shell startup files.
        args, cwd, process_env = wrap_command(
            execution,
            ["/bin/sh", "-c", command],
            worktree,
            phase=phase,
        )
        return _stream_process(
            args,
            cwd=cwd,
            source="check",
            event_type="check.output",
            emit=emit,
            cancelled=cancelled,
            parse_json=False,
            phase=phase,
            resumed=False,
            process_env=process_env,
            redact_values=_execution_secrets(execution),
        )


class _VendorNormalizer:
    """Turn Codex/Claude JSONL into stable Odysseus telemetry events."""

    def __init__(self, lane: str, phase: str, resumed: bool) -> None:
        self.lane = lane
        self.phase = phase
        self.resumed = resumed
        self.session_id = ""
        self.tools: dict[str, str] = {}

    def _base(self) -> dict[str, Any]:
        return {"phase": self.phase, "session_id": self.session_id}

    @staticmethod
    def _usage(value: Any) -> dict[str, int]:
        usage = value if isinstance(value, dict) else {}
        return {
            "input_tokens": _safe_int(usage.get("input_tokens", 0)),
            "cached_input_tokens": _safe_int(
                usage.get("cached_input_tokens", usage.get("cache_read_input_tokens", 0))
            ),
            "output_tokens": _safe_int(usage.get("output_tokens", 0)),
            "reasoning_output_tokens": _safe_int(usage.get("reasoning_output_tokens", 0)),
        }

    def events(self, vendor: Mapping[str, Any]) -> list[tuple[str, dict[str, Any]]]:
        return self._codex(vendor) if self.lane == "codex" else self._claude(vendor) if self.lane == "claude" else []

    def _codex(self, vendor: Mapping[str, Any]) -> list[tuple[str, dict[str, Any]]]:
        event_type = str(vendor.get("type") or "")
        values: list[tuple[str, dict[str, Any]]] = []
        if event_type == "thread.started":
            self.session_id = str(vendor.get("thread_id") or "")
            values.append(("agent.session", {**self._base(), "resumed": self.resumed}))
        elif event_type in {"item.started", "item.completed"}:
            item = vendor.get("item") if isinstance(vendor.get("item"), dict) else {}
            item_type = str(item.get("type") or "")
            item_id = str(item.get("id") or "")
            if item_type in {"command_execution", "mcp_tool_call", "web_search", "file_change"}:
                name = str(item.get("tool") or item.get("name") or item_type)
                if item_type == "command_execution":
                    name = "shell"
                self.tools[item_id] = name
                data = {
                    **self._base(),
                    "tool_call_id": item_id,
                    "tool": name,
                    "kind": item_type,
                    "status": str(item.get("status") or ("started" if event_type.endswith("started") else "completed")),
                }
                for key in ("command", "query", "path", "exit_code", "aggregated_output", "error"):
                    if item.get(key) is not None:
                        data[key] = str(item[key])[:20_000] if key in {"aggregated_output", "error"} else item[key]
                values.append(("agent.tool.started" if event_type.endswith("started") else "agent.tool.completed", data))
            elif item_type == "agent_message" and event_type.endswith("completed"):
                text = _extract_text(item)[:20_000]
                values.append(("agent.message", {**self._base(), "text": text}))
                attention = _attention_from_text(text)
                if attention:
                    attention_type, attention_data = attention
                    values.append((attention_type, {**self._base(), **attention_data}))
            elif item_type == "reasoning" and event_type.endswith("completed"):
                values.append(("agent.reasoning", {**self._base(), "text": _extract_text(item)[:20_000]}))
            elif item_type in {"request_user_input", "approval_request"}:
                attention_type = "agent.question" if item_type == "request_user_input" else "agent.permission_request"
                values.append(
                    (
                        attention_type,
                        {
                            **self._base(),
                            "attention_type": "question" if item_type == "request_user_input" else "permission_request",
                            "title": str(item.get("title") or "Agent needs operator input")[:500],
                            "message": str(item.get("question") or item.get("message") or "")[:20_000],
                            "options": item.get("options") if isinstance(item.get("options"), list) else [],
                            "priority": "high" if item_type == "approval_request" else "medium",
                        },
                    )
                )
        elif event_type == "turn.completed":
            values.append(("agent.usage", {**self._base(), **self._usage(vendor.get("usage"))}))
        return values

    def _claude(self, vendor: Mapping[str, Any]) -> list[tuple[str, dict[str, Any]]]:
        event_type = str(vendor.get("type") or "")
        values: list[tuple[str, dict[str, Any]]] = []
        incoming_session = str(vendor.get("session_id") or "")
        if incoming_session and incoming_session != self.session_id:
            self.session_id = incoming_session
            values.append(("agent.session", {**self._base(), "resumed": self.resumed}))
        message = vendor.get("message") if isinstance(vendor.get("message"), dict) else {}
        content = message.get("content") if isinstance(message.get("content"), list) else []
        if event_type == "assistant":
            for block in content:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "text":
                    text = str(block.get("text") or "")[:20_000]
                    values.append(("agent.message", {**self._base(), "text": text}))
                    attention = _attention_from_text(text)
                    if attention:
                        attention_type, attention_data = attention
                        values.append((attention_type, {**self._base(), **attention_data}))
                elif block.get("type") == "thinking":
                    values.append(("agent.reasoning", {**self._base(), "text": str(block.get("thinking") or "")[:20_000]}))
                elif block.get("type") == "tool_use":
                    item_id = str(block.get("id") or "")
                    name = str(block.get("name") or "tool")
                    self.tools[item_id] = name
                    values.append(("agent.tool.started", {**self._base(), "tool_call_id": item_id, "tool": name, "kind": "tool_use", "input": _sanitize(block.get("input", {}))}))
                    if name.lower() in {"askuserquestion", "request_user_input"}:
                        raw_input = block.get("input") if isinstance(block.get("input"), dict) else {}
                        questions = raw_input.get("questions") if isinstance(raw_input.get("questions"), list) else []
                        question = questions[0] if questions and isinstance(questions[0], dict) else raw_input
                        raw_options = question.get("options") if isinstance(question.get("options"), list) else []
                        options: list[Any] = []
                        for option in raw_options[:12]:
                            if isinstance(option, dict):
                                options.append(
                                    {
                                        "id": str(option.get("value") or option.get("label") or ""),
                                        "label": str(option.get("label") or option.get("description") or ""),
                                    }
                                )
                            else:
                                options.append(str(option))
                        values.append(
                            (
                                "agent.question",
                                {
                                    **self._base(),
                                    "attention_type": "question",
                                    "title": str(question.get("header") or "Agent question")[:500],
                                    "message": str(question.get("question") or "")[:20_000],
                                    "options": options,
                                    "priority": "medium",
                                },
                            )
                        )
        elif event_type == "user":
            for block in content:
                if not isinstance(block, dict) or block.get("type") != "tool_result":
                    continue
                item_id = str(block.get("tool_use_id") or "")
                output = _extract_text(block.get("content"))[:20_000]
                tool = self.tools.get(item_id, "tool")
                values.append(("agent.tool.completed", {**self._base(), "tool_call_id": item_id, "tool": tool, "kind": "tool_result", "error": bool(block.get("is_error")), "output": output}))
                if block.get("is_error") and any(
                    phrase in output.lower()
                    for phrase in ("requires approval", "permission denied", "not allowed")
                ):
                    values.append(
                        (
                            "agent.permission_request",
                            {
                                **self._base(),
                                "attention_type": "permission_request",
                                "title": f"Permission required for {tool}",
                                "message": output,
                                "tool": tool,
                                "tool_call_id": item_id,
                                "options": [
                                    {"id": "takeover", "label": "Continue in terminal"},
                                    {"id": "retry", "label": "Retry with guidance"},
                                    {"id": "reject", "label": "Reject"},
                                ],
                                "priority": "high",
                            },
                        )
                    )
        elif event_type == "result":
            values.append(("agent.usage", {**self._base(), **self._usage(vendor.get("usage")), "cumulative": True}))
            cost = vendor.get("total_cost_usd")
            if isinstance(cost, (int, float)):
                values.append(("agent.cost", {**self._base(), "cost_usd": float(cost)}))
        return values


def _terminate(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except (OSError, ProcessLookupError):
        process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (OSError, ProcessLookupError):
            process.kill()


def _stream_process(
    args: Sequence[str],
    *,
    cwd: Path,
    source: str,
    event_type: str,
    emit: Emit,
    cancelled: Cancelled,
    parse_json: bool,
    phase: str,
    resumed: bool,
    timeout_seconds: float = 0,
    stall_seconds: float = 0,
    process_env: Mapping[str, str] | None = None,
    redact_values: Sequence[str] = (),
) -> ProcessResult:
    started = time.monotonic()
    try:
        process = subprocess.Popen(
            list(args),
            cwd=cwd,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=1,
            start_new_session=True,
            env=dict(process_env) if process_env is not None else None,
        )
    except (OSError, ValueError) as exc:
        message = str(exc)
        emit(event_type, source, {"stream": "stderr", "text": message})
        return ProcessResult(127, message, time.monotonic() - started)

    normalizer = _VendorNormalizer(source, phase, resumed)

    lines: queue.Queue[tuple[str, str | None]] = queue.Queue()

    def reader(stream_name: str, stream: Any) -> None:
        try:
            for line in iter(stream.readline, ""):
                lines.put((stream_name, line.rstrip("\n")))
        finally:
            lines.put((stream_name, None))

    threads = [
        threading.Thread(target=reader, args=("stdout", process.stdout), daemon=True),
        threading.Thread(target=reader, args=("stderr", process.stderr), daemon=True),
    ]
    for thread in threads:
        thread.start()

    completed_streams = 0
    output: list[str] = []
    output_size = 0
    was_cancelled = False
    stop_reason = ""
    last_activity = started
    next_heartbeat = started + 15
    while completed_streams < 2 or process.poll() is None:
        current = time.monotonic()
        if timeout_seconds > 0 and current - started >= timeout_seconds and process.poll() is None:
            was_cancelled = True
            stop_reason = "timeout"
            emit(
                "run.stalled",
                "odysseus",
                {"message": f"{phase} exceeded its {timeout_seconds:g}s timeout.", "reason": "timeout", "phase": phase},
            )
            _terminate(process)
        elif stall_seconds > 0 and current - last_activity >= stall_seconds and process.poll() is None:
            was_cancelled = True
            stop_reason = "stall"
            emit(
                "run.stalled",
                "odysseus",
                {"message": f"{phase} produced no output for {stall_seconds:g}s.", "reason": "stall", "phase": phase},
            )
            _terminate(process)
        elif cancelled() and process.poll() is None:
            was_cancelled = True
            stop_reason = "cancelled"
            _terminate(process)
        if current >= next_heartbeat and process.poll() is None:
            emit(
                "run.heartbeat",
                "odysseus",
                {"phase": phase, "elapsed_seconds": round(current - started, 1), "idle_seconds": round(current - last_activity, 1)},
            )
            next_heartbeat = current + 15
        try:
            stream_name, line = lines.get(timeout=0.2)
        except queue.Empty:
            continue
        if line is None:
            completed_streams += 1
            continue
        last_activity = time.monotonic()
        data: dict[str, Any] = {"stream": stream_name}
        text = line
        vendor: Any = None
        if parse_json and stream_name == "stdout":
            try:
                vendor = json.loads(line)
            except json.JSONDecodeError:
                vendor = None
            if isinstance(vendor, dict):
                data["vendor_type"] = str(vendor.get("type", "event"))
                extracted = _extract_text(vendor)
                if extracted:
                    text = extracted
                else:
                    text = f"[{data['vendor_type']}]"
        data["text"] = _redact_values(_sanitize(text[:20_000]), redact_values)
        data["phase"] = phase
        normalized_events = normalizer.events(vendor) if isinstance(vendor, dict) else []
        if not normalized_events:
            emit(event_type, source, data)
        if isinstance(vendor, dict):
            for normalized_type, normalized_data in normalized_events:
                emit(normalized_type, source, _redact_values(_sanitize(normalized_data), redact_values))
        if output_size < 120_000:
            chunk = str(_redact_values(_sanitize(text), redact_values)) + "\n"
            output.append(chunk)
            output_size += len(chunk)

    returncode = process.wait()
    for thread in threads:
        thread.join(timeout=1)
    if process.stdout is not None:
        process.stdout.close()
    if process.stderr is not None:
        process.stderr.close()
    return ProcessResult(
        returncode=returncode,
        output="".join(output)[:120_000].rstrip(),
        duration_seconds=round(time.monotonic() - started, 3),
        cancelled=was_cancelled,
        session_id=normalizer.session_id,
        stop_reason=stop_reason,
    )
