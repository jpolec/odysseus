"""Read-only requirement decomposition into an operator-approved task DAG."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from .epics import EpicStore, VALID_ROLES
from .events import now_iso
from .runners import AgentRunner, ProcessResult


PLAN_MARKER = "ODYSSEUS_PLAN:"


class EpicPlanner:
    """Keep planning separate from implementation and require explicit approval."""

    def __init__(
        self,
        store: Any,
        *,
        agent_runner: AgentRunner | None = None,
    ) -> None:
        self.store = store
        self.epics: EpicStore = store.epics
        self.agent_runner = agent_runner or AgentRunner(store.config().get("lanes", {}))

    def plan(
        self,
        requirement: str,
        project_path: str | Path,
        *,
        lane: str = "",
        title: str = "",
        default_task_lane: str = "",
        default_review_lane: str = "",
        checks: list[str] | None = None,
        source_documents: list[Mapping[str, Any]] | None = None,
        source_kind: str = "user_request",
    ) -> dict[str, Any]:
        requirement = requirement.strip()
        if not requirement:
            raise ValueError("epic requirement is required")
        project = Path(project_path).expanduser().resolve()
        if not project.is_dir():
            raise ValueError(f"project directory does not exist: {project}")
        config = self.store.config()
        planner_lane = lane or str(config.get("planner_lane") or config["default_lane"])
        implementation_lane = default_task_lane or str(config["default_lane"])
        reviewer_lane = default_review_lane or str(config.get("review_lane") or implementation_lane)
        sources = list(source_documents or [])
        if not sources:
            sources = [
                {
                    "kind": source_kind or "user_request",
                    "path": "odysseus://user-request",
                    "title": title.strip() or "Submitted requirement",
                    "content": requirement,
                }
            ]
        epic = self.epics.create(
            {
                "title": title.strip() or requirement.splitlines()[0][:100],
                "description": requirement,
                "project_path": str(project),
                "planner_lane": planner_lane,
                "status": "planning",
                "source_documents": sources,
            }
        )
        planner_events: list[dict[str, Any]] = []

        def emit(event_type: str, source: str, data: Mapping[str, Any]) -> None:
            if len(planner_events) < 500:
                planner_events.append(
                    {"type": event_type, "source": source, "data": dict(data)}
                )

        result = self.agent_runner.run(
            planner_lane,
            project,
            self._prompt(
                requirement,
                implementation_lane,
                reviewer_lane,
                checks or [],
                epic.get("source_documents") or [],
            ),
            review=True,
            emit=emit,
            cancelled=lambda: False,
            phase="planner",
        )
        if result.returncode != 0:
            self.epics.update(
                epic["id"],
                status="planning_failed",
                planner_error=result.output[-20_000:],
                planner_events=planner_events,
            )
            raise RuntimeError(f"planner process exited with code {result.returncode}")
        proposal = self.parse_proposal(
            result,
            project_path=str(project),
            default_lane=implementation_lane,
            default_review_lane=reviewer_lane,
            default_checks=checks or [],
        )
        self.epics.update(
            epic["id"], planner_session_id=result.session_id, planner_events=planner_events, planner_error=""
        )
        return self.epics.save_plan(epic["id"], proposal)

    def approve(self, epic_id: str) -> dict[str, Any]:
        epic = self.epics.get(epic_id)
        if epic.get("status") != "proposed":
            raise ValueError("only a proposed epic can be approved")
        plan = epic.get("plan")
        if not isinstance(plan, dict) or not isinstance(plan.get("tasks"), list):
            raise ValueError("epic has no valid task proposal")
        impact = self.epics.source_impact(epic_id)
        if impact["requires_reapproval"]:
            affected = ", ".join(impact["affected_task_keys"])
            raise ValueError(f"source changed; review affected tasks before approval: {affected}")
        version = epic.get("plan_version") if isinstance(epic.get("plan_version"), dict) else {}
        if not version:
            # Backward compatibility: proposals created before PlanVersion
            # existed are frozen once at the approval boundary. They still
            # receive the same immutable contract binding before any run is
            # materialized.
            epic = self.epics.save_plan(epic_id, plan)
            plan = epic["plan"]
            version = epic.get("plan_version") if isinstance(epic.get("plan_version"), dict) else {}
        mapping = self.epics.create_task_batch(epic_id, plan["tasks"])
        return self.epics.update(
            epic_id,
            status="active",
            approved=True,
            task_run_ids=mapping,
            plan_version={**version, "status": "approved", "approved_at": now_iso()},
        )

    @classmethod
    def parse_proposal(
        cls,
        result: ProcessResult,
        *,
        project_path: str,
        default_lane: str,
        default_review_lane: str,
        default_checks: list[str],
    ) -> dict[str, Any]:
        payload = ""
        for line in reversed(result.output.splitlines()):
            if PLAN_MARKER in line:
                payload = line.split(PLAN_MARKER, 1)[1].strip()
                break
        if not payload:
            raise ValueError(f"planner did not return the required {PLAN_MARKER} marker")
        try:
            value = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise ValueError(f"planner returned invalid plan JSON: {exc}") from exc
        if not isinstance(value, dict) or not isinstance(value.get("tasks"), list):
            raise ValueError("planner output must be an object with a tasks array")
        raw_tasks = value["tasks"]
        if not raw_tasks or len(raw_tasks) > 40:
            raise ValueError("planner must return between 1 and 40 tasks")
        tasks: list[dict[str, Any]] = []
        keys: set[str] = set()
        for raw in raw_tasks:
            if not isinstance(raw, dict):
                raise ValueError("every planned task must be an object")
            key = str(raw.get("task_key") or raw.get("id") or "").strip()
            title = str(raw.get("title") or "").strip()
            task = str(raw.get("task") or raw.get("description") or "").strip()
            if not key or not title or not task:
                raise ValueError("every planned task requires task_key, title, and task")
            if key in keys:
                raise ValueError(f"duplicate planned task key: {key}")
            keys.add(key)
            role = str(raw.get("role") or "implementer")
            if role not in VALID_ROLES:
                raise ValueError(f"unsupported planned role: {role}")
            depends_on = raw.get("depends_on") or []
            if not isinstance(depends_on, list) or not all(isinstance(item, str) for item in depends_on):
                raise ValueError(f"depends_on for {key} must be a list of task keys")
            raw_checks = raw.get("checks", default_checks)
            if not isinstance(raw_checks, list) or not all(isinstance(item, str) for item in raw_checks):
                raise ValueError(f"checks for {key} must be a list of commands")
            tasks.append(
                {
                    "task_key": key,
                    "title": title,
                    "task": task,
                    "role": role,
                    "outcome": str(raw.get("outcome") or raw.get("intended_outcome") or title),
                    "source_refs": raw.get("source_refs") or [],
                    "acceptance_criteria": raw.get("acceptance_criteria") or [],
                    "required_evidence": raw.get("required_evidence") or raw_checks,
                    "depends_on": depends_on,
                    "parallelizable": bool(raw.get("parallelizable", True)),
                    "lane": str(raw.get("lane") or default_lane),
                    "review_lane": str(raw.get("review_lane") or default_review_lane),
                    "project_path": project_path,
                    "checks": list(raw_checks),
                    "execution_profile": raw.get("execution_profile") or {
                        "mode": "auto",
                        "harness": "auto",
                        "review_lane": default_review_lane,
                        "reason": "Auto will select from repository evidence",
                    },
                    "estimate": raw.get("estimate") or {
                        "confidence": "unknown",
                        "basis": "No calibrated repository estimate yet",
                    },
                }
            )
        unknown = sorted({dep for task in tasks for dep in task["depends_on"]} - keys)
        if unknown:
            raise ValueError(f"planned tasks depend on unknown keys: {', '.join(unknown)}")
        return {
            "summary": str(value.get("summary") or "").strip(),
            "tasks": tasks,
        }

    @staticmethod
    def _prompt(
        requirement: str,
        default_lane: str,
        default_review_lane: str,
        checks: list[str],
        source_documents: list[Mapping[str, Any]] | None = None,
    ) -> str:
        source_context = ""
        if source_documents:
            documents = []
            for source in source_documents:
                sections = source.get("sections") or []
                rendered = "\n".join(
                    f"[{section.get('ref')}] {section.get('text')}"
                    for section in sections
                    if isinstance(section, Mapping)
                )
                documents.append(
                    f"SOURCE {source.get('path') or source.get('title') or 'decision'}\n"
                    f"SHA256: {source.get('sha256') or ''}\n"
                    f"{rendered or str(source.get('content') or '')[:80_000]}"
                )
            source_context = "\n\nFrozen requirement sources (treat as auditable requirements):\n\n" + "\n\n".join(documents)
        return (
            "You are the read-only Planner role in an Odysseus engineering workflow. "
            "Inspect the repository architecture but do not edit files and do not implement the requirement. "
            "Decompose the requirement into the smallest useful acyclic task DAG. Separate investigation, "
            "implementation, integration, and independent review when the work warrants it. Avoid artificial "
            "parallelism when tasks will modify the same semantic surface. Finish with exactly one single-line "
            f"{PLAN_MARKER} JSON object. The object schema is: "
            '{"summary":"...","constraints":["global invariant"],"tasks":[{"task_key":"stable-key","title":"...",'
            '"outcome":"finished state","task":"complete editable implementation instruction",'
            '"source_refs":["S1"],"acceptance_criteria":["observable criterion"],'
            '"required_evidence":["test or review evidence"],"role":"implementer|reviewer",'
            '"depends_on":["other-key"],"parallelizable":true,"lane":"optional",'
            '"review_lane":"optional","checks":["optional command"],'
            '"execution_profile":{"mode":"auto","harness":"auto","model":"",'
            '"skills":[],"environment":"isolated_worktree","policy":"standard",'
            '"review_policy":"independent_review","review_lane":"optional","review_model":"",'
            '"reason":"why this profile fits"},'
            '"estimate":{"cost_usd_min":null,"cost_usd_max":null,"duration_minutes_min":null,'
            '"duration_minutes_max":null,"confidence":"unknown","basis":"historical basis or unavailable"}}]}. '
            "Do not wrap that final JSON in a Markdown fence. Planner is a role, not an implementation task.\n\n"
            f"Default implementation lane: {default_lane}\n"
            f"Default independent review lane: {default_review_lane}\n"
            f"Default checks: {json.dumps(checks)}\n\n"
            f"Requirement:\n{requirement}\n"
            f"{source_context}\n"
        )
