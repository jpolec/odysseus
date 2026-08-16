"""Portable, project-scoped engineering skill catalog and policy resolver."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping

from .events import now_iso
from .resources import resource_path


VALID_MODES = frozenset({"auto", "required", "disabled"})
VALID_TASK_MODES = frozenset({"auto", "manual", "none"})
SKILL_LOCATIONS = (".agents/skills", ".github/skills", ".claude/skills")
BUNDLED_SKILLS = resource_path("skills")
LOCAL_SKILL_NAME = re.compile(r"[a-z0-9][a-z0-9-]{1,63}")
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


def _frontmatter_value(value: str) -> str:
    """Keep generated single-line frontmatter inert and readable."""

    return re.sub(r"\s+", " ", value).strip().replace('"', "'")


class SkillRegistry:
    def __init__(self, store: Any) -> None:
        self.store = store
        self.policy_dir = store.root / "project_skill_policies"
        if not store.readonly:
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

    def create_local(self, project_id: str, request: Mapping[str, Any]) -> dict[str, Any]:
        """Create a repository-owned skill without accepting an arbitrary path."""

        if self.store.readonly:
            raise RuntimeError("state is read-only")
        project = self.store.projects.get(project_id)
        name = str(request.get("name") or "").strip().lower()
        description = _frontmatter_value(str(request.get("description") or ""))
        body = str(request.get("content") or "").strip()
        raw_triggers = request.get("triggers") or []
        if isinstance(raw_triggers, str):
            raw_triggers = [item.strip() for item in raw_triggers.split(",")]
        if not isinstance(raw_triggers, list) or not all(isinstance(item, str) for item in raw_triggers):
            raise ValueError("triggers must be a list of strings")
        triggers = [_frontmatter_value(item.lower()) for item in raw_triggers if item.strip()]
        if not LOCAL_SKILL_NAME.fullmatch(name):
            raise ValueError("skill name must be a lowercase slug, 2-64 characters")
        if not description:
            raise ValueError("skill description is required")
        if not body:
            raise ValueError("skill instructions are required")

        project_root = Path(str(project["path"])).resolve()
        target_dir = project_root / ".agents" / "skills" / name
        target = target_dir / "SKILL.md"
        if target.exists():
            raise ValueError(f"local skill already exists: {name}")
        content = (
            "---\n"
            f"name: {name}\n"
            f"description: {description}\n"
            f"triggers: {', '.join(triggers)}\n"
            "---\n\n"
            f"{body}\n"
        )
        target_dir.mkdir(parents=True, exist_ok=False)
        target.write_text(content, encoding="utf-8")
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
        if task_mode == "none":
            return []
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
            recommendation = self.recommend(str(project["id"]), task)
            for item in recommendation["recommendations"]:
                if not item["selected"] or item["name"] in selected:
                    continue
                skill = by_name[item["name"]]
                selected[item["name"]] = {
                    **skill,
                    "reason": "; ".join(item["reasons"]),
                    "policy": "auto",
                    "routing_score": item["score"],
                    "routing_algorithm": recommendation["algorithm"],
                    "signals": item["signals"],
                }
        return [selected[name] for name in sorted(selected)]

    def recommend(self, project_id: str, task: str) -> dict[str, Any]:
        project = self.store.projects.get(project_id)
        policy = self.policy(project_id)
        history = self.effectiveness(project_id)
        task_tokens = _tokens(task)
        ranked: list[dict[str, Any]] = []
        for skill in self.discover(project):
            mode = policy.get(skill["name"], "auto")
            if mode == "disabled":
                continue
            signals = sorted(task_tokens & _tokens(" ".join(skill.get("triggers") or [])))
            if mode != "required" and not signals:
                continue
            observed = history.get(skill["name"], self._empty_effectiveness())
            runs = int(observed.get("runs") or 0)
            success_rate = observed.get("success_rate")
            history_weight = min(runs / 8.0, 1.0)
            history_adjustment = 0.0
            reasons = ["required by project policy"] if mode == "required" else [f"matched task signals: {', '.join(signals)}"]
            if success_rate is not None and runs >= 2:
                history_adjustment = (float(success_rate) - 0.5) * 4.0 * history_weight
                reasons.append(f"{round(float(success_rate) * 100)}% success across {runs} observed runs")
            interventions = int(observed.get("interventions") or 0)
            intervention_penalty = min(interventions / max(runs, 1), 2.0) * history_weight
            if interventions and runs >= 2:
                reasons.append(f"{interventions} human intervention{'s' if interventions != 1 else ''} in history")
            score = (100.0 if mode == "required" else len(signals) * 10.0) + history_adjustment - intervention_penalty
            ranked.append(
                {
                    "name": skill["name"],
                    "description": skill["description"],
                    "scope": skill["scope"],
                    "policy": mode,
                    "signals": signals,
                    "score": round(score, 3),
                    "reasons": reasons,
                    "effectiveness": observed,
                }
            )
        ranked.sort(key=lambda item: (-float(item["score"]), item["name"]))
        automatic = 0
        for item in ranked:
            if item["policy"] == "required":
                item["selected"] = True
            elif automatic < 3:
                item["selected"] = True
                automatic += 1
            else:
                item["selected"] = False
        return {
            "project_id": project_id,
            "algorithm": "project-skill-router-v1",
            "task_sha256": hashlib.sha256(task.encode("utf-8")).hexdigest(),
            "recommendations": ranked,
        }
