from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from odysseus.lifecycle import ResourceLifecycle
from odysseus.lifecycle import ServerLease
from odysseus.store import RunStore
from odysseus.worktrees import WorktreeManager


def git(repo: Path, *args: str, check: bool = True) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=check,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ).stdout.strip()


class LifecycleLeaseTests(unittest.TestCase):
    def test_only_one_server_can_own_a_state_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            first = ServerLease(temp)
            second = ServerLease(temp)
            first.acquire()
            try:
                with self.assertRaisesRegex(RuntimeError, "another Odysseus server"):
                    second.acquire()
            finally:
                first.release()
            second.acquire()
            second.release()

    def test_server_refuses_active_maintenance(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            lock = Path(temp) / "runtime" / "maintenance.lock"
            lock.mkdir(parents=True)
            (lock / "owner.json").write_text(
                json.dumps({"pid": os.getpid(), "token": "installer"}),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(RuntimeError, "maintenance is active"):
                ServerLease(temp).acquire()

    def test_reclaim_removes_delivered_worktree_and_runtime_but_keeps_branch(self) -> None:
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
            store = RunStore(root / "state")
            run = store.create({"task": "deliver a change", "project_path": str(repo)})
            info = WorktreeManager(store.worktrees_dir).create(run, lambda *_args: None)
            (Path(info["worktree_path"]) / "feature.txt").write_text("feature\n")
            runtime = store.root / "runtime" / run["id"]
            runtime.mkdir(parents=True)
            (runtime / "scratch.txt").write_text("scratch\n")
            store.update(
                run["id"],
                **info,
                status="accepted",
                delivery={"status": "applied", "delivered_at": "2020-01-01T00:00:00Z"},
            )

            lifecycle = ResourceLifecycle(store)
            preview = lifecycle.inspect(retention_days=1)
            self.assertEqual(preview["totals"]["reclaimable_worktrees"], 1)
            self.assertEqual(preview["totals"]["reclaimable_runtime_directories"], 1)
            result = lifecycle.reclaim(retention_days=1)

            self.assertFalse(Path(info["worktree_path"]).exists())
            self.assertFalse(runtime.exists())
            self.assertEqual(result["errors"], [])
            self.assertIn(info["branch"], git(repo, "branch", "--format=%(refname:short)"))
            updated = store.get(run["id"])
            self.assertIsNone(updated["worktree_path"])
            self.assertTrue(updated["resource_reclaimed_at"])

    def test_delivery_status_matrix_controls_reclaim_eligibility(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            repo.mkdir()
            store = RunStore(root / "state")
            cases = [
                ("applied", "accepted", "applied", True),
                ("draft-pr", "pr_created", "pr_created", True),
                ("integrated-applied", "accepted", "integrated_applied", True),
                ("integrated-pr", "accepted", "integrated_pr_created", True),
                ("not-applied", "accepted", "not_applied", False),
                ("integration-queued", "accepted", "integration_queued", False),
                ("failed-recovery", "failed", "not_applied", False),
            ]
            for name, status, delivery_status, _expected in cases:
                run = store.create({"title": name, "task": name, "project_path": str(repo)})
                worktree = store.worktrees_dir / name
                worktree.mkdir(parents=True)
                (worktree / "marker.txt").write_text(name, encoding="utf-8")
                store.update(
                    run["id"],
                    status=status,
                    worktree_path=str(worktree),
                    delivery={"status": delivery_status, "delivered_at": "2020-01-01T00:00:00Z"},
                    finished_at="2020-01-01T00:00:00Z",
                )

            preview = ResourceLifecycle(store).inspect(retention_days=1)
            records = {item["title"]: item for item in preview["worktrees"]}

            for name, _status, _delivery_status, expected in cases:
                self.assertEqual(records[name]["force_reclaimable"], expected, name)
                self.assertEqual(records[name]["reclaimable"], expected, name)

    def test_reclaim_keeps_failed_worktree_for_recovery(self) -> None:
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
            store = RunStore(root / "state")
            run = store.create({"task": "recover me", "project_path": str(repo)})
            info = WorktreeManager(store.worktrees_dir).create(run, lambda *_args: None)
            store.update(run["id"], **info, status="failed", finished_at="2020-01-01T00:00:00Z")

            result = ResourceLifecycle(store).reclaim(retention_days=1, force=True)

            self.assertTrue(Path(info["worktree_path"]).is_dir())
            self.assertEqual(result["reclaimed"], [])

    def test_reclaim_keeps_orphan_runtime_with_live_owner(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            store = RunStore(Path(temp) / "state")
            runtime = store.root / "runtime" / "orphan-active"
            runtime.mkdir(parents=True)
            (runtime / "owner.json").write_text(json.dumps({"pid": os.getpid()}), encoding="utf-8")
            (runtime / "scratch.txt").write_text("scratch\n", encoding="utf-8")

            lifecycle = ResourceLifecycle(store)
            preview = lifecycle.inspect(retention_days=0)
            [record] = [item for item in preview["runtime_directories"] if item["path"] == str(runtime)]
            self.assertFalse(record["reclaimable"])
            self.assertFalse(record["force_reclaimable"])
            self.assertIn("live owner", record["reason"])

            result = lifecycle.reclaim(retention_days=0, force=True)

            self.assertTrue(runtime.is_dir())
            self.assertEqual(result["reclaimed"], [])


if __name__ == "__main__":
    unittest.main()
