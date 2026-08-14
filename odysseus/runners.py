"""Agent and check process adapters emitting one normalized event protocol."""

from __future__ import annotations

import json
import os
import queue
import re
import shlex
import signal
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence


Emit = Callable[[str, str, Mapping[str, Any]], None]
Cancelled = Callable[[], bool]
SENSITIVE_KEY = re.compile(r"(?:api[_-]?key|authorization|password|passwd|secret|token|credential|cookie)", re.I)
SENSITIVE_VALUE = re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/-]+=*|\b(?:sk|ghp|github_pat|xox[baprs])[-_A-Za-z0-9]{12,}\b")


@dataclass(slots=True)
class ProcessResult:
    returncode: int
    output: str
    duration_seconds: float
    cancelled: bool = False
    session_id: str = ""


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
    if key and SENSITIVE_KEY.search(key):
        return "[REDACTED]"
    if isinstance(value, str):
        return SENSITIVE_VALUE.sub(lambda match: f"{match.group(1) if match.lastindex else ''}[REDACTED]", value)[:20_000]
    if isinstance(value, list):
        return [_sanitize(item) for item in value[:100]]
    if isinstance(value, dict):
        return {str(item_key): _sanitize(item_value, key=str(item_key)) for item_key, item_value in list(value.items())[:100]}
    return value


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
                    "resume",
                    "--json",
                    "--sandbox",
                    sandbox,
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
    ) -> ProcessResult:
        args = self.command(
            lane,
            worktree,
            prompt,
            review=review,
            resume_session_id=resume_session_id,
        )
        return _stream_process(
            args,
            cwd=worktree,
            source=lane,
            event_type="agent.output",
            emit=emit,
            cancelled=cancelled,
            parse_json=True,
            phase=phase,
            resumed=bool(resume_session_id),
        )


class CheckRunner:
    def run(
        self,
        command: str,
        worktree: Path,
        *,
        emit: Emit,
        cancelled: Cancelled,
    ) -> ProcessResult:
        return _stream_process(
            ["/bin/sh", "-lc", command],
            cwd=worktree,
            source="check",
            event_type="check.output",
            emit=emit,
            cancelled=cancelled,
            parse_json=False,
            phase="check",
            resumed=False,
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
            "input_tokens": int(usage.get("input_tokens", 0) or 0),
            "cached_input_tokens": int(usage.get("cached_input_tokens", usage.get("cache_read_input_tokens", 0)) or 0),
            "output_tokens": int(usage.get("output_tokens", 0) or 0),
            "reasoning_output_tokens": int(usage.get("reasoning_output_tokens", 0) or 0),
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
                values.append(("agent.message", {**self._base(), "text": _extract_text(item)[:20_000]}))
            elif item_type == "reasoning" and event_type.endswith("completed"):
                values.append(("agent.reasoning", {**self._base(), "text": _extract_text(item)[:20_000]}))
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
                    values.append(("agent.message", {**self._base(), "text": str(block.get("text") or "")[:20_000]}))
                elif block.get("type") == "thinking":
                    values.append(("agent.reasoning", {**self._base(), "text": str(block.get("thinking") or "")[:20_000]}))
                elif block.get("type") == "tool_use":
                    item_id = str(block.get("id") or "")
                    name = str(block.get("name") or "tool")
                    self.tools[item_id] = name
                    values.append(("agent.tool.started", {**self._base(), "tool_call_id": item_id, "tool": name, "kind": "tool_use", "input": _sanitize(block.get("input", {}))}))
        elif event_type == "user":
            for block in content:
                if not isinstance(block, dict) or block.get("type") != "tool_result":
                    continue
                item_id = str(block.get("tool_use_id") or "")
                values.append(("agent.tool.completed", {**self._base(), "tool_call_id": item_id, "tool": self.tools.get(item_id, "tool"), "kind": "tool_result", "error": bool(block.get("is_error")), "output": _extract_text(block.get("content"))[:20_000]}))
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
    while completed_streams < 2 or process.poll() is None:
        if cancelled() and process.poll() is None:
            was_cancelled = True
            _terminate(process)
        try:
            stream_name, line = lines.get(timeout=0.2)
        except queue.Empty:
            continue
        if line is None:
            completed_streams += 1
            continue
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
        data["text"] = _sanitize(text[:20_000])
        data["phase"] = phase
        normalized_events = normalizer.events(vendor) if isinstance(vendor, dict) else []
        if not normalized_events:
            emit(event_type, source, data)
        if isinstance(vendor, dict):
            for normalized_type, normalized_data in normalized_events:
                emit(normalized_type, source, _sanitize(normalized_data))
        if output_size < 120_000:
            chunk = text + "\n"
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
    )
