"""Evidence-backed project overview and cross-run activity projection."""

from __future__ import annotations

import hashlib
import json
import re
import secrets
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


def _stable_digest(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return _digest(encoded)


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
        self.items_dir = store.root / "project_knowledge"
        self.items_dir.mkdir(exist_ok=True)

    def _profile_path(self, project_id: str) -> Path:
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", project_id):
            raise ValueError("invalid project id")
        return self.profile_dir / f"{project_id}.json"

    def _items_path(self, project_id: str) -> Path:
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", project_id):
            raise ValueError("invalid project id")
        return self.items_dir / f"{project_id}.json"

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

    def items(self, project_id: str) -> dict[str, Any]:
        self.store.projects.get(project_id)
        try:
            value = json.loads(self._items_path(project_id).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            value = {}
        items = value.get("items") if isinstance(value, dict) else []
        if not isinstance(items, list):
            items = []
        clean = [item for item in items if isinstance(item, dict) and item.get("id")]
        return {
            "project_id": project_id,
            "items": sorted(clean, key=lambda item: (not bool(item.get("enabled", True)), str(item.get("title") or "").lower())),
            "suggestions": self.suggestions(project_id, existing=clean),
            "updated_at": value.get("updated_at") if isinstance(value, dict) else None,
        }

    @staticmethod
    def _string_list(value: Any, field: str, limit: int = 20) -> list[str]:
        if isinstance(value, str):
            value = [item.strip() for item in value.split(",") if item.strip()]
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise ValueError(f"{field} must be a list of strings")
        return list(dict.fromkeys(item.strip().lower() for item in value if item.strip()))[:limit]

    def update_item(self, project_id: str, changes: Mapping[str, Any]) -> dict[str, Any]:
        self.store.projects.get(project_id)
        title = str(changes.get("title") or "").strip()
        content = str(changes.get("content") or "").strip()
        if not title or len(title) > 200:
            raise ValueError("knowledge title is required and must be at most 200 characters")
        if not content or len(content) > 20_000:
            raise ValueError("knowledge content is required and must be at most 20000 characters")
        current = self.items(project_id)
        items = current["items"]
        item_id = str(changes.get("id") or f"knowledge-{secrets.token_hex(4)}")
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", item_id):
            raise ValueError("invalid knowledge id")
        existing = next((item for item in items if item["id"] == item_id), {})
        value = {
            "id": item_id,
            "title": title,
            "content": content,
            "triggers": self._string_list(changes.get("triggers", existing.get("triggers", [])), "triggers"),
            "folders": self._string_list(changes.get("folders", existing.get("folders", [])), "folders"),
            "enabled": bool(changes.get("enabled", existing.get("enabled", True))),
            "source": str(changes.get("source") or existing.get("source") or "operator"),
            "status": "active",
            "created_at": existing.get("created_at") or now_iso(),
            "updated_at": now_iso(),
        }
        items = [item for item in items if item["id"] != item_id] + [value]
        payload = {"items": items, "updated_at": now_iso()}
        with self.store.locked():
            self.store._atomic_json(self._items_path(project_id), payload)
        return self.items(project_id)

    def select_items(self, project_id: str, task: str, limit: int = 4) -> list[dict[str, Any]]:
        task_lower = task.lower()
        selected: list[tuple[int, str, dict[str, Any]]] = []
        for item in self.items(project_id)["items"]:
            if not item.get("enabled", True):
                continue
            triggers = [str(value).lower() for value in item.get("triggers") or []]
            folders = [str(value).lower() for value in item.get("folders") or []]
            signals = [value for value in triggers + folders if value and value in task_lower]
            if (triggers or folders) and not signals:
                continue
            reason = "always-on project memory" if not (triggers or folders) else f"matched {', '.join(signals[:3])}"
            selected.append((len(signals), str(item.get("title") or ""), {**item, "reason": reason}))
        return [item for _, _, item in sorted(selected, key=lambda value: (-value[0], value[1].lower()))[:limit]]

    @staticmethod
    def _suggestion_key(value: str) -> str:
        return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9/_. -]+", " ", value.lower())).strip()[:300]

    def suggestions(self, project_id: str, *, existing: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
        samples: dict[str, dict[str, Any]] = {}
        for run in self.store.list():
            if str(run.get("project_id")) != project_id:
                continue
            for event in self.store.events(str(run["id"]), limit=3_000):
                event_type = str(event.get("type") or "")
                data = event.get("data") if isinstance(event.get("data"), dict) else {}
                text = ""
                if event_type == "review.sent_back":
                    text = str(data.get("message") or data.get("feedback") or run.get("feedback") or "")
                elif event_type == "check.completed":
                    try:
                        failed_check = int(data.get("returncode") or 0) != 0
                    except (TypeError, ValueError):
                        failed_check = False
                    command = str(data.get("command") or "").strip()
                    text = f"Run and fix `{command}` before review." if failed_check and command else ""
                elif event_type == "ci.failed":
                    text = str(data.get("summary") or "").strip()
                if len(text) < 12:
                    continue
                key = self._suggestion_key(text)
                sample = samples.setdefault(key, {"content": text[:2_000], "count": 0, "run_ids": []})
                if run["id"] not in sample["run_ids"]:
                    sample["count"] += 1
                    sample["run_ids"].append(run["id"])
        known = {self._suggestion_key(str(item.get("content") or "")) for item in (existing or [])}
        suggestions: list[dict[str, Any]] = []
        stop = {"this", "that", "with", "from", "before", "after", "review", "always", "should", "have"}
        for key, sample in samples.items():
            if sample["count"] < 2 or key in known:
                continue
            tokens = [token for token in re.findall(r"[a-z][a-z0-9_.-]{3,}", key) if token not in stop]
            folders = re.findall(r"(?:[A-Za-z0-9_.-]+/)+[A-Za-z0-9_.-]+", sample["content"])
            suggestions.append(
                {
                    "id": f"suggestion-{_digest(key)[:10]}",
                    "title": "Repeated project guidance",
                    "content": sample["content"],
                    "triggers": list(dict.fromkeys(tokens))[:5],
                    "folders": list(dict.fromkeys(folders))[:5],
                    "enabled": False,
                    "source": "history",
                    "status": "suggested",
                    "evidence_count": sample["count"],
                    "run_ids": sample["run_ids"][:5],
                }
            )
        return sorted(suggestions, key=lambda item: (-int(item["evidence_count"]), item["id"]))[:8]

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

    def snapshot(
        self,
        project: Mapping[str, Any],
        task: str,
        selected_skills: list[Mapping[str, Any]],
        selected_memory: list[Mapping[str, Any]],
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Freeze the exact project context and provenance sent to one run."""

        root = Path(str(project["path"])).resolve()
        bundle: list[dict[str, Any]] = []
        remaining_bytes = 64_000

        def capture(kind: str, title: str, path: str, reason: str, content: str, per_source_limit: int) -> None:
            nonlocal remaining_bytes
            if remaining_bytes <= 0 or not content:
                return
            encoded = content.encode("utf-8")[: min(remaining_bytes, per_source_limit)]
            clipped = encoded.decode("utf-8", errors="ignore")
            if not clipped:
                return
            size = len(clipped.encode("utf-8"))
            remaining_bytes -= size
            bundle.append(
                {
                    "kind": kind,
                    "title": title,
                    "path": path,
                    "reason": reason,
                    "content": clipped,
                    "sha256": _digest(clipped),
                    "bytes": size,
                }
            )

        profile = self.profile(str(project["id"]))
        profile_content = "\n\n".join(
            value
            for value in (
                f"Project brief:\n{profile['summary']}" if profile["summary"] else "",
                f"Operator notes:\n{profile['notes']}" if profile["notes"] else "",
            )
            if value
        )
        if profile_content:
            capture("project_profile", "Odysseus project brief", "odysseus://project-profile", "project-level operator context", profile_content, 8_000)
        for item in selected_memory:
            capture(
                "project_memory",
                str(item.get("title") or "Project memory"),
                f"odysseus://project-memory/{item.get('id')}",
                str(item.get("reason") or "matched task context"),
                str(item.get("content") or ""),
                6_000,
            )
        for relative in README_CANDIDATES:
            path = root / relative
            if path.is_file():
                content = _read_text(path, limit=20_000)
                if content:
                    capture("readme", relative, relative, "primary repository overview", content, 16_000)
                break
        instruction_paths = [root / relative for relative in INSTRUCTION_CANDIDATES]
        cursor_rules = root / ".cursor" / "rules"
        if cursor_rules.is_dir():
            instruction_paths.extend(sorted(cursor_rules.glob("*.md*"))[:12])
        for path in instruction_paths:
            if not path.is_file():
                continue
            content = _read_text(path, limit=16_000)
            if not content:
                continue
            relative = str(path.relative_to(root))
            capture("agent_instructions", relative, relative, "repository-authored agent instructions", content, 8_000)
        sources = [
            {key: item[key] for key in ("kind", "title", "path", "reason", "sha256", "bytes")}
            for item in bundle
        ]
        for skill in selected_skills:
            content = str(skill.get("content") or "")[:16_000]
            sources.append(
                {
                    "kind": "skill",
                    "title": str(skill.get("name") or "skill"),
                    "path": str(skill.get("relative_path") or ""),
                    "reason": str(skill.get("reason") or "selected for task"),
                    "sha256": _digest(content),
                    "bytes": len(content.encode("utf-8")),
                }
            )
        digest_material = [
            {"kind": item["kind"], "path": item["path"], "sha256": item["sha256"]}
            for item in sources
        ]
        receipt = {
            "version": "context-receipt-v1",
            "algorithm": "deterministic-project-context-v1",
            "created_at": now_iso(),
            "project_id": str(project["id"]),
            "task_sha256": _digest(task),
            "bundle_sha256": _stable_digest(digest_material),
            "source_count": len(sources),
            "sources": sources,
        }
        return bundle, receipt

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
