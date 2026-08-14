from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from odysseus.worktrees import WorktreeManager


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ).stdout.strip()


class WorktreeTests(unittest.TestCase):
    def test_task_gets_branch_worktree_and_review_diff(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            repo.mkdir()
            git(repo, "init", "-b", "main")
            git(repo, "config", "user.name", "Odysseus Test")
            git(repo, "config", "user.email", "odysseus@example.test")
            (repo / "tracked.txt").write_text("before\n")
            git(repo, "add", "tracked.txt")
            git(repo, "commit", "-m", "base")

            events: list[str] = []
            manager = WorktreeManager(root / "worktrees")
            info = manager.create(
                {"id": "run-1", "project_path": str(repo), "base_ref": ""},
                lambda event_type, _source, _data: events.append(event_type),
            )
            worktree = Path(info["worktree_path"])
            (worktree / "tracked.txt").write_text("after\n")
            (worktree / "new.txt").write_text("new\n")
            diff = manager.diff(info)

            self.assertEqual(info["branch"], "odysseus/run-1")
            self.assertIn("worktree.ready", events)
            self.assertIn("-before", diff["patch"])
            self.assertIn("+after", diff["patch"])
            self.assertIn("b/new.txt", diff["patch"])

            recovered = manager.create(
                {"id": "run-1", "project_path": str(repo), "base_ref": ""},
                lambda _event_type, _source, _data: None,
            )
            self.assertEqual(recovered["worktree_path"], info["worktree_path"])


if __name__ == "__main__":
    unittest.main()
