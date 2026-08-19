from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from odysseus.projects import repository_identity
from odysseus.store import RUN_SCHEMA_VERSION, RunStore


class StoreTests(unittest.TestCase):
    def test_repository_identity_normalizes_https_and_ssh_remotes(self) -> None:
        self.assertEqual(
            repository_identity("https://github.com/jpolec/odysseus.git"),
            {"provider": "github.com", "repository": "jpolec/odysseus", "repository_name": "odysseus"},
        )
        self.assertEqual(
            repository_identity("git@gitlab.example.com:group/platform/api.git"),
            {"provider": "gitlab.example.com", "repository": "group/platform/api", "repository_name": "api"},
        )

    def test_project_uses_repository_name_and_keeps_checkout_folder_separate(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / "old-folder-name"
            project.mkdir()
            subprocess.run(["git", "init", "-q", str(project)], check=True)
            subprocess.run(
                ["git", "-C", str(project), "remote", "add", "origin", "https://github.com/jpolec/odysseus.git"],
                check=True,
            )
            store = RunStore(root / "state")

            described = store.projects.describe(project)
            self.assertEqual(described["name"], "odysseus")
            self.assertEqual(store.projects.list(), [])
            registered = store.projects.upsert(project)

            self.assertEqual(registered["name"], "odysseus")
            self.assertTrue(registered["git_repository"])
            self.assertEqual(registered["repository"], "jpolec/odysseus")
            self.assertEqual(registered["folder_name"], "old-folder-name")
            self.assertEqual(registered["name_source"], "automatic")
            renamed = store.projects.upsert(project, {"name": "Odysseus Control"})
            self.assertEqual(renamed["name"], "Odysseus Control")
            self.assertEqual(store.projects.get(registered["id"])["name"], "Odysseus Control")
            store.projects.remove(registered["id"])
            self.assertEqual(store.projects.list(), [])
            self.assertTrue(project.is_dir())

            plain_folder = root / "not-a-repository"
            plain_folder.mkdir()
            with self.assertRaisesRegex(ValueError, "not a Git repository"):
                store.projects.upsert(plain_folder, require_git=True)

    def test_internal_odysseus_worktrees_are_not_user_projects(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            store = RunStore(Path(temp) / "state")
            internal = store.worktrees_dir / "source" / "task-run"
            internal.mkdir(parents=True)

            registered = store.projects.upsert(internal)

            self.assertEqual(store.projects.list(), [])
            self.assertEqual(store.projects.get(registered["id"])["path"], str(internal.resolve()))

    def test_run_and_events_are_durable_json_and_ndjson(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / "project"
            project.mkdir()
            store = RunStore(root / "state")
            run = store.create({"task": "Build the thing", "project_path": str(project)})
            store.append_event(run["id"], "step.started", "odysseus", {"step": "agent"})

            persisted = json.loads((store.runs_dir / f"{run['id']}.json").read_text())
            lines = (store.events_dir / f"{run['id']}.ndjson").read_text().splitlines()
            events = [json.loads(line) for line in lines]

            self.assertEqual(persisted["event_seq"], 3)
            self.assertEqual([event["seq"] for event in events], [1, 2, 3])
            self.assertEqual(events[0]["type"], "run.queued")
            self.assertEqual(events[1]["type"], "context.receipt.created")

    def test_migration_derives_route_observation_from_existing_outcome_routing(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / "project"
            project.mkdir()
            store = RunStore(root / "state")
            run = store.create({"task": "Migrate route observation", "project_path": str(project)})
            path = store.runs_dir / f"{run['id']}.json"
            legacy = json.loads(path.read_text(encoding="utf-8"))
            legacy["schema_version"] = 12
            legacy.pop("route_observation", None)
            path.write_text(json.dumps(legacy, indent=2, sort_keys=True) + "\n", encoding="utf-8")

            migrated = RunStore(root / "state").get(run["id"])

            self.assertEqual(migrated["schema_version"], RUN_SCHEMA_VERSION)
            self.assertEqual(migrated["route_observation"]["format"], "odysseus-route-observation-v1")
            self.assertEqual(migrated["route_observation"]["task_class"], "implementer-api")
            self.assertEqual(migrated["route_observation"]["upcast"]["source"], "run.outcome_routing")

    def test_run_title_falls_back_to_task_when_title_is_null(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / "project"
            project.mkdir()
            store = RunStore(root / "state")

            run = store.create(
                {"title": None, "task": "Fix the popup\nwith details", "project_path": str(project)}
            )

            self.assertEqual(run["title"], "Fix the popup")
            self.assertNotIn("none", run["id"].lower())

    def test_persistent_config_updates_concurrency(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            store = RunStore(Path(temp) / "state")
            config = store.update_config({"max_parallel": 4})
            self.assertEqual(config["max_parallel"], 4)
            self.assertEqual(RunStore(store.root).config()["max_parallel"], 4)

    def test_claim_enforces_global_parallel_limit(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / "project"
            project.mkdir()
            store = RunStore(root / "state")
            first = store.create({"task": "First", "project_path": str(project)})
            second = store.create({"task": "Second", "project_path": str(project)})

            self.assertIsNotNone(store.claim(first["id"], max_parallel=1))
            self.assertIsNone(store.claim(second["id"], max_parallel=1))

    def test_queued_run_can_be_cancelled_without_a_worker(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / "project"
            project.mkdir()
            store = RunStore(root / "state")
            run = store.create({"task": "Cancel me", "project_path": str(project)})

            cancelled = store.request_cancel(run["id"])

            self.assertEqual(cancelled["status"], "cancelled")
            self.assertFalse(cancelled["cancel_requested"])
            self.assertEqual(store.events(run["id"])[-1]["type"], "run.cancelled")

    def test_projects_inbox_and_usage_are_aggregated(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / "project"
            project.mkdir()
            store = RunStore(root / "state")
            run = store.create({"task": "Measure", "project_path": str(project)})
            self.assertEqual(len(store.projects.list()), 1)
            item = store.inbox.create({"title": "Later", "task": "Do it", "project_path": str(project)})
            self.assertEqual(store.inbox.get(item["id"])["status"], "open")
            store.append_event(run["id"], "agent.session", "codex", {"phase": "agent", "session_id": "thread-1"})
            store.append_event(run["id"], "agent.tool.started", "codex", {"tool": "shell"})
            store.append_event(run["id"], "agent.usage", "codex", {"input_tokens": 100, "cached_input_tokens": 80, "output_tokens": 10})
            measured = store.get(run["id"])
            self.assertEqual(measured["agent_sessions"]["agent"], "thread-1")
            self.assertEqual(measured["metrics"]["input_tokens"], 100)
            self.assertEqual(measured["metrics"]["tool_calls"], 1)

    def test_redacted_vendor_usage_does_not_crash_the_run(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / "project"
            project.mkdir()
            store = RunStore(root / "state")
            run = store.create({"task": "Measure safely", "project_path": str(project)})
            store.append_event(
                run["id"],
                "agent.usage",
                "claude",
                {
                    "session_id": "thread-redacted",
                    "input_tokens": "[REDACTED]",
                    "cached_input_tokens": "[REDACTED]",
                    "output_tokens": "[REDACTED]",
                    "cumulative": True,
                },
            )
            self.assertEqual(store.get(run["id"])["metrics"]["input_tokens"], 0)

    def test_scheduler_runtime_scan_reuses_redacted_persisted_snapshots(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / "project"
            project.mkdir()
            store = RunStore(root / "state")
            store.create(
                {
                    "task": "Never persist ghp_abcdefghijklmnop1234",
                    "project_path": str(project),
                }
            )

            with mock.patch.object(store, "_redact_snapshot", wraps=store._redact_snapshot) as redact:
                public = store.list()
                self.assertGreater(redact.call_count, 0)
                redact.reset_mock()
                runtime = store.runtime_runs()
                self.assertEqual(redact.call_count, 0)

            self.assertNotIn("ghp_abcdefghijklmnop1234", json.dumps(public))
            self.assertNotIn("ghp_abcdefghijklmnop1234", json.dumps(runtime))

            cached = store.runtime_runs()
            self.assertEqual(cached[0]["status"], "queued")
            store.update(cached[0]["id"], status="blocked")
            refreshed = store.runtime_runs()
            self.assertEqual(refreshed[0]["status"], "blocked")

    def test_durable_run_and_event_boundaries_redact_adversarial_payloads(self) -> None:
        secret = "ghp_abcdefghijklmnop1234"
        bearer = "Bearer abcdefghijklmnop"
        env_value = "OPENAI_API_KEY=sk-abcdefghijklmnop1234"
        traceback = "Traceback (most recent call last):\n  RuntimeError: password=supersecretvalue"
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / "project"
            project.mkdir()
            store = RunStore(root / "state")
            run = store.create(
                {
                    "title": f"Fix leak {secret}",
                    "task": f"Handle nested {secret}",
                    "project_path": str(project),
                    "checks": [f"curl -H 'Authorization: {bearer}'"],
                    "environment": {"allow_env": ["SERVICE_TOKEN"]},
                }
            )
            store.update(
                run["id"],
                last_error=traceback,
                check_results=[{"command": "cat .env", "output": env_value}],
                review_summary={"nested": {"api_key": "plain-api-key-value"}},
            )
            store.append_event(
                run["id"],
                "agent.tool.completed",
                "codex",
                {
                    "tool": "shell",
                    "command": f"cat .env && echo {secret}",
                    "aggregated_output": f"{env_value}\nAuthorization: {bearer}\n{traceback}",
                    "nested": {"api_key": "plain-api-key-value"},
                },
            )

            persisted = (store.runs_dir / f"{run['id']}.json").read_text(encoding="utf-8")
            journal = (store.events_dir / f"{run['id']}.ndjson").read_text(encoding="utf-8")
            combined = persisted + journal + json.dumps(store.get(run["id"])) + json.dumps(store.events(run["id"]))

            for leaked in (secret, "sk-abcdefghijklmnop1234", "abcdefghijklmnop", "supersecretvalue", "plain-api-key-value"):
                self.assertNotIn(leaked, combined)
            self.assertNotIn(secret.lower().replace("_", "-"), run["id"].lower())
            self.assertIn("[REDACTED]", combined)
            self.assertIn("redaction_receipt", persisted)
            self.assertIn("redaction_receipt", journal)

    def test_schema_two_snapshot_migrates_forward_without_rewriting_events(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / "project"
            project.mkdir()
            store = RunStore(root / "state")
            run = store.create({"task": "Old snapshot", "project_path": str(project)})
            path = store.runs_dir / f"{run['id']}.json"
            legacy = json.loads(path.read_text())
            legacy["schema_version"] = 2
            legacy.pop("depends_on")
            legacy.pop("evaluation")
            path.write_text(json.dumps(legacy))
            journal_before = (store.events_dir / f"{run['id']}.ndjson").read_text()

            migrated = RunStore(store.root).get(run["id"])

            self.assertEqual(migrated["schema_version"], RUN_SCHEMA_VERSION)
            self.assertEqual(migrated["depends_on"], [])
            self.assertEqual(migrated["evaluation"], {})
            self.assertEqual(migrated["integration_disposition"]["state"], "pending")
            self.assertEqual(migrated["integration_disposition"]["superseded_by"], "")
            self.assertEqual(
                (store.events_dir / f"{run['id']}.ndjson").read_text(), journal_before
            )

    def test_adopted_session_is_not_scheduler_eligible(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / "project"
            project.mkdir()
            store = RunStore(root / "state")
            run = store.create_external({"task": "Interactive", "project_path": str(project), "kind": "tmux"})
            self.assertEqual(run["status"], "session")
            self.assertIsNone(store.claim(run["id"], max_parallel=1))


if __name__ == "__main__":
    unittest.main()
