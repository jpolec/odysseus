"""Local HTTP API, static web UI, and Server-Sent Events transport."""

from __future__ import annotations

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
from .scheduler import ReviewActions, Scheduler
from .store import RunStore
from .worktrees import WorktreeManager


RUN_ROUTE = re.compile(
    r"^/api/runs/(?P<run_id>[A-Za-z0-9_.-]+)(?:/(?P<action>events|stream|diff|cancel|accept|send-back|draft-pr))?$"
)


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
    server_version = "Odysseus/0.1"

    def log_message(self, format: str, *args: Any) -> None:
        if self.server.app.verbose:
            super().log_message(format, *args)

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
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
                    "default_workflow": config["default_workflow"],
                    "lanes": list(dict.fromkeys(lanes)),
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
                }
            )
            return
        if parsed.path == "/api/runs":
            self._json({"runs": self.server.app.store.list()})
            return
        match = RUN_ROUTE.fullmatch(parsed.path)
        if match:
            self._get_run_route(match.group("run_id"), match.group("action"), parsed)
            return
        self._static(parsed.path)

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
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
            elif action == "draft-pr":
                self._json(self.server.app.actions.draft_pr(run_id))
            else:
                self._json_error(HTTPStatus.NOT_FOUND, "unknown action")
        except KeyError:
            self._json_error(HTTPStatus.NOT_FOUND, "run not found")
        except (ValueError, RuntimeError) as exc:
            self._json_error(HTTPStatus.BAD_REQUEST, str(exc))
        except Exception as exc:
            self._json_error(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))

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
        self.send_header("Content-Security-Policy", "default-src 'self'; connect-src 'self'; style-src 'self'; script-src 'self'")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        self.wfile.write(payload)
