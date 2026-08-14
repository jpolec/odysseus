"""Git worktree isolation and review artifacts for Odysseus runs."""

from __future__ import annotations

import difflib
import os
import re
import subprocess
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence


class GitError(RuntimeError):
    pass


def _run(
    args: Sequence[str],
    *,
    cwd: Path | None = None,
    check: bool = True,
    timeout: int = 120,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        list(args),
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
    )
    if check and result.returncode:
        detail = result.stderr.strip() or result.stdout.strip() or f"exit {result.returncode}"
        raise GitError(f"{' '.join(args)}: {detail}")
    return result


def _safe_component(value: str, limit: int = 64) -> str:
    value = re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip(".-")
    return (value or "run")[:limit]


class WorktreeManager:
    def __init__(self, root: Path | str) -> None:
        self.root = Path(root).expanduser()
        self.root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def repository(path: Path | str) -> Path:
        source = Path(path).expanduser().resolve()
        result = _run(["git", "-C", str(source), "rev-parse", "--show-toplevel"])
        return Path(result.stdout.strip()).resolve()

    @staticmethod
    def _base_ref(repo: Path, requested: str) -> str:
        if requested:
            _run(["git", "-C", str(repo), "rev-parse", "--verify", requested])
            return requested
        result = _run(
            ["git", "-C", str(repo), "symbolic-ref", "--quiet", "--short", "HEAD"],
            check=False,
        )
        return result.stdout.strip() if result.returncode == 0 else "HEAD"

    def create(
        self,
        run: Mapping[str, Any],
        emit: Callable[[str, str, Mapping[str, Any]], None],
    ) -> dict[str, Any]:
        existing = run.get("worktree_path")
        if existing and Path(str(existing)).is_dir():
            return {
                "project_path": str(run.get("project_path") or self.repository(str(existing))),
                "worktree_path": str(Path(str(existing)).resolve()),
                "branch": str(run.get("branch") or ""),
                "base_ref": str(run.get("base_ref") or "HEAD"),
                "base_sha": str(run.get("base_sha") or ""),
                "base_was_dirty": bool(run.get("base_was_dirty")),
            }

        repo = self.repository(str(run["project_path"]))
        base_ref = self._base_ref(repo, str(run.get("base_ref") or ""))
        base_sha = _run(["git", "-C", str(repo), "rev-parse", base_ref]).stdout.strip()
        dirty = bool(_run(["git", "-C", str(repo), "status", "--porcelain"], check=True).stdout.strip())
        branch = f"odysseus/{_safe_component(str(run['id']), 72)}"
        repo_key = f"{_safe_component(repo.name, 36)}-{base_sha[:8]}"
        destination = (self.root / repo_key / _safe_component(str(run["id"]), 90)).resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)

        emit("worktree.creating", "git", {"base_ref": base_ref, "base_sha": base_sha})
        if dirty:
            emit(
                "worktree.dirty_base",
                "git",
                {"message": "The source checkout has uncommitted changes; the task starts from HEAD."},
            )
        if destination.is_dir():
            recovered = self.repository(destination)
            if recovered != destination:
                raise GitError(f"existing worktree path resolves unexpectedly: {destination}")
        else:
            branch_exists = (
                _run(
                    ["git", "-C", str(repo), "show-ref", "--verify", "--quiet", f"refs/heads/{branch}"],
                    check=False,
                ).returncode
                == 0
            )
            command = ["git", "-C", str(repo), "worktree", "add"]
            if branch_exists:
                command.extend([str(destination), branch])
            else:
                command.extend(["-b", branch, str(destination), base_sha])
            _run(command, timeout=180)
        result = {
            "project_path": str(repo),
            "worktree_path": str(destination),
            "branch": branch,
            "base_ref": base_ref,
            "base_sha": base_sha,
            "base_was_dirty": dirty,
        }
        emit("worktree.ready", "git", result)
        return result

    @staticmethod
    def diff(run: Mapping[str, Any], limit: int = 600_000) -> dict[str, Any]:
        worktree = Path(str(run.get("worktree_path") or ""))
        base_sha = str(run.get("base_sha") or "")
        if not worktree.is_dir() or not base_sha:
            return {"patch": "", "stat": "", "truncated": False, "untracked": []}

        stat = _run(
            ["git", "-C", str(worktree), "diff", "--stat", base_sha], check=False
        ).stdout
        patch = _run(
            [
                "git",
                "-C",
                str(worktree),
                "diff",
                "--no-ext-diff",
                "--src-prefix=a/",
                "--dst-prefix=b/",
                base_sha,
            ],
            check=False,
        ).stdout
        untracked_result = _run(
            ["git", "-C", str(worktree), "ls-files", "--others", "--exclude-standard"],
            check=False,
        )
        untracked = [item for item in untracked_result.stdout.splitlines() if item]
        for relative in untracked:
            if len(patch) >= limit:
                break
            path = (worktree / relative).resolve()
            try:
                if not path.is_relative_to(worktree.resolve()) or path.stat().st_size > 256_000:
                    continue
                raw = path.read_bytes()
                if b"\0" in raw:
                    patch += f"\nBinary file b/{relative} added\n"
                    continue
                text = raw.decode("utf-8", errors="replace").splitlines(keepends=True)
            except OSError:
                continue
            patch += "".join(
                difflib.unified_diff([], text, fromfile="/dev/null", tofile=f"b/{relative}")
            )
        truncated = len(patch) > limit
        if truncated:
            patch = patch[:limit] + "\n\n[diff truncated by Odysseus]\n"
        if untracked:
            suffix = "\n".join(f" {name} | new file" for name in untracked)
            stat = f"{stat.rstrip()}\n{suffix}\n"
        return {"patch": patch, "stat": stat, "truncated": truncated, "untracked": untracked}

    @staticmethod
    def draft_pr(run: Mapping[str, Any]) -> str:
        worktree = Path(str(run.get("worktree_path") or ""))
        branch = str(run.get("branch") or "")
        base_ref = str(run.get("base_ref") or "main")
        if not worktree.is_dir() or not branch:
            raise GitError("run has no worktree or branch")

        _run(["git", "-C", str(worktree), "add", "-A"])
        dirty = _run(["git", "-C", str(worktree), "status", "--porcelain"]).stdout.strip()
        if dirty:
            message = f"Odysseus: {str(run.get('title') or run.get('id'))[:70]}"
            _run(["git", "-C", str(worktree), "commit", "-m", message])
        _run(["git", "-C", str(worktree), "push", "-u", "origin", branch], timeout=300)

        body = (
            "Created from an Odysseus review gate.\n\n"
            f"Run: `{run.get('id')}`\n"
            f"Workflow: `{run.get('workflow')}`\n"
            f"Lane: `{run.get('lane')}`\n"
        )
        result = _run(
            [
                "gh",
                "pr",
                "create",
                "--draft",
                "--base",
                base_ref,
                "--head",
                branch,
                "--title",
                str(run.get("title") or run.get("id")),
                "--body",
                body,
            ],
            cwd=worktree,
            timeout=300,
        )
        url = result.stdout.strip().splitlines()[-1] if result.stdout.strip() else ""
        if not url.startswith("http"):
            raise GitError(result.stderr.strip() or "gh did not return a pull request URL")
        return url
