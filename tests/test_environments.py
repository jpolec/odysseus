from __future__ import annotations

import json
import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from odysseus.environments import EnvironmentManager, normalize_environment_request, wrap_command
from odysseus.runners import CheckRunner
from odysseus.scheduler import ReviewActions, Scheduler
from odysseus.store import RunStore


class EnvironmentTests(unittest.TestCase):
    @staticmethod
    def _git_repo(path: Path) -> None:
        subprocess.run(["git", "init", "-b", "main", str(path)], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        subprocess.run(["git", "-C", str(path), "config", "user.name", "Odysseus Test"], check=True)
        subprocess.run(["git", "-C", str(path), "config", "user.email", "odysseus@example.test"], check=True)
        (path / "README.md").write_text("test\n")
        subprocess.run(["git", "-C", str(path), "add", "README.md"], check=True)
        subprocess.run(["git", "-C", str(path), "commit", "-m", "base"], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def test_secret_values_are_never_accepted_into_persistent_configuration(self) -> None:
        with self.assertRaisesRegex(ValueError, "allow_env"):
            normalize_environment_request({"env": {"OPENAI_API_KEY": "secret-value"}})
        request = normalize_environment_request(
            {"profile": "docker", "image": "agent:test", "allow_env": ["OPENAI_API_KEY"]}
        )
        self.assertEqual(request["allow_env"], ["OPENAI_API_KEY"])
        self.assertNotIn("secret-value", json.dumps(request))

    def test_host_plan_allocates_preview_port_and_private_env_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            worktree = root / "worktree"
            worktree.mkdir()
            manager = EnvironmentManager(root / "state")
            events: list[tuple[str, str, dict]] = []
            with mock.patch("odysseus.environments._allocate_port", return_value=43123):
                plan = manager.prepare(
                    {
                        "id": "run-1",
                        "environment_request": {
                            "profile": "host",
                            "env": {"APP_MODE": "test"},
                            "ports": {"APP_PORT": 3000},
                        },
                    },
                    worktree,
                    {},
                    lambda event_type, source, data: events.append((event_type, source, dict(data))),
                )
            mode = stat.S_IMODE(Path(plan["env_file"]).stat().st_mode)
            args, cwd, environment = wrap_command(plan, ["/usr/bin/env"], worktree, phase="check")

            self.assertEqual(plan["profile"], "host")
            self.assertEqual(mode, 0o600)
            self.assertEqual(plan["ports"]["APP_PORT"]["container"], 3000)
            self.assertGreater(plan["ports"]["APP_PORT"]["host"], 0)
            self.assertEqual(environment["APP_MODE"], "test")
            self.assertEqual(environment["APP_PORT"], str(plan["ports"]["APP_PORT"]["host"]))
            self.assertEqual(args, ["/usr/bin/env"])
            self.assertEqual(cwd, worktree)
            self.assertEqual(events[0][0], "environment.prepared")

    def test_docker_wrapper_scopes_mounts_resources_network_ports_and_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as temp, mock.patch.dict(
            os.environ, {"OPENAI_API_KEY": "never-persist-this"}, clear=False
        ):
            root = Path(temp)
            worktree = root / "worktree"
            worktree.mkdir()
            self._git_repo(worktree)
            manager = EnvironmentManager(root / "state")
            with mock.patch("odysseus.environments.shutil.which", return_value="/usr/bin/docker"), mock.patch(
                "odysseus.environments._allocate_port", return_value=43124
            ):
                plan = manager.prepare(
                    {
                        "id": "run-2",
                        "project_path": str(worktree),
                        "branch": "main",
                        "environment_request": {
                            "profile": "docker",
                            "image": "agent:test",
                            "network": "bridge",
                            "allow_env": ["OPENAI_API_KEY"],
                            "ports": {"APP_PORT": 3000},
                            "cpus": 2,
                            "memory": "4g",
                        },
                    },
                    worktree,
                    {},
                    lambda *_: None,
                )
            args, cwd, environment = wrap_command(
                plan,
                ["codex", "exec", "-C", str(worktree), "do work"],
                worktree,
                phase="agent",
            )
            rendered = " ".join(args)

            self.assertIn("docker run", rendered)
            self.assertIn("--read-only", args)
            self.assertIn("no-new-privileges", args)
            self.assertIn("--cap-drop ALL", rendered)
            self.assertIn("--cpus 2.0", rendered)
            self.assertIn("--memory 4g", rendered)
            self.assertIn("--network bridge", rendered)
            self.assertIn("/workspace", args)
            self.assertIn("OPENAI_API_KEY", args)
            self.assertNotIn("never-persist-this", rendered)
            self.assertNotIn("never-persist-this", Path(plan["env_file"]).read_text())
            self.assertEqual(cwd, worktree)
            self.assertEqual(environment["OPENAI_API_KEY"], "never-persist-this")

    def test_untrusted_projects_require_operator_controlled_docker(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            worktree = root / "worktree"
            worktree.mkdir()
            manager = EnvironmentManager(root / "state")
            for profile in ("host", "devcontainer"):
                request = {"profile": profile}
                if profile == "devcontainer":
                    (worktree / ".devcontainer.json").write_text("{}")
                with self.assertRaisesRegex(ValueError, "require the Docker profile"):
                    manager.prepare(
                        {"id": f"run-{profile}", "untrusted_project": True, "environment_request": request},
                        worktree,
                        {},
                        lambda *_: None,
                    )

    def test_untrusted_repository_command_gate_can_be_approved_once(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / "project"
            project.mkdir()
            store = RunStore(root / "state")
            run = store.create(
                {
                    "task": "Inspect safely",
                    "project_path": str(project),
                    "environment": {"profile": "docker", "image": "agent:test"},
                    "untrusted_project": True,
                }
            )
            store.update(
                run["id"],
                status="attention",
                environment={"profile": "docker", "status": "awaiting_approval", "trust_status": "pending"},
            )
            store.append_event(
                run["id"],
                "agent.permission_request",
                "odysseus",
                {"title": "Approve repository execution configuration", "message": "- npm test", "options": ["approve", "reject"]},
            )
            item = store.attention.list(status="open", run_id=run["id"])[0]
            actions = ReviewActions(store, Scheduler(store))

            result = actions.answer_attention(item["id"], "approve")

            self.assertEqual(result["run"]["status"], "queued")
            self.assertTrue(result["run"]["project_commands_approved"])
            self.assertEqual(result["run"]["environment"]["trust_status"], "approved")
            self.assertIn("environment.approved", [event["type"] for event in store.events(run["id"])])

    @unittest.skipUnless(os.environ.get("ODYSSEUS_DOCKER_TEST") == "1", "set ODYSSEUS_DOCKER_TEST=1")
    def test_real_docker_check_sees_isolated_git_and_review_is_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / "project"
            project.mkdir()
            self._git_repo(project)
            worktree = root / "task-worktree"
            subprocess.run(
                ["git", "-C", str(project), "worktree", "add", "-b", "odysseus/docker-proof", str(worktree)],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            manager = EnvironmentManager(root / "state")
            plan = manager.prepare(
                {
                    "id": "docker-proof",
                    "project_path": str(project),
                    "branch": "odysseus/docker-proof",
                    "environment_request": {
                        "profile": "docker",
                        "image": "node:20-bookworm",
                        "network": "none",
                        "env": {"PROOF_VALUE": "isolated"},
                    },
                },
                worktree,
                {},
                lambda *_: None,
            )
            runner = CheckRunner()
            events: list[tuple[str, str, dict]] = []
            result = runner.run(
                "git status --short && test \"$PROOF_VALUE\" = isolated && "
                "printf 'container proof\\n' > docker-proof.txt && printf 'runner output\\n'",
                worktree,
                emit=lambda event_type, source, data: events.append((event_type, source, dict(data))),
                cancelled=lambda: False,
                execution=plan,
            )
            review_write = runner.run(
                "printf 'must fail' > review-write.txt",
                worktree,
                emit=lambda *_: None,
                cancelled=lambda: False,
                execution=plan,
                phase="review",
            )

            self.assertEqual(result.returncode, 0, result.output)
            self.assertEqual((worktree / "docker-proof.txt").read_text(), "container proof\n")
            self.assertFalse((worktree / "review-write.txt").exists())
            self.assertNotEqual(review_write.returncode, 0)
            self.assertTrue(events)


if __name__ == "__main__":
    unittest.main()
