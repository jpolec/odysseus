from __future__ import annotations

import base64
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from odysseus.server import OdysseusApp
from odysseus.store import RunStore


class DummyScheduler:
    def start(self) -> None:
        pass

    def stop(self, timeout=10) -> None:  # noqa: ANN001
        pass

    def active_count(self) -> int:
        return 0

    def cancel(self, run_id):  # noqa: ANN001
        raise AssertionError(f"unexpected cancel: {run_id}")


class ServerTests(unittest.TestCase):
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

                body = json.dumps({"task": "Test API", "project_path": str(project)}).encode()
                forbidden = urllib.request.Request(
                    f"{base}/api/runs", data=body, headers={"Content-Type": "application/json"}
                )
                with self.assertRaises(urllib.error.HTTPError) as caught:
                    urllib.request.urlopen(forbidden)
                self.assertEqual(caught.exception.code, 403)
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
                self.assertIn('id="projectHome"', html)
                self.assertIn('id="projectTimeline"', html)
                self.assertIn('data-section="summary"', html)
                self.assertIn('data-section="evidence"', html)

                with urllib.request.urlopen(f"{base}/api/projects") as response:
                    projects = json.load(response)
                self.assertEqual(len(projects["projects"]), 1)

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


if __name__ == "__main__":
    unittest.main()
