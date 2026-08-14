"""Portable, project-scoped engineering skill catalog and policy resolver."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping

from .events import now_iso


VALID_MODES = frozenset({"auto", "required", "disabled"})
VALID_TASK_MODES = frozenset({"auto", "manual", "none"})
SKILL_LOCATIONS = (".agents/skills", ".github/skills", ".claude/skills")
BUNDLED_SKILLS = Path(__file__).resolve().parent.parent / "skills"


def _frontmatter(value: str) -> tuple[dict[str, str], str]:
    if not value.startswith("---\n"):
        return {}, value
    end = value.find("\n---", 4)
    if end < 0:
        return {}, value
    metadata: dict[str, str] = {}
    for line in value[4:end].splitlines():
        if ":" not in line:
            continue
        key, raw = line.split(":", 1)
        metadata[key.strip()] = raw.strip().strip('"\'')
    return metadata, value[end + 4 :].lstrip()


def _tokens(value: str) -> set[str]:
    return {item for item in re.findall(r"[a-z0-9][a-z0-9+_.-]+", value.lower()) if len(item) > 2}


class SkillRegistry:
    def __init__(self, store: Any) -> None:
        self.store = store
        self.policy_dir = store.root / "project_skill_policies"
        self.policy_dir.mkdir(exist_ok=True)

    def _policy_path(self, project_id: str) -> Path:
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", project_id):
            raise ValueError("invalid project id")
        return self.policy_dir / f"{project_id}.json"

    @staticmethod
    def _parse_skill(path: Path, *, scope: str, root: Path) -> dict[str, Any] | None:
        try:
            content = path.read_text(encoding="utf-8")
        except OSError:
            return None
        metadata, body = _frontmatter(content)
        name = str(metadata.get("name") or path.parent.name).strip()
        description = str(metadata.get("description") or "").strip()
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,63}", name) or not description:
            return None
        triggers = [item.strip().lower() for item in str(metadata.get("triggers") or "").split(",") if item.strip()]
        return {
            "name": name,
            "description": description,
            "triggers": triggers,
            "scope": scope,
            "path": str(path),
            "relative_path": str(path.relative_to(root)),
            "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
            "content": content,
            "body": body,
            "preview": body[:2_000],
        }

    def discover(self, project: Mapping[str, Any]) -> list[dict[str, Any]]:
        found: dict[str, dict[str, Any]] = {}
        if BUNDLED_SKILLS.is_dir():
            for path in sorted(BUNDLED_SKILLS.glob("*/SKILL.md")):
                skill = self._parse_skill(path, scope="bundled", root=BUNDLED_SKILLS)
                if skill:
                    found[skill["name"]] = skill
        project_root = Path(str(project["path"])).resolve()
        for relative in SKILL_LOCATIONS:
            source = project_root / relative
            if not source.is_dir():
                continue
            for path in sorted(source.glob("*/SKILL.md")):
                skill = self._parse_skill(path, scope="project", root=project_root)
                if skill:
                    # Repository-local skills intentionally override the
                    # bundled catalog for this project only.
                    found[skill["name"]] = skill
        return sorted(found.values(), key=lambda item: (item["scope"] != "project", item["name"]))

    def policy(self, project_id: str) -> dict[str, str]:
        path = self._policy_path(project_id)
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            value = {}
        policies = value.get("policies") if isinstance(value, dict) else {}
        if not isinstance(policies, dict):
            return {}
        return {str(name): str(mode) for name, mode in policies.items() if str(mode) in VALID_MODES}

    def update_policy(self, project_id: str, changes: Mapping[str, Any]) -> dict[str, Any]:
        project = self.store.projects.get(project_id)
        known = {skill["name"] for skill in self.discover(project)}
        incoming = changes.get("policies") or {}
        if not isinstance(incoming, dict):
            raise ValueError("policies must be an object")
        current = self.policy(project_id)
        for name, mode in incoming.items():
            name, mode = str(name), str(mode)
            if name not in known:
                raise ValueError(f"unknown skill: {name}")
            if mode not in VALID_MODES:
                raise ValueError(f"invalid skill mode for {name}: {mode}")
            current[name] = mode
        value = {"policies": current, "updated_at": now_iso()}
        with self.store.locked():
            self.store._atomic_json(self._policy_path(project_id), value)
        return self.catalog(project_id)

    def catalog(self, project_id: str, *, include_content: bool = False) -> dict[str, Any]:
        project = self.store.projects.get(project_id)
        policy = self.policy(project_id)
        skills = []
        for skill in self.discover(project):
            item = dict(skill)
            item["mode"] = policy.get(skill["name"], "auto")
            if not include_content:
                item.pop("content", None)
                item.pop("body", None)
            skills.append(item)
        return {"project_id": project_id, "skills": skills, "updated_at": now_iso()}

    def select(
        self,
        project: Mapping[str, Any],
        task: str,
        *,
        task_mode: str = "auto",
        requested: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        if task_mode not in VALID_TASK_MODES:
            raise ValueError("skill mode must be auto, manual, or none")
        requested = list(dict.fromkeys(str(item) for item in (requested or [])))
        skills = self.discover(project)
        by_name = {skill["name"]: skill for skill in skills}
        unknown = set(requested) - set(by_name)
        if unknown:
            raise ValueError(f"unknown skills: {', '.join(sorted(unknown))}")
        policy = self.policy(str(project["id"]))
        selected: dict[str, dict[str, Any]] = {}
        for skill in skills:
            mode = policy.get(skill["name"], "auto")
            if mode == "required":
                selected[skill["name"]] = {**skill, "reason": "required by project policy", "policy": mode}
        if task_mode == "manual":
            for name in requested:
                if policy.get(name, "auto") == "disabled":
                    raise ValueError(f"skill is disabled for this project: {name}")
                selected[name] = {**by_name[name], "reason": "selected for this task", "policy": policy.get(name, "auto")}
        elif task_mode == "auto":
            task_tokens = _tokens(task)
            ranked: list[tuple[int, str, dict[str, Any]]] = []
            for skill in skills:
                if policy.get(skill["name"], "auto") != "auto":
                    continue
                trigger_tokens = _tokens(" ".join(skill.get("triggers") or []))
                score = len(task_tokens & trigger_tokens)
                if score:
                    ranked.append((score, skill["name"], skill))
            for score, name, skill in sorted(ranked, key=lambda item: (-item[0], item[1]))[:3]:
                selected[name] = {**skill, "reason": f"matched {score} task signal{'s' if score != 1 else ''}", "policy": "auto"}
        return [selected[name] for name in sorted(selected)]
