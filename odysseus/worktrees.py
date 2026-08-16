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


class IntegrationError(GitError):
    """Raised when accepted dependency artifacts cannot be composed safely."""


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
    def changed_files(run: Mapping[str, Any]) -> list[str]:
        """Return the complete artifact surface relative to the run base."""

        worktree = Path(str(run.get("worktree_path") or ""))
        base_sha = str(run.get("base_sha") or "")
        artifact_sha = str(run.get("artifact_sha") or "HEAD")
        if not worktree.is_dir() or not base_sha:
            return []
        tracked = _run(
            [
                "git",
                "-C",
                str(worktree),
                "diff",
                "--name-only",
                "--diff-filter=ACDMRTUXB",
                base_sha,
                artifact_sha,
            ],
            check=False,
        ).stdout.splitlines()
        untracked = _run(
            ["git", "-C", str(worktree), "ls-files", "--others", "--exclude-standard"],
            check=False,
        ).stdout.splitlines()
        return sorted({item.strip() for item in [*tracked, *untracked] if item.strip()})

    @staticmethod
    def snapshot(run: Mapping[str, Any], *, reason: str = "accepted") -> dict[str, Any]:
        """Create a durable local commit without pushing or merging it elsewhere."""

        worktree = Path(str(run.get("worktree_path") or ""))
        if not worktree.is_dir():
            raise GitError("run has no worktree to snapshot")
        _run(["git", "-C", str(worktree), "add", "-A"])
        dirty = _run(["git", "-C", str(worktree), "status", "--porcelain"]).stdout.strip()
        if dirty:
            title = str(run.get("title") or run.get("id") or "task")[:70]
            _run(["git", "-C", str(worktree), "commit", "-m", f"Odysseus {reason}: {title}"])
        sha = _run(["git", "-C", str(worktree), "rev-parse", "HEAD"]).stdout.strip()
        value = dict(run)
        value["artifact_sha"] = sha
        return {"artifact_sha": sha, "artifact_files": WorktreeManager.changed_files(value)}

    @staticmethod
    def apply_to_repository(run: Mapping[str, Any]) -> dict[str, Any]:
        """Merge a durable task artifact into its clean source checkout.

        The complete artifact branch is merged, rather than cherry-picking only
        its final snapshot commit, because a DAG task may contain composed
        predecessor artifacts. A failed merge is aborted before returning.
        """

        project_path = str(run.get("project_path") or "")
        artifact_sha = str(run.get("artifact_sha") or "")
        base_sha = str(run.get("base_sha") or "")
        base_ref = str(run.get("base_ref") or "")
        if not project_path or not artifact_sha or not base_sha or not base_ref:
            raise GitError("the accepted task is missing repository or artifact metadata")

        repo = WorktreeManager.repository(project_path)
        branch_result = _run(
            ["git", "-C", str(repo), "symbolic-ref", "--quiet", "--short", "HEAD"],
            check=False,
        )
        target_branch = branch_result.stdout.strip()
        if branch_result.returncode or not target_branch:
            raise GitError("the source checkout is detached; check out the task base branch first")
        expected_branch = base_ref.removeprefix("refs/heads/")
        if expected_branch == "HEAD" or target_branch != expected_branch:
            raise GitError(
                f"the source checkout is on {target_branch}, but this task targets {expected_branch}"
            )

        if _run(
            ["git", "-C", str(repo), "cat-file", "-e", f"{artifact_sha}^{{commit}}"],
            check=False,
        ).returncode:
            raise GitError("the accepted artifact commit is no longer available in this repository")

        before_sha = _run(["git", "-C", str(repo), "rev-parse", "HEAD"]).stdout.strip()
        # A previously integrated artifact is safe to acknowledge even when the
        # operator has started new local work since the merge.
        if _run(
            ["git", "-C", str(repo), "merge-base", "--is-ancestor", artifact_sha, before_sha],
            check=False,
        ).returncode == 0:
            return {
                "status": "applied",
                "method": "local_merge",
                "target_branch": target_branch,
                "target_before_sha": before_sha,
                "target_after_sha": before_sha,
                "delivered_at": None,
                "error": "",
                "already_applied": True,
            }

        # Tracked edits can be silently included in or disturbed by a merge, so
        # they remain a hard gate. Harmless untracked files are allowed: Git
        # itself refuses the merge if an artifact would overwrite one.
        dirty = _run(
            ["git", "-C", str(repo), "status", "--porcelain", "--untracked-files=no"]
        ).stdout.splitlines()
        if dirty:
            paths = [line[3:].strip() for line in dirty[:5] if len(line) > 3]
            detail = f" Local changes: {', '.join(paths)}." if paths else ""
            raise GitError(
                "the source checkout has tracked local changes; commit or stash "
                f"them before applying this task.{detail}"
            )

        if _run(
            ["git", "-C", str(repo), "merge-base", "--is-ancestor", base_sha, before_sha],
            check=False,
        ).returncode:
            raise GitError(
                "the source branch no longer descends from the task base; "
                "create a pull request or rebase the task before applying it"
            )

        merge = _run(
            ["git", "-C", str(repo), "merge", "--no-edit", artifact_sha],
            check=False,
            timeout=300,
        )
        if merge.returncode:
            conflicts = _run(
                ["git", "-C", str(repo), "diff", "--name-only", "--diff-filter=U"],
                check=False,
            ).stdout.splitlines()
            merge_head = _run(
                ["git", "-C", str(repo), "rev-parse", "--verify", "-q", "MERGE_HEAD"],
                check=False,
            )
            abort = None
            if merge_head.returncode == 0:
                abort = _run(["git", "-C", str(repo), "merge", "--abort"], check=False)
            if abort is not None and abort.returncode:
                raise GitError(
                    "applying the artifact failed and Git could not abort the merge; "
                    f"inspect {repo} before continuing"
                )
            detail = merge.stderr.strip() or merge.stdout.strip() or "Git merge failed"
            conflict_note = f" Conflicts: {', '.join(conflicts)}." if conflicts else ""
            raise GitError(f"the artifact could not be applied; the merge was aborted.{conflict_note} {detail}")

        after_sha = _run(["git", "-C", str(repo), "rev-parse", "HEAD"]).stdout.strip()
        return {
            "status": "applied",
            "method": "local_merge",
            "target_branch": target_branch,
            "target_before_sha": before_sha,
            "target_after_sha": after_sha,
            "delivered_at": None,
            "error": "",
            "already_applied": False,
        }

    @staticmethod
    def analyze_dependencies(dependencies: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
        """Predict cross-task file overlap before attempting an integration merge."""

        surfaces: dict[str, set[str]] = {}
        for dependency in dependencies:
            run_id = str(dependency.get("id") or "")
            files = dependency.get("artifact_files")
            if not isinstance(files, list) or not files:
                files = WorktreeManager.changed_files(dependency)
            surfaces[run_id] = {str(item) for item in files if str(item)}
        overlaps: list[dict[str, Any]] = []
        ids = list(surfaces)
        for index, left in enumerate(ids):
            for right in ids[index + 1 :]:
                common = sorted(surfaces[left] & surfaces[right])
                if common:
                    overlaps.append({"left": left, "right": right, "files": common})
        source_count = len(dependencies)
        risk = "high" if overlaps else "medium" if source_count > 1 else "low" if source_count else "none"
        return {
            "risk": risk,
            "source_count": source_count,
            "overlaps": overlaps,
            "files": sorted({item for values in surfaces.values() for item in values}),
        }

    @staticmethod
    def unmerged_files(worktree: Path | str) -> list[str]:
        result = _run(
            ["git", "-C", str(worktree), "diff", "--name-only", "--diff-filter=U"],
            check=False,
        )
        return [item for item in result.stdout.splitlines() if item]

    @staticmethod
    def head(worktree: Path | str) -> str:
        return _run(["git", "-C", str(worktree), "rev-parse", "HEAD"]).stdout.strip()

    @staticmethod
    def integrate(
        run: Mapping[str, Any],
        dependencies: Sequence[Mapping[str, Any]],
        emit: Callable[[str, str, Mapping[str, Any]], None],
        *,
        allow_conflicts: bool = False,
    ) -> dict[str, Any]:
        """Merge accepted dependency artifacts into the downstream task branch."""

        worktree = Path(str(run.get("worktree_path") or ""))
        if not worktree.is_dir():
            raise IntegrationError("run has no worktree for dependency integration")
        analysis = WorktreeManager.analyze_dependencies(dependencies)
        sources: list[dict[str, str]] = []
        integration_conflicts: list[dict[str, Any]] = []
        emit("integration.started", "git", analysis)
        for dependency in dependencies:
            dependency_id = str(dependency.get("id") or "")
            sha = str(dependency.get("artifact_sha") or "")
            if not sha:
                raise IntegrationError(f"dependency {dependency_id} has no durable artifact")
            if Path(str(dependency.get("project_path") or "")).resolve() != Path(
                str(run.get("project_path") or "")
            ).resolve():
                raise IntegrationError(f"dependency {dependency_id} belongs to another repository")
            ancestor = _run(
                ["git", "-C", str(worktree), "merge-base", "--is-ancestor", sha, "HEAD"],
                check=False,
            )
            if ancestor.returncode != 0:
                result = _run(
                    [
                        "git",
                        "-C",
                        str(worktree),
                        "merge",
                        "--no-ff",
                        "-m",
                        f"Odysseus integrate {dependency_id}",
                        sha,
                    ],
                    check=False,
                    timeout=180,
                )
                if result.returncode != 0:
                    conflicts = WorktreeManager.unmerged_files(worktree)
                    detail = {
                        **analysis,
                        "dependency_run_id": dependency_id,
                        "artifact_sha": sha,
                        "conflicts": [item for item in conflicts if item],
                        "preserved_branches": [
                            str(run.get("branch") or "integration worktree"),
                            str(dependency.get("branch") or dependency.get("artifact_sha") or dependency_id),
                        ],
                        "message": f"Dependency artifact {dependency_id} conflicts with the integration branch.",
                    }
                    emit("integration.conflict", "git", detail)
                    if allow_conflicts:
                        integration_conflicts.append(detail)
                        sources.append({"run_id": dependency_id, "artifact_sha": sha})
                        break
                    _run(["git", "-C", str(worktree), "merge", "--abort"], check=False)
                    raise IntegrationError(detail["message"])
            sources.append({"run_id": dependency_id, "artifact_sha": sha})
            emit(
                "integration.artifact_applied",
                "git",
                {"dependency_run_id": dependency_id, "artifact_sha": sha},
            )
        head = _run(["git", "-C", str(worktree), "rev-parse", "HEAD"]).stdout.strip()
        result = {
            "integration_sources": sources,
            "integration_head": head,
            "integration_conflicts": integration_conflicts,
            "merge_analysis": analysis,
        }
        if not integration_conflicts:
            emit("integration.completed", "git", {**analysis, "integration_head": head})
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

    @staticmethod
    def push_update(run: Mapping[str, Any]) -> str:
        """Snapshot and push a new attempt to an already published task branch."""

        worktree = Path(str(run.get("worktree_path") or ""))
        branch = str(run.get("branch") or "")
        if not worktree.is_dir() or not branch or not run.get("pull_request_url"):
            raise GitError("run has no existing pull request branch")
        artifact = WorktreeManager.snapshot(run, reason="CI retry")
        _run(["git", "-C", str(worktree), "push", "origin", branch], timeout=300)
        return str(artifact["artifact_sha"])
