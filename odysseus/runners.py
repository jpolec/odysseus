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


Emit = Callable[[str, str, Mapping[str, Any]], None]
Cancelled = Callable[[], bool]


@dataclass(slots=True)
class ProcessResult:
    returncode: int
    output: str
    duration_seconds: float
    cancelled: bool = False


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


class AgentRunner:
    def __init__(self, lanes: Mapping[str, Any] | None = None) -> None:
        self.lanes = dict(lanes or {})

    def command(self, lane: str, worktree: Path, prompt: str, *, review: bool) -> list[str]:
        if lane == "codex":
            sandbox = "read-only" if review else "workspace-write"
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
            return [
                "claude",
                "-p",
                "--output-format",
                "stream-json",
                "--verbose",
                "--permission-mode",
                permission_mode,
                prompt,
            ]

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
    ) -> ProcessResult:
        args = self.command(lane, worktree, prompt, review=review)
        return _stream_process(
            args,
            cwd=worktree,
            source=lane,
            event_type="agent.output",
            emit=emit,
            cancelled=cancelled,
            parse_json=True,
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
        )


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
                    text = line
        data["text"] = text[:20_000]
        emit(event_type, source, data)
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
    )
