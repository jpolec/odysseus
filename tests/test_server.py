from __future__ import annotations

import base64
import json
import os
import socket
import subprocess
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

from odysseus.server import OdysseusApp, OdysseusHandler
from odysseus.store import RunStore


class DummyScheduler:
    def __init__(self) -> None:
        self.started = False

    def start(self) -> None:
        self.started = True

    def stop(self, timeout=10) -> None:  # noqa: ANN001
        pass

    def active_count(self) -> int:
        return 0

    def cancel(self, run_id):  # noqa: ANN001
        raise AssertionError(f"unexpected cancel: {run_id}")


class ServerTests(unittest.TestCase):
    def test_port_conflict_never_starts_background_scheduler(self) -> None:
        with tempfile.TemporaryDirectory() as temp, socket.socket() as occupied:
            occupied.bind(("127.0.0.1", 0))
            occupied.listen()
            port = int(occupied.getsockname()[1])
            scheduler = DummyScheduler()
            app = OdysseusApp(
                RunStore(Path(temp) / "state"),
                host="127.0.0.1",
                port=port,
                scheduler=scheduler,
            )

            with self.assertRaises(OSError):
                app.start()

            self.assertFalse(scheduler.started)
            self.assertIsNone(app.httpd)

    def test_ui_bootstrap_and_token_protected_create(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / "project"
            project.mkdir()
            store = RunStore(root / "state")
            app = OdysseusApp(store, host="127.0.0.1", port=0, scheduler=DummyScheduler())
            host, port = app.start()
            thread = threading.Thread(target=app.httpd.serve_forever, daemon=True)
            thread.start()
            base = f"http://{host}:{port}"
            try:
                with urllib.request.urlopen(f"{base}/api/bootstrap") as response:
                    bootstrap = json.load(response)
                self.assertEqual(bootstrap["name"], "Odysseus")
                self.assertEqual(bootstrap["version"], "0.6.5")
                self.assertIn("git", bootstrap["capabilities"])
                self.assertIn("docker", bootstrap["capabilities"])
                self.assertIn("devcontainer", bootstrap["capabilities"])
                self.assertIn("codex", bootstrap["assistant"])
                self.assertEqual(bootstrap["assistant"]["codex"]["mode"], "local_cli")
                self.assertIn("claude", bootstrap["assistant"])
                self.assertEqual(bootstrap["assistant"]["claude"]["mode"], "local_cli")
                self.assertEqual(bootstrap["assistant"]["openai"]["env"], "OPENAI_API_KEY")
                self.assertEqual(bootstrap["assistant"]["openai"]["mode"], "direct_api")
                self.assertIn("anthropic", bootstrap["assistant"])
                self.assertTrue(bootstrap["working_directory"])
                self.assertIsInstance(bootstrap["current_repository"], dict)

                body = json.dumps({"task": "Test API", "project_path": str(project)}).encode()
                forbidden = urllib.request.Request(
                    f"{base}/api/runs", data=body, headers={"Content-Type": "application/json"}
                )
                with self.assertRaises(urllib.error.HTTPError) as caught:
                    urllib.request.urlopen(forbidden)
                self.assertEqual(caught.exception.code, 403)
                caught.exception.close()

                invalid_repository = urllib.request.Request(
                    f"{base}/api/projects",
                    data=json.dumps({"path": str(project)}).encode(),
                    headers={
                        "Content-Type": "application/json",
                        "X-Odysseus-Token": bootstrap["token"],
                    },
                )
                with self.assertRaises(urllib.error.HTTPError) as caught:
                    urllib.request.urlopen(invalid_repository)
                self.assertEqual(caught.exception.code, 400)
                self.assertIn("not a Git repository", caught.exception.read().decode())
                caught.exception.close()

                request = urllib.request.Request(
                    f"{base}/api/runs",
                    data=body,
                    headers={
                        "Content-Type": "application/json",
                        "X-Odysseus-Token": bootstrap["token"],
                    },
                )
                with urllib.request.urlopen(request) as response:
                    run = json.load(response)
                self.assertEqual(run["status"], "queued")
                secret_title = "Secret title sk-abcdefghijklmnop"
                secret_task = "Do not leak ghp_abcdefghijklmnop"
                secret_check = "curl -H 'Authorization: Bearer abcdefghijklmnop'"
                store.update(
                    run["id"],
                    title=secret_title,
                    task=secret_task,
                    check_results=[{"command": secret_check, "returncode": 1}],
                )

                with urllib.request.urlopen(f"{base}/") as response:
                    html = response.read().decode()
                self.assertIn("ODYSSEUS", html)
                self.assertIn('id="projectExplorer"', html)
                self.assertIn('id="projectTree"', html)
                self.assertIn('id="workView"', html)
                self.assertIn('id="quickStart"', html)
                self.assertIn('id="journeyStepper"', html)
                self.assertIn('data-journey-step="1"', html)
                self.assertIn('data-journey-step="2"', html)
                self.assertIn('data-journey-step="3"', html)
                self.assertIn("Choose a repository", html)
                self.assertIn("New task", html)
                self.assertIn("What should the agent change?", html)
                self.assertIn("Start &amp; add another", html)
                self.assertIn("Repositories saved on this computer", html)
                self.assertIn("Follow &amp; review", html)
                self.assertIn("Manage repositories", html)
                self.assertIn("A repository is the code Codex will work on", html)
                self.assertNotIn("Other repository path", html)
                self.assertIn('id="projectHome"', html)
                self.assertIn('id="projectTimeline"', html)
                self.assertIn('id="projectSkillList"', html)
                self.assertIn('id="taskSkillMode"', html)
                self.assertIn('id="contextReceipt"', html)
                self.assertIn('id="projectMemoryList"', html)
                self.assertIn('id="taskSkillRecommendations"', html)
                self.assertIn('id="environmentProfile"', html)
                self.assertIn('id="environmentCard"', html)
                self.assertIn('id="assistantPanel"', html)
                self.assertIn('id="assistantProvider"', html)
                self.assertIn('id="assistantMessages"', html)
                self.assertIn('id="assistantComposer"', html)
                self.assertIn('id="recoveryCard"', html)
                self.assertIn('id="inlineFeedback"', html)
                self.assertIn("Direct API: ChatGPT", html)
                self.assertIn("Share diff/code excerpt", html)
                self.assertIn("blank scratch workspace", html)
                self.assertIn('data-section="summary"', html)
                self.assertIn('data-section="evidence"', html)

                with urllib.request.urlopen(f"{base}/app.js") as response:
                    app_js = response.read().decode()
                self.assertIn("Follow up with agent", app_js)
                self.assertIn('["review", "failed", "attention"]', app_js)
                self.assertIn('["review", "failed", "attention", "accepted", "pr_created"]', app_js)
                self.assertIn("feedbackDialog", app_js)

                assist_request = urllib.request.Request(
                    f"{base}/api/assist",
                    data=json.dumps({"provider": "codex", "run_id": run["id"], "messages": [{"role": "user", "content": "draft feedback"}]}).encode(),
                    headers={"Content-Type": "application/json", "X-Odysseus-Token": bootstrap["token"]},
                )
                with mock.patch.object(OdysseusHandler, "_call_local_assistant", return_value="Send this next.") as local_call:
                    with urllib.request.urlopen(assist_request) as response:
                        drafted = json.load(response)
                self.assertEqual(drafted["provider"], "codex")
                self.assertEqual(drafted["prompt"], "Send this next.")
                self.assertEqual(drafted["shared_context"], ["Task", "Checks"])
                self.assertIn("[Diff/code] Not shared", local_call.call_args.args[2])
                self.assertNotIn("Diff excerpt", local_call.call_args.args[2])
                self.assertNotIn("sk-abcdefghijklmnop", local_call.call_args.args[2])
                self.assertNotIn("ghp_abcdefghijklmnop", local_call.call_args.args[2])
                self.assertNotIn("Bearer abcdefghijklmnop", local_call.call_args.args[2])
                self.assertIn("[REDACTED]", local_call.call_args.args[2])

                assist_request = urllib.request.Request(
                    f"{base}/api/assist",
                    data=json.dumps({"provider": "codex", "run_id": run["id"], "messages": [{"role": "user", "content": "no context please"}], "scopes": []}).encode(),
                    headers={"Content-Type": "application/json", "X-Odysseus-Token": bootstrap["token"]},
                )
                with mock.patch.object(OdysseusHandler, "_call_local_assistant", return_value="No context.") as local_call:
                    with urllib.request.urlopen(assist_request) as response:
                        drafted = json.load(response)
                self.assertEqual(drafted["shared_context"], [])
                self.assertNotIn("Title:", local_call.call_args.args[2])
                self.assertNotIn("Status:", local_call.call_args.args[2])
                self.assertNotIn(secret_title, local_call.call_args.args[2])
                self.assertNotIn(secret_task, local_call.call_args.args[2])

                assist_request = urllib.request.Request(
                    f"{base}/api/assist",
                    data=json.dumps({"provider": "codex", "run_id": run["id"], "messages": [{"role": "user", "content": "draft feedback"}]}).encode(),
                    headers={"Content-Type": "application/json", "X-Odysseus-Token": bootstrap["token"]},
                )
                completed = subprocess.CompletedProcess(["codex"], 0, '{"message":{"content":"Scratch answer."}}\n', "")
                with mock.patch("odysseus.server.shutil.which", return_value="/usr/bin/codex"):
                    with mock.patch("odysseus.server.subprocess.run", return_value=completed) as process:
                        with urllib.request.urlopen(assist_request) as response:
                            drafted = json.load(response)
                self.assertEqual(drafted["prompt"], "Scratch answer.")
                command = " ".join(process.call_args.args[0])
                self.assertNotIn(str(project), command)
                self.assertNotIn(str(project), process.call_args.kwargs["cwd"])
                self.assertFalse(Path(process.call_args.kwargs["cwd"]).exists())

                assist_request = urllib.request.Request(
                    f"{base}/api/assist",
                    data=json.dumps({"provider": "openai", "run_id": run["id"], "messages": [{"role": "user", "content": "draft feedback"}]}).encode(),
                    headers={"Content-Type": "application/json", "X-Odysseus-Token": bootstrap["token"]},
                )
                with mock.patch.dict(os.environ, {"OPENAI_API_KEY": ""}, clear=False):
                    with self.assertRaises(urllib.error.HTTPError) as caught:
                        urllib.request.urlopen(assist_request)
                self.assertEqual(caught.exception.code, 400)
                self.assertIn("OPENAI_API_KEY", caught.exception.read().decode())
                caught.exception.close()

                assist_request = urllib.request.Request(
                    f"{base}/api/assist",
                    data=json.dumps({"provider": "openai", "run_id": run["id"], "messages": [{"role": "user", "content": "draft feedback"}]}).encode(),
                    headers={"Content-Type": "application/json", "X-Odysseus-Token": bootstrap["token"]},
                )
                with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}, clear=False):
                    with mock.patch.object(OdysseusHandler, "_call_openai", return_value="Send this next.") as call:
                        with urllib.request.urlopen(assist_request) as response:
                            drafted = json.load(response)
                self.assertEqual(drafted["provider"], "openai")
                self.assertEqual(drafted["prompt"], "Send this next.")
                self.assertIn("[Diff/code] Not shared", call.call_args.args[2])
                self.assertNotIn("sk-abcdefghijklmnop", call.call_args.args[2])
                self.assertNotIn("ghp_abcdefghijklmnop", call.call_args.args[2])
                self.assertNotIn("Bearer abcdefghijklmnop", call.call_args.args[2])
                self.assertIn("[REDACTED]", call.call_args.args[2])

                assist_request = urllib.request.Request(
                    f"{base}/api/assist",
                    data=json.dumps({"provider": "openai", "run_id": run["id"], "messages": [{"role": "user", "content": "direct no context"}], "scopes": []}).encode(),
                    headers={"Content-Type": "application/json", "X-Odysseus-Token": bootstrap["token"]},
                )
                with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}, clear=False):
                    with mock.patch.object(OdysseusHandler, "_call_openai", return_value="No context.") as call:
                        with urllib.request.urlopen(assist_request) as response:
                            drafted = json.load(response)
                self.assertEqual(drafted["shared_context"], [])
                self.assertNotIn("Title:", call.call_args.args[2])
                self.assertNotIn("Status:", call.call_args.args[2])
                self.assertNotIn(secret_title, call.call_args.args[2])
                self.assertNotIn(secret_task, call.call_args.args[2])

                assist_request = urllib.request.Request(
                    f"{base}/api/assist",
                    data=json.dumps({
                        "provider": "openai",
                        "run_id": run["id"],
                        "messages": [{"role": "user", "content": "review this diff"}],
                        "include_diff": True,
                    }).encode(),
                    headers={"Content-Type": "application/json", "X-Odysseus-Token": bootstrap["token"]},
                )
                with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}, clear=False):
                    with mock.patch("odysseus.server.WorktreeManager.diff", return_value={"stat": "app.py | 1 +", "patch": "Authorization: Bearer abcdefghijklmnop"}):
                        with mock.patch.object(OdysseusHandler, "_call_openai", return_value="Diff feedback.") as call:
                            with urllib.request.urlopen(assist_request) as response:
                                drafted = json.load(response)
                self.assertIn("Diff/code", drafted["shared_context"])
                self.assertIn("[REDACTED]", call.call_args.args[2])
                self.assertNotIn("abcdefghijklmnop", call.call_args.args[2])

                assist_request = urllib.request.Request(
                    f"{base}/api/assist",
                    data=json.dumps({
                        "provider": "openai",
                        "run_id": run["id"],
                        "messages": [
                            {"role": "user", "content": "review code", "shared_context": ["Diff/code"]},
                            {"role": "assistant", "content": "SECRET_CODE_DERIVED_RESPONSE", "shared_context": ["Diff/code"]},
                            {"role": "user", "content": "now answer without code", "shared_context": ["Task"]},
                        ],
                        "scopes": ["task"],
                        "include_diff": False,
                    }).encode(),
                    headers={"Content-Type": "application/json", "X-Odysseus-Token": bootstrap["token"]},
                )
                with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}, clear=False):
                    with mock.patch.object(OdysseusHandler, "_call_openai", return_value="No-code answer.") as call:
                        with urllib.request.urlopen(assist_request) as response:
                            drafted = json.load(response)
                self.assertEqual(drafted["shared_context"], ["Task"])
                self.assertIn("now answer without code", call.call_args.args[2])
                self.assertNotIn("SECRET_CODE_DERIVED_RESPONSE", call.call_args.args[2])
                self.assertNotIn("review code", call.call_args.args[2])

                with urllib.request.urlopen(f"{base}/api/projects") as response:
                    projects = json.load(response)
                self.assertEqual(len(projects["projects"]), 1)

                with urllib.request.urlopen(f"{base}/api/health") as response:
                    health = json.load(response)
                self.assertEqual(health["product"], "odysseus")

                inbox_request = urllib.request.Request(
                    f"{base}/api/inbox",
                    data=json.dumps({"title": "Follow-up", "task": "Later"}).encode(),
                    headers={"Content-Type": "application/json", "X-Odysseus-Token": bootstrap["token"]},
                )
                with urllib.request.urlopen(inbox_request) as response:
                    inbox = json.load(response)
                self.assertEqual(inbox["status"], "open")

                store.append_event(
                    run["id"],
                    "agent.question",
                    "claude",
                    {"title": "Choose migration", "message": "Retain nullable email?", "options": ["retain", "not-null"]},
                )
                with urllib.request.urlopen(f"{base}/api/attention?status=open") as response:
                    attention = json.load(response)["items"]
                self.assertEqual(attention[0]["type"], "question")
                answer_request = urllib.request.Request(
                    f"{base}/api/attention/{attention[0]['id']}/respond",
                    data=json.dumps({"response": "retain"}).encode(),
                    headers={"Content-Type": "application/json", "X-Odysseus-Token": bootstrap["token"]},
                )
                with urllib.request.urlopen(answer_request) as response:
                    answered = json.load(response)
                self.assertEqual(answered["attention"]["response"], "retain")

                epic = store.epics.create(
                    {
                        "title": "API epic",
                        "project_path": str(project),
                        "status": "proposed",
                        "plan": {
                            "summary": "One step",
                            "tasks": [{"task_key": "ship", "title": "Ship", "task": "Ship it", "project_path": str(project)}],
                        },
                    }
                )
                approve_request = urllib.request.Request(
                    f"{base}/api/epics/{epic['id']}/approve",
                    data=b"{}",
                    headers={"Content-Type": "application/json", "X-Odysseus-Token": bootstrap["token"]},
                )
                with urllib.request.urlopen(approve_request) as response:
                    approved = json.load(response)
                self.assertEqual(approved["status"], "active")
                self.assertEqual(len(approved["task_run_ids"]), 1)
            finally:
                app.stop()
                thread.join(timeout=2)

    def test_optional_basic_auth_protects_reads(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            store = RunStore(Path(temp) / "state")
            app = OdysseusApp(
                store,
                host="127.0.0.1",
                port=0,
                scheduler=DummyScheduler(),
                auth_user="operator",
                auth_password="correct horse",
            )
            host, port = app.start()
            thread = threading.Thread(target=app.httpd.serve_forever, daemon=True)
            thread.start()
            url = f"http://{host}:{port}/api/health"
            try:
                with self.assertRaises(urllib.error.HTTPError) as caught:
                    urllib.request.urlopen(url)
                self.assertEqual(caught.exception.code, 401)
                caught.exception.close()
                token = base64.b64encode(b"operator:correct horse").decode()
                request = urllib.request.Request(url, headers={"Authorization": f"Basic {token}"})
                with urllib.request.urlopen(request) as response:
                    health = json.load(response)
                self.assertTrue(health["ok"])
            finally:
                app.stop()
                thread.join(timeout=2)

    def test_sse_connections_are_bounded_and_visible_in_health(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / "project"
            project.mkdir()
            store = RunStore(root / "state")
            run = store.create({"task": "Stream events", "project_path": str(project)})
            app = OdysseusApp(
                store,
                host="127.0.0.1",
                port=0,
                scheduler=DummyScheduler(),
                max_http_connections=4,
                max_sse_connections=1,
            )
            host, port = app.start()
            thread = threading.Thread(target=app.httpd.serve_forever, daemon=True)
            thread.start()
            base = f"http://{host}:{port}"
            stream = urllib.request.urlopen(f"{base}/api/runs/{run['id']}/stream", timeout=3)
            try:
                with urllib.request.urlopen(f"{base}/api/health") as response:
                    health = json.load(response)
                self.assertEqual(health["sse_connections"], 1)
                self.assertEqual(health["sse_connection_limit"], 1)
                with self.assertRaises(urllib.error.HTTPError) as caught:
                    urllib.request.urlopen(f"{base}/api/runs/{run['id']}/stream", timeout=3)
                self.assertEqual(caught.exception.code, 503)
                caught.exception.close()
            finally:
                stream.close()
                app.stop()
                thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
