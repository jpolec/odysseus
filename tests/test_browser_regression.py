from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import threading
import time
import unittest
import urllib.request
from pathlib import Path

from odysseus.server import OdysseusApp
from odysseus.store import RunStore

try:
    from .test_server import DummyScheduler
except ImportError:
    from test_server import DummyScheduler


def _browser() -> str | None:
    for name in ("chromium", "chromium-browser", "google-chrome", "google-chrome-stable"):
        found = shutil.which(name)
        if found:
            return found
    mac = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
    return str(mac) if mac.exists() else None


class BrowserRegressionTests(unittest.TestCase):
    @staticmethod
    def _git_repo(root: Path) -> Path:
        repo = root / "repo"
        repo.mkdir()
        subprocess.run(["git", "-C", str(repo), "init", "-b", "main"], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        subprocess.run(["git", "-C", str(repo), "config", "user.name", "Odysseus Test"], check=True)
        subprocess.run(["git", "-C", str(repo), "config", "user.email", "odysseus@example.test"], check=True)
        (repo / "README.md").write_text("base\n")
        subprocess.run(["git", "-C", str(repo), "add", "README.md"], check=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-m", "base"], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return repo

    def test_artifact_integration_and_sidebar_recovery_flow_in_real_browser(self) -> None:
        browser = _browser()
        if not browser:
            self.skipTest("Chrome or Chromium is not installed")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = self._git_repo(root)
            base_sha = subprocess.run(
                ["git", "-C", str(repo), "rev-parse", "HEAD"],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
            ).stdout.strip()
            store = RunStore(root / "state")
            accepted = []
            for title in ("Stale UI", "Backend", "API", "Docs"):
                run = store.create({"title": title, "task": title, "project_path": str(repo), "status": "review"})
                accepted.append(
                    store.update(
                        run["id"],
                        status="accepted",
                        base_ref="main",
                        base_sha=base_sha,
                        artifact_sha=base_sha,
                        artifact_files=[f"{title.lower().replace(' ', '-')}.py"],
                        artifact_created_at="2026-08-16T00:00:00Z",
                        check_results=[{"command": "python -m unittest", "returncode": 0, "output": "ok"}],
                        confidence=0.92,
                        metrics={"input_tokens": 1000, "output_tokens": 200, "session_usage": {"agent": {"input_tokens": 1000, "output_tokens": 200}}},
                        delivery={**run["delivery"], "status": "not_applied", "target_branch": "main"},
                    )
                )
            delivered = store.create({"title": "Delivered integration source", "task": "Delivered", "project_path": str(repo), "status": "review"})
            store.update(
                delivered["id"],
                status="accepted",
                base_ref="main",
                base_sha=base_sha,
                artifact_sha=base_sha,
                artifact_files=["delivered.py"],
                delivery={
                    "status": "integrated_applied",
                    "method": "integration_delivery",
                    "target_branch": "main",
                    "target_before_sha": base_sha,
                    "target_after_sha": base_sha,
                    "delivered_at": "2026-08-16T00:00:00Z",
                    "error": "",
                    "integration_run_id": "integration-existing",
                },
            )
            conflict_run = store.create({"title": "Conflict integration", "task": "Resolve conflicts", "project_path": str(repo), "status": "attention"})
            store.append_event(
                conflict_run["id"],
                "integration.conflict",
                "git",
                {
                    "message": "Dependency artifact conflicts with the integration branch.",
                    "conflicts": ["web/app.js", "web/styles.css"],
                    "preserved_branches": ["odysseus/integration", "odysseus/source-artifact"],
                    "dependency_run_id": accepted[0]["id"],
                    "artifact_sha": base_sha,
                },
            )
            app = OdysseusApp(store, host="127.0.0.1", port=0, scheduler=DummyScheduler())
            host, port = app.start()
            thread = threading.Thread(target=app.httpd.serve_forever, daemon=True)
            thread.start()
            try:
                with urllib.request.urlopen(f"http://{host}:{port}/api/bootstrap") as response:
                    json.load(response)
                process = subprocess.Popen(
                    [
                        browser,
                        "--headless=new",
                        "--disable-gpu",
                        "--no-first-run",
                        "--no-default-browser-check",
                        "--disable-dev-shm-usage",
                        f"--user-data-dir={root / 'chrome-profile'}",
                        f"http://{host}:{port}/?browser-regression=1",
                    ],
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                deadline = time.monotonic() + 20
                passed = False
                failure = ""
                while time.monotonic() < deadline:
                    with urllib.request.urlopen(f"http://{host}:{port}/api/inbox") as response:
                        items = json.load(response)["items"]
                    if any(item.get("title") == "PASS browser regression" for item in items):
                        passed = True
                        break
                    failed = next((item for item in items if item.get("title") == "FAIL browser regression"), None)
                    if failed:
                        failure = str(failed.get("task") or "")
                        break
                    if process.poll() is not None:
                        break
                    time.sleep(0.2)
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                stderr = process.stderr.read() if process.stderr else ""
                if process.stdout:
                    process.stdout.close()
                if process.stderr:
                    process.stderr.close()
                self.assertTrue(passed, failure or stderr[-1000:])
            finally:
                app.stop()
                thread.join(timeout=2)
