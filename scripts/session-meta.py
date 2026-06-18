#!/usr/bin/env python3
"""Read recent Codex JSONL sessions and print compact picker metadata.

Output is tab-separated:
  state age context_remaining title session_file
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any


DEFAULT_SCAN_LIMIT = 80
DEFAULT_TAIL_BYTES = 2 * 1024 * 1024
DEFAULT_TAIL_LINES = 4000


def normalize_path(value: str | None) -> str:
    if not value:
        return ""
    try:
        return str(Path(value).expanduser().resolve())
    except OSError:
        return str(Path(value).expanduser())


def clean_text(value: Any, limit: int = 92) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        value = " ".join(clean_text(item, limit=limit * 2) for item in value)
    elif isinstance(value, dict):
        for key in ("text", "message", "summary", "content"):
            if key in value:
                value = value[key]
                break
        else:
            value = " ".join(clean_text(v, limit=limit * 2) for v in value.values())
    text = re.sub(r"\s+", " ", str(value)).strip()
    if len(text) > limit:
        return text[: limit - 1].rstrip() + "..."
    return text


def timestamp_to_epoch(value: Any) -> float | None:
    if not value:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value)
    try:
        return dt.datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def human_age(epoch: float | None, now: float) -> str:
    if not epoch:
        return "-"
    seconds = max(0, int(now - epoch))
    if seconds < 60:
        return "0m"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m"
    hours = minutes // 60
    if hours < 48:
        return f"{hours}h"
    return f"{hours // 24}d"


def state_for_event(event: str | None) -> str:
    if not event:
        return ""
    event = event.lower().replace("_", "-")
    if "permission" in event or "approval" in event or event in {
        "ask-user",
        "input-required",
        "needs-input",
    }:
        return "waiting"
    if event in {
        "agent-turn-start",
        "start",
        "started",
        "task-start",
        "task-started",
        "turn-start",
        "working",
        "running",
    }:
        return "working"
    if event in {
        "agent-turn-complete",
        "complete",
        "completed",
        "done",
        "idle",
        "stop",
        "task-complete",
        "turn-aborted",
        "turn-complete",
        "turn-completed",
    }:
        return "idle"
    if event.startswith("fail") or event in {"error", "errored"}:
        return "waiting"
    return ""


def token_total(usage: dict[str, Any] | None) -> int | None:
    if not isinstance(usage, dict):
        return None
    total = usage.get("total_tokens")
    if isinstance(total, (int, float)):
        return int(total)
    parts = [
        usage.get("input_tokens"),
        usage.get("output_tokens"),
        usage.get("reasoning_output_tokens"),
    ]
    if all(isinstance(part, (int, float)) for part in parts):
        return int(sum(parts))
    return None


def context_remaining(info: dict[str, Any] | None) -> str:
    if not isinstance(info, dict):
        return "-"
    window = info.get("model_context_window")
    if not isinstance(window, (int, float)) or window <= 0:
        return "-"
    used = token_total(info.get("last_token_usage"))
    if used is None:
        used = token_total(info.get("total_token_usage"))
    if used is None:
        return "-"
    remaining = max(0, min(100, round(((window - used) / window) * 100)))
    return f"{remaining}%"


def tail_lines(path: Path, max_bytes: int, max_lines: int) -> list[str]:
    with path.open("rb") as fh:
        fh.seek(0, os.SEEK_END)
        size = fh.tell()
        start = max(0, size - max_bytes)
        fh.seek(start)
        if start:
            fh.readline()
        lines = fh.readlines()
    return [line.decode("utf-8", "replace") for line in lines[-max_lines:]]


def inspect_session(path: Path, now: float, max_bytes: int, max_lines: int) -> dict[str, Any]:
    meta: dict[str, Any] = {
        "file": str(path),
        "cwd": "",
        "state": "",
        "title": "",
        "ctx": "-",
        "epoch": None,
        "mtime": path.stat().st_mtime,
    }
    try:
        lines = tail_lines(path, max_bytes, max_lines)
    except OSError:
        return meta

    for line in lines:
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue

        epoch = timestamp_to_epoch(entry.get("timestamp"))
        if epoch:
            meta["epoch"] = epoch

        payload = entry.get("payload")
        if not isinstance(payload, dict):
            continue

        record_type = entry.get("type")
        payload_type = payload.get("type")

        if record_type == "turn_context":
            cwd = normalize_path(payload.get("cwd"))
            if cwd:
                meta["cwd"] = cwd
            continue

        if payload_type == "user_message":
            title = clean_text(payload.get("message") or payload.get("text_elements"))
            if title:
                meta["title"] = title
        elif payload_type == "task_complete":
            title = clean_text(payload.get("last_agent_message"))
            if title and not meta["title"]:
                meta["title"] = title

        if payload_type == "token_count":
            meta["ctx"] = context_remaining(payload.get("info"))

        mapped = state_for_event(str(payload_type) if payload_type else None)
        if mapped:
            meta["state"] = mapped

    if not meta["epoch"]:
        meta["epoch"] = meta["mtime"]
    meta["age"] = human_age(meta["epoch"], now)
    if not meta["title"]:
        meta["title"] = "-"
    return meta


def match_score(target: str, cwd: str) -> int:
    if not target or not cwd:
        return 0
    if target == cwd:
        return 100
    try:
        common = os.path.commonpath([target, cwd])
    except ValueError:
        return 0
    if common == cwd:
        return 70
    if common == target:
        return 60
    return 0


def session_files(base: Path, limit: int) -> list[Path]:
    if not base.exists():
        return []
    files = [path for path in base.glob("**/*.jsonl") if path.is_file()]
    files.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    return files[:limit]


def best_for_path(args: argparse.Namespace) -> dict[str, Any] | None:
    target = normalize_path(args.path)
    base = Path(args.sessions_dir).expanduser()
    now = time.time()
    best: tuple[int, float, dict[str, Any]] | None = None

    for path in session_files(base, args.limit):
        meta = inspect_session(path, now, args.tail_bytes, args.tail_lines)
        score = match_score(target, meta.get("cwd", ""))
        if score <= 0:
            continue
        if score == 100:
            return meta
        candidate = (score, float(meta.get("epoch") or meta.get("mtime") or 0), meta)
        if best is None or candidate[:2] > best[:2]:
            best = candidate

    return best[2] if best else None


def main() -> int:
    parser = argparse.ArgumentParser(description="Print Codex session metadata for a cwd")
    parser.add_argument("--path", required=True)
    parser.add_argument(
        "--sessions-dir",
        default=os.environ.get("CODEX_SESSIONS_DIR", str(Path.home() / ".codex" / "sessions")),
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=int(os.environ.get("CODEX_SESSION_SCAN_LIMIT", DEFAULT_SCAN_LIMIT)),
    )
    parser.add_argument("--tail-bytes", type=int, default=DEFAULT_TAIL_BYTES)
    parser.add_argument("--tail-lines", type=int, default=DEFAULT_TAIL_LINES)
    args = parser.parse_args()

    meta = best_for_path(args) or {}
    fields = [
        meta.get("state", ""),
        meta.get("age", "-"),
        meta.get("ctx", "-"),
        meta.get("title", "-"),
        meta.get("file", ""),
    ]
    print("\t".join(clean_text(field, limit=120) for field in fields))
    return 0


if __name__ == "__main__":
    sys.exit(main())
