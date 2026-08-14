"""Small GitHub CLI adapter used for issue intake."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any


class GitHubBridge:
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
