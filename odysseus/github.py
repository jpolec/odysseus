"""Small GitHub CLI adapter used for issue intake."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any


class GitHubBridge:
    @staticmethod
    def _gh(args: list[str], project_path: Path | str, *, timeout: int = 20, accepted: set[int] | None = None) -> str:
        if not shutil.which("gh"):
            raise RuntimeError("GitHub CLI (gh) is not installed")
        path = Path(project_path).expanduser().resolve()
        try:
            result = subprocess.run(
                ["gh", *args],
                cwd=path,
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("GitHub query timed out") from exc
        except OSError as exc:
            raise RuntimeError(f"GitHub CLI could not start: {exc}") from exc
        if result.returncode not in (accepted or {0}):
            raise RuntimeError(result.stderr.strip() or "GitHub query failed")
        return result.stdout

    @staticmethod
    def issues(project_path: Path | str, *, limit: int = 50) -> list[dict[str, Any]]:
        if not shutil.which("gh"):
            raise RuntimeError("GitHub CLI (gh) is not installed")
        path = Path(project_path).expanduser().resolve()
        try:
            result = subprocess.run(
                [
                    "gh",
                    "issue",
                    "list",
                    "--limit",
                    str(max(1, min(limit, 100))),
                    "--state",
                    "open",
                    "--json",
                    "number,title,url,state,labels,assignees,updatedAt,body",
                ],
                cwd=path,
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=12,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("GitHub issue query timed out") from exc
        except OSError as exc:
            raise RuntimeError(f"GitHub CLI could not start: {exc}") from exc
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "GitHub issue query failed")
        try:
            value = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError("GitHub CLI returned invalid JSON") from exc
        return value if isinstance(value, list) else []

    @classmethod
    def checks(cls, pull_request_url: str, project_path: Path | str) -> dict[str, Any]:
        """Return a normalized pull-request check state and best-effort failed logs."""

        raw = cls._gh(
            [
                "pr",
                "checks",
                pull_request_url,
                "--json",
                "name,state,bucket,link,workflow",
            ],
            project_path,
            accepted={0, 8},  # gh uses 8 while checks are still pending
        )
        try:
            value = json.loads(raw or "[]")
        except json.JSONDecodeError as exc:
            raise RuntimeError("GitHub CLI returned invalid check JSON") from exc
        checks = value if isinstance(value, list) else []
        failing = [item for item in checks if str(item.get("bucket") or item.get("state") or "").lower() in {"fail", "cancel", "failure", "cancelled", "timed_out", "action_required"}]
        pending = [item for item in checks if str(item.get("bucket") or item.get("state") or "").lower() in {"pending", "queued", "in_progress", "waiting", "requested"}]
        status = "failed" if failing else "pending" if pending or not checks else "passed"
        logs = ""
        if failing:
            link = str(failing[0].get("link") or "")
            match = re.search(r"/actions/runs/(\d+)", link)
            if match:
                try:
                    logs = cls._gh(
                        ["run", "view", match.group(1), "--log-failed"],
                        project_path,
                        timeout=45,
                    )[-40_000:]
                except RuntimeError as exc:
                    logs = f"Failed log unavailable: {exc}"
        return {
            "status": status,
            "checks": checks,
            "summary": (
                f"{len(failing)} failed, {len(pending)} pending, {len(checks) - len(failing) - len(pending)} passed"
                if checks
                else "GitHub has not reported any checks yet"
            ),
            "logs": logs,
        }

    @classmethod
    def review_comments(cls, pull_request_url: str, project_path: Path | str) -> list[dict[str, Any]]:
        raw = cls._gh(
            ["pr", "view", pull_request_url, "--json", "reviews,comments"],
            project_path,
        )
        try:
            value = json.loads(raw or "{}")
        except json.JSONDecodeError as exc:
            raise RuntimeError("GitHub CLI returned invalid review JSON") from exc
        values: list[dict[str, Any]] = []
        for kind in ("reviews", "comments"):
            for item in value.get(kind) or []:
                if isinstance(item, dict):
                    values.append({"kind": kind[:-1], **item})
        return values
