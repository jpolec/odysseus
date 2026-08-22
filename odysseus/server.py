"""Local HTTP API, static web UI, and Server-Sent Events transport."""

from __future__ import annotations

import base64
import json
import mimetypes
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen

from . import __version__
from .ci import CIWatcher
from .commands import CommandOutcomeUnknown, IdempotencyConflict
from .economics import economics_csv, economics_ndjson, outcome_economics
from .planner import EpicPlanner
from .portfolio import engineering_portfolio
from .redaction import DEFAULT_REDACTION_ENGINE
from .runners import AgentRunner, _extract_text, _sanitize
from .scheduler import ReviewActions, Scheduler
from .search import search, statistics
from .github import GitHubBridge
from .intake import IntakeCoordinator, github_issue_signal
from .lifecycle import ResourceLifecycle
from .kernel import ConcurrencyConflict
from .resources import resource_path
from .store import RunStore
from .tmux import TmuxBridge
from .worktrees import WorktreeManager


RUN_ROUTE = re.compile(r"^/api/runs/(?P<run_id>[A-Za-z0-9_.-]+)(?:/(?P<action>events|stream|diff|cancel|accept|apply|integration-candidates|integration|variants|send-back|resume|takeover|draft-pr|ci-poll))?$")
TMUX_ROUTE = re.compile(r"^/api/tmux/sessions/(?P<name>[A-Za-z0-9_.-]+)(?:/(?P<action>adopt|takeover))?$")
PROJECT_ROUTE = re.compile(r"^/api/projects/(?P<project_id>[A-Za-z0-9_.-]+)(?:/(?P<action>overview|profile|skills|knowledge))?$")
PROJECT_ROUTER_ROUTE = re.compile(r"^/api/projects/(?P<project_id>[A-Za-z0-9_.-]+)/router(?:/(?P<action>recommend|backtest|delete))?$")
PROJECT_SKILL_RECOMMEND_ROUTE = re.compile(r"^/api/projects/(?P<project_id>[A-Za-z0-9_.-]+)/skills/recommend$")
PROJECT_SKILL_LOCAL_ROUTE = re.compile(r"^/api/projects/(?P<project_id>[A-Za-z0-9_.-]+)/skills/local$")
INBOX_ROUTE = re.compile(r"^/api/inbox/(?P<item_id>[A-Za-z0-9_.-]+)(?:/(?P<action>resolve|reopen|promote))?$")
EPIC_ROUTE = re.compile(r"^/api/epics/(?P<epic_id>[A-Za-z0-9_.-]+)(?:/(?P<action>approve|plan|refresh-sources))?$")
ATTENTION_ROUTE = re.compile(r"^/api/attention/(?P<item_id>[A-Za-z0-9_.-]+)(?:/(?P<action>respond|resolve))?$")
COMMAND_ROUTE = re.compile(r"^/api/commands(?:/(?P<command_id>[0-9a-f-]{36}))?$")

DIRECT_ASSISTANT_PROVIDER_ENV = {
    "openai": ("OPENAI_API_KEY", "ODYSSEUS_ASSISTANT_OPENAI_MODEL", "gpt-4o-mini"),
    "anthropic": ("ANTHROPIC_API_KEY", "ODYSSEUS_ASSISTANT_ANTHROPIC_MODEL", "claude-3-5-sonnet-latest"),
}
ASSISTANT_PROVIDERS = ("codex", "claude", "openai", "anthropic")
RUN_SUMMARY_FIELDS = (
    "id",
    "title",
    "task",
    "task_key",
    "status",
    "kind",
    "project_id",
    "lane",
    "priority",
    "workflow",
    "created_at",
    "started_at",
    "finished_at",
    "artifact_created_at",
    "updated_at",
    "epic_id",
    "depends_on",
    "dependency_keys",
    "blocks",
    "block_keys",
    "tmux_session",
    "tmux_target",
)


def _run_summary(run: Mapping[str, Any]) -> dict[str, Any]:
    """Return only fields needed by repository and task navigation lists."""

    def observed_int(value: Any) -> int:
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0

    def observed_float(value: Any) -> float | None:
        try:
            return round(float(value), 8)
        except (TypeError, ValueError):
            return None

    summary = {key: run.get(key) for key in RUN_SUMMARY_FIELDS}
    artifact_files = run.get("artifact_files") if isinstance(run.get("artifact_files"), list) else []
    metrics = run.get("metrics") if isinstance(run.get("metrics"), Mapping) else {}
    checks = run.get("check_results") if isinstance(run.get("check_results"), list) else []
    environment = run.get("environment") if isinstance(run.get("environment"), Mapping) else {}
    passed_checks = sum(
        1
        for check in checks
        if isinstance(check, Mapping)
        and (bool(check.get("skipped")) or str(check.get("returncode", "")).strip() == "0")
    )
    cost_usd = observed_float(metrics.get("cost_usd")) if metrics.get("cost_observed") else None
    summary["navigation"] = {
        "files_changed": len([path for path in artifact_files if str(path)]),
        "tool_calls": observed_int(metrics.get("tool_calls")),
        "total_tokens": sum(observed_int(metrics.get(key)) for key in ("input_tokens", "output_tokens", "reasoning_output_tokens")),
        "cost_observed": cost_usd is not None,
        "cost_usd": cost_usd,
        "checks_passed": passed_checks,
        "checks_total": len(checks),
        "evidence_score": run.get("confidence"),
        "environment": str(environment.get("profile") or "host"),
        "isolated": bool(run.get("worktree")),
    }
    summary["merge_analysis"] = {"risk": (run.get("merge_analysis") or {}).get("risk", "none")}
    summary["ci"] = {"status": (run.get("ci") or {}).get("status", "not_started")}
    summary["delivery"] = {"status": (run.get("delivery") or {}).get("status", "not_started")}
    return summary


def _epic_summary(epic: Mapping[str, Any]) -> dict[str, Any]:
    """Keep exact source snapshots private to the explicit Epic detail route."""

    value = dict(epic)
    value["source_documents"] = [
        {key: source.get(key) for key in ("kind", "path", "title", "status", "sha256", "bytes")}
        for source in epic.get("source_documents") or []
        if isinstance(source, dict)
    ]
    return value


class OdysseusApp:
    def __init__(
        self,
        store: RunStore,
        *,
        host: str = "127.0.0.1",
        port: int = 8741,
        allow_remote: bool = False,
        verbose: bool = False,
        static_root: Path | None = None,
        scheduler: Scheduler | None = None,
        auth_user: str = "",
        auth_password: str = "",
        max_http_connections: int = 64,
        max_sse_connections: int = 32,
        test_capabilities: Mapping[str, bool] | None = None,
    ) -> None:
        self.store = store
        self.commands = store.commands
        self.host = host
        self.port = port
        self.allow_remote = allow_remote
        self.verbose = verbose
        self.static_root = static_root or resource_path("web")
        self.token = secrets.token_urlsafe(24)
        self.scheduler = scheduler or Scheduler(store)
        self.actions = ReviewActions(store, self.scheduler)
        self.planner = EpicPlanner(store)
        self.tmux = TmuxBridge(store)
        self.github = GitHubBridge()
        self.intake = IntakeCoordinator(store)
        self.ci = CIWatcher(store, self.actions, bridge=self.github)
        self.resources = ResourceLifecycle(store)
        self.auth_user = auth_user
        self.auth_password = auth_password
        self.max_http_connections = max(4, int(max_http_connections))
        self.max_sse_connections = max(1, min(int(max_sse_connections), self.max_http_connections - 1))
        self.test_capabilities = {key: True for key, value in (test_capabilities or {}).items() if value}
        self.shutdown_event = threading.Event()
        self.sse_slots = threading.BoundedSemaphore(self.max_sse_connections)
        self._sse_active = 0
        self._sse_lock = threading.Lock()
        self.httpd: OdysseusHTTPServer | None = None

    def start(self) -> tuple[str, int]:
        if self.httpd is not None:
            return self.httpd.server_address[:2]
        self.shutdown_event.clear()
        self.httpd = OdysseusHTTPServer((self.host, self.port), OdysseusHandler, self)
        # Bind first. A port conflict must not leave background scheduler/CI
        # threads alive in a process that never became a server.
        try:
            self.scheduler.start()
            self.ci.start()
            self.resources.reclaim(retention_days=int(self.store.config().get("resource_retention_days", 14)))
        except BaseException:
            self.httpd.server_close()
            self.httpd = None
            raise
        return self.httpd.server_address[:2]

    def serve_forever(self) -> None:
        self.start()
        assert self.httpd is not None
        self.httpd.serve_forever(poll_interval=0.35)

    def stop(self) -> None:
        self.shutdown_event.set()
        self.ci.stop()
        if self.httpd is not None:
            self.httpd.shutdown()
            self.httpd.server_close()
            self.httpd = None
        self.scheduler.stop()

    def sse_active(self) -> int:
        with self._sse_lock:
            return self._sse_active

    def enter_sse(self) -> bool:
        if not self.sse_slots.acquire(blocking=False):
            return False
        with self._sse_lock:
            self._sse_active += 1
        return True

    def leave_sse(self) -> None:
        with self._sse_lock:
            self._sse_active = max(0, self._sse_active - 1)
        self.sse_slots.release()


class OdysseusHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 64

    def __init__(self, address: tuple[str, int], handler: type[BaseHTTPRequestHandler], app: OdysseusApp):
        self.app = app
        self._request_slots = threading.BoundedSemaphore(app.max_http_connections)
        super().__init__(address, handler)

    def process_request(self, request: Any, client_address: Any) -> None:
        if not self._request_slots.acquire(blocking=False):
            try:
                request.sendall(
                    b"HTTP/1.1 503 Service Unavailable\r\n"
                    b"Content-Length: 0\r\nConnection: close\r\nRetry-After: 2\r\n\r\n"
                )
            finally:
                self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self._request_slots.release()
            raise

    def process_request_thread(self, request: Any, client_address: Any) -> None:
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._request_slots.release()

    def handle_error(self, request: Any, client_address: Any) -> None:
        """Do not print tracebacks for ordinary transport disconnects."""

        error = sys.exc_info()[1]
        if isinstance(
            error,
            (BrokenPipeError, ConnectionAbortedError, ConnectionResetError, TimeoutError),
        ):
            return
        super().handle_error(request, client_address)


class OdysseusHandler(BaseHTTPRequestHandler):
    server: OdysseusHTTPServer
    protocol_version = "HTTP/1.1"
    server_version = f"Odysseus/{__version__}"

    def setup(self) -> None:
        super().setup()
        self.connection.settimeout(15)
        self._command_ticket = None

    def log_message(self, format: str, *args: Any) -> None:
        if self.server.app.verbose:
            super().log_message(format, *args)

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        if not self._authenticated():
            return
        if not self._host_allowed():
            self._json_error(HTTPStatus.FORBIDDEN, "invalid Host header")
            return
        parsed = urlparse(self.path)
        if parsed.path == "/api/bootstrap":
            config = self.server.app.store.config()
            lanes = ["codex", "claude", *sorted(config.get("lanes", {}).keys())]
            self._json(
                {
                    "name": "Odysseus",
                    "version": __version__,
                    "token": self.server.app.token,
                    "max_parallel": config["max_parallel"],
                    "default_lane": config["default_lane"],
                    "planner_lane": config.get("planner_lane") or config["default_lane"],
                    "review_lane": config.get("review_lane") or config["default_lane"],
                    "default_workflow": config["default_workflow"],
                    "lanes": list(dict.fromkeys(lanes)),
                    "tmux_available": self.server.app.tmux.available(),
                    "capabilities": {
                        name: bool(shutil.which(name))
                        for name in ("git", "codex", "claude", "tmux", "gh", "docker", "devcontainer")
                    },
                    "intake": self.server.app.intake.connector_capabilities(),
                    "assistant": self._assistant_bootstrap(),
                    "working_directory": str(Path.cwd()),
                    "current_repository": self.server.app.store.projects.describe(Path.cwd()),
                    "repository_url": "https://github.com/jpolec/odysseus",
                    "ci": config.get("ci") or {},
                    "test_capabilities": self.server.app.test_capabilities,
                }
            )
            return
        if parsed.path == "/api/config":
            self._json(self.server.app.store.config())
            return
        command_match = COMMAND_ROUTE.fullmatch(parsed.path)
        if command_match:
            try:
                command_id = command_match.group("command_id")
                if command_id:
                    self._json(self.server.app.commands.get(command_id))
                else:
                    query = parse_qs(parsed.query)
                    self._json({"commands": self.server.app.commands.list(limit=int(query.get("limit", ["100"])[0]))})
            except (KeyError, ValueError):
                self._json_error(HTTPStatus.NOT_FOUND, "command not found")
            return
        if parsed.path == "/api/health":
            self._json(
                {
                    "ok": True,
                    "product": "odysseus",
                    "scheduler_active": self.server.app.scheduler.active_count(),
                    "queued": sum(
                        1 for run in self.server.app.store.list() if run.get("status") == "queued"
                    ),
                    "blocked": sum(
                        1 for run in self.server.app.store.list() if run.get("status") == "blocked"
                    ),
                    "needs_attention": len(self.server.app.store.attention.list(status="open")),
                    "ci_red": sum(
                        1 for run in self.server.app.store.list() if (run.get("ci") or {}).get("status") == "failed"
                    ),
                    "http_connection_limit": self.server.app.max_http_connections,
                    "sse_connections": self.server.app.sse_active(),
                    "sse_connection_limit": self.server.app.max_sse_connections,
                }
            )
            return
        if parsed.path == "/api/runs":
            query = parse_qs(parsed.query)
            runs = self.server.app.store.list()
            project_id = str(query.get("project_id", [""])[0])
            status = str(query.get("status", [""])[0])
            if project_id:
                runs = [run for run in runs if str(run.get("project_id")) == project_id]
            if status:
                runs = [run for run in runs if str(run.get("status")) == status]
            if str(query.get("summary", [""])[0]).lower() in {"1", "true", "yes"}:
                runs = [_run_summary(run) for run in runs]
            self._json({"runs": runs})
            return
        if parsed.path == "/api/search":
            query = parse_qs(parsed.query)
            self._json({"results": search(self.server.app.store, str(query.get("q", [""])[0]))})
            return
        if parsed.path == "/api/stats":
            self._json(statistics(self.server.app.store))
            return
        if parsed.path == "/api/portfolio":
            query = parse_qs(parsed.query)
            try:
                days = int(query.get("days", ["7"])[0])
            except (TypeError, ValueError):
                days = 7
            self._json(engineering_portfolio(self.server.app.store, days=days))
            return
        if parsed.path == "/api/economics":
            query = parse_qs(parsed.query)
            privacy = str(query.get("privacy", ["redacted"])[0])
            view = str(query.get("view", ["lead"])[0])
            format_name = str(query.get("format", ["json"])[0])
            economics = outcome_economics(self.server.app.store, privacy=privacy)
            if format_name == "csv":
                self._text(economics_csv(economics, view=view), "text/csv; charset=utf-8")
            elif format_name == "ndjson":
                self._text(economics_ndjson(economics, view=view), "application/x-ndjson; charset=utf-8")
            else:
                self._json(economics)
            return
        if parsed.path == "/api/resources":
            retention = self.server.app.store.config().get("resource_retention_days", 14)
            self._json(self.server.app.resources.inspect(retention_days=int(retention)))
            return
        if parsed.path == "/api/router/export":
            query = parse_qs(parsed.query)
            self._json(self.server.app.store.outcome_router.export(str(query.get("project_id", [""])[0])))
            return
        if parsed.path == "/api/projects":
            self._json({"projects": self.server.app.store.projects.list()})
            return
        if parsed.path == "/api/tmux/sessions":
            self._json({"sessions": self.server.app.tmux.list()})
            return
        if parsed.path == "/api/inbox":
            query = parse_qs(parsed.query)
            self._json({"items": self.server.app.store.inbox.list(status=query.get("status", [None])[0])})
            return
        if parsed.path == "/api/attention":
            query = parse_qs(parsed.query)
            self._json({"items": self.server.app.store.attention.list(status=query.get("status", [None])[0])})
            return
        if parsed.path == "/api/epics":
            self._json({"epics": [_epic_summary(epic) for epic in self.server.app.store.epics.list()]})
            return
        if parsed.path == "/api/github/issues":
            query = parse_qs(parsed.query)
            try:
                project = self.server.app.store.projects.get(str(query.get("project_id", [""])[0]))
                self._json({"issues": self.server.app.github.issues(project["path"]), "project": project})
            except KeyError:
                self._json_error(HTTPStatus.NOT_FOUND, "project not found")
            except RuntimeError as exc:
                self._json_error(HTTPStatus.BAD_GATEWAY, str(exc))
            return
        router_match = PROJECT_ROUTER_ROUTE.fullmatch(parsed.path)
        if router_match:
            try:
                project_id = router_match.group("project_id")
                action = router_match.group("action") or ""
                if action == "backtest":
                    self.server.app.store.projects.get(project_id)
                    self._json(self.server.app.store.outcome_router.backtest(project_id))
                else:
                    self._json_error(HTTPStatus.METHOD_NOT_ALLOWED, "router action requires POST")
            except KeyError:
                self._json_error(HTTPStatus.NOT_FOUND, "project not found")
            return
        match = RUN_ROUTE.fullmatch(parsed.path)
        if match:
            self._get_run_route(match.group("run_id"), match.group("action"), parsed)
            return
        epic_match = EPIC_ROUTE.fullmatch(parsed.path)
        if epic_match and not epic_match.group("action"):
            try:
                epic_id = epic_match.group("epic_id")
                epic = self.server.app.store.epics.get(epic_id)
                self._json(
                    {
                        **epic,
                        "runs": self.server.app.store.epics.runs(epic_id),
                        "source_impact": self.server.app.store.epics.source_impact(epic_id),
                    }
                )
            except KeyError:
                self._json_error(HTTPStatus.NOT_FOUND, "epic not found")
            return
        attention_match = ATTENTION_ROUTE.fullmatch(parsed.path)
        if attention_match and not attention_match.group("action"):
            try:
                self._json(self.server.app.store.attention.get(attention_match.group("item_id")))
            except KeyError:
                self._json_error(HTTPStatus.NOT_FOUND, "attention item not found")
            return
        project_match = PROJECT_ROUTE.fullmatch(parsed.path)
        if project_match:
            try:
                project_id = project_match.group("project_id")
                action = project_match.group("action")
                if action == "overview":
                    self._json(self.server.app.store.knowledge.overview(project_id))
                elif action == "profile":
                    self._json(self.server.app.store.knowledge.profile(project_id))
                elif action == "skills":
                    self._json(self.server.app.store.skills.catalog(project_id))
                elif action == "knowledge":
                    self._json(self.server.app.store.knowledge.items(project_id))
                else:
                    self._json(self.server.app.store.projects.get(project_id))
            except KeyError:
                self._json_error(HTTPStatus.NOT_FOUND, "project not found")
            return
        self._static(parsed.path)

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        if not self._authenticated():
            return
        if not self._host_allowed() or not self._origin_allowed():
            self._json_error(HTTPStatus.FORBIDDEN, "request origin is not allowed")
            return
        if not secrets.compare_digest(
            self.headers.get("X-Odysseus-Token", ""), self.server.app.token
        ):
            self._json_error(HTTPStatus.FORBIDDEN, "missing or invalid Odysseus token")
            return
        parsed = urlparse(self.path)
        try:
            body = self._body()
            if not self._begin_http_command("post", parsed.path, body):
                return
            if parsed.path == "/api/config":
                changes: dict[str, Any] = {}
                for key in (
                    "max_parallel",
                    "default_lane",
                    "planner_lane",
                    "review_lane",
                    "max_retries",
                    "assistant_models",
                    "budgets",
                    "ci",
                    "resource_retention_days",
                    "outcome_router",
                    "portfolio",
                ):
                    if key in body:
                        changes[key] = body[key]
                self._json(self.server.app.store.update_config(changes))
                return
            router_match = PROJECT_ROUTER_ROUTE.fullmatch(parsed.path)
            if router_match:
                project_id = router_match.group("project_id")
                self.server.app.store.projects.get(project_id)
                action = router_match.group("action") or "recommend"
                if action == "recommend":
                    self._json(
                        self.server.app.store.outcome_router.recommend(
                            project_id,
                            task=str(body.get("task") or ""),
                            operator_default=str(body.get("operator_default") or ""),
                            request=body,
                        )
                    )
                elif action == "delete":
                    self._json(self.server.app.store.outcome_router.delete(project_id))
                elif action == "backtest":
                    self._json(self.server.app.store.outcome_router.backtest(project_id))
                else:
                    self._json_error(HTTPStatus.NOT_FOUND, "unknown router action")
                return
            if parsed.path == "/api/runs":
                request = {**body, "origin": "web", "evidence_class": "observed"}
                variants = request.get("variants") if isinstance(request.get("variants"), Mapping) else {}
                if variants.get("enabled") and not request.get("workflow"):
                    request["workflow"] = "variants"
                run = self.server.app.store.create(request)
                self._json(run, HTTPStatus.CREATED)
                return
            if parsed.path == "/api/assist":
                self._json(self._assist(body))
                return
            if parsed.path == "/api/resources/reclaim":
                retention = body.get("retention_days", self.server.app.store.config().get("resource_retention_days", 14))
                self._json(
                    self.server.app.resources.reclaim(
                        retention_days=int(retention),
                        force=bool(body.get("force")),
                    )
                )
                return
            if parsed.path == "/api/projects":
                self._json(self.server.app.store.projects.upsert(str(body.get("path") or ""), body, require_git=True), HTTPStatus.CREATED)
                return
            recommend_match = PROJECT_SKILL_RECOMMEND_ROUTE.fullmatch(parsed.path)
            if recommend_match:
                self._json(
                    self.server.app.store.skills.recommend(
                        recommend_match.group("project_id"), str(body.get("task") or "")
                    )
                )
                return
            local_skill_match = PROJECT_SKILL_LOCAL_ROUTE.fullmatch(parsed.path)
            if local_skill_match:
                self._json(
                    self.server.app.store.skills.create_local(local_skill_match.group("project_id"), body),
                    HTTPStatus.CREATED,
                )
                return
            project_match = PROJECT_ROUTE.fullmatch(parsed.path)
            if project_match and project_match.group("action") == "profile":
                self._json(self.server.app.store.knowledge.update_profile(project_match.group("project_id"), body))
                return
            if project_match and project_match.group("action") == "skills":
                self._json(self.server.app.store.skills.update_policy(project_match.group("project_id"), body))
                return
            if project_match and project_match.group("action") == "knowledge":
                self._json(self.server.app.store.knowledge.update_item(project_match.group("project_id"), body))
                return
            if parsed.path == "/api/inbox":
                self._json(self.server.app.store.inbox.create(body), HTTPStatus.CREATED)
                return
            if parsed.path == "/api/epics/plan":
                requirement = str(body.get("requirement") or "")
                project_path = str(body.get("project_path") or ".")
                source_paths = body.get("source_paths") or []
                if not isinstance(source_paths, list) or not all(isinstance(item, str) for item in source_paths):
                    raise ValueError("source_paths must be a list of decision paths")
                source_documents = []
                if source_paths:
                    project_id = str(body.get("project_id") or "")
                    project = self.server.app.store.projects.get(project_id)
                    project_path = str(project["path"])
                    source_documents = self.server.app.store.knowledge.decision_sources(project_id, source_paths)
                    if not requirement.strip():
                        titles = ", ".join(str(item.get("title") or item.get("path")) for item in source_documents)
                        requirement = f"Implement the selected architecture decisions as one coherent, verified change: {titles}."
                checks = body.get("checks") or []
                if not isinstance(checks, list) or not all(isinstance(item, str) for item in checks):
                    raise ValueError("checks must be a list of commands")
                epic = self.server.app.planner.plan(
                    requirement,
                    project_path,
                    lane=str(body.get("planner_lane") or ""),
                    title=str(body.get("title") or ""),
                    default_task_lane=str(body.get("lane") or ""),
                    default_review_lane=str(body.get("review_lane") or ""),
                    checks=checks,
                    source_documents=source_documents,
                    source_kind=str(body.get("source_kind") or "user_request"),
                )
                self._json(epic, HTTPStatus.CREATED)
                return
            if parsed.path == "/api/github/import":
                project = self.server.app.store.projects.get(str(body.get("project_id") or ""))
                checks = body.get("checks") or []
                if not isinstance(checks, list) or not all(isinstance(item, str) for item in checks):
                    raise ValueError("checks must be a list of commands")
                issue = self.server.app.github.issue(project["path"], body.get("number"))
                signal = github_issue_signal(issue, project)
                epic = self.server.app.intake.propose(
                    signal,
                    project_path=str(project["path"]),
                    lane=str(body.get("lane") or self.server.app.store.config()["default_lane"]),
                    review_lane=str(body.get("review_lane") or ""),
                    checks=checks,
                    gate_policy=str(body.get("gate_policy") or "human_review"),
                )
                self._json(epic, HTTPStatus.OK if epic.get("duplicate") else HTTPStatus.CREATED)
                return
            tmux_match = TMUX_ROUTE.fullmatch(parsed.path)
            if tmux_match:
                name = tmux_match.group("name")
                if tmux_match.group("action") == "adopt":
                    self._json(self.server.app.tmux.adopt(name), HTTPStatus.CREATED)
                elif tmux_match.group("action") == "takeover":
                    run = self.server.app.tmux.adopt(name)
                    self._json(self.server.app.tmux.takeover(run))
                else:
                    self._json_error(HTTPStatus.NOT_FOUND, "unknown tmux action")
                return
            inbox_match = INBOX_ROUTE.fullmatch(parsed.path)
            if inbox_match:
                self._post_inbox(inbox_match.group("item_id"), inbox_match.group("action"), body)
                return
            epic_match = EPIC_ROUTE.fullmatch(parsed.path)
            if epic_match and epic_match.group("action") == "refresh-sources":
                epic_id = epic_match.group("epic_id")
                refreshed = self.server.app.store.epics.refresh_local_sources(epic_id)
                self._json({**refreshed, "source_impact": self.server.app.store.epics.source_impact(epic_id)})
                return
            if epic_match and epic_match.group("action") == "plan":
                plan = body.get("plan") if isinstance(body.get("plan"), dict) else body
                epic_id = epic_match.group("epic_id")
                saved = self.server.app.store.epics.save_plan(epic_id, plan)
                self._json({**saved, "source_impact": self.server.app.store.epics.source_impact(epic_id)})
                return
            if epic_match and epic_match.group("action") == "approve":
                self._json(self.server.app.planner.approve(epic_match.group("epic_id")))
                return
            attention_match = ATTENTION_ROUTE.fullmatch(parsed.path)
            if attention_match:
                self._post_attention(
                    attention_match.group("item_id"),
                    attention_match.group("action"),
                    body,
                )
                return
            match = RUN_ROUTE.fullmatch(parsed.path)
            if not match:
                self._json_error(HTTPStatus.NOT_FOUND, "not found")
                return
            run_id = match.group("run_id")
            action = match.group("action")
            if action == "cancel":
                self._json(self.server.app.scheduler.cancel(run_id), HTTPStatus.ACCEPTED)
            elif action == "accept":
                self._json(self.server.app.actions.accept(run_id))
            elif action == "apply":
                self._json(self.server.app.actions.apply(run_id))
            elif action == "integration":
                self._json(self.server.app.actions.create_integration_delivery(run_id, body), HTTPStatus.CREATED)
            elif action == "variants":
                self._json(self.server.app.actions.decide_variants(run_id, body), HTTPStatus.CREATED)
            elif action == "send-back":
                self._json(self.server.app.actions.send_back(run_id, str(body.get("feedback", ""))))
            elif action == "resume":
                self._json(
                    self.server.app.actions.resume(
                        run_id,
                        str(body.get("prompt", "")),
                        strategy=str(body.get("strategy") or "resume"),
                        lane=str(body.get("lane") or ""),
                    ),
                    HTTPStatus.ACCEPTED,
                )
            elif action == "takeover":
                self._json(self.server.app.tmux.takeover(self.server.app.store.get(run_id)), HTTPStatus.CREATED)
            elif action == "draft-pr":
                self._json(self.server.app.actions.draft_pr(run_id))
            elif action == "ci-poll":
                self.server.app.ci.poll_once(force=True, run_id=run_id)
                self._json(self.server.app.store.get(run_id))
            else:
                self._json_error(HTTPStatus.NOT_FOUND, "unknown action")
        except (ConcurrencyConflict, IdempotencyConflict, CommandOutcomeUnknown) as exc:
            self._json_error(HTTPStatus.CONFLICT, str(exc))
        except KeyError:
            self._json_error(HTTPStatus.NOT_FOUND, "record not found")
        except (ValueError, RuntimeError) as exc:
            self._json_error(HTTPStatus.BAD_REQUEST, str(exc))
        except Exception as exc:
            self._json_error(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))

    def do_DELETE(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        if not self._authenticated():
            return
        if not self._host_allowed() or not self._origin_allowed():
            self._json_error(HTTPStatus.FORBIDDEN, "request origin is not allowed")
            return
        if not secrets.compare_digest(self.headers.get("X-Odysseus-Token", ""), self.server.app.token):
            self._json_error(HTTPStatus.FORBIDDEN, "missing or invalid Odysseus token")
            return
        parsed = urlparse(self.path)
        try:
            if not self._begin_http_command("delete", parsed.path, {}):
                return
            match = PROJECT_ROUTE.fullmatch(parsed.path)
            if not match or match.group("action"):
                self._json_error(HTTPStatus.NOT_FOUND, "not found")
                return
            self.server.app.store.projects.remove(match.group("project_id"))
            self._json({"ok": True})
        except (ConcurrencyConflict, IdempotencyConflict, CommandOutcomeUnknown) as exc:
            self._json_error(HTTPStatus.CONFLICT, str(exc))
        except KeyError:
            self._json_error(HTTPStatus.NOT_FOUND, "project not found")
        except (ValueError, RuntimeError) as exc:
            self._json_error(HTTPStatus.BAD_REQUEST, str(exc))
        except Exception as exc:
            self._json_error(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))

    def _post_inbox(self, item_id: str, action: str | None, body: Mapping[str, Any]) -> None:
        if action == "resolve":
            self._json(self.server.app.store.inbox.update(item_id, status="resolved"))
        elif action == "reopen":
            self._json(self.server.app.store.inbox.update(item_id, status="open"))
        elif action == "promote":
            item = self.server.app.store.inbox.get(item_id)
            if not item.get("project_path"):
                raise ValueError("follow-up has no project")
            run = self.server.app.store.create({"task": item["task"], "title": item["title"], "project_path": item["project_path"], "lane": body.get("lane") or self.server.app.store.config()["default_lane"], "origin": "inbox", "evidence_class": "observed"})
            self.server.app.store.inbox.update(item_id, status="promoted")
            self.server.app.store.append_event(run["id"], "inbox.promoted", "user", {"inbox_id": item_id})
            self._json(run, HTTPStatus.CREATED)
        else:
            self._json_error(HTTPStatus.NOT_FOUND, "unknown inbox action")

    def _post_attention(self, item_id: str, action: str | None, body: Mapping[str, Any]) -> None:
        if action == "resolve":
            item = self.server.app.store.attention.resolve(
                item_id, str(body.get("resolution") or "resolved")
            )
            if item.get("run_id"):
                self.server.app.store.append_event(
                    str(item["run_id"]),
                    "attention.resolved",
                    "user",
                    {"attention_id": item_id, "resolution": item["resolution"]},
                )
            self._json(item)
            return
        if action == "respond":
            response = str(body.get("response") or "")
            if response == "takeover":
                item = self.server.app.store.attention.respond(item_id, response)
                run_id = str(item.get("run_id") or "")
                if not run_id:
                    raise ValueError("attention item has no run")
                self.server.app.store.append_event(
                    run_id,
                    "attention.answered",
                    "user",
                    {"attention_id": item_id, "response": response},
                )
                self.server.app.store.attention.resolve_for_run(run_id, resolution="takeover")
                self._json(
                    {"attention": item, "takeover": self.server.app.tmux.takeover(self.server.app.store.get(run_id))},
                    HTTPStatus.CREATED,
                )
            else:
                self._json(self.server.app.actions.answer_attention(item_id, response), HTTPStatus.ACCEPTED)
            return
        self._json_error(HTTPStatus.NOT_FOUND, "unknown attention action")

    def _get_run_route(self, run_id: str, action: str | None, parsed: Any) -> None:
        try:
            if action is None:
                value = dict(self.server.app.store.get(run_id))
                value["_canonical_stream_version"] = self.server.app.store.kernel.stream_version(run_id)
                self._json(value)
            elif action == "events":
                query = parse_qs(parsed.query)
                after = int(query.get("after", ["0"])[0])
                self._json({"events": self.server.app.store.events(run_id, after=after)})
            elif action == "stream":
                self._sse(run_id, parsed)
            elif action == "diff":
                self._json(WorktreeManager.diff(self.server.app.store.get(run_id)))
            elif action == "integration-candidates":
                self._json(self.server.app.actions.integration_candidates(run_id))
            else:
                self._json_error(HTTPStatus.METHOD_NOT_ALLOWED, "use POST for this action")
        except KeyError:
            self._json_error(HTTPStatus.NOT_FOUND, "run not found")
        except ValueError as exc:
            self._json_error(HTTPStatus.BAD_REQUEST, str(exc))

    def _body(self) -> dict[str, Any]:
        try:
            size = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise ValueError("invalid Content-Length") from exc
        if size > 1_000_000:
            raise ValueError("request body is too large")
        if not size:
            return {}
        try:
            value = json.loads(self.rfile.read(size))
        except json.JSONDecodeError as exc:
            raise ValueError("request body must be valid JSON") from exc
        if not isinstance(value, dict):
            raise ValueError("request body must be a JSON object")
        return value

    def _begin_http_command(self, method: str, path: str, body: Mapping[str, Any]) -> bool:
        run_match = RUN_ROUTE.fullmatch(path)
        target_stream = f"run:{run_match.group('run_id')}" if run_match else ""
        raw_expected: Any = self.headers.get("X-Odysseus-Expected-Version")
        if raw_expected in {None, ""}:
            raw_expected = body.get("_expected_version")
        expected_version: int | None = None
        if raw_expected not in {None, ""}:
            try:
                expected_version = int(raw_expected)
            except (TypeError, ValueError) as exc:
                raise ValueError("expected stream version must be an integer") from exc
            if expected_version < 0:
                raise ValueError("expected stream version cannot be negative")
        policy_context = body.get("_policy_context") if isinstance(body.get("_policy_context"), Mapping) else {}
        ticket = self.server.app.commands.begin(
            f"http.{method}:{path}",
            body,
            idempotency_key=str(self.headers.get("Idempotency-Key") or body.get("_idempotency_key") or ""),
            actor={"type": "user", "id": str(self.headers.get("X-Odysseus-Actor") or "web-operator")},
            policy_context=policy_context,
            target_stream=target_stream,
            expected_version=expected_version,
        )
        self._command_ticket = ticket
        if ticket.replayed:
            result = ticket.receipt.get("result")
            if not isinstance(result, Mapping):
                result = {"result": result}
            self._json(result, HTTPStatus(int(ticket.receipt.get("http_status") or 200)))
            return False
        self.server.app.commands.activate(ticket)
        return True

    def _assist(self, body: Mapping[str, Any]) -> dict[str, Any]:
        provider = str(body.get("provider") or "codex").strip().lower()
        if provider not in ASSISTANT_PROVIDERS:
            raise ValueError("provider must be codex, claude, openai, or anthropic")
        messages = body.get("messages") or []
        if not isinstance(messages, list):
            raise ValueError("messages must be a list")
        messages = [item for item in messages if isinstance(item, dict)]
        instruction = str(body.get("instruction") or (messages[-1].get("content") if messages else "") or "").strip()
        if len(instruction) < 4:
            raise ValueError("message is required")
        scopes = body["scopes"] if "scopes" in body else ["task", "failure", "review", "checks"]
        if not isinstance(scopes, list):
            raise ValueError("scopes must be a list")
        scopes = [str(item).strip().lower() for item in scopes]
        include_diff = bool(body.get("include_diff"))
        run_id = str(body.get("run_id") or "").strip()
        run: Mapping[str, Any] | None = None
        diff: Mapping[str, Any] = {}
        if run_id:
            run = self.server.app.store.get(run_id)
            if include_diff:
                diff = WorktreeManager.diff(run)
        prompt, shared_context = self._assistant_prompt(provider, messages, instruction, run, diff, scopes, include_diff)
        if provider in {"codex", "claude"}:
            answer = self._call_local_assistant(provider, run, prompt)
            return {"provider": provider, "model": "local-cli", "prompt": answer.strip(), "shared_context": shared_context}
        key_env, model_env, default_model = DIRECT_ASSISTANT_PROVIDER_ENV[provider]
        api_key = os.environ.get(key_env)
        if not api_key:
            raise RuntimeError(f"set {key_env} before using direct API mode")
        configured_models = self.server.app.store.config().get("assistant_models") or {}
        model = str(
            body.get("model")
            or (configured_models.get(provider) if isinstance(configured_models, dict) else "")
            or os.environ.get(model_env)
            or default_model
        ).strip()
        if provider == "anthropic":
            answer = self._call_anthropic(api_key, model, prompt)
        else:
            answer = self._call_openai(api_key, model, prompt)
        return {"provider": provider, "model": model, "prompt": answer.strip(), "shared_context": shared_context}

    def _assistant_bootstrap(self) -> dict[str, Any]:
        configured_models = self.server.app.store.config().get("assistant_models") or {}
        direct = {
            provider: {
                "mode": "direct_api",
                "configured": bool(os.environ.get(env_name)),
                "env": env_name,
                "model": (
                    configured_models.get(provider)
                    if isinstance(configured_models, dict)
                    else ""
                )
                or os.environ.get(model_env, default_model),
                "model_env": model_env,
            }
            for provider, (env_name, model_env, default_model) in DIRECT_ASSISTANT_PROVIDER_ENV.items()
        }
        return {
            "codex": {"mode": "local_cli", "configured": bool(shutil.which("codex")), "command": "codex"},
            "claude": {"mode": "local_cli", "configured": bool(shutil.which("claude")), "command": "claude"},
            **direct,
        }

    def _assistant_prompt(
        self,
        provider: str,
        messages: list[Mapping[str, Any]],
        instruction: str,
        run: Mapping[str, Any] | None,
        diff: Mapping[str, Any],
        scopes: list[str],
        include_diff: bool,
    ) -> tuple[str, list[str]]:
        shared: list[str] = []
        context: list[str] = [
            "You are an assistant inside the Odysseus operator UI.",
            "Help the operator decide what feedback or next prompt to send to a coding agent.",
            "Answer conversationally, but make any suggested agent prompt easy to paste.",
            "Do not claim you saw repository code unless code/diff context is explicitly provided below.",
            "Local CLI helpers are launched in a temporary scratch working directory, not the task repository.",
            "Odysseus intentionally attaches only the selected context below, although a local CLI process still runs with the host filesystem permissions of the Odysseus user.",
            f"Assistant provider: {provider}.",
        ]
        if run:
            context.append("")
            context.append("Shared Odysseus context:")
            if "task" in scopes:
                shared.append("Task")
                context.extend(
                    [
                        "[Task]",
                        f"Title: {self._assistant_context_text(run.get('title'))}",
                        f"Status: {self._assistant_context_text(run.get('status'))}",
                        f"Agent lane: {self._assistant_context_text(run.get('lane'))}",
                        f"Task: {self._assistant_context_text(run.get('task'))}",
                    ]
                )
            if "failure" in scopes and run.get("last_error"):
                shared.append("Failure")
                context.extend(["[Failure]", self._assistant_context_text(run.get("last_error"), 6000)])
            if "review" in scopes and run.get("review_summary"):
                shared.append("Review")
                context.extend(["[Review]", self._assistant_context_text(run.get("review_summary"), 6000)])
            if "checks" in scopes:
                checks = run.get("check_results") or []
                if isinstance(checks, list) and checks:
                    shared.append("Checks")
                    rows = []
                    for check in checks[:12]:
                        if isinstance(check, Mapping):
                            command = self._assistant_context_text(check.get("command") or "check", 2000)
                            returncode = self._assistant_context_text(check.get("returncode"), 100)
                            rows.append(f"{command} -> {returncode}")
                    context.extend(["[Checks]", "\n".join(rows)])
            if include_diff:
                shared.append("Diff/code")
                context.extend(["[Diff/code shared by explicit opt-in]", str(_sanitize(str(diff.get("stat") or "No diff stat.")))[:4000]])
                patch = str(diff.get("patch") or "")
                if patch:
                    context.extend(["Redacted diff excerpt:", str(_sanitize(patch))[:12000]])
            else:
                context.append("[Diff/code] Not shared. The operator did not opt in.")
        prior = [
            (str(item.get("role") or "user"), str(item.get("content") or ""))
            for item in messages[-12:]
            if str(item.get("content") or "").strip() and self._assistant_message_allowed(item, scopes, include_diff)
        ]
        if prior:
            context.append("")
            context.append("Conversation so far:")
            for role, content in prior:
                context.append(f"{role.upper()}: {content[:6000]}")
        else:
            context.extend(["", f"USER: {instruction}"])
        return "\n".join(context), shared

    @staticmethod
    def _assistant_context_text(value: Any, limit: int = 6000) -> str:
        return str(_sanitize("" if value is None else str(value)))[:limit]

    @staticmethod
    def _assistant_message_allowed(message: Mapping[str, Any], scopes: list[str], include_diff: bool) -> bool:
        shared = message.get("shared_context")
        if not isinstance(shared, list):
            return str(message.get("role") or "user") == "user"
        allowed = {item[0].upper() + item[1:] for item in scopes if item}
        for item in shared:
            label = str(item)
            if label == "Diff/code" and not include_diff:
                return False
            if label != "Diff/code" and label not in allowed:
                return False
        return True

    def _call_local_assistant(self, provider: str, run: Mapping[str, Any] | None, prompt: str) -> str:
        if not shutil.which(provider):
            raise RuntimeError(f"{provider} CLI is not installed or is not on PATH")
        with tempfile.TemporaryDirectory(prefix="odysseus-assistant-") as scratch:
            scratch_path = Path(scratch)
            args = AgentRunner().command(provider, scratch_path, prompt, review=True)
            completed = subprocess.run(
                args,
                cwd=str(scratch_path),
                text=True,
                capture_output=True,
                timeout=120,
                check=False,
            )
        output = "\n".join(part for part in [completed.stdout, completed.stderr] if part)
        text_parts: list[str] = []
        for line in output.splitlines():
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            text = _extract_text(payload)
            if text:
                text_parts.append(text)
        answer = "\n".join(text_parts).strip() or output.strip()
        if completed.returncode != 0:
            raise RuntimeError(answer[-2000:] or f"{provider} exited with {completed.returncode}")
        if not answer:
            raise RuntimeError(f"{provider} returned no text")
        return str(_sanitize(answer))

    def _call_openai(self, api_key: str, model: str, prompt: str) -> str:
        payload = json.dumps(
            {
                "model": model,
                "messages": [
                    {"role": "system", "content": "Draft implementation prompts for coding agents."},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.2,
            }
        ).encode("utf-8")
        request = Request(
            "https://api.openai.com/v1/chat/completions",
            data=payload,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=60) as response:
            data = json.load(response)
        choices = data.get("choices") or []
        if not choices:
            raise RuntimeError("OpenAI returned no choices")
        return str(((choices[0].get("message") or {}).get("content")) or "")

    def _call_anthropic(self, api_key: str, model: str, prompt: str) -> str:
        payload = json.dumps(
            {
                "model": model,
                "max_tokens": 1200,
                "temperature": 0.2,
                "system": "Draft implementation prompts for coding agents.",
                "messages": [{"role": "user", "content": prompt}],
            }
        ).encode("utf-8")
        request = Request(
            "https://api.anthropic.com/v1/messages",
            data=payload,
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urlopen(request, timeout=60) as response:
            data = json.load(response)
        parts = data.get("content") or []
        text = "\n".join(str(part.get("text") or "") for part in parts if isinstance(part, dict))
        if not text:
            raise RuntimeError("Anthropic returned no text")
        return text

    def _host_allowed(self) -> bool:
        if self.server.app.allow_remote:
            return True
        raw = self.headers.get("Host", "").lower()
        host = raw.rsplit(":", 1)[0].strip("[]")
        return host in {"127.0.0.1", "localhost", "::1"}

    def _authenticated(self) -> bool:
        app = self.server.app
        if not app.auth_user:
            return True
        raw = self.headers.get("Authorization", "")
        expected = base64.b64encode(f"{app.auth_user}:{app.auth_password}".encode("utf-8")).decode("ascii")
        if raw.startswith("Basic ") and secrets.compare_digest(raw[6:], expected):
            return True
        payload = b"Authentication required"
        self.send_response(HTTPStatus.UNAUTHORIZED)
        self.send_header("WWW-Authenticate", 'Basic realm="Odysseus", charset="UTF-8"')
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self._write_payload(payload)
        return False

    def _write_payload(self, payload: bytes) -> bool:
        """Treat a client disconnect after headers as a normal HTTP outcome."""

        try:
            self.wfile.write(payload)
            return True
        except (BrokenPipeError, ConnectionResetError, OSError):
            self.close_connection = True
            return False

    def _origin_allowed(self) -> bool:
        if self.server.app.allow_remote:
            return True
        origin = self.headers.get("Origin")
        if not origin:
            return True
        host = (urlparse(origin).hostname or "").lower()
        return host in {"127.0.0.1", "localhost", "::1"}

    def _json(self, value: Mapping[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        command_headers: dict[str, str] = {}
        ticket = getattr(self, "_command_ticket", None)
        if ticket is not None:
            if ticket.replayed:
                receipt = ticket.receipt
            else:
                receipt = self.server.app.commands.finish(ticket, value, http_status=int(status))
            command = receipt.get("command") if isinstance(receipt.get("command"), Mapping) else {}
            command_headers = {
                "X-Odysseus-Command-Id": str(command.get("command_id") or ""),
                "X-Odysseus-Command-State": str(receipt.get("state") or ""),
                "X-Odysseus-Idempotent-Replay": "true" if ticket.replayed else "false",
            }
            self._command_ticket = None
        redacted, _receipt = DEFAULT_REDACTION_ENGINE.redact(value, boundary="http_json")
        if (
            isinstance(value, Mapping)
            and isinstance(redacted, dict)
            and value.get("name") == "Odysseus"
            and "token" in value
        ):
            redacted["token"] = value["token"]
        payload = json.dumps(redacted, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        for name, header_value in command_headers.items():
            if header_value:
                self.send_header(name, header_value)
        self.end_headers()
        self._write_payload(payload)

    def _text(self, value: str, content_type: str, status: HTTPStatus = HTTPStatus.OK) -> None:
        redacted, _receipt = DEFAULT_REDACTION_ENGINE.redact(value, boundary="http_text")
        payload = str(redacted).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        self._write_payload(payload)

    def _json_error(self, status: HTTPStatus, message: str) -> None:
        self._json({"error": message}, status)

    def _sse(self, run_id: str, parsed: Any) -> None:
        self.server.app.store.get(run_id)
        if not self.server.app.enter_sse():
            self.send_response(HTTPStatus.SERVICE_UNAVAILABLE)
            self.send_header("Content-Length", "0")
            self.send_header("Retry-After", "2")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            return
        query = parse_qs(parsed.query)
        header_after = self.headers.get("Last-Event-ID", "0")
        try:
            after = int(query.get("after", [header_after])[0])
        except ValueError:
            after = 0
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache, no-transform")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        last_ping = time.monotonic()
        try:
            while not self.server.app.shutdown_event.is_set():
                events = self.server.app.store.events(run_id, after=after, limit=250)
                for event in events:
                    after = int(event["seq"])
                    redacted, _receipt = DEFAULT_REDACTION_ENGINE.redact(event, boundary="sse_event")
                    payload = json.dumps(redacted, ensure_ascii=False, separators=(",", ":"))
                    frame = f"id: {after}\nevent: odysseus\ndata: {payload}\n\n".encode("utf-8")
                    self.wfile.write(frame)
                if events:
                    self.wfile.flush()
                    last_ping = time.monotonic()
                elif time.monotonic() - last_ping >= 10:
                    self.wfile.write(b": keepalive\n\n")
                    self.wfile.flush()
                    last_ping = time.monotonic()
                self.server.app.shutdown_event.wait(0.35)
        except (BrokenPipeError, ConnectionResetError, OSError):
            return
        finally:
            # BaseHTTPRequestHandler otherwise attempts to parse another HTTP/1.1
            # request after an EventSource client has disconnected.
            self.close_connection = True
            self.server.app.leave_sse()

    def _static(self, requested: str) -> None:
        routes = {"/": "index.html", "/index.html": "index.html", "/app.js": "app.js", "/styles.css": "styles.css", "/odysseus-icon.svg": "odysseus-icon.svg"}
        relative = routes.get(requested)
        if relative is None:
            self._json_error(HTTPStatus.NOT_FOUND, "not found")
            return
        path = self.server.app.static_root / relative
        try:
            payload = path.read_bytes()
        except OSError:
            self._json_error(HTTPStatus.NOT_FOUND, "web asset not found")
            return
        media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", f"{media_type}; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Content-Security-Policy", "default-src 'self'; connect-src 'self'; style-src 'self'; script-src 'self'")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        self._write_payload(payload)
