"""Evidence-backed project overview and cross-run activity projection."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any, Mapping

from .events import now_iso


README_CANDIDATES = ("README.md", "README.rst", "README.txt", "README")
INSTRUCTION_CANDIDATES = (
    "AGENTS.md",
    "CLAUDE.md",
    "GEMINI.md",
    ".github/copilot-instructions.md",
    ".cursorrules",
)
STACK_MARKERS = {
    "pyproject.toml": "Python",
    "requirements.txt": "Python",
    "package.json": "Node.js",
    "Cargo.toml": "Rust",
    "go.mod": "Go",
    "Gemfile": "Ruby",
    "pom.xml": "Java",
    "build.gradle": "Java",
    "Dockerfile": "Docker",
    "docker-compose.yml": "Docker Compose",
    "compose.yml": "Docker Compose",
    "Makefile": "Make",
}
SIGNIFICANT_EVENTS = frozenset(
    {
        "run.queued",
        "run.started",
        "run.review_ready",
        "run.accepted",
        "run.failed",
        "run.cancelled",
        "agent.question",
        "agent.permission_request",
        "artifact.created",
        "integration.completed",
        "integration.conflict",
        "pr.created",
        "ci.failed",
        "ci.retry_pushed",
        "ci.passed",
        "review.sent_back",
    }
)


def _read_text(path: Path, limit: int = 120_000) -> str:
    try:
        return path.read_bytes()[:limit].decode("utf-8", errors="replace")
    except OSError:
        return ""


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _plain_markdown(value: str) -> str:
    text = re.sub(r"```.*?```", " ", value, flags=re.DOTALL)
    text = re.sub(r"!\[[^]]*]\([^)]*\)", " ", text)
    text = re.sub(r"\[([^]]+)]\([^)]*\)", r"\1", text)
    text = re.sub(r"^\s{0,3}[#>*+-]+\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"[`*_~]", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _summary(value: str, limit: int = 900) -> str:
    plain = _plain_markdown(value)
    if len(plain) <= limit:
        return plain
    clipped = plain[:limit].rsplit(" ", 1)[0]
    return f"{clipped}…"


def _git_log(path: Path, limit: int = 6) -> list[dict[str, str]]:
    try:
        result = subprocess.run(
            [
                "git",
                "-C",
                str(path),
                "log",
                f"-{limit}",
                "--date=iso-strict",
                "--format=%H%x1f%h%x1f%ad%x1f%an%x1f%s",
            ],
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    commits: list[dict[str, str]] = []
    if result.returncode != 0:
        return commits
    for line in result.stdout.splitlines():
        parts = line.split("\x1f", 4)
        if len(parts) == 5:
            commits.append(
                {"sha": parts[0], "short_sha": parts[1], "ts": parts[2], "author": parts[3], "subject": parts[4]}
            )
    return commits


class ProjectKnowledge:
    def __init__(self, store: Any) -> None:
        self.store = store
        self.profile_dir = store.root / "project_profiles"
        self.profile_dir.mkdir(exist_ok=True)

    def _profile_path(self, project_id: str) -> Path:
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", project_id):
            raise ValueError("invalid project id")
        return self.profile_dir / f"{project_id}.json"

    def profile(self, project_id: str) -> dict[str, Any]:
        path = self._profile_path(project_id)
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            value = {}
        if not isinstance(value, dict):
            value = {}
        return {
            "summary": str(value.get("summary") or ""),
            "notes": str(value.get("notes") or ""),
            "updated_at": value.get("updated_at"),
        }

    def update_profile(self, project_id: str, changes: Mapping[str, Any]) -> dict[str, Any]:
        self.store.projects.get(project_id)
        summary = str(changes.get("summary") or "").strip()
        notes = str(changes.get("notes") or "").strip()
        if len(summary) > 2_000:
            raise ValueError("project summary is too long")
        if len(notes) > 20_000:
            raise ValueError("project notes are too long")
        value = {"summary": summary, "notes": notes, "updated_at": now_iso()}
        with self.store.locked():
            self.store._atomic_json(self._profile_path(project_id), value)
        return value

    def discover(self, project: Mapping[str, Any]) -> dict[str, Any]:
        root = Path(str(project["path"])).resolve()
        readme: dict[str, Any] | None = None
        for relative in README_CANDIDATES:
            path = root / relative
            if path.is_file():
                content = _read_text(path)
                readme = {
                    "path": relative,
                    "summary": _summary(content),
                    "sha256": _digest(content),
                    "bytes": len(content.encode("utf-8")),
                }
                break
        instructions: list[dict[str, Any]] = []
        for relative in INSTRUCTION_CANDIDATES:
            path = root / relative
            if not path.is_file():
                continue
            content = _read_text(path, limit=60_000)
            instructions.append(
                {
                    "path": relative,
                    "summary": _summary(content, limit=260),
                    "sha256": _digest(content),
                    "bytes": len(content.encode("utf-8")),
                }
            )
        cursor_rules = root / ".cursor" / "rules"
        if cursor_rules.is_dir():
            for path in sorted(cursor_rules.glob("*.md*"))[:12]:
                content = _read_text(path, limit=60_000)
                instructions.append(
                    {
                        "path": str(path.relative_to(root)),
                        "summary": _summary(content, limit=260),
                        "sha256": _digest(content),
                        "bytes": len(content.encode("utf-8")),
                    }
                )
        stack = sorted({label for marker, label in STACK_MARKERS.items() if (root / marker).is_file()})
        return {
            "readme": readme,
            "instructions": instructions,
            "stack": stack,
            "commits": _git_log(root),
        }

    @staticmethod
    def _event_summary(event_type: str, data: Mapping[str, Any], run: Mapping[str, Any]) -> str:
        if data.get("message"):
            return str(data["message"])[:500]
        if event_type == "run.queued":
            return "Task entered the project queue."
        if event_type == "run.started":
            return "An isolated agent workflow started."
        if event_type == "run.review_ready":
            return str(run.get("review_summary") or "Implementation is ready for review.")[:500]
        if event_type == "run.accepted":
            return "The change was approved and preserved as a local artifact."
        if event_type == "artifact.created":
            return f"Artifact {str(data.get('artifact_sha') or run.get('artifact_sha') or '')[:12]} was recorded."
        if event_type == "pr.created":
            return str(data.get("url") or run.get("pull_request_url") or "Draft pull request created.")
        if event_type.startswith("ci."):
            return str(data.get("summary") or (run.get("ci") or {}).get("summary") or event_type.replace(".", " "))[:500]
        return event_type.replace(".", " ")

    def activity(self, project_id: str, limit: int = 50) -> list[dict[str, Any]]:
        self.store.projects.get(project_id)
        values: list[dict[str, Any]] = []
        for run in self.store.list():
            if str(run.get("project_id")) != project_id:
                continue
            for event in self.store.events(str(run["id"]), limit=2_000):
                if event.get("type") not in SIGNIFICANT_EVENTS:
                    continue
                values.append(
                    {
                        "ts": event.get("ts"),
                        "type": event.get("type"),
                        "source": event.get("source"),
                        "run_id": run["id"],
                        "run_title": run.get("title") or run["id"],
                        "summary": self._event_summary(str(event.get("type")), event.get("data") or {}, run),
                    }
                )
        values.sort(key=lambda item: str(item.get("ts") or ""), reverse=True)
        return values[: max(1, min(int(limit), 200))]

    def overview(self, project_id: str) -> dict[str, Any]:
        project = self.store.projects.get(project_id)
        discovered = self.discover(project)
        profile = self.profile(project_id)
        about = profile["summary"] or (discovered.get("readme") or {}).get("summary") or "No project brief or README was found."
        return {
            "project": project,
            "about": about,
            "profile": profile,
            **discovered,
            "activity": self.activity(project_id, limit=30),
        }
