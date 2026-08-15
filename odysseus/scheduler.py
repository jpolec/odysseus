"""Persistent bounded-concurrency scheduler and agent-check-review workflow."""

from __future__ import annotations

import json
import inspect
import os
import threading
import time
import traceback
from pathlib import Path
from typing import Any, Mapping

from .evaluation import EvaluationEngine
from .environments import EnvironmentManager
from .events import now_iso
from .runners import AgentRunner, CheckRunner, ProcessResult
from .store import RunStore
from .worktrees import WorktreeManager


class Scheduler:
    def __init__(
        self,
        store: RunStore,
        *,
        agent_runner: AgentRunner | None = None,
        check_runner: CheckRunner | None = None,
        poll_seconds: float = 0.35,
    ) -> None:
        self.store = store
        config = store.config()
        self.agent_runner = agent_runner or AgentRunner(config.get("lanes", {}))
        self.check_runner = check_runner or CheckRunner()
        self.worktrees = WorktreeManager(store.worktrees_dir)
        self.environments = EnvironmentManager(store.root)
        self.poll_seconds = poll_seconds
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._active: dict[str, tuple[threading.Thread, threading.Event]] = {}
        self._guard = threading.Lock()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self.store.recover_interrupted()
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="odysseus-scheduler", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 10) -> None:
        self._stop.set()
        with self._guard:
            active = list(self._active.values())
        for _, cancel in active:
            cancel.set()
        deadline = time.monotonic() + timeout
        if self._thread:
            self._thread.join(timeout=max(0, deadline - time.monotonic()))
        for worker, _ in active:
            worker.join(timeout=max(0, deadline - time.monotonic()))

    def active_count(self) -> int:
        with self._guard:
            return len(self._active)

    def cancel(self, run_id: str) -> dict[str, Any]:
        run = self.store.request_cancel(run_id)
        with self._guard:
            active = self._active.get(run_id)
        if active:
            active[1].set()
        return run

    def _loop(self) -> None:
        while not self._stop.is_set():
            self._reap_and_cancel()
            self.store.epics.refresh_all()
            config = self.store.config()
            available = int(config["max_parallel"]) - self.active_count()
            if available > 0:
                queued = [run for run in self.store.list() if run.get("status") == "queued"]
                queued.sort(
                    key=lambda run: (
                        -int(run.get("priority", 50)),
                        str(run.get("created_at") or ""),
                    )
                )
                for candidate in queued[:available]:
                    run_id = str(candidate["id"])
                    claimed = self.store.claim(run_id, max_parallel=int(config["max_parallel"]))
                    if claimed is not None:
                        self._start_worker(run_id)
            self._stop.wait(self.poll_seconds)

    def _start_worker(self, run_id: str) -> None:
        cancel = threading.Event()
        worker = threading.Thread(
            target=self._worker,
            args=(run_id, cancel),
            name=f"odysseus-{run_id}",
            daemon=True,
        )
        with self._guard:
            self._active[run_id] = (worker, cancel)
        worker.start()

    def _reap_and_cancel(self) -> None:
        with self._guard:
            active = list(self._active.items())
        finished: list[str] = []
        for run_id, (thread, cancel) in active:
            if not thread.is_alive():
                finished.append(run_id)
                continue
            try:
                run = self.store.get(run_id)
            except KeyError:
                cancel.set()
                continue
            if run.get("cancel_requested"):
                cancel.set()
        if finished:
            with self._guard:
                for run_id in finished:
                    self._active.pop(run_id, None)

    def _emit(self, run_id: str, event_type: str, source: str, data: Mapping[str, Any]) -> None:
        self.store.append_event(run_id, event_type, source, data)

    def _run_agent(self, *args: Any, **kwargs: Any) -> ProcessResult:
        """Keep simple third-party/test runners compatible with the v1 adapter."""
        parameters = inspect.signature(self.agent_runner.run).parameters
        supported = {key: value for key, value in kwargs.items() if key in parameters}
        return self.agent_runner.run(*args, **supported)

    def _run_check(self, *args: Any, **kwargs: Any) -> ProcessResult:
        """Keep simple third-party/test check runners compatible."""
        parameters = inspect.signature(self.check_runner.run).parameters
        supported = {key: value for key, value in kwargs.items() if key in parameters}
        return self.check_runner.run(*args, **supported)

    def _worker(self, run_id: str, cancel: threading.Event) -> None:
        try:
            self._execute(run_id, cancel)
        except Exception as exc:  # worker boundary: persist every unexpected failure
            message = str(exc) or exc.__class__.__name__
            self.store.transition(
                run_id,
                "failed",
                event_type="run.failed",
                last_error=message,
                worker_pid=None,
                data={"message": message, "trace": traceback.format_exc(limit=8)},
            )
        finally:
            self.store.update(run_id, worker_pid=None)

    def _is_cancelled(self, run_id: str, cancel: threading.Event) -> bool:
        if cancel.is_set() or self._stop.is_set():
            return True
        try:
            return bool(self.store.get(run_id).get("cancel_requested"))
        except KeyError:
            return True

    def _cancel_run(self, run_id: str) -> None:
        self.store.transition(
            run_id,
            "cancelled",
            event_type="run.cancelled",
            cancel_requested=False,
            worker_pid=None,
        )

    def _budget_reason(self, run_id: str) -> str:
        run = self.store.get(run_id)
        budgets = run.get("budgets") if isinstance(run.get("budgets"), dict) else {}
        metrics = run.get("metrics") if isinstance(run.get("metrics"), dict) else {}
        tokens = sum(
            int(metrics.get(key) or 0)
            for key in ("input_tokens", "output_tokens", "reasoning_output_tokens")
        )
        max_tokens = int(budgets.get("max_tokens") or 0)
        if max_tokens and tokens >= max_tokens:
            return f"Token budget exceeded: {tokens:,} / {max_tokens:,}."
        tools = int(metrics.get("tool_calls") or 0)
        max_tools = int(budgets.get("max_tool_calls") or 0)
        if max_tools and tools >= max_tools:
            return f"Tool-call budget exceeded: {tools} / {max_tools}."
        try:
            cost = float(metrics.get("cost_usd") or 0.0)
            max_cost = float(budgets.get("max_cost_usd") or 0.0)
        except (TypeError, ValueError):
            cost, max_cost = 0.0, 0.0
        if max_cost and cost >= max_cost:
            return f"Cost budget exceeded: ${cost:.4f} / ${max_cost:.4f}."
        return ""

    def _fail_budget(self, run_id: str, reason: str) -> None:
        self.store.update(run_id, budget_status={"state": "exceeded", "reason": reason})
        self.store.transition(
            run_id,
            "failed",
            event_type="run.budget_exceeded",
            last_error=reason,
            data={"message": reason},
        )

    def _fail_liveness(self, run_id: str, result: ProcessResult) -> None:
        reason = "Process timed out." if result.stop_reason == "timeout" else "Process stopped after an output stall."
        self.store.update(
            run_id,
            status="failed",
            finished_at=now_iso(),
            worker_pid=None,
            last_error=reason,
        )

    def _finish_interruption(self, run_id: str) -> None:
        run = self.store.get(run_id)
        if self._stop.is_set() and not run.get("cancel_requested"):
            self.store.update(
                run_id,
                status="queued",
                cancel_requested=False,
                worker_pid=None,
                last_error="Scheduler stopped; the persistent run was re-queued.",
            )
            self.store.append_event(
                run_id,
                "system.recovered",
                "odysseus",
                {"reason": "scheduler_stopped"},
            )
            return
        self._cancel_run(run_id)

    @staticmethod
    def _project_options(worktree: Path) -> dict[str, Any]:
        path = worktree / ".odysseus.json"
        if not path.is_file():
            return {}
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"invalid {path}: {exc}") from exc
        if not isinstance(value, dict):
            raise ValueError(f"{path} must contain a JSON object")
        return value

    def _execute(self, run_id: str, cancel: threading.Event) -> None:
        run = self.store.get(run_id)
        if run.get("workflow") != "agent-check-review":
            raise ValueError(f"unsupported workflow: {run.get('workflow')}")

        emit = lambda event_type, source, data: self._emit(run_id, event_type, source, data)
        worktree_info = self.worktrees.create(run, emit)
        run = self.store.update(run_id, **worktree_info)
        dependencies = [self.store.get(str(item)) for item in run.get("depends_on") or []]
        if dependencies:
            integration = self.worktrees.integrate(run, dependencies, emit)
            run = self.store.update(run_id, **integration)
        worktree = Path(str(run["worktree_path"]))
        options = self._project_options(worktree)
        checks = run.get("checks") or options.get("checks") or []
        if not isinstance(checks, list) or not all(isinstance(item, str) for item in checks):
            raise ValueError("checks must be a JSON array of command strings")
        environment = self.environments.prepare(run, worktree, options, emit)
        if environment.get("missing_credential_env_names"):
            missing = ", ".join(environment["missing_credential_env_names"])
            raise ValueError(f"requested credential environment variables are missing: {missing}")
        requested_environment = run.get("environment_request") if isinstance(run.get("environment_request"), dict) else {}
        project_environment = options.get("environment") if isinstance(options.get("environment"), dict) else {}
        repository_commands = [
            *(
                [str(item) for item in options.get("checks") or []]
                if not run.get("checks") and isinstance(options.get("checks"), list)
                else []
            ),
            *(
                [str(item.get("command")) for item in options.get("evaluators") or [] if isinstance(item, dict)]
                if isinstance(options.get("evaluators"), list)
                else []
            ),
            *(
                [str(item) for item in project_environment.get("setup") or []]
                if "setup" not in requested_environment and isinstance(project_environment.get("setup"), list)
                else []
            ),
        ]
        if run.get("untrusted_project") and (repository_commands or options.get("environment")) and not run.get("project_commands_approved"):
            environment = {**environment, "trust_status": "pending", "status": "awaiting_approval"}
            self.store.update(run_id, status="attention", environment=environment, worker_pid=None)
            approval_lines = [
                f"profile: {environment.get('profile') or 'unknown'}",
                *([f"image: {environment['image']}"] if environment.get("image") else []),
                f"network: {environment.get('network') or 'default'}",
                *[f"command: {item}" for item in repository_commands[:20] if item],
            ]
            emit(
                "agent.permission_request",
                "odysseus",
                {
                    "title": "Approve repository execution configuration",
                    "message": "This untrusted repository supplies checks, evaluators, setup commands, or a container profile. Review and approve them before any agent or repository command runs.\n\n" + "\n".join(f"- {item}" for item in approval_lines),
                    "options": [
                        {"id": "approve", "label": "Approve once"},
                        {"id": "reject", "label": "Reject task"},
                    ],
                    "priority": "critical",
                },
            )
            return
        self.environments.activate(environment, worktree, emit)
        setup_results: list[dict[str, Any]] = []
        for command in environment.get("setup") or []:
            emit("environment.setup_started", "odysseus", {"command": command})
            result = self._run_check(
                command,
                worktree,
                emit=emit,
                cancelled=lambda: self._is_cancelled(run_id, cancel),
                execution=environment,
                phase="setup",
            )
            record = {
                "command": command,
                "returncode": result.returncode,
                "output": result.output[-30_000:],
                "duration_seconds": result.duration_seconds,
            }
            setup_results.append(record)
            emit("environment.setup_completed", "odysseus", record)
            if result.returncode != 0:
                raise ValueError(f"environment setup failed: {command}")
        environment = {**environment, "status": "active", "setup_results": setup_results}
        run = self.store.update(run_id, environment=environment)

        max_retries = int(run.get("max_retries", 2))
        feedback = str(run.get("feedback") or "").strip()
        failure_context = feedback
        cycle = int(run.get("review_cycle", 0))
        sessions = run.get("agent_sessions") if isinstance(run.get("agent_sessions"), dict) else {}
        implementation_session = str(sessions.get("agent") or "")
        budget_stop = {"reason": ""}

        def should_stop() -> bool:
            if self._is_cancelled(run_id, cancel):
                return True
            reason = self._budget_reason(run_id)
            if reason:
                budget_stop["reason"] = reason
                return True
            return False

        budgets = run.get("budgets") if isinstance(run.get("budgets"), dict) else {}
        timeout_seconds = float(budgets.get("timeout_seconds") or 0)
        stall_seconds = float(budgets.get("stall_seconds") or 0)

        for attempt in range(1, max_retries + 2):
            if self._is_cancelled(run_id, cancel):
                self._finish_interruption(run_id)
                return
            self.store.update(
                run_id,
                status="running",
                attempt=attempt,
                worker_pid=os.getpid(),
                finished_at=None,
            )
            implement_prompt = self._implementation_prompt(run, attempt, cycle, failure_context)
            for skill in run.get("skills_selected") or []:
                emit("skill.loaded", "odysseus", {"name": skill.get("name"), "sha256": skill.get("sha256"), "phase": "agent"})
            emit(
                "step.started",
                "odysseus",
                {"step": "agent", "attempt": attempt, "lane": run["lane"]},
            )
            agent_result = self._run_agent(
                str(run["lane"]),
                worktree,
                implement_prompt,
                review=False,
                emit=emit,
                cancelled=should_stop,
                resume_session_id=implementation_session,
                phase="agent",
                timeout_seconds=timeout_seconds,
                stall_seconds=stall_seconds,
                execution=environment,
            )
            if budget_stop["reason"]:
                self._fail_budget(run_id, budget_stop["reason"])
                return
            if agent_result.stop_reason in {"timeout", "stall"}:
                self._fail_liveness(run_id, agent_result)
                return
            if agent_result.cancelled or self._is_cancelled(run_id, cancel):
                self._finish_interruption(run_id)
                return
            if agent_result.returncode != 0:
                self._fail_process(run_id, "agent", agent_result)
                return
            if implementation_session:
                emit(
                    "session.resumed",
                    str(run["lane"]),
                    {"phase": "agent", "session_id": implementation_session, "attempt": attempt},
                )
            implementation_session = agent_result.session_id or implementation_session
            emit(
                "agent.completed",
                str(run["lane"]),
                {"attempt": attempt, "duration_seconds": agent_result.duration_seconds},
            )
            emit("step.completed", "odysseus", {"step": "agent", "attempt": attempt})

            pending = [
                item
                for item in self.store.attention.list(status="open", run_id=run_id)
                if item.get("type")
                in {"question", "permission_request", "blocked", "decision_required"}
            ]
            if pending:
                self.store.transition(
                    run_id,
                    "attention",
                    event_type="run.attention",
                    worker_pid=None,
                    last_error="Agent needs an operator decision before checks can continue.",
                    data={"message": "Agent needs an operator decision.", "attention_ids": [item["id"] for item in pending]},
                )
                return

            self.store.update(run_id, status="checking")
            emit(
                "step.started",
                "odysseus",
                {"step": "check", "attempt": attempt, "commands": checks},
            )
            check_results, failing = self._run_checks(run_id, worktree, checks, cancel, emit, should_stop, environment)
            self.store.update(run_id, check_results=check_results)
            if budget_stop["reason"]:
                self._fail_budget(run_id, budget_stop["reason"])
                return
            if self._is_cancelled(run_id, cancel):
                self._finish_interruption(run_id)
                return
            if failing is not None:
                if attempt <= max_retries:
                    failure_context = self._retry_context(failing)
                    emit(
                        "workflow.retry",
                        "odysseus",
                        {
                            "attempt": attempt,
                            "next_attempt": attempt + 1,
                            "max_retries": max_retries,
                            "command": failing["command"],
                        },
                    )
                    continue
                message = f"Checks still fail after {max_retries} retries: {failing['command']}"
                self.store.transition(
                    run_id,
                    "failed",
                    event_type="run.failed",
                    last_error=message,
                    review_status="checks_failed",
                    data={"message": message},
                )
                return
            emit("step.completed", "odysseus", {"step": "check", "attempt": attempt})

            verifier_results = self._run_verifiers(
                run_id,
                worktree,
                options.get("evaluators") or [],
                cancel,
                emit,
                should_stop,
                environment,
            )
            self.store.update(run_id, verifier_results=verifier_results)

            followups = self.store.inbox.ingest_agent_file(self.store.get(run_id), worktree)
            for item in followups:
                emit(
                    "inbox.created",
                    "agent",
                    {"inbox_id": item["id"], "title": item["title"]},
                )

            self.store.update(run_id, status="reviewing")
            emit(
                "step.started",
                "odysseus",
                {"step": "review", "lane": run["review_lane"]},
            )
            review_result = self._run_agent(
                str(run["review_lane"]),
                worktree,
                self._review_prompt(run, check_results),
                review=True,
                emit=emit,
                cancelled=should_stop,
                phase="review",
                timeout_seconds=timeout_seconds,
                stall_seconds=stall_seconds,
                execution=environment,
            )
            if budget_stop["reason"]:
                self._fail_budget(run_id, budget_stop["reason"])
                return
            if review_result.stop_reason in {"timeout", "stall"}:
                self._fail_liveness(run_id, review_result)
                return
            if review_result.cancelled or self._is_cancelled(run_id, cancel):
                self._finish_interruption(run_id)
                return
            if review_result.returncode != 0:
                self._fail_process(run_id, "review", review_result)
                return
            emit("step.completed", "odysseus", {"step": "review"})
            emit("evaluation.started", "odysseus", {"verifiers": len(verifier_results)})
            evaluation = EvaluationEngine.evaluate(
                self.store.get(run_id),
                check_results,
                review_result.output,
                verifier_results=verifier_results,
                policy=options.get("policy") or self.store.config().get("evaluation_policy") or {},
            )
            self.store.update(
                run_id,
                evaluation=evaluation,
                confidence=evaluation["confidence"],
                policy_decision=evaluation["decision"],
                human_review_required=evaluation["human_review_required"],
            )
            evaluation_event = "evaluation.completed" if evaluation["eligible"] else "evaluation.failed"
            emit(
                evaluation_event,
                "odysseus",
                {
                    "message": (
                        "Evaluation reached the configured confidence policy."
                        if evaluation["eligible"]
                        else "Evaluation requires operator review."
                    ),
                    "confidence": evaluation["confidence"],
                    "threshold": evaluation["threshold"],
                    "decision": evaluation["decision"],
                    "failing_evaluators": evaluation["failing_evaluators"],
                    "missing_evaluators": evaluation["missing_evaluators"],
                },
            )
            current = self.store.get(run_id)
            if current.get("ci_retry_active") and current.get("pull_request_url") and evaluation["eligible"]:
                artifact_sha = self.worktrees.push_update(current)
                artifact_value = {**current, "artifact_sha": artifact_sha}
                artifact = {
                    "artifact_sha": artifact_sha,
                    "artifact_files": self.worktrees.changed_files(artifact_value),
                }
                ci = dict(current.get("ci") or {})
                ci.update({"status": "pending", "summary": "Repair pushed; waiting for GitHub checks.", "updated_at": now_iso()})
                self.store.update(
                    run_id,
                    **artifact,
                    artifact_created_at=now_iso(),
                    ci=ci,
                    ci_retry_active=False,
                    review_summary=review_result.output[-40_000:],
                    review_status="ci_repair_pushed",
                )
                emit("artifact.created", "git", artifact)
                self.store.transition(
                    run_id,
                    "pr_created",
                    event_type="ci.retry_pushed",
                    worker_pid=None,
                    last_error="",
                    data={"attempt": ci.get("attempt"), "artifact_sha": artifact_sha},
                )
                return
            final = self.store.transition(
                run_id,
                "review",
                event_type="run.review_ready",
                review_summary=review_result.output[-40_000:],
                review_status="waiting",
                feedback="",
                last_error="",
                data={"message": "Diff and checks are ready for a human decision."},
            )
            if evaluation["decision"] == "auto_accept_eligible":
                artifact = self.worktrees.snapshot(self.store.get(run_id), reason="policy accepted")
                self.store.update(run_id, **artifact, artifact_created_at=now_iso())
                emit("artifact.created", "git", artifact)
                self.store.append_event(run_id, "review.accepted", "policy", {"confidence": evaluation["confidence"]})
                self.store.transition(
                    run_id,
                    "accepted",
                    event_type="run.accepted",
                    source="policy",
                    review_status="accepted_by_policy",
                    data={"confidence": evaluation["confidence"]},
                )
            return

    def _run_checks(
        self,
        run_id: str,
        worktree: Path,
        checks: list[str],
        cancel: threading.Event,
        emit: Any,
        should_stop: Any,
        execution: Mapping[str, Any] | None = None,
    ) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        results: list[dict[str, Any]] = []
        if not checks:
            result = {"command": "", "returncode": 0, "output": "No checks configured.", "skipped": True}
            emit("check.completed", "check", result)
            return [result], None
        for command in checks:
            result = self._run_check(
                command,
                worktree,
                emit=emit,
                cancelled=should_stop,
                execution=execution,
                phase="check",
            )
            record = {
                "command": command,
                "returncode": result.returncode,
                "output": result.output[-30_000:],
                "duration_seconds": result.duration_seconds,
            }
            results.append(record)
            emit("check.completed", "check", record)
            if result.cancelled or result.returncode != 0:
                return results, record
        return results, None

    def _run_verifiers(
        self,
        run_id: str,
        worktree: Path,
        raw_verifiers: Any,
        cancel: threading.Event,
        emit: Any,
        should_stop: Any,
        execution: Mapping[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        if not isinstance(raw_verifiers, list):
            raise ValueError("evaluators must be a JSON array")
        results: list[dict[str, Any]] = []
        for index, value in enumerate(raw_verifiers[:20]):
            if not isinstance(value, dict) or not str(value.get("command") or "").strip():
                raise ValueError("each evaluator requires a command")
            command = str(value["command"])
            emit("step.started", "odysseus", {"step": "evaluator", "id": value.get("id") or index, "command": command})
            result = self._run_check(
                command,
                worktree,
                emit=emit,
                cancelled=should_stop,
                execution=execution,
                phase="evaluator",
            )
            record = {
                "id": str(value.get("id") or f"evaluator-{index + 1}"),
                "kind": str(value.get("kind") or "deterministic"),
                "command": command,
                "returncode": result.returncode,
                "output": result.output[-30_000:],
                "duration_seconds": result.duration_seconds,
                "weight": value.get("weight", 0.2),
                "score": value.get("score") if value.get("score") is not None else (1.0 if result.returncode == 0 else 0.0),
            }
            results.append(record)
            emit("check.completed", "evaluator", record)
            emit("step.completed", "odysseus", {"step": "evaluator", "id": record["id"]})
            if result.cancelled:
                break
        return results

    def _fail_process(self, run_id: str, step: str, result: ProcessResult) -> None:
        message = f"{step} process exited with code {result.returncode}"
        self.store.append_event(
            run_id,
            "step.failed",
            "odysseus",
            {"step": step, "returncode": result.returncode, "output": result.output[-10_000:]},
        )
        self.store.transition(
            run_id,
            "failed",
            event_type="run.failed",
            last_error=message,
            data={"message": message},
        )

    @staticmethod
    def _implementation_prompt(
        run: Mapping[str, Any], attempt: int, cycle: int, failure_context: str
    ) -> str:
        prompt = (
            "You are the implementation agent in an Odysseus workflow. Work only in the current "
            "git worktree. Implement the task completely, inspect existing conventions, and leave "
            "the working tree ready for checks and review. Do not create a pull request.\n\n"
            "If you discover useful work that is outside this task, write a JSON array of objects "
            "with title, task, and optional priority to .odysseus-followups.json. Do not put the "
            "current task in that file.\n\n"
            "If you cannot proceed without operator input, do not guess. Finish with one single-line "
            "ODYSSEUS_ATTENTION: JSON object containing type (question, permission_request, blocked, "
            "or decision_required), title, message, optional options, and priority.\n\n"
            f"Task:\n{run['task']}\n"
        )
        if cycle:
            prompt += f"\nThis is human review cycle {cycle + 1}.\n"
        if failure_context:
            label = "Review feedback" if attempt == 1 else "Failed check from the previous attempt"
            prompt += f"\n{label}:\n{failure_context[-20_000:]}\n"
        context_bundle = run.get("context_bundle") if isinstance(run.get("context_bundle"), list) else []
        if context_bundle:
            prompt += "\nProject context captured when this task was queued:\n"
            for source in context_bundle:
                prompt += (
                    f"\n--- CONTEXT {source.get('path')} ({source.get('reason')}) ---\n"
                    f"{str(source.get('content') or '')}\n"
                )
        skill_context = run.get("skill_context") if isinstance(run.get("skill_context"), list) else []
        if skill_context:
            prompt += "\nEngineering skills selected for this task:\n"
            for skill in skill_context:
                prompt += f"\n--- SKILL {skill.get('name')} ({skill.get('reason')}) ---\n{str(skill.get('content') or '')[:16_000]}\n"
        return prompt

    @staticmethod
    def _review_prompt(run: Mapping[str, Any], checks: list[dict[str, Any]]) -> str:
        check_lines = [
            f"- {item.get('command') or 'No checks configured'}: exit {item.get('returncode', 0)}"
            for item in checks
        ]
        return (
            "You are the read-only review agent in an Odysseus workflow. Inspect the complete diff "
            "against the base commit and the repository context. Do not edit files. Report concrete "
            "correctness, security, regression, and test concerns, ordered by severity. If there are "
            "no material concerns, say so explicitly. Finish with exactly one single-line "
            "ODYSSEUS_EVALUATION: JSON object containing score (0..1), verdict "
            "(pass, fail, or needs_review), and a findings array. Do not wrap it in a Markdown fence.\n\n"
            f"Original task:\n{run['task']}\n\nChecks:\n" + "\n".join(check_lines)
        )

    @staticmethod
    def _retry_context(failing: Mapping[str, Any]) -> str:
        return (
            f"Command: {failing.get('command')}\n"
            f"Exit code: {failing.get('returncode')}\n"
            f"Output:\n{str(failing.get('output') or '')[-18_000:]}"
        )


class ReviewActions:
    def __init__(self, store: RunStore, scheduler: Scheduler) -> None:
        self.store = store
        self.scheduler = scheduler

    def accept(self, run_id: str) -> dict[str, Any]:
        run = self.store.get(run_id)
        if run.get("status") != "review":
            raise ValueError("only a run waiting for review can be accepted")
        artifact = self.scheduler.worktrees.snapshot(run, reason="accepted")
        self.store.update(run_id, **artifact, artifact_created_at=now_iso())
        self.store.append_event(run_id, "artifact.created", "git", artifact)
        self.store.append_event(run_id, "review.accepted", "user", {})
        self.store.attention.resolve_for_run(run_id, resolution="accepted")
        return self.store.transition(
            run_id,
            "accepted",
            event_type="run.accepted",
            review_status="accepted",
        )

    def send_back(self, run_id: str, feedback: str) -> dict[str, Any]:
        feedback = feedback.strip()
        if not feedback:
            raise ValueError("feedback is required")
        run = self.store.get(run_id)
        if run.get("status") not in {"review", "failed", "attention"}:
            raise ValueError("only a review, failed, or attention run can be sent back")
        cycle = int(run.get("review_cycle", 0)) + 1
        self.store.update(
            run_id,
            status="queued",
            feedback=feedback,
            review_cycle=cycle,
            review_status="sent_back",
            cancel_requested=False,
            finished_at=None,
            worker_pid=None,
        )
        self.store.append_event(
            run_id,
            "review.sent_back",
            "user",
            {"feedback": feedback, "review_cycle": cycle},
        )
        self.store.attention.resolve_for_run(run_id, resolution="sent_back")
        self.store.append_event(run_id, "run.queued", "odysseus", {"reason": "review_feedback"})
        return self.store.get(run_id)

    def resume(
        self,
        run_id: str,
        prompt: str,
        *,
        strategy: str = "resume",
        lane: str = "",
    ) -> dict[str, Any]:
        feedback = prompt.strip() or "Continue this task from the existing agent session and address any remaining work."
        run = self.store.get(run_id)
        if run.get("status") not in {"review", "failed", "accepted", "attention", "pr_created"}:
            raise ValueError("only a reviewed, failed, accepted, attention, or published run can be resumed")
        if strategy not in {"resume", "switch", "clean"}:
            raise ValueError("strategy must be resume, switch, or clean")
        if strategy == "switch" and not lane.strip():
            raise ValueError("switch strategy requires a lane")
        cycle = int(run.get("review_cycle", 0)) + 1
        sessions = dict(run.get("agent_sessions") or {})
        changes: dict[str, Any] = {}
        if strategy in {"switch", "clean"}:
            sessions.pop("agent", None)
            changes["agent_sessions"] = sessions
            changes["agent_session_id"] = ""
        if strategy == "switch":
            changes["lane"] = lane.strip()
        self.store.update(
            run_id,
            status="queued",
            feedback=feedback,
            review_cycle=cycle,
            review_status="continued",
            cancel_requested=False,
            finished_at=None,
            worker_pid=None,
            **changes,
        )
        self.store.append_event(
            run_id,
            "run.queued",
            "user",
            {
                "reason": "resume",
                "prompt": feedback,
                "review_cycle": cycle,
                "strategy": strategy,
                "lane": lane.strip() or run.get("lane"),
            },
        )
        self.store.attention.resolve_for_run(run_id, resolution="resumed")
        return self.store.get(run_id)

    def answer_attention(self, item_id: str, response: str) -> dict[str, Any]:
        item = self.store.attention.respond(item_id, response)
        run_id = str(item.get("run_id") or "")
        if not run_id:
            return {"attention": item}
        run = self.store.get(run_id)
        environment = run.get("environment") if isinstance(run.get("environment"), dict) else {}
        if item.get("type") == "permission_request" and environment.get("trust_status") == "pending":
            decision = response.strip().lower()
            self.store.append_event(
                run_id,
                "attention.answered",
                "user",
                {"attention_id": item_id, "response": response.strip()},
            )
            if decision in {"approve", "approved", "allow", "yes"}:
                updated_environment = {**environment, "trust_status": "approved", "status": "pending"}
                self.store.update(
                    run_id,
                    status="queued",
                    environment=updated_environment,
                    project_commands_approved=True,
                    last_error="",
                    worker_pid=None,
                )
                self.store.append_event(run_id, "environment.approved", "user", {"attention_id": item_id})
                self.store.append_event(run_id, "run.queued", "odysseus", {"reason": "environment_approved"})
                return {"attention": item, "run": self.store.get(run_id)}
            updated_environment = {**environment, "trust_status": "rejected", "status": "rejected"}
            self.store.update(run_id, environment=updated_environment)
            self.store.append_event(run_id, "environment.rejected", "user", {"attention_id": item_id})
            rejected = self.store.transition(
                run_id,
                "cancelled",
                event_type="run.cancelled",
                last_error="Repository execution configuration was rejected by the operator.",
                worker_pid=None,
            )
            return {"attention": item, "run": rejected}
        if item.get("type") == "review_comment":
            if response.strip().lower() in {"ignore", "reject", "resolve"}:
                self.store.append_event(
                    run_id,
                    "attention.answered",
                    "user",
                    {"attention_id": item_id, "response": response.strip()},
                )
                self.store.attention.resolve(item_id, resolution="ignored")
                return {"attention": self.store.attention.get(item_id), "run": run}
            response = (
                "Address this pull request review feedback in the existing branch and session:\n\n"
                f"{item.get('message', '')}\n\nOperator decision: {response}"
            )
        elif item.get("type") in {"ci_failed", "merge_conflict", "budget", "stalled"}:
            response = (
                f"Continue after this Odysseus exception:\n\n{item.get('message', '')}\n\n"
                f"Operator decision: {response}"
            )
        self.store.append_event(
            run_id,
            "attention.answered",
            "user",
            {"attention_id": item_id, "response": response},
        )
        self.store.attention.resolve_for_run(run_id, resolution="answered_together")
        if run.get("status") in {"attention", "review", "failed", "accepted"}:
            resumed = self.resume(
                run_id,
                f"Operator response to your pending question or permission request:\n{response}",
            )
            return {"attention": item, "run": resumed}
        self.store.update(run_id, pending_operator_response=response)
        return {"attention": item, "run": self.store.get(run_id)}

    def draft_pr(self, run_id: str) -> dict[str, Any]:
        run = self.store.get(run_id)
        if run.get("pull_request_url"):
            return run
        if run.get("status") not in {"review", "accepted"}:
            raise ValueError("a draft PR can only be created from review or accepted state")
        previous_status = str(run["status"])
        artifact = self.scheduler.worktrees.snapshot(run, reason="published")
        self.store.update(run_id, **artifact, artifact_created_at=now_iso())
        self.store.append_event(run_id, "artifact.created", "git", artifact)
        self.store.update(run_id, status="publishing", worker_pid=os.getpid())
        self.store.append_event(run_id, "pr.creating", "user", {})
        try:
            url = WorktreeManager.draft_pr(self.store.get(run_id))
        except Exception as exc:
            self.store.update(run_id, status=previous_status, worker_pid=None, last_error=str(exc))
            self.store.append_event(run_id, "pr.failed", "git", {"message": str(exc)})
            raise
        self.store.append_event(run_id, "pr.created", "git", {"url": url})
        ci = dict(self.store.get(run_id).get("ci") or {})
        ci.update({"status": "pending", "summary": "Waiting for GitHub checks.", "updated_at": now_iso()})
        return self.store.transition(
            run_id,
            "pr_created",
            pull_request_url=url,
            ci=ci,
            review_status="published",
            worker_pid=None,
        )
