"""Durable epics and dependency-aware task DAG scheduling."""

from __future__ import annotations

import hashlib
import json
import re
import secrets
from pathlib import Path
from typing import TYPE_CHECKING, Any, Mapping

from .events import now_iso

if TYPE_CHECKING:
    from .store import RunStore


EPIC_ID_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
VALID_ROLES = frozenset({"planner", "implementer", "reviewer"})
DEPENDENCY_MET_STATUSES = frozenset({"accepted", "pr_created"})
DEPENDENCY_FAILED_STATUSES = frozenset({"failed", "cancelled"})
EPIC_FINAL_STATUSES = DEPENDENCY_MET_STATUSES | DEPENDENCY_FAILED_STATUSES
ACTIVE_RUN_STATUSES = frozenset(
    {"starting", "running", "checking", "reviewing", "cancelling", "publishing"}
)
EPIC_SCHEMA_VERSION = 4
ESTIMATE_CONFIDENCE = frozenset({"low", "medium", "high", "unknown"})
EXECUTION_MODES = frozenset({"auto", "override"})


class CycleError(ValueError):
    """Raised when an epic task graph contains a dependency cycle."""


def _digest(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _source_sections(content: str, *, start: int = 1) -> list[dict[str, Any]]:
    """Split a source into stable, reviewable paragraph references."""

    sections: list[dict[str, Any]] = []
    buffer: list[str] = []
    first_line = 1
    lines = content.splitlines()

    def flush(end_line: int) -> None:
        nonlocal buffer, first_line
        text = "\n".join(buffer).strip()
        if text:
            ref = f"S{start + len(sections)}"
            sections.append(
                {
                    "ref": ref,
                    "text": text[:12_000],
                    "start_line": first_line,
                    "end_line": max(first_line, end_line),
                    "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                }
            )
        buffer = []

    for index, line in enumerate(lines, start=1):
        if not line.strip():
            flush(index - 1)
            first_line = index + 1
            continue
        if not buffer:
            first_line = index
        buffer.append(line)
        if len(sections) >= 199:
            break
    flush(len(lines))
    return sections[:200]


def _normalize_sources(raw_sources: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    values: list[dict[str, Any]] = []
    next_ref = 1
    for raw in raw_sources[:20]:
        source = {
            key: raw.get(key)
            for key in ("kind", "path", "title", "status", "sha256", "bytes", "content", "frozen_at")
            if raw.get(key) is not None
        }
        content = str(source.get("content") or "")[:80_000]
        source["kind"] = str(source.get("kind") or "source")
        source["path"] = str(source.get("path") or f"odysseus://source/{len(values) + 1}")
        source["title"] = str(source.get("title") or source["path"])
        source["content"] = content
        encoded = content.encode("utf-8")
        # Content is the source of truth whenever it is present. Never bind a
        # SourceVersion to a caller-supplied digest that does not match its
        # frozen bytes.
        source["sha256"] = hashlib.sha256(encoded).hexdigest() if content else str(
            source.get("sha256") or hashlib.sha256(encoded).hexdigest()
        )
        source["bytes"] = len(encoded) if content else int(source.get("bytes") or 0)
        source["version_id"] = f"source:{source['sha256'][:16]}"
        source["frozen_at"] = str(source.get("frozen_at") or now_iso())
        source["sections"] = _source_sections(content, start=next_ref)
        next_ref += len(source["sections"])
        values.append(source)
    return values


def _string_list(value: Any, *, field: str) -> list[str]:
    if value in (None, ""):
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{field} must be a list of strings")
    return list(dict.fromkeys(item.strip() for item in value if item.strip()))


def _execution_profile(raw: Any, *, lane: str, review_lane: str, role: str) -> dict[str, Any]:
    value = dict(raw) if isinstance(raw, Mapping) else {}
    mode = str(value.get("mode") or ("override" if lane else "auto"))
    if mode not in EXECUTION_MODES:
        raise ValueError("execution profile mode must be auto or override")
    skills = _string_list(value.get("skills") or [], field="execution profile skills")
    return {
        "version": "execution-profile-v1",
        "mode": mode,
        "harness": str(value.get("harness") or lane or "auto")[:80],
        "model": str(value.get("model") or "")[:120],
        "skills": skills,
        "environment": str(value.get("environment") or "isolated_worktree")[:80],
        "policy": str(value.get("policy") or "standard")[:80],
        "review_policy": str(value.get("review_policy") or ("independent_provider" if role == "reviewer" else "independent_review"))[:80],
        "review_lane": str(value.get("review_lane") or review_lane)[:80],
        "review_model": str(value.get("review_model") or "")[:120],
        "reason": str(value.get("reason") or ("operator override" if mode == "override" else "Auto will select from repository evidence"))[:500],
    }


def _estimate(raw: Any) -> dict[str, Any]:
    value = dict(raw) if isinstance(raw, Mapping) else {}

    def number(name: str) -> float | None:
        if value.get(name) in (None, ""):
            return None
        try:
            return max(0.0, float(value[name]))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"estimate {name} must be numeric") from exc

    confidence = str(value.get("confidence") or "unknown").lower()
    if confidence not in ESTIMATE_CONFIDENCE:
        raise ValueError("estimate confidence must be low, medium, high, or unknown")
    cost_min, cost_max = number("cost_usd_min"), number("cost_usd_max")
    duration_min, duration_max = number("duration_minutes_min"), number("duration_minutes_max")
    if cost_min is not None and cost_max is not None and cost_min > cost_max:
        raise ValueError("estimate cost range is reversed")
    if duration_min is not None and duration_max is not None and duration_min > duration_max:
        raise ValueError("estimate duration range is reversed")
    return {
        "version": "task-estimate-v1",
        "cost_usd_min": cost_min,
        "cost_usd_max": cost_max,
        "duration_minutes_min": duration_min,
        "duration_minutes_max": duration_max,
        "confidence": confidence,
        "basis": str(value.get("basis") or "No calibrated repository estimate yet")[:500],
    }


class EpicStore:
    """Persist epic proposals and materialize approved tasks as a safe DAG."""

    def __init__(self, store: RunStore) -> None:
        self.store = store
        self.epics_dir = store.root / "epics"
        if not store.readonly:
            self.epics_dir.mkdir(exist_ok=True)

    def _path(self, epic_id: str):  # noqa: ANN202 - Path type follows store root
        if not EPIC_ID_RE.fullmatch(epic_id):
            raise ValueError("invalid epic id")
        return self.epics_dir / f"{epic_id}.json"

    def create(self, request: Mapping[str, Any]) -> dict[str, Any]:
        title = str(request.get("title") or "").strip()
        if not title:
            raise ValueError("epic title is required")
        project_path = str(request.get("project_path") or "").strip()
        project_id = ""
        if project_path:
            project = self.store.projects.upsert(project_path)
            project_path = str(project["path"])
            project_id = str(project["id"])
        stamp = now_iso()
        compact = stamp.replace("-", "").replace(":", "").replace("T", "-")[:15]
        epic_id = f"epic-{compact}-{secrets.token_hex(2)}"
        raw_sources = request.get("source_documents") or []
        if not isinstance(raw_sources, list) or not all(isinstance(item, dict) for item in raw_sources):
            raise ValueError("source_documents must be a list of objects")
        source_documents = _normalize_sources(raw_sources)
        raw_plan = request.get("plan") if isinstance(request.get("plan"), dict) else None
        epic = {
            "schema_version": EPIC_SCHEMA_VERSION,
            "id": epic_id,
            "title": title,
            "description": str(request.get("description") or request.get("requirement") or "").strip(),
            "project_path": project_path,
            "project_id": project_id,
            "status": str(request.get("status") or "planning"),
            "planner_lane": str(request.get("planner_lane") or ""),
            "planner_session_id": "",
            "planner_events": [],
            "planner_error": "",
            "plan": raw_plan,
            "plan_version": None,
            "plan_history": [],
            "intake": request.get("intake") if isinstance(request.get("intake"), dict) else {},
            "gate_policy": str(request.get("gate_policy") or "human_review"),
            "source_documents": source_documents,
            "approved": False,
            "task_keys": [],
            "run_ids": [],
            "task_run_ids": {},
            "created_at": stamp,
            "updated_at": stamp,
            "evidence_class": str(request.get("evidence_class") or "observed"),
            "release": str(request.get("release") or ""),
        }
        with self.store.locked():
            self.store._atomic_json(self._path(epic_id), epic)
        return epic

    def get(self, epic_id: str) -> dict[str, Any]:
        path = self._path(epic_id)
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise KeyError(epic_id) from exc
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"corrupt epic record: {path}") from exc
        if not isinstance(value, dict):
            raise RuntimeError(f"invalid epic record: {path}")
        schema_version = int(value.get("schema_version", 0) or 0)
        if schema_version > EPIC_SCHEMA_VERSION:
            raise RuntimeError(
                f"epic record {path} uses schema {schema_version}; "
                f"this Odysseus supports up to {EPIC_SCHEMA_VERSION}"
            )
        if schema_version < EPIC_SCHEMA_VERSION:
            value.setdefault("evidence_class", "unclassified")
            value.setdefault("release", "")
            value.setdefault("source_documents", [])
            value.setdefault("intake", {})
            value.setdefault("gate_policy", "human_review")
            value.setdefault("plan_version", None)
            value.setdefault("plan_history", [])
            value["source_documents"] = _normalize_sources(value.get("source_documents") or [])
        return value

    def list(self) -> list[dict[str, Any]]:
        values: list[dict[str, Any]] = []
        for path in self.epics_dir.glob("*.json"):
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(value, dict):
                schema_version = int(value.get("schema_version", 0) or 0)
                if schema_version < EPIC_SCHEMA_VERSION:
                    value.setdefault("evidence_class", "unclassified")
                    value.setdefault("release", "")
                    value.setdefault("source_documents", [])
                    value.setdefault("intake", {})
                    value.setdefault("gate_policy", "human_review")
                    value.setdefault("plan_version", None)
                    value.setdefault("plan_history", [])
                    value["source_documents"] = _normalize_sources(value.get("source_documents") or [])
                values.append(value)
        return sorted(values, key=lambda item: str(item.get("created_at", "")), reverse=True)

    def update(self, epic_id: str, **changes: Any) -> dict[str, Any]:
        with self.store.locked():
            epic = self.get(epic_id)
            epic.update(changes)
            epic["updated_at"] = now_iso()
            self.store._atomic_json(self._path(epic_id), epic)
        return epic

    def runs(self, epic_id: str) -> list[dict[str, Any]]:
        epic = self.get(epic_id)
        values: list[dict[str, Any]] = []
        for run_id in epic.get("run_ids") or []:
            try:
                values.append(self.store.get(str(run_id)))
            except KeyError:
                continue
        return values

    def save_plan(self, epic_id: str, plan: Mapping[str, Any]) -> dict[str, Any]:
        """Persist an editable draft as a new immutable plan version."""

        epic = self.get(epic_id)
        if epic.get("approved") or epic.get("status") not in {"planning", "proposed"}:
            raise ValueError("only an unapproved plan can be edited")
        raw_tasks = plan.get("tasks")
        if not isinstance(raw_tasks, list) or not raw_tasks:
            raise ValueError("plan requires at least one task")
        normalized = self._normalize_tasks(raw_tasks)
        valid_refs = {
            str(section.get("ref") or "")
            for source in epic.get("source_documents") or []
            for section in source.get("sections") or []
        }
        unknown_refs = sorted({ref for task in normalized for ref in task.get("source_refs") or []} - valid_refs)
        if unknown_refs:
            raise ValueError(f"tasks reference unknown source sections: {', '.join(unknown_refs)}")
        graph = {str(item["task_key"]): list(item["depends_on"]) for item in normalized}
        unknown = sorted({dependency for dependencies in graph.values() for dependency in dependencies} - set(graph))
        if unknown:
            raise ValueError(f"tasks depend on unknown keys: {', '.join(unknown)}")
        self._check_cycles(graph)

        previous = epic.get("plan_version") if isinstance(epic.get("plan_version"), dict) else None
        number = int((previous or {}).get("number") or 0) + 1
        frozen_plan = {
            "summary": str(plan.get("summary") or "").strip()[:4_000],
            "constraints": _string_list(plan.get("constraints") or [], field="plan constraints"),
            "tasks": normalized,
        }
        source_versions = [
            {
                "path": str(source.get("path") or ""),
                "version_id": str(source.get("version_id") or ""),
                "sha256": str(source.get("sha256") or ""),
            }
            for source in epic.get("source_documents") or []
        ]
        contract_hash = _digest({"plan": frozen_plan, "source_versions": source_versions})
        version = {
            "schema": "plan-version-v1",
            "number": number,
            "id": f"plan-v{number}-{contract_hash[:12]}",
            "sha256": contract_hash,
            "plan_sha256": _digest(frozen_plan),
            "source_versions": source_versions,
            "source_hashes": [item["sha256"] for item in source_versions],
            "status": "draft",
            "created_at": now_iso(),
        }
        history = list(epic.get("plan_history") or [])
        if previous and isinstance(epic.get("plan"), dict):
            history.append({"version": previous, "plan": epic["plan"]})
        return self.update(
            epic_id,
            schema_version=EPIC_SCHEMA_VERSION,
            status="proposed",
            plan=frozen_plan,
            plan_version=version,
            plan_history=history[-20:],
        )

    def replace_sources(self, epic_id: str, sources: list[Mapping[str, Any]]) -> dict[str, Any]:
        epic = self.get(epic_id)
        if epic.get("approved"):
            raise ValueError("approved source versions are immutable")
        return self.update(epic_id, source_documents=_normalize_sources(sources))

    def refresh_local_sources(self, epic_id: str) -> dict[str, Any]:
        """Explicitly freeze the current bytes of local sources into a new source version."""

        epic = self.get(epic_id)
        if epic.get("approved"):
            raise ValueError("approved source versions are immutable")
        refreshed: list[dict[str, Any]] = []
        for source in epic.get("source_documents") or []:
            path_value = str(source.get("path") or "")
            if not path_value or path_value.startswith(("http://", "https://", "odysseus://")):
                refreshed.append(dict(source))
                continue
            path = Path(path_value)
            if not path.is_absolute() and epic.get("project_path"):
                path = Path(str(epic["project_path"])) / path
            try:
                content = path.read_text(encoding="utf-8")[:80_000]
            except OSError as exc:
                raise ValueError(f"cannot refresh missing source: {path_value}") from exc
            refreshed.append(
                {
                    **dict(source),
                    "content": content,
                    "sha256": "",
                    "bytes": 0,
                    "sections": [],
                    "frozen_at": now_iso(),
                }
            )
        return self.replace_sources(epic_id, refreshed)

    def source_impact(self, epic_id: str) -> dict[str, Any]:
        """Compare local sources with their frozen sections and identify affected nodes."""

        epic = self.get(epic_id)
        changed_refs: set[str] = set()
        source_changed = False
        sources: list[dict[str, Any]] = []
        for source in epic.get("source_documents") or []:
            item = {
                "path": str(source.get("path") or ""),
                "title": str(source.get("title") or ""),
                "status": "current",
                "changed_refs": [],
            }
            path_value = str(source.get("path") or "")
            if not path_value or path_value.startswith(("http://", "https://", "odysseus://")):
                item["status"] = "frozen"
                sources.append(item)
                continue
            path = Path(path_value)
            if not path.is_absolute() and epic.get("project_path"):
                path = Path(str(epic["project_path"])) / path
            try:
                content = path.read_text(encoding="utf-8")[:80_000]
            except OSError:
                source_changed = True
                item["status"] = "missing"
                refs = [str(section.get("ref") or "") for section in source.get("sections") or []]
                changed_refs.update(refs)
                item["changed_refs"] = refs
                sources.append(item)
                continue
            if hashlib.sha256(content.encode("utf-8")).hexdigest() == str(source.get("sha256") or ""):
                sources.append(item)
                continue
            source_changed = True
            item["status"] = "changed"
            old_sections = source.get("sections") or []
            current_sections = _source_sections(content, start=int(str((old_sections or [{"ref": "S1"}])[0].get("ref") or "S1")[1:] or 1))
            current_hashes = {str(section.get("ref")): str(section.get("sha256")) for section in current_sections}
            refs = [
                str(section.get("ref") or "")
                for section in old_sections
                if current_hashes.get(str(section.get("ref") or "")) != str(section.get("sha256") or "")
            ]
            changed_refs.update(refs)
            item["changed_refs"] = refs
            sources.append(item)

        tasks = ((epic.get("plan") or {}).get("tasks") or []) if isinstance(epic.get("plan"), dict) else []
        affected = sorted(
            str(task.get("task_key"))
            for task in tasks
            if set(str(ref) for ref in task.get("source_refs") or []) & changed_refs
        )
        return {
            "status": "changed" if source_changed else "current",
            "changed_refs": sorted(changed_refs),
            "affected_task_keys": affected,
            "requires_reapproval": bool(affected),
            "sources": sources,
        }

    def create_task_batch(
        self,
        epic_id: str,
        tasks: list[Mapping[str, Any]],
    ) -> dict[str, str]:
        """Validate a complete graph, then create initially inert task records."""

        if not tasks:
            raise ValueError("at least one task is required")
        if len(tasks) > 100:
            raise ValueError("an epic can add at most 100 tasks at once")
        epic = self.get(epic_id)
        existing_runs = self.runs(epic_id)
        existing_by_key = {
            str(run.get("task_key")): run
            for run in existing_runs
            if str(run.get("task_key") or "")
        }
        normalized = self._normalize_tasks(tasks)
        new_keys = [str(item["task_key"]) for item in normalized]
        overlap = set(new_keys) & set(existing_by_key)
        if overlap:
            raise ValueError(f"task keys already exist in epic: {', '.join(sorted(overlap))}")

        graph: dict[str, list[str]] = {
            key: [str(item) for item in run.get("dependency_keys") or []]
            for key, run in existing_by_key.items()
        }
        graph.update({str(item["task_key"]): list(item["depends_on"]) for item in normalized})
        known = set(graph)
        unknown = sorted({dependency for dependencies in graph.values() for dependency in dependencies} - known)
        if unknown:
            raise ValueError(f"tasks depend on unknown keys: {', '.join(unknown)}")
        self._check_cycles(graph)

        blocks_by_key: dict[str, list[str]] = {key: [] for key in graph}
        for key, dependencies in graph.items():
            for dependency in dependencies:
                blocks_by_key[dependency].append(key)

        # Every new run starts blocked, including roots. This closes the race in
        # which the live scheduler could claim a root before all key->id edges
        # and the epic record were durably written.
        created: dict[str, str] = {}
        try:
            for spec in normalized:
                profile = spec.get("execution_profile") if isinstance(spec.get("execution_profile"), dict) else {}
                version = epic.get("plan_version") if isinstance(epic.get("plan_version"), dict) else {}
                request = {
                    **spec,
                    "project_path": spec.get("project_path") or epic.get("project_path"),
                    "epic_id": epic_id,
                    "depends_on": [],
                    "dependency_keys": list(spec["depends_on"]),
                    "blocks": [],
                    "block_keys": blocks_by_key[str(spec["task_key"])],
                    "status": "blocked",
                    "blocked_reason": "materializing approved task graph",
                    "origin": "planner",
                    "source_documents": list(epic.get("source_documents") or []),
                    "evidence_class": str(epic.get("evidence_class") or "unclassified"),
                    "release": str(epic.get("release") or ""),
                    "plan_version_id": str(version.get("id") or ""),
                    "plan_version_sha256": str(version.get("sha256") or ""),
                    "source_version_hashes": list(version.get("source_hashes") or []),
                    "skills": list(profile.get("skills") or []),
                    "skill_mode": "manual" if profile.get("skills") else "auto",
                    "auto_route": str(profile.get("mode") or "auto") == "auto",
                }
                if request.get("max_retries") is None:
                    request.pop("max_retries", None)
                run = self.store.create(
                    request
                )
                created[str(spec["task_key"])] = str(run["id"])
        except Exception:
            self.update(epic_id, status="materialization_failed")
            raise

        all_ids = {key: str(run["id"]) for key, run in existing_by_key.items()}
        all_ids.update(created)
        for spec in normalized:
            key = str(spec["task_key"])
            dependencies = [all_ids[item] for item in spec["depends_on"]]
            blocked = [all_ids[item] for item in blocks_by_key[key]]
            status = "blocked" if dependencies else "queued"
            reason = (
                f"waiting on dependencies: {', '.join(spec['depends_on'])}"
                if dependencies
                else ""
            )
            self.store.update(
                created[key],
                depends_on=dependencies,
                blocks=blocked,
                status=status,
                blocked_reason=reason,
            )
            self.store.append_event(
                created[key],
                "epic.task_created",
                "odysseus",
                {
                    "epic_id": epic_id,
                    "task_key": key,
                    "dependency_keys": list(spec["depends_on"]),
                },
            )
            self.store.append_event(
                created[key],
                "run.queued" if status == "queued" else "dag.blocked",
                "odysseus",
                {"title": spec["title"]} if status == "queued" else {"reason": reason},
            )

        # A later batch may add downstream tasks to existing roots.
        for key, run in existing_by_key.items():
            self.store.update(
                str(run["id"]),
                blocks=[all_ids[item] for item in blocks_by_key[key]],
                block_keys=blocks_by_key[key],
            )

        task_keys = list(existing_by_key) + new_keys
        run_ids = [all_ids[key] for key in task_keys]
        mapping = {key: all_ids[key] for key in task_keys}
        self.update(
            epic_id,
            status="active",
            approved=True,
            task_keys=task_keys,
            run_ids=run_ids,
            task_run_ids=mapping,
        )
        first = created[new_keys[0]]
        self.store.append_event(
            first,
            "epic.activated",
            "odysseus",
            {"epic_id": epic_id, "task_keys": task_keys},
        )
        return created

    @staticmethod
    def _normalize_tasks(tasks: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
        values: list[dict[str, Any]] = []
        seen: set[str] = set()
        for raw in tasks:
            key = str(raw.get("task_key") or "").strip()
            task = str(raw.get("task") or "").strip()
            if not key or not task:
                raise ValueError("every epic task requires task_key and task")
            if not re.fullmatch(r"[A-Za-z0-9_.-]+", key):
                raise ValueError(f"invalid task key: {key}")
            if key in seen:
                raise ValueError(f"duplicate task key: {key}")
            seen.add(key)
            role = str(raw.get("role") or "implementer")
            if role not in VALID_ROLES:
                raise ValueError(f"invalid role {role!r}; expected planner, implementer, or reviewer")
            dependencies = raw.get("depends_on") or []
            if not isinstance(dependencies, list) or not all(isinstance(item, str) for item in dependencies):
                raise ValueError(f"depends_on for {key} must be a list of task keys")
            checks = _string_list(raw.get("checks") or [], field=f"checks for {key}")
            source_refs = _string_list(raw.get("source_refs") or [], field=f"source_refs for {key}")
            acceptance = _string_list(raw.get("acceptance_criteria") or [], field=f"acceptance criteria for {key}")
            evidence = _string_list(raw.get("required_evidence") or checks, field=f"required evidence for {key}")
            lane = str(raw.get("lane") or "")
            review_lane = str(raw.get("review_lane") or lane)
            profile = _execution_profile(
                raw.get("execution_profile"), lane=lane, review_lane=review_lane, role=role
            )
            if profile["mode"] == "override" and profile["harness"] not in {"", "auto"}:
                lane = str(profile["harness"])
            selected_review_lane = str(profile.get("review_lane") or "")
            review_lane = str(
                review_lane or lane
                if selected_review_lane in {"", "auto"}
                else selected_review_lane
            )
            values.append(
                {
                    "task_key": key,
                    "title": str(raw.get("title") or task.splitlines()[0][:100]),
                    "task": task,
                    "project_path": str(raw.get("project_path") or ""),
                    "role": role,
                    "outcome": str(raw.get("outcome") or raw.get("intended_outcome") or task.splitlines()[0])[:2_000],
                    "source_refs": source_refs,
                    "acceptance_criteria": acceptance,
                    "required_evidence": evidence,
                    "depends_on": list(dict.fromkeys(dependencies)),
                    "parallelizable": bool(raw.get("parallelizable", True)),
                    "lane": lane,
                    "review_lane": review_lane,
                    "checks": checks,
                    "execution_profile": profile,
                    "estimate": _estimate(raw.get("estimate")),
                    "max_retries": raw.get("max_retries"),
                }
            )
        return values

    @staticmethod
    def _check_cycles(graph: Mapping[str, list[str]]) -> None:
        state = {key: 0 for key in graph}
        path: list[str] = []

        def visit(key: str) -> None:
            state[key] = 1
            path.append(key)
            for dependency in graph[key]:
                if state[dependency] == 1:
                    start = path.index(dependency)
                    raise CycleError("dependency cycle: " + " -> ".join(path[start:] + [dependency]))
                if state[dependency] == 0:
                    visit(dependency)
            path.pop()
            state[key] = 2

        for key in graph:
            if state[key] == 0:
                visit(key)

    def refresh_all(self, *, runs: list[Mapping[str, Any]] | None = None) -> list[str]:
        unblocked: list[str] = []
        for epic in self.list():
            if epic.get("status") in {"active", "failed"}:
                unblocked.extend(self.refresh_dag(str(epic["id"]), runs=runs))
        return unblocked

    def refresh_dag(
        self,
        epic_id: str,
        *,
        runs: list[Mapping[str, Any]] | None = None,
    ) -> list[str]:
        epic = self.get(epic_id)
        if runs is None:
            epic_runs = self.runs(epic_id)
        else:
            run_ids = {str(value) for value in epic.get("run_ids") or []}
            epic_runs = [dict(run) for run in runs if str(run.get("id") or "") in run_ids]
        runs_by_id = {str(run["id"]): run for run in epic_runs}
        unblocked: list[str] = []
        for run_id, run in runs_by_id.items():
            if run.get("status") != "blocked":
                continue
            dependencies = [str(item) for item in run.get("depends_on") or []]
            dependency_runs = [runs_by_id.get(item) or self._optional_run(item) for item in dependencies]
            missing = [dependencies[index] for index, value in enumerate(dependency_runs) if value is None]
            failed = [
                str(value["id"])
                for value in dependency_runs
                if value and value.get("status") in DEPENDENCY_FAILED_STATUSES
            ]
            met = [
                str(value["id"])
                for value in dependency_runs
                if value and value.get("status") in DEPENDENCY_MET_STATUSES
            ]
            recorded = set(str(item) for item in run.get("dependencies_met") or [])
            for dependency_id in met:
                if dependency_id not in recorded:
                    self.store.append_event(
                        run_id,
                        "dag.dependency_met",
                        "odysseus",
                        {"dependency_run_id": dependency_id},
                    )
            if set(met) != recorded:
                self.store.update(run_id, dependencies_met=met)
            if failed or missing:
                reason = (
                    f"dependency failed or cancelled: {', '.join(failed)}"
                    if failed
                    else f"dependency record missing: {', '.join(missing)}"
                )
                if reason != str(run.get("blocked_reason") or ""):
                    self.store.update(run_id, blocked_reason=reason)
                    self.store.append_event(
                        run_id,
                        "dag.blocked",
                        "odysseus",
                        {"reason": reason, "failed_dependencies": failed, "missing_dependencies": missing},
                    )
                continue
            if len(met) == len(dependencies):
                self.store.update(run_id, status="queued", blocked_reason="")
                self.store.append_event(run_id, "dag.unblocked", "odysseus", {"dependencies": met})
                self.store.append_event(run_id, "run.queued", "odysseus", {"reason": "dependencies_complete"})
                unblocked.append(run_id)

        current = (
            [self.store.get(run_id) for run_id in runs_by_id]
            if runs is None
            else [dict(run) for run in runs_by_id.values()]
        )
        if current and all(run.get("status") in EPIC_FINAL_STATUSES for run in current):
            status = "failed" if any(run.get("status") in DEPENDENCY_FAILED_STATUSES for run in current) else "completed"
            if epic.get("status") != status:
                self.update(epic_id, status=status)
                self.store.append_event(
                    str(current[0]["id"]),
                    "epic.completed" if status == "completed" else "epic.failed",
                    "odysseus",
                    {"epic_id": epic_id, "status": status},
                )
        return unblocked

    def _optional_run(self, run_id: str) -> dict[str, Any] | None:
        try:
            return self.store.get(run_id)
        except KeyError:
            return None

    def can_start(self, run: Mapping[str, Any]) -> bool:
        if run.get("status") != "queued":
            return False
        dependencies = [self._optional_run(str(item)) for item in run.get("depends_on") or []]
        if any(value is None or value.get("status") not in DEPENDENCY_MET_STATUSES for value in dependencies):
            return False
        epic_id = str(run.get("epic_id") or "")
        if not epic_id:
            return True
        siblings = [item for item in self.runs(epic_id) if item.get("id") != run.get("id")]
        active = [item for item in siblings if item.get("status") in ACTIVE_RUN_STATUSES]
        if not run.get("parallelizable", True) and active:
            return False
        if any(not item.get("parallelizable", True) for item in active):
            return False
        return True
