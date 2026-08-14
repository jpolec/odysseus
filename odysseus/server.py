"""Local HTTP API, static web UI, and Server-Sent Events transport."""

from __future__ import annotations

import base64
import json
import mimetypes
import re
import secrets
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import parse_qs, urlparse

from . import __version__
from .planner import EpicPlanner
from .scheduler import ReviewActions, Scheduler
from .github import GitHubBridge
from .store import RunStore
from .tmux import TmuxBridge
from .worktrees import WorktreeManager


RUN_ROUTE = re.compile(r"^/api/runs/(?P<run_id>[A-Za-z0-9_.-]+)(?:/(?P<action>events|stream|diff|cancel|accept|send-back|resume|takeover|draft-pr))?$")
TMUX_ROUTE = re.compile(r"^/api/tmux/sessions/(?P<name>[A-Za-z0-9_.-]+)(?:/(?P<action>adopt|takeover))?$")
PROJECT_ROUTE = re.compile(r"^/api/projects/(?P<project_id>[A-Za-z0-9_.-]+)$")
INBOX_ROUTE = re.compile(r"^/api/inbox/(?P<item_id>[A-Za-z0-9_.-]+)(?:/(?P<action>resolve|reopen|promote))?$")
EPIC_ROUTE = re.compile(r"^/api/epics/(?P<epic_id>[A-Za-z0-9_.-]+)(?:/(?P<action>approve))?$")
ATTENTION_ROUTE = re.compile(r"^/api/attention/(?P<item_id>[A-Za-z0-9_.-]+)(?:/(?P<action>respond|resolve))?$")


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
    ) -> None:
        self.store = store
        self.host = host
        self.port = port
        self.allow_remote = allow_remote
        self.verbose = verbose
        self.static_root = static_root or Path(__file__).resolve().parent.parent / "web"
        self.token = secrets.token_urlsafe(24)
        self.scheduler = scheduler or Scheduler(store)
        self.actions = ReviewActions(store, self.scheduler)
        self.planner = EpicPlanner(store)
        self.tmux = TmuxBridge(store)
        self.github = GitHubBridge()
        self.auth_user = auth_user
        self.auth_password = auth_password
        self.httpd: OdysseusHTTPServer | None = None

    def start(self) -> tuple[str, int]:
        if self.httpd is not None:
            return self.httpd.server_address[:2]
        self.scheduler.start()
        self.httpd = OdysseusHTTPServer((self.host, self.port), OdysseusHandler, self)
        return self.httpd.server_address[:2]

    def serve_forever(self) -> None:
        self.start()
        assert self.httpd is not None
        self.httpd.serve_forever(poll_interval=0.35)

    def stop(self) -> None:
        if self.httpd is not None:
            self.httpd.shutdown()
            self.httpd.server_close()
            self.httpd = None
        self.scheduler.stop()


class OdysseusHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], handler: type[BaseHTTPRequestHandler], app: OdysseusApp):
        self.app = app
        super().__init__(address, handler)


class OdysseusHandler(BaseHTTPRequestHandler):
    server: OdysseusHTTPServer
    protocol_version = "HTTP/1.1"
    server_version = "Odysseus/0.3"

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
                    "repository_url": "https://github.com/jpolec/odysseus",
                }
            )
            return
        if parsed.path == "/api/health":
            self._json(
                {
                    "ok": True,
                    "scheduler_active": self.server.app.scheduler.active_count(),
                    "queued": sum(
                        1 for run in self.server.app.store.list() if run.get("status") == "queued"
                    ),
                    "blocked": sum(
                        1 for run in self.server.app.store.list() if run.get("status") == "blocked"
                    ),
                    "needs_attention": len(self.server.app.store.attention.list(status="open")),
                }
            )
            return
        if parsed.path == "/api/runs":
            self._json({"runs": self.server.app.store.list()})
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
            self._json({"epics": self.server.app.store.epics.list()})
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
        match = RUN_ROUTE.fullmatch(parsed.path)
        if match:
            self._get_run_route(match.group("run_id"), match.group("action"), parsed)
            return
        epic_match = EPIC_ROUTE.fullmatch(parsed.path)
        if epic_match and not epic_match.group("action"):
            try:
                epic_id = epic_match.group("epic_id")
                epic = self.server.app.store.epics.get(epic_id)
                self._json({**epic, "runs": self.server.app.store.epics.runs(epic_id)})
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
            if parsed.path == "/api/runs":
                run = self.server.app.store.create(body)
                self._json(run, HTTPStatus.CREATED)
                return
            if parsed.path == "/api/projects":
                self._json(self.server.app.store.projects.upsert(str(body.get("path") or ""), body), HTTPStatus.CREATED)
                return
            if parsed.path == "/api/inbox":
                self._json(self.server.app.store.inbox.create(body), HTTPStatus.CREATED)
                return
            if parsed.path == "/api/epics/plan":
                requirement = str(body.get("requirement") or "")
                project_path = str(body.get("project_path") or ".")
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
                )
                self._json(epic, HTTPStatus.CREATED)
                return
            if parsed.path == "/api/github/import":
                project = self.server.app.store.projects.get(str(body.get("project_id") or ""))
                title = str(body.get("title") or "GitHub issue")
                url = str(body.get("url") or "")
                issue_body = str(body.get("body") or "")
                task = f"Implement GitHub issue: {title}\n\n{issue_body}"
                if url:
                    task += f"\n\nIssue: {url}"
                run = self.server.app.store.create({"task": task, "title": title, "project_path": project["path"], "lane": body.get("lane") or self.server.app.store.config()["default_lane"]})
                self._json(run, HTTPStatus.CREATED)
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
            elif action == "send-back":
                self._json(self.server.app.actions.send_back(run_id, str(body.get("feedback", ""))))
            elif action == "resume":
                self._json(self.server.app.actions.resume(run_id, str(body.get("prompt", ""))), HTTPStatus.ACCEPTED)
            elif action == "takeover":
                self._json(self.server.app.tmux.takeover(self.server.app.store.get(run_id)), HTTPStatus.CREATED)
            elif action == "draft-pr":
                self._json(self.server.app.actions.draft_pr(run_id))
            else:
                self._json_error(HTTPStatus.NOT_FOUND, "unknown action")
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
        match = PROJECT_ROUTE.fullmatch(urlparse(self.path).path)
        if not match:
            self._json_error(HTTPStatus.NOT_FOUND, "not found")
            return
        try:
            self.server.app.store.projects.remove(match.group("project_id"))
            self._json({"ok": True})
        except KeyError:
            self._json_error(HTTPStatus.NOT_FOUND, "project not found")

    def _post_inbox(self, item_id: str, action: str | None, body: Mapping[str, Any]) -> None:
        if action == "resolve":
            self._json(self.server.app.store.inbox.update(item_id, status="resolved"))
        elif action == "reopen":
            self._json(self.server.app.store.inbox.update(item_id, status="open"))
        elif action == "promote":
            item = self.server.app.store.inbox.get(item_id)
            if not item.get("project_path"):
                raise ValueError("follow-up has no project")
            run = self.server.app.store.create({"task": item["task"], "title": item["title"], "project_path": item["project_path"], "lane": body.get("lane") or self.server.app.store.config()["default_lane"]})
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
                self._json(self.server.app.store.get(run_id))
            elif action == "events":
                query = parse_qs(parsed.query)
                after = int(query.get("after", ["0"])[0])
                self._json({"events": self.server.app.store.events(run_id, after=after)})
            elif action == "stream":
                self._sse(run_id, parsed)
            elif action == "diff":
                self._json(WorktreeManager.diff(self.server.app.store.get(run_id)))
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
        self.wfile.write(payload)
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
        payload = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        self.wfile.write(payload)

    def _json_error(self, status: HTTPStatus, message: str) -> None:
        self._json({"error": message}, status)

    def _sse(self, run_id: str, parsed: Any) -> None:
        self.server.app.store.get(run_id)
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
            while True:
                events = self.server.app.store.events(run_id, after=after, limit=250)
                for event in events:
                    after = int(event["seq"])
                    payload = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
                    frame = f"id: {after}\nevent: odysseus\ndata: {payload}\n\n".encode("utf-8")
                    self.wfile.write(frame)
                if events:
                    self.wfile.flush()
                    last_ping = time.monotonic()
                elif time.monotonic() - last_ping >= 10:
                    self.wfile.write(b": keepalive\n\n")
                    self.wfile.flush()
                    last_ping = time.monotonic()
                time.sleep(0.35)
        except (BrokenPipeError, ConnectionResetError, OSError):
            return
        finally:
            # BaseHTTPRequestHandler otherwise attempts to parse another HTTP/1.1
            # request after an EventSource client has disconnected.
            self.close_connection = True

    def _static(self, requested: str) -> None:
        routes = {"/": "index.html", "/index.html": "index.html", "/app.js": "app.js", "/styles.css": "styles.css"}
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
        self.wfile.write(payload)
