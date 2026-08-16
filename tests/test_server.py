from __future__ import annotations

import base64
import json
import socket
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from odysseus.server import OdysseusApp
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
                self.assertIn('data-section="summary"', html)
                self.assertIn('data-section="evidence"', html)

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
