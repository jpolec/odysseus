"""GitHub CI feedback loop for published Odysseus task branches."""

from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from typing import Any

from .events import now_iso
from .github import GitHubBridge
from .store import RunStore


def _age_seconds(value: Any) -> float:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return max(0.0, (datetime.now(timezone.utc) - parsed).total_seconds())
    except (TypeError, ValueError):
        return 1e12


class CIWatcher:
    """Poll PR checks and resume the original agent with actionable failures."""

    def __init__(
        self,
        store: RunStore,
        actions: Any,
        *,
        bridge: GitHubBridge | None = None,
        poll_seconds: float | None = None,
    ) -> None:
        self.store = store
        self.actions = actions
        self.bridge = bridge or GitHubBridge()
        configured = store.config().get("ci") or {}
        self.poll_seconds = float(poll_seconds or configured.get("poll_seconds") or 30)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        if not bool((self.store.config().get("ci") or {}).get("watch", True)):
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="odysseus-ci", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 5) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=timeout)

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.poll_once()
            except Exception:
                # An individual run records its own bridge errors. A watcher
                # must never take down the HTTP server or scheduler.
                pass
            self._stop.wait(max(5.0, self.poll_seconds))

    def poll_once(self, *, force: bool = False, run_id: str = "") -> list[str]:
        changed: list[str] = []
        config = self.store.config().get("ci") or {}
        for run in self.store.list():
            if run_id and str(run.get("id")) != run_id:
                continue
            if run.get("status") != "pr_created" or not run.get("pull_request_url"):
                continue
            ci = dict(run.get("ci") or {})
            if not force and _age_seconds(ci.get("updated_at")) < max(5.0, self.poll_seconds * 0.8):
                continue
            try:
                result = self.bridge.checks(
                    str(run["pull_request_url"]),
                    str(run["project_path"]),
                )
            except RuntimeError as exc:
                ci.update({"status": "poll_error", "summary": str(exc), "updated_at": now_iso()})
                self.store.update(str(run["id"]), ci=ci)
                self.store.append_event(
                    str(run["id"]), "ci.poll_failed", "github", {"message": str(exc)}
                )
                continue
            self._ingest_review_feedback(run)
            previous = str(ci.get("status") or "not_started")
            ci.update(
                {
                    "status": result["status"],
                    "checks": result["checks"],
                    "summary": result["summary"],
                    "logs": result.get("logs") or "",
                    "updated_at": now_iso(),
                }
            )
            self.store.update(str(run["id"]), ci=ci)
            if result["status"] == previous:
                continue
            changed.append(str(run["id"]))
            if result["status"] == "passed":
                self.store.append_event(
                    str(run["id"]), "ci.passed", "github", {"message": result["summary"]}
                )
                continue
            if result["status"] == "pending":
                self.store.append_event(
                    str(run["id"]), "ci.started", "github", {"message": result["summary"]}
                )
                continue
            self._handle_failure(run, ci, config)
        return changed

    def _ingest_review_feedback(self, run: dict[str, Any]) -> None:
        if not hasattr(self.bridge, "review_comments"):
            return
        try:
            comments = self.bridge.review_comments(
                str(run["pull_request_url"]), str(run["project_path"])
            )
        except RuntimeError:
            return
        seen = {str(item) for item in run.get("github_feedback_seen") or []}
        changed = False
        for item in comments[:100]:
            body = str(item.get("body") or "").strip()
            state = str(item.get("state") or "").upper()
            if not body and state != "CHANGES_REQUESTED":
                continue
            author = item.get("author") if isinstance(item.get("author"), dict) else {}
            key = str(
                item.get("id")
                or item.get("url")
                or f"{author.get('login', '')}:{item.get('submittedAt', '')}:{body}"
            )
            if key in seen:
                continue
            seen.add(key)
            changed = True
            message = body or "A reviewer requested changes on the pull request."
            self.store.append_event(
                str(run["id"]),
                "review.comment",
                "github",
                {
                    "title": f"PR feedback from {author.get('login') or 'reviewer'}",
                    "message": message,
                    "state": state,
                    "url": item.get("url") or run.get("pull_request_url"),
                    "options": [
                        {"id": "fix", "label": "Send to agent"},
                        {"id": "takeover", "label": "Continue in terminal"},
                        {"id": "ignore", "label": "Resolve without changes"},
                    ],
                },
            )
        if changed:
            self.store.update(str(run["id"]), github_feedback_seen=sorted(seen)[-500:])

    def _handle_failure(self, run: dict[str, Any], ci: dict[str, Any], config: dict[str, Any]) -> None:
        run_id = str(run["id"])
        attempt = int(ci.get("attempt") or 0)
        maximum = max(0, int(config.get("max_attempts") or 0))
        message = str(ci.get("summary") or "GitHub checks failed")
        self.store.append_event(
            run_id,
            "ci.failed",
            "github",
            {
                "message": message,
                "attempt": attempt,
                "max_attempts": maximum,
                "options": [
                    {"id": "resume", "label": "Resume original agent"},
                    {"id": "takeover", "label": "Continue in terminal"},
                ],
            },
        )
        if not bool(config.get("auto_resume", True)):
            return
        if attempt >= maximum:
            self.store.append_event(
                run_id,
                "ci.retry_exhausted",
                "odysseus",
                {"message": f"CI is still red after {attempt} automatic repair attempts."},
            )
            return
        ci["attempt"] = attempt + 1
        ci["status"] = "repairing"
        ci["updated_at"] = now_iso()
        self.store.update(run_id, ci=ci, ci_retry_active=True)
        logs = str(ci.get("logs") or "No failed log was available from GitHub.")[-35_000:]
        review_context = "\n\n".join(
            str(item.get("message") or "")
            for item in self.store.attention.list(status="open", run_id=run_id)
            if item.get("type") == "review_comment" and item.get("message")
        )
        prompt = (
            "GitHub CI failed on the existing draft pull request. Diagnose the failure, make the "
            "smallest correct fix in this same worktree, and preserve the task intent.\n\n"
            f"CI summary: {message}\n\nFailed logs:\n{logs}"
            + (f"\n\nNew pull-request review feedback:\n{review_context}" if review_context else "")
        )
        self.actions.resume(run_id, prompt)
        self.store.append_event(
            run_id,
            "ci.retry_queued",
            "odysseus",
            {"attempt": attempt + 1, "max_attempts": maximum},
        )
