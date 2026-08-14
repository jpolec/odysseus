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
SUCCESS_STATUSES = frozenset({"accepted", "pr_created", "completed"})
TERMINAL_STATUSES = SUCCESS_STATUSES | frozenset({"failed", "cancelled"})
INTERVENTION_EVENTS = frozenset(
    {"agent.question", "agent.permission_request", "agent.blocked", "agent.decision_required", "run.attention"}
)


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
        effectiveness = self.effectiveness(project_id)
        skills = []
        for skill in self.discover(project):
            item = dict(skill)
            item["mode"] = policy.get(skill["name"], "auto")
            item["effectiveness"] = effectiveness.get(skill["name"], self._empty_effectiveness())
            if not include_content:
                item.pop("content", None)
                item.pop("body", None)
            skills.append(item)
        return {"project_id": project_id, "skills": skills, "updated_at": now_iso()}

    @staticmethod
    def _empty_effectiveness() -> dict[str, Any]:
        return {
            "runs": 0,
            "terminal_runs": 0,
            "successful_runs": 0,
            "success_rate": None,
            "avg_tokens": 0,
            "avg_cost_usd": 0.0,
            "interventions": 0,
        }

    def effectiveness(self, project_id: str) -> dict[str, dict[str, Any]]:
        self.store.projects.get(project_id)
        values: dict[str, dict[str, Any]] = {}
        for run in self.store.list():
            if str(run.get("project_id")) != project_id:
                continue
            selected = {
                str(item.get("name"))
                for item in (run.get("skills_selected") or [])
                if isinstance(item, dict) and item.get("name")
            }
            if not selected:
                continue
            status = str(run.get("status") or "")
            metrics = run.get("metrics") if isinstance(run.get("metrics"), dict) else {}
            tokens = int(metrics.get("input_tokens") or 0) + int(metrics.get("output_tokens") or 0)
            try:
                cost = float(metrics.get("cost_usd") or 0.0)
            except (TypeError, ValueError):
                cost = 0.0
            interventions = sum(
                1 for event in self.store.events(str(run["id"]), limit=5_000) if event.get("type") in INTERVENTION_EVENTS
            )
            for name in selected:
                item = values.setdefault(name, {**self._empty_effectiveness(), "total_tokens": 0, "total_cost_usd": 0.0})
                item["runs"] += 1
                item["total_tokens"] += tokens
                item["total_cost_usd"] += cost
                item["interventions"] += interventions
                if status in TERMINAL_STATUSES:
                    item["terminal_runs"] += 1
                if status in SUCCESS_STATUSES:
                    item["successful_runs"] += 1
        for item in values.values():
            runs = max(1, int(item["runs"]))
            terminal = int(item["terminal_runs"])
            item["avg_tokens"] = round(int(item.pop("total_tokens")) / runs)
            item["avg_cost_usd"] = round(float(item.pop("total_cost_usd")) / runs, 4)
            item["success_rate"] = round(int(item["successful_runs"]) / terminal, 3) if terminal else None
        return values

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
