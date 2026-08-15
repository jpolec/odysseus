"""Discovery and takeover bridge for interactive tmux agent sessions."""

from __future__ import annotations

import json
import hashlib
import os
import re
import shlex
import subprocess
import time
from pathlib import Path
from typing import Any, Mapping

from .events import now_iso
from .resources import resource_path


SESSION_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
UUID_RE = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")


def _run(*args: str, timeout: float = 5) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(args),
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
    )


class TmuxBridge:
    def __init__(self, store: Any, *, receipts_dir: Path | str | None = None) -> None:
        self.store = store
        self.receipts_dir = (
            Path(receipts_dir).expanduser()
            if receipts_dir is not None
            else Path(os.environ.get("ODYSSEUS_TMUX_RECEIPTS", "~/.tmux-ai-sessions/receipts")).expanduser()
        )
        self.session_meta = resource_path("scripts", "session-meta.py")
        self._git_roots: dict[str, str] = {}
        self._managed_worktrees: dict[str, str] = {}
        self._cache_at = 0.0
        self._cache: list[dict[str, Any]] = []

    @staticmethod
    def available() -> bool:
        try:
            return _run("tmux", "list-sessions", timeout=2).returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            return False

    def _receipts(self) -> dict[str, dict[str, Any]]:
        values: dict[str, dict[str, Any]] = {}
        if not self.receipts_dir.is_dir():
            return values
        for path in self.receipts_dir.glob("*.json"):
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(value, dict) and value.get("tmux_session"):
                values[str(value["tmux_session"])] = value
        return values

    def _codex_metadata(self, project_path: str) -> dict[str, str]:
        if not project_path or not self.session_meta.is_file():
            return {}
        try:
            result = _run(str(self.session_meta), "--path", project_path, timeout=4)
        except (OSError, subprocess.TimeoutExpired):
            return {}
        fields = result.stdout.rstrip("\n").split("\t")
        if result.returncode != 0 or len(fields) < 5:
            return {}
        session_match = UUID_RE.search(fields[4])
        return {
            "detected_status": fields[0],
            "age": fields[1],
            "context_remaining": fields[2],
            "title": fields[3],
            "session_file": fields[4],
            "agent_session_id": session_match.group(0) if session_match else "",
        }

    def _canonical_project_path(self, path: str) -> str:
        if not path or not Path(path).is_dir():
            return path
        try:
            root = self._git_roots.get(path)
            if root is None:
                result = _run("git", "-C", path, "rev-parse", "--show-toplevel", timeout=3)
                root = result.stdout.strip() if result.returncode == 0 else ""
                self._git_roots[path] = root
            if not root:
                return path
            resolved = str(Path(root).resolve())
            return self._managed_worktrees.get(resolved, resolved)
        except (OSError, subprocess.TimeoutExpired, ValueError):
            return path

    @staticmethod
    def _panes() -> list[dict[str, str]]:
        try:
            result = _run(
                "tmux",
                "list-panes",
                "-a",
                "-F",
                "#{session_name}\t#{window_index}\t#{window_name}\t#{pane_id}\t#{pane_pid}\t#{pane_current_command}\t#{pane_current_path}\t#{pane_title}",
            )
        except (OSError, subprocess.TimeoutExpired):
            return []
        panes: list[dict[str, str]] = []
        for line in result.stdout.splitlines():
            fields = line.split("\t")
            if len(fields) >= 8:
                panes.append(
                    dict(
                        zip(
                            ("session", "window_index", "window_name", "target", "pid", "command", "path", "pane_title"),
                            fields[:8],
                        )
                    )
                )
        return panes

    @staticmethod
    def _pane_status(title: str) -> str:
        lowered = title.strip().lower()
        if "action required" in lowered or "waiting" in lowered:
            return "waiting"
        if "working" in lowered or any(spinner in title for spinner in "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"):
            return "working"
        return "unknown"

    @staticmethod
    def _pane_display_title(pane: Mapping[str, str], lane: str) -> str:
        path_name = Path(str(pane.get("path") or "")).name.lower()
        generic = {"", "tmux", "working", "zsh", "bash", "sh", "fish", "jakub", path_name}
        pane_title = str(pane.get("pane_title") or "").strip()
        if lane == "claude" and pane_title.startswith("✳"):
            return pane_title.lstrip("✳ ")
        window_name = str(pane.get("window_name") or "").strip()
        if window_name.lower() not in generic and not window_name.isdigit():
            return window_name
        pane_title = pane_title.lstrip("⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏ ")
        if pane_title.lower() not in generic and not any(suffix in pane_title.lower() for suffix in (".local", ".home")):
            return pane_title
        return f"{lane.capitalize()} pane {pane.get('target') or ''}".strip()

    @staticmethod
    def _agent_roots(panes: list[dict[str, str]]) -> dict[str, str]:
        roots = {int(item["pid"]): item["target"] for item in panes if item.get("pid", "").isdigit()}
        lanes: dict[str, str] = {}
        for item in panes:
            command = item.get("command", "").lower()
            if command == "codex":
                lanes[item["target"]] = "codex"
            elif command == "claude":
                lanes[item["target"]] = "claude"
        try:
            result = _run("ps", "-axo", "pid=,ppid=,command=", timeout=4)
        except (OSError, subprocess.TimeoutExpired):
            return lanes
        parents: dict[int, int] = {}
        commands: dict[int, str] = {}
        for line in result.stdout.splitlines():
            match = re.match(r"\s*(\d+)\s+(\d+)\s+(.*)$", line)
            if match:
                pid = int(match.group(1))
                parents[pid] = int(match.group(2))
                commands[pid] = match.group(3)
        for pid, command in commands.items():
            lowered = command.lower()
            if re.search(r"(^|[\s/])claude([\s/]|$)", lowered):
                lane = "claude"
            elif re.search(r"(^|[\s/])codex([\s/]|$)|@openai/codex|codex-[^\s]*/bin/codex", lowered):
                lane = "codex"
            else:
                continue
            current = pid
            seen: set[int] = set()
            while current in parents and current not in seen:
                seen.add(current)
                if current in roots:
                    lanes.setdefault(roots[current], lane)
                    break
                current = parents[current]
        return lanes

    def list(self) -> list[dict[str, Any]]:
        if time.monotonic() - self._cache_at < 2:
            return [dict(item) for item in self._cache]
        self._managed_worktrees = {
            str(Path(str(run.get("worktree_path"))).resolve()): str(run.get("project_path"))
            for run in self.store.list()
            if run.get("worktree_path") and run.get("project_path")
        }
        panes = self._panes()
        pane_lanes = self._agent_roots(panes)
        metadata_cache: dict[str, dict[str, str]] = {}

        def codex_metadata(path: str) -> dict[str, str]:
            if path not in metadata_cache:
                metadata_cache[path] = self._codex_metadata(path)
            return metadata_cache[path]

        panes_by_session: dict[str, list[dict[str, str]]] = {}
        for pane in panes:
            panes_by_session.setdefault(pane["session"], []).append(pane)
        try:
            result = _run(
                "tmux",
                "list-sessions",
                "-F",
                "#{session_name}\t#{session_created}\t#{session_activity}\t#{session_windows}\t#{session_attached}\t#{@ai_session_managed}\t#{@ai_session_lane}\t#{@ai_session_role}\t#{@ai_session_project_path}\t#{@ai_session_command}\t#{@ai_session_state}\t#{@codex_state}",
            )
        except (OSError, subprocess.TimeoutExpired):
            return []
        if result.returncode != 0:
            return []
        receipts = self._receipts()
        adopted = {
            (str(run.get("tmux_session")), str(run.get("tmux_target") or "")): str(run.get("id"))
            for run in self.store.list()
            if run.get("kind") == "tmux" and run.get("tmux_session")
        }
        sessions: list[dict[str, Any]] = []
        for line in result.stdout.splitlines():
            fields = line.split("\t")
            if len(fields) < 12:
                continue
            (
                name, created, activity, windows, attached, managed_option, lane_option,
                role_option, project_option, command_option, state_option, codex_state,
            ) = fields[:12]
            if not SESSION_RE.fullmatch(name):
                continue
            receipt = receipts.get(name, {})
            first_pane = (panes_by_session.get(name) or [{}])[0]
            working_path = str(
                project_option
                or receipt.get("project_path")
                or first_pane.get("path", "")
            )
            project_path = self._canonical_project_path(working_path)
            lane = str(lane_option or receipt.get("lane") or "")
            if not lane:
                if name.startswith("codex-"):
                    lane = "codex"
                else:
                    lane = "unknown"
            explicit_state = str(
                state_option
                or codex_state
                or receipt.get("status")
                or "unknown"
            ).lower()
            status_map = {"work": "working", "wait": "waiting", "idle": "idle", "dead": "dead"}
            explicit_state = status_map.get(explicit_state, explicit_state)
            meta = codex_metadata(project_path) if lane == "codex" else {}
            status = explicit_state if explicit_state in {"working", "waiting", "idle", "dead"} else meta.get("detected_status") or "unknown"
            managed = bool(managed_option == "1" or receipt or name.startswith(("codex-", "ai-", "odysseus-")))
            if not managed:
                continue
            record = {
                "id": name,
                "tmux_session": name,
                "project_path": project_path,
                "working_path": working_path,
                "lane": lane,
                "role": str(role_option or receipt.get("role") or "general"),
                "command": str(command_option or receipt.get("command") or first_pane.get("command", "")),
                "status": status,
                "managed": managed,
                "attached": attached != "0",
                "windows": int(windows or 0),
                "created_at_epoch": int(created or 0),
                "activity_at_epoch": int(activity or 0),
                "pane_pid": int(first_pane["pid"]) if first_pane.get("pid", "").isdigit() else None,
                "tmux_target": "",
                "kind": "session",
                "adopted_run_id": adopted.get((name, "")),
                "metadata_confidence": "heuristic" if meta else "tmux",
                **meta,
            }
            sessions.append(record)
        managed_names = {item["tmux_session"] for item in sessions}
        session_details = {
            line.split("\t", 1)[0]: line.split("\t")
            for line in result.stdout.splitlines()
            if "\t" in line
        }
        for pane in panes:
            lane = pane_lanes.get(pane["target"])
            if not lane or pane["session"] in managed_names:
                continue
            detail = session_details.get(pane["session"], [])
            identifier = f"pane-{pane['target'].lstrip('%')}"
            pane_title = str(pane.get("pane_title") or "")
            working_path = pane["path"]
            record = {
                "id": identifier,
                "tmux_session": pane["session"],
                "tmux_target": pane["target"],
                "kind": "pane",
                "window_index": int(pane["window_index"]) if pane.get("window_index", "").isdigit() else None,
                "window_name": str(pane.get("window_name") or ""),
                "pane_title": pane_title,
                "title": self._pane_display_title(pane, lane),
                "project_path": self._canonical_project_path(working_path),
                "working_path": working_path,
                "lane": lane,
                "role": "existing",
                "command": pane["command"],
                "status": self._pane_status(pane_title),
                "managed": False,
                "attached": len(detail) > 4 and detail[4] != "0",
                "windows": int(detail[3]) if len(detail) > 3 and detail[3].isdigit() else 0,
                "created_at_epoch": int(detail[1]) if len(detail) > 1 and detail[1].isdigit() else 0,
                "activity_at_epoch": int(detail[2]) if len(detail) > 2 and detail[2].isdigit() else 0,
                "pane_pid": int(pane["pid"]) if pane["pid"].isdigit() else None,
                "adopted_run_id": adopted.get((pane["session"], pane["target"])),
                "metadata_confidence": "tmux",
            }
            sessions.append(record)
        sessions = sorted(sessions, key=lambda item: int(item.get("activity_at_epoch", 0)), reverse=True)
        self._cache = [dict(item) for item in sessions]
        self._cache_at = time.monotonic()
        return sessions

    def get(self, name: str) -> dict[str, Any]:
        if not SESSION_RE.fullmatch(name):
            raise KeyError(name)
        for session in self.list():
            if session["id"] == name:
                return session
        raise KeyError(name)

    def adopt(self, name: str) -> dict[str, Any]:
        session = self.get(name)
        existing = session.get("adopted_run_id")
        if existing:
            return self.store.get(str(existing))
        project_path = str(session.get("project_path") or "")
        if not project_path or not Path(project_path).is_dir():
            raise ValueError("tmux session has no usable project directory")
        run = self.store.create_external(
            {
                "title": session.get("title") if session.get("title") not in {"", "-"} else name,
                "task": session.get("title") if session.get("title") not in {"", "-"} else f"Interactive tmux session {name}",
                "project_path": project_path,
                "lane": session.get("lane") or "unknown",
                "kind": "tmux",
                "status": "session",
                "tmux_session": session["tmux_session"],
                "tmux_target": session.get("tmux_target") or "",
                "agent_session_id": session.get("agent_session_id") or "",
            }
        )
        self.store.append_event(
            run["id"],
            "session.adopted",
            "tmux",
            {"tmux_session": session["tmux_session"], "tmux_target": session.get("tmux_target") or "", "agent_session_id": session.get("agent_session_id") or ""},
        )
        self._cache_at = 0
        return self.store.get(run["id"])

    @staticmethod
    def attach_command(name: str, target: str = "") -> str:
        if not SESSION_RE.fullmatch(name):
            raise ValueError("invalid tmux session name")
        if target:
            if not re.fullmatch(r"%\d+", target):
                raise ValueError("invalid tmux pane target")
            return f"tmux select-pane -t {shlex.quote(target)} \\; attach-session -t {shlex.quote(name)}"
        return f"tmux attach-session -t {shlex.quote(name)}"

    def takeover(self, run: Mapping[str, Any]) -> dict[str, Any]:
        existing = str(run.get("tmux_session") or "")
        if existing:
            target = str(run.get("tmux_target") or "")
            if any(item["tmux_session"] == existing and str(item.get("tmux_target") or "") == target for item in self.list()):
                return {"tmux_session": existing, "tmux_target": target, "command": self.attach_command(existing, target), "created": False}
            if run.get("kind") == "tmux":
                raise ValueError("the tracked tmux pane is no longer available; Odysseus will not guess which agent thread to resume")
        lane = str(run.get("lane") or "codex")
        sessions = run.get("agent_sessions") if isinstance(run.get("agent_sessions"), dict) else {}
        session_id = str(sessions.get("agent") or run.get("agent_session_id") or "")
        if not session_id:
            raise ValueError("this run has no resumable agent session yet")
        digest = hashlib.sha256(str(run.get("id", "session")).encode("utf-8")).hexdigest()[:10]
        name = f"odysseus-{digest}"[:60]
        worktree = str(run.get("worktree_path") or run.get("project_path") or "")
        if not Path(worktree).is_dir():
            raise ValueError("run worktree is not available")
        if lane == "codex":
            command = ["codex", "resume", "--include-non-interactive", "-C", worktree, session_id]
        elif lane == "claude":
            command = ["claude", "--resume", session_id]
        else:
            raise ValueError(f"interactive takeover is not configured for lane {lane!r}")
        shell_command = " ".join(shlex.quote(part) for part in command)
        try:
            result = _run("tmux", "new-session", "-d", "-s", name, "-c", worktree, shell_command)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RuntimeError(f"could not start tmux takeover: {exc}") from exc
        if result.returncode != 0:
            if "duplicate session" not in result.stderr.lower():
                raise RuntimeError(result.stderr.strip() or "could not start tmux takeover")
        for key, value in {
            "@ai_session_managed": "1",
            "@ai_session_lane": lane,
            "@ai_session_role": "takeover",
            "@ai_session_project_path": worktree,
            "@ai_session_command": shell_command,
            "@odysseus_run_id": str(run.get("id") or ""),
        }.items():
            try:
                _run("tmux", "set-option", "-t", f"={name}", key, value)
            except (OSError, subprocess.TimeoutExpired):
                pass
        self.store.update(str(run["id"]), tmux_session=name)
        self.store.append_event(
            str(run["id"]),
            "session.takeover_ready",
            "tmux",
            {"tmux_session": name, "agent_session_id": session_id},
        )
        self._cache_at = 0
        return {"tmux_session": name, "command": self.attach_command(name), "created": result.returncode == 0}
