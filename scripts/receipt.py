#!/usr/bin/env python3
"""Write lightweight JSON receipts for managed agent sessions."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path
from typing import Any


STATUS_VALUES = {"WORK", "WAIT", "IDLE", "UNKNOWN", "DEAD"}


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def clean_status(value: str) -> str:
    status = value.upper()
    return status if status in STATUS_VALUES else "UNKNOWN"


def receipt_path(receipts_dir: Path, tmux_session: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", tmux_session).strip("._")
    if not safe:
        safe = "session"
    return receipts_dir / f"{safe}.json"


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    tmp.replace(path)


def cmd_write(args: argparse.Namespace) -> int:
    receipts_dir = Path(args.receipts_dir).expanduser()
    path = receipt_path(receipts_dir, args.tmux_session)
    existing = read_json(path)
    stamp = now_iso()

    data: dict[str, Any] = {
        "session_id": args.session_id or args.tmux_session,
        "tmux_session": args.tmux_session,
        "project_path": args.project_path,
        "lane": args.lane,
        "role": args.role,
        "command": args.command,
        "prompt_file": args.prompt_file,
        "created_at": existing.get("created_at") or stamp,
        "updated_at": stamp,
        "status": clean_status(args.status),
        "managed": True,
        "receipt_path": str(path),
    }
    if args.prompt_file_path:
        data["prompt_file_path"] = args.prompt_file_path

    write_json(path, data)
    print(path)
    return 0


def cmd_update_status(args: argparse.Namespace) -> int:
    receipts_dir = Path(args.receipts_dir).expanduser()
    path = receipt_path(receipts_dir, args.tmux_session)
    data = read_json(path)
    stamp = now_iso()
    if not data:
        data = {
            "session_id": args.tmux_session,
            "tmux_session": args.tmux_session,
            "created_at": stamp,
            "managed": True,
        }

    data["updated_at"] = stamp
    data["status"] = clean_status(args.status)
    write_json(path, data)
    print(path)
    return 0


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    sub = root.add_subparsers(dest="command", required=True)

    write = sub.add_parser("write", help="create or refresh a session receipt")
    write.add_argument("--receipts-dir", required=True)
    write.add_argument("--session-id", default="")
    write.add_argument("--tmux-session", required=True)
    write.add_argument("--project-path", required=True)
    write.add_argument("--lane", required=True)
    write.add_argument("--role", required=True)
    write.add_argument("--command", required=True)
    write.add_argument("--prompt-file", default="")
    write.add_argument("--prompt-file-path", default="")
    write.add_argument("--status", default="UNKNOWN")
    write.set_defaults(func=cmd_write)

    update = sub.add_parser("update-status", help="update a receipt status")
    update.add_argument("--receipts-dir", required=True)
    update.add_argument("--tmux-session", required=True)
    update.add_argument("--status", required=True)
    update.set_defaults(func=cmd_update_status)

    return root


def main() -> int:
    args = parser().parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
