"""Durable epics and dependency-aware task DAG scheduling."""

from __future__ import annotations

import json
import re
import secrets
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
EPIC_SCHEMA_VERSION = 3


class CycleError(ValueError):
    """Raised when an epic task graph contains a dependency cycle."""


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
        source_documents = [
            {
                key: source.get(key)
                for key in ("kind", "path", "title", "status", "sha256", "bytes", "content")
                if source.get(key) is not None
            }
            for source in raw_sources[:20]
        ]
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
            "plan": request.get("plan") if isinstance(request.get("plan"), dict) else None,
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
            checks = raw.get("checks") or []
            if not isinstance(checks, list) or not all(isinstance(item, str) for item in checks):
                raise ValueError(f"checks for {key} must be a list of commands")
            values.append(
                {
                    "task_key": key,
                    "title": str(raw.get("title") or task.splitlines()[0][:100]),
                    "task": task,
                    "project_path": str(raw.get("project_path") or ""),
                    "role": role,
                    "depends_on": list(dict.fromkeys(dependencies)),
                    "parallelizable": bool(raw.get("parallelizable", True)),
                    "lane": str(raw.get("lane") or ""),
                    "review_lane": str(raw.get("review_lane") or raw.get("lane") or ""),
                    "checks": list(checks),
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

    def refresh_all(self) -> list[str]:
        unblocked: list[str] = []
        for epic in self.list():
            if epic.get("status") in {"active", "failed"}:
                unblocked.extend(self.refresh_dag(str(epic["id"])))
        return unblocked

    def refresh_dag(self, epic_id: str) -> list[str]:
        epic = self.get(epic_id)
        runs = {str(run["id"]): run for run in self.runs(epic_id)}
        unblocked: list[str] = []
        for run_id, run in runs.items():
            if run.get("status") != "blocked":
                continue
            dependencies = [str(item) for item in run.get("depends_on") or []]
            dependency_runs = [runs.get(item) or self._optional_run(item) for item in dependencies]
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

        current = [self.store.get(run_id) for run_id in runs]
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
