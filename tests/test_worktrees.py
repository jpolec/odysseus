from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from odysseus.worktrees import IntegrationError, WorktreeManager


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

    def test_accepted_artifacts_are_composed_into_a_downstream_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            repo.mkdir()
            git(repo, "init", "-b", "main")
            git(repo, "config", "user.name", "Odysseus Test")
            git(repo, "config", "user.email", "odysseus@example.test")
            (repo / "base.txt").write_text("base\n")
            git(repo, "add", ".")
            git(repo, "commit", "-m", "base")
            manager = WorktreeManager(root / "worktrees")
            emit = lambda *_args: None

            left = manager.create({"id": "left", "project_path": str(repo)}, emit)
            (Path(left["worktree_path"]) / "backend.txt").write_text("backend\n")
            left.update(manager.snapshot(left))
            left["id"] = "left"

            right = manager.create({"id": "right", "project_path": str(repo)}, emit)
            (Path(right["worktree_path"]) / "frontend.txt").write_text("frontend\n")
            right.update(manager.snapshot(right))
            right["id"] = "right"

            downstream = manager.create({"id": "integration", "project_path": str(repo)}, emit)
            downstream["id"] = "integration"
            result = manager.integrate(downstream, [left, right], emit)
            target = Path(downstream["worktree_path"])

            self.assertEqual((target / "backend.txt").read_text(), "backend\n")
            self.assertEqual((target / "frontend.txt").read_text(), "frontend\n")
            self.assertEqual(result["merge_analysis"]["risk"], "medium")
            self.assertEqual(len(result["integration_sources"]), 2)

    def test_conflicting_artifacts_stop_on_the_isolated_integration_branch(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            repo.mkdir()
            git(repo, "init", "-b", "main")
            git(repo, "config", "user.name", "Odysseus Test")
            git(repo, "config", "user.email", "odysseus@example.test")
            (repo / "shared.txt").write_text("base\n")
            git(repo, "add", ".")
            git(repo, "commit", "-m", "base")
            manager = WorktreeManager(root / "worktrees")
            events: list[tuple[str, dict]] = []
            emit = lambda event, _source, data: events.append((event, dict(data)))

            artifacts = []
            for run_id, content in (("one", "one\n"), ("two", "two\n")):
                item = manager.create({"id": run_id, "project_path": str(repo)}, emit)
                (Path(item["worktree_path"]) / "shared.txt").write_text(content)
                item.update(manager.snapshot(item))
                item["id"] = run_id
                artifacts.append(item)
            downstream = manager.create({"id": "join", "project_path": str(repo)}, emit)
            downstream["id"] = "join"

            with self.assertRaises(IntegrationError):
                manager.integrate(downstream, artifacts, emit)

            conflict = [data for event, data in events if event == "integration.conflict"][-1]
            self.assertEqual(conflict["conflicts"], ["shared.txt"])
            self.assertEqual(conflict["risk"], "high")


if __name__ == "__main__":
    unittest.main()
