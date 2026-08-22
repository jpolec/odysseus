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

    def test_transport_disconnects_do_not_print_server_tracebacks(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            app = OdysseusApp(
                RunStore(Path(temp) / "state"),
                host="127.0.0.1",
                port=0,
                scheduler=DummyScheduler(),
            )
            app.start()
            thread = threading.Thread(target=app.httpd.serve_forever, daemon=True)
            thread.start()
            try:
                with mock.patch("http.server.ThreadingHTTPServer.handle_error") as fallback:
                    try:
                        raise ConnectionResetError("client disconnected")
                    except ConnectionResetError:
                        app.httpd.handle_error(None, ("127.0.0.1", 0))
                    fallback.assert_not_called()

                    try:
                        raise RuntimeError("unexpected server failure")
                    except RuntimeError:
                        app.httpd.handle_error(None, ("127.0.0.1", 0))
                    fallback.assert_called_once()
            finally:
                app.stop()
                thread.join(timeout=2)

    def test_config_endpoint_updates_safe_settings(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            store = RunStore(Path(temp) / "state")
            app = OdysseusApp(store, host="127.0.0.1", port=0, scheduler=DummyScheduler())
            host, port = app.start()
            thread = threading.Thread(target=app.httpd.serve_forever, daemon=True)
            thread.start()
            base = f"http://{host}:{port}"
            try:
                with urllib.request.urlopen(f"{base}/api/bootstrap") as response:
                    token = json.load(response)["token"]
                request = urllib.request.Request(
                    f"{base}/api/config",
                    data=json.dumps(
                        {
                            "max_parallel": 4,
                            "default_lane": "claude",
                            "assistant_models": {"openai": "gpt-test"},
                            "openai_api_key": "must-not-be-persisted",
                            "budgets": {"max_tokens": 1200},
                        }
                    ).encode(),
                    headers={"Content-Type": "application/json", "X-Odysseus-Token": token},
                )
                with urllib.request.urlopen(request) as response:
                    updated = json.load(response)
                self.assertEqual(updated["max_parallel"], 4)
                self.assertEqual(updated["default_lane"], "claude")
                self.assertEqual(updated["assistant_models"]["openai"], "gpt-test")
                self.assertNotIn("openai_api_key", updated)
                self.assertEqual(updated["budgets"]["max_tokens"], 1200)
                with urllib.request.urlopen(f"{base}/api/config") as response:
                    fetched = json.load(response)
                self.assertEqual(fetched["max_parallel"], 4)
                self.assertNotIn("openai_api_key", fetched)
                with urllib.request.urlopen(f"{base}/api/bootstrap") as response:
                    bootstrap = json.load(response)
                self.assertEqual(bootstrap["assistant"]["openai"]["model"], "gpt-test")
            finally:
                app.stop()

    def test_portfolio_and_outcome_router_endpoints_use_durable_local_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / "project"
            project.mkdir()
            store = RunStore(root / "state")
            registered = store.projects.upsert(project)
            store.update_config({"outcome_router": {"min_samples": 1}})
            run = store.create({"task": "Router fixture", "project_path": str(project), "lane": "claude"})
            store.update(run["id"], status="accepted", started_at=run["created_at"], finished_at=run["created_at"], delivery={"status": "applied"})
            app = OdysseusApp(store, host="127.0.0.1", port=0, scheduler=DummyScheduler())
            host, port = app.start()
            thread = threading.Thread(target=app.httpd.serve_forever, daemon=True)
            thread.start()
            base = f"http://{host}:{port}"
            try:
                with urllib.request.urlopen(f"{base}/api/bootstrap") as response:
                    token = json.load(response)["token"]
                with urllib.request.urlopen(f"{base}/api/portfolio?days=7") as response:
                    portfolio = json.load(response)
                self.assertEqual(portfolio["format"], "odysseus-engineering-portfolio-v1")
                self.assertEqual(portfolio["metrics"]["delivered"], 1)

                forbidden = urllib.request.Request(
                    f"{base}/api/projects/{registered['id']}/router/recommend",
                    data=b"{}",
                    headers={"Content-Type": "application/json"},
                )
                with self.assertRaises(urllib.error.HTTPError) as caught:
                    urllib.request.urlopen(forbidden)
                self.assertEqual(caught.exception.code, 403)
                caught.exception.close()
                request = urllib.request.Request(
                    f"{base}/api/projects/{registered['id']}/router/recommend",
                    data=json.dumps({"operator_default": "codex"}).encode(),
                    headers={"Content-Type": "application/json", "X-Odysseus-Token": token},
                )
                with urllib.request.urlopen(request) as response:
                    recommendation = json.load(response)
                self.assertEqual(recommendation["recommended_lane"], "claude")
                self.assertEqual(recommendation["applied_lane"], "codex")
            finally:
                app.stop()
                thread.join(timeout=2)

    def test_github_import_refetches_issue_and_proposes_plan_without_starting_run(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = self._git_repo(root)
            subprocess.run(["git", "-C", str(repo), "remote", "add", "origin", "https://github.com/acme/app.git"], check=True)
            store = RunStore(root / "state")
            project = store.projects.upsert(repo)
            app = OdysseusApp(store, host="127.0.0.1", port=0, scheduler=DummyScheduler())
            app.github.issue = mock.Mock(
                return_value={
                    "number": 7,
                    "title": "Incident: API timeout",
                    "body": "Trace includes user@example.com and ghp_abcdefghijklmnop1234.",
                    "url": "https://github.com/acme/app/issues/7",
                    "labels": [{"name": "sev1"}],
                    "assignees": [],
                    "state": "open",
                    "updatedAt": "2026-08-16T10:00:00Z",
                }
            )
            host, port = app.start()
            thread = threading.Thread(target=app.httpd.serve_forever, daemon=True)
            thread.start()
            base = f"http://{host}:{port}"
            try:
                with urllib.request.urlopen(f"{base}/api/bootstrap") as response:
                    token = json.load(response)["token"]
                request = urllib.request.Request(
                    f"{base}/api/github/import",
                    data=json.dumps({"project_id": project["id"], "number": 7, "title": "forged browser title"}).encode(),
                    headers={"Content-Type": "application/json", "X-Odysseus-Token": token},
                )
                with urllib.request.urlopen(request) as response:
                    epic = json.load(response)
                app.github.issue.assert_called_once_with(project["path"], 7)
                self.assertEqual(epic["title"], "Incident: API timeout")
                self.assertEqual(epic["status"], "proposed")
                self.assertEqual(epic["intake"]["severity"], "high")
                self.assertNotIn("user@example.com", epic["intake"]["evidence"]["body_excerpt"])
                self.assertEqual(store.list(), [])
            finally:
                app.stop()
                thread.join(timeout=2)

    def test_plan_endpoint_freezes_only_discovered_adr_sources(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = self._git_repo(root)
            decisions = project / "_ADR"
            decisions.mkdir()
            (decisions / "0001-runtime.md").write_text(
                "# ADR-0001: Runtime isolation\n\nStatus: Accepted\n\nUse a separate runtime per task.\n",
                encoding="utf-8",
            )
            (project / "outside.md").write_text("# Outside\n", encoding="utf-8")
            store = RunStore(root / "state")
            registered = store.projects.upsert(project)
            app = OdysseusApp(store, host="127.0.0.1", port=0, scheduler=DummyScheduler())
            host, port = app.start()
            thread = threading.Thread(target=app.httpd.serve_forever, daemon=True)
            thread.start()
            base = f"http://{host}:{port}"
            try:
                with urllib.request.urlopen(f"{base}/api/bootstrap") as response:
                    token = json.load(response)["token"]
                payload = {
                    "project_id": registered["id"],
                    "source_paths": ["_ADR/0001-runtime.md"],
                    "requirement": "Implement the selected decision.",
                }
                request = urllib.request.Request(
                    f"{base}/api/epics/plan",
                    data=json.dumps(payload).encode(),
                    headers={"Content-Type": "application/json", "X-Odysseus-Token": token},
                )
                with mock.patch.object(app.planner, "plan", return_value={"id": "epic-test"}) as planner:
                    with urllib.request.urlopen(request) as response:
                        planned = json.load(response)
                self.assertEqual(planned["id"], "epic-test")
                source = planner.call_args.kwargs["source_documents"][0]
                self.assertEqual(source["path"], "_ADR/0001-runtime.md")
                self.assertIn("separate runtime", source["content"])
                self.assertEqual(Path(planner.call_args.args[1]).resolve(), project.resolve())

                invalid = urllib.request.Request(
                    f"{base}/api/epics/plan",
                    data=json.dumps({**payload, "source_paths": ["outside.md"]}).encode(),
                    headers={"Content-Type": "application/json", "X-Odysseus-Token": token},
                )
                with mock.patch.object(app.planner, "plan") as planner:
                    with self.assertRaises(urllib.error.HTTPError) as caught:
                        urllib.request.urlopen(invalid)
                self.assertEqual(caught.exception.code, 400)
                caught.exception.close()
                planner.assert_not_called()
            finally:
                app.stop()
                thread.join(timeout=2)

    def test_plan_endpoint_accepts_bounded_uploaded_requirement_documents(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = self._git_repo(root)
            store = RunStore(root / "state")
            registered = store.projects.upsert(project)
            app = OdysseusApp(store, host="127.0.0.1", port=0, scheduler=DummyScheduler())
            host, port = app.start()
            thread = threading.Thread(target=app.httpd.serve_forever, daemon=True)
            thread.start()
            base = f"http://{host}:{port}"
            try:
                with urllib.request.urlopen(f"{base}/api/bootstrap") as response:
                    token = json.load(response)["token"]
                payload = {
                    "project_id": registered["id"],
                    "project_path": str(root / "forged-browser-path"),
                    "source_kind": "specification",
                    "requirement": "Implement the uploaded specification.",
                    "source_documents": [
                        {"title": "../PASSKEY-PRD.md", "path": "/tmp/ignored", "content": "# Passkeys\n\nKeep password login working."}
                    ],
                }
                request = urllib.request.Request(
                    f"{base}/api/epics/plan",
                    data=json.dumps(payload).encode(),
                    headers={"Content-Type": "application/json", "X-Odysseus-Token": token},
                )
                with mock.patch.object(app.planner, "plan", return_value={"id": "epic-upload"}) as planner:
                    with urllib.request.urlopen(request) as response:
                        planned = json.load(response)
                self.assertEqual(planned["id"], "epic-upload")
                self.assertEqual(Path(planner.call_args.args[1]).resolve(), project.resolve())
                source = planner.call_args.kwargs["source_documents"][0]
                self.assertEqual(source["kind"], "specification")
                self.assertEqual(source["path"], "upload://PASSKEY-PRD.md")
                self.assertIn("password login", source["content"])

                invalid = urllib.request.Request(
                    f"{base}/api/epics/plan",
                    data=json.dumps({**payload, "source_documents": [{"title": "huge.md", "content": "x" * 80_001}]}).encode(),
                    headers={"Content-Type": "application/json", "X-Odysseus-Token": token},
                )
                with mock.patch.object(app.planner, "plan") as planner:
                    with self.assertRaises(urllib.error.HTTPError) as caught:
                        urllib.request.urlopen(invalid)
                self.assertEqual(caught.exception.code, 400)
                caught.exception.close()
                planner.assert_not_called()
            finally:
                app.stop()
                thread.join(timeout=2)

    def test_run_summary_endpoint_omits_heavy_task_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / "project"
            project.mkdir()
            store = RunStore(root / "state")
            run = store.create({"task": "Keep navigation light", "project_path": str(project)})
            store.update(
                run["id"],
                check_results=[{"command": "test", "returncode": 0, "output": "x" * 100_000}],
                context_bundle=[{"path": "README.md", "content": "y" * 100_000}],
                review_summary="z" * 100_000,
                artifact_files=["src/navigation.py", "tests/test_navigation.py"],
                confidence=0.91,
                metrics={"input_tokens": 1200, "output_tokens": 300, "tool_calls": 7, "cost_usd": 1.25, "cost_observed": True},
            )
            app = OdysseusApp(store, host="127.0.0.1", port=0, scheduler=DummyScheduler())
            host, port = app.start()
            thread = threading.Thread(target=app.httpd.serve_forever, daemon=True)
            thread.start()
            base = f"http://{host}:{port}"
            try:
                with urllib.request.urlopen(f"{base}/api/runs?summary=1") as response:
                    summary = json.load(response)["runs"][0]
                self.assertEqual(summary["id"], run["id"])
                self.assertEqual(summary["task"], "Keep navigation light")
                self.assertEqual(
                    summary["navigation"],
                    {
                        "files_changed": 2,
                        "tool_calls": 7,
                        "total_tokens": 1500,
                        "cost_observed": True,
                        "cost_usd": 1.25,
                        "checks_passed": 1,
                        "checks_total": 1,
                        "evidence_score": 0.91,
                        "environment": "project-default",
                        "isolated": False,
                    },
                )
                self.assertNotIn("check_results", summary)
                self.assertNotIn("context_bundle", summary)
                self.assertNotIn("review_summary", summary)
                with urllib.request.urlopen(f"{base}/api/runs") as response:
                    complete = json.load(response)["runs"][0]
                self.assertIn("check_results", complete)
                self.assertIn("context_bundle", complete)
            finally:
                app.stop()
                thread.join(timeout=2)

    def test_plan_studio_reads_and_versions_execution_contracts(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = self._git_repo(root)
            source = project / "SPEC.md"
            source.write_text("Preserve login.\n\nAdd passkeys.\n", encoding="utf-8")
            store = RunStore(root / "state")
            epic = store.epics.create(
                {"title": "Passkeys", "project_path": str(project), "source_documents": [{"kind": "specification", "path": "SPEC.md", "content": source.read_text()}]}
            )
            epic = store.epics.save_plan(
                epic["id"],
                {"summary": "Passkey contract", "tasks": [{"task_key": "auth", "title": "Authentication", "task": "Add passkeys", "source_refs": ["S2"]}]},
            )
            app = OdysseusApp(store, host="127.0.0.1", port=0, scheduler=DummyScheduler())
            host, port = app.start()
            thread = threading.Thread(target=app.httpd.serve_forever, daemon=True)
            thread.start()
            base = f"http://{host}:{port}"
            try:
                with urllib.request.urlopen(f"{base}/api/bootstrap") as response:
                    token = json.load(response)["token"]
                with urllib.request.urlopen(f"{base}/api/epics/{epic['id']}") as response:
                    detail = json.load(response)
                self.assertEqual(detail["source_documents"][0]["sections"][1]["ref"], "S2")
                self.assertEqual(detail["source_impact"]["status"], "current")

                edited = {**detail["plan"], "tasks": [{**detail["plan"]["tasks"][0], "outcome": "Passkey login works"}]}
                request = urllib.request.Request(
                    f"{base}/api/epics/{epic['id']}/plan",
                    data=json.dumps({"plan": edited}).encode(),
                    headers={"Content-Type": "application/json", "X-Odysseus-Token": token},
                )
                with urllib.request.urlopen(request) as response:
                    saved = json.load(response)
                self.assertEqual(saved["plan_version"]["number"], 2)
                self.assertEqual(saved["plan"]["tasks"][0]["outcome"], "Passkey login works")
                self.assertEqual(len(saved["plan_history"]), 1)
            finally:
                app.stop()
                thread.join(timeout=2)

    def test_economics_endpoint_exports_csv_and_ndjson(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / "project"
            project.mkdir()
            store = RunStore(root / "state")
            run = store.create({"title": "Costed change", "task": "Ship costed change", "project_path": str(project), "status": "accepted"})
            store.append_event(run["id"], "agent.cost", "codex", {"cost_usd": 1.0})
            app = OdysseusApp(store, host="127.0.0.1", port=0, scheduler=DummyScheduler())
            host, port = app.start()
            thread = threading.Thread(target=app.httpd.serve_forever, daemon=True)
            thread.start()
            base = f"http://{host}:{port}"
            try:
                with urllib.request.urlopen(f"{base}/api/economics") as response:
                    payload = json.load(response)
                self.assertEqual(payload["format"], "odysseus-outcome-economics-v1")
                with urllib.request.urlopen(f"{base}/api/economics?format=csv&view=lead") as response:
                    csv_payload = response.read().decode()
                    self.assertEqual(response.headers.get_content_type(), "text/csv")
                self.assertIn("receipt_id", csv_payload)
                with urllib.request.urlopen(f"{base}/api/economics?format=ndjson&view=operator") as response:
                    ndjson_payload = response.read().decode()
                    self.assertEqual(response.headers.get_content_type(), "application/x-ndjson")
                self.assertIn(run["id"], ndjson_payload)
            finally:
                app.stop()
                thread.join(timeout=2)

    def test_http_and_sse_event_boundaries_are_redacted(self) -> None:
        secret = "ghp_abcdefghijklmnop1234"
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / "project"
            project.mkdir()
            store = RunStore(root / "state")
            run = store.create({"task": f"Stream {secret}", "project_path": str(project)})
            store.append_event(
                run["id"],
                "agent.tool.completed",
                "codex",
                {
                    "tool": "shell",
                    "command": f"printf {secret}",
                    "output": f"OPENAI_API_KEY=sk-abcdefghijklmnop1234\nAuthorization: Bearer abcdefghijklmnop",
                    "nested": {"password": "traceback-secret"},
                },
            )
            app = OdysseusApp(store, host="127.0.0.1", port=0, scheduler=DummyScheduler())
            host, port = app.start()
            thread = threading.Thread(target=app.httpd.serve_forever, daemon=True)
            thread.start()
            base = f"http://{host}:{port}"
            try:
                with urllib.request.urlopen(f"{base}/api/runs/{run['id']}") as response:
                    run_payload = response.read().decode()
                with urllib.request.urlopen(f"{base}/api/runs/{run['id']}/events") as response:
                    events_payload = response.read().decode()
                with urllib.request.urlopen(f"{base}/api/runs/{run['id']}/stream?after=1", timeout=2) as response:
                    lines = []
                    while len(lines) < 4:
                        line = response.readline().decode()
                        if not line:
                            break
                        lines.append(line)
                        if line.startswith("data: "):
                            break
                stream_payload = "".join(lines)
                combined = run_payload + events_payload + stream_payload
                for leaked in (secret, "sk-abcdefghijklmnop1234", "abcdefghijklmnop", "traceback-secret"):
                    self.assertNotIn(leaked, combined)
                self.assertIn("[REDACTED]", combined)
                self.assertIn("redaction_receipt", events_payload)
            finally:
                app.stop()
                thread.join(timeout=2)

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
                self.assertEqual(bootstrap["version"], "0.9.2")
                self.assertIn("git", bootstrap["capabilities"])
                self.assertIn("docker", bootstrap["capabilities"])
                self.assertIn("devcontainer", bootstrap["capabilities"])
                self.assertIn("codex", bootstrap["assistant"])
                self.assertEqual(bootstrap["assistant"]["codex"]["mode"], "local_cli")
                self.assertIn("claude", bootstrap["assistant"])
                self.assertEqual(bootstrap["assistant"]["claude"]["mode"], "local_cli")
                self.assertEqual(bootstrap["assistant"]["openai"]["env"], "OPENAI_API_KEY")
                self.assertEqual(bootstrap["assistant"]["openai"]["model_env"], "ODYSSEUS_ASSISTANT_OPENAI_MODEL")
                self.assertEqual(bootstrap["assistant"]["openai"]["mode"], "direct_api")
                self.assertIn("anthropic", bootstrap["assistant"])
                self.assertEqual(bootstrap["intake"]["connectors"]["github_issue"]["credential_storage"], "external:gh")
                self.assertTrue(bootstrap["working_directory"])
                self.assertIsInstance(bootstrap["current_repository"], dict)
                self.assertEqual(bootstrap["test_capabilities"], {})

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
                self.assertIn('id="portfolioView"', html)
                self.assertIn('id="portfolioKpis"', html)
                self.assertIn("The delivery system for coding agents", html)
                self.assertIn('id="quickStart"', html)
                self.assertIn('id="journeyStepper"', html)
                self.assertIn('data-journey-step="1"', html)
                self.assertIn('data-journey-step="2"', html)
                self.assertIn('data-journey-step="3"', html)
                self.assertIn("Choose a repository", html)
                self.assertIn("New task", html)
                self.assertIn("What should the agent change?", html)
                self.assertIn("Start task", html)
                self.assertIn("Saved local checkouts", html)
                self.assertIn("<strong>Review</strong>", html)
                self.assertIn("Manage repositories", html)
                self.assertIn('id="settingsView"', html)
                self.assertIn('id="settingsForm"', html)
                self.assertIn("Models and API keys", html)
                self.assertIn("Choose a local Git folder", html)
                self.assertNotIn("Other repository path", html)
                self.assertIn('id="projectHome"', html)
                self.assertIn('id="repositoryStatusView"', html)
                self.assertIn('id="repositoryDeliveryMetrics"', html)
                self.assertIn('id="repositoryDependencyGraph"', html)
                self.assertIn('id="repositoryGantt"', html)
                self.assertIn('id="projectTimeline"', html)
                self.assertIn('id="projectSkillList"', html)
                self.assertIn('id="skillsView"', html)
                self.assertIn('id="skillDialog"', html)
                self.assertIn('id="taskSkillMode"', html)
                self.assertIn('id="contextReceipt"', html)
                self.assertIn('id="projectMemoryList"', html)
                self.assertIn('id="projectDecisionList"', html)
                self.assertIn('id="planSelectedDecisions"', html)
                self.assertIn('id="epicDecisionSources"', html)
                self.assertIn('id="epicRepositorySources"', html)
                self.assertIn('id="epicSourceUpload"', html)
                self.assertIn('id="epicUploadedSources"', html)
                self.assertIn("Upload documents", html)
                self.assertIn('id="taskSkillRecommendations"', html)
                self.assertIn('id="environmentProfile"', html)
                self.assertIn('id="environmentCard"', html)
                self.assertIn('id="assistantPanel"', html)
                self.assertIn('id="assistantProvider"', html)
                self.assertIn('id="assistantMessages"', html)
                self.assertIn('id="assistantComposer"', html)
                self.assertIn('id="summaryAssistant"', html)
                self.assertIn('id="summaryAssistantComposer"', html)
                self.assertIn('id="summaryAssistantProvider"', html)
                self.assertIn('id="themeToggle"', html)
                self.assertIn('id="workListToggle"', html)
                self.assertIn('id="workListPanel"', html)
                self.assertNotIn("Reset width", html)
                self.assertIn('href="/odysseus-icon.svg"', html)
                self.assertIn('value="repositories"', html)
                self.assertIn('id="recoveryCard"', html)
                self.assertIn('id="inlineFeedback"', html)
                self.assertIn('id="reviewDecisionCard"', html)
                self.assertIn('id="confirmDialog"', html)
                self.assertIn('id="integrationDialog"', html)
                self.assertIn("Direct API: ChatGPT", html)
                self.assertIn("Share diff/code excerpt", html)
                self.assertIn("blank scratch workspace", html)
                self.assertIn("not the task repository", html)
                self.assertIn('data-section="summary"', html)
                self.assertIn('data-section="evidence"', html)

                with urllib.request.urlopen(f"{base}/app.js") as response:
                    app_js = response.read().decode()
                self.assertIn("Follow up", app_js)
                self.assertIn("summaryAssistantSend", app_js)
                self.assertIn("syncAssistantProvider", app_js)
                self.assertIn('["failed", "attention"]', app_js)
                self.assertIn('["review", "failed", "attention", "accepted", "pr_created"]', app_js)
                self.assertIn("feedbackDialog", app_js)
                self.assertIn("Apply to repository", app_js)
                self.assertIn("Combine approved changes", app_js)
                self.assertIn("integration-candidates", app_js)
                self.assertIn("approved · not applied", app_js)
                self.assertIn("Open Changes to load the diff.", app_js)
                self.assertIn("eventsLoadedRunId", app_js)
                self.assertIn("Resolve integration", app_js)
                self.assertIn("Delivered in integration PR", app_js)
                self.assertIn("Open integration PR", app_js)
                self.assertIn("Plan selected", app_js)
                self.assertIn("source_paths", app_js)
                self.assertIn("source_documents", app_js)
                self.assertIn("refreshEpicSourceChoices", app_js)
                self.assertIn('sessionScope: "repositories"', app_js)
                self.assertIn("repositoryScopedSessions", app_js)
                self.assertIn('$("#sessionNavCount").textContent = count || "";', app_js)
                self.assertNotIn('$("#sessionNavCount").textContent = state.sessions.length || "";', app_js)
                self.assertIn("runTitle(run)", app_js)
                self.assertIn('dataset.theme = savedTheme === "dark" ? "dark" : "light"', app_js)
                self.assertIn('state.workListExpanded = !project', app_js)
                self.assertIn('$("#workSummary").classList.add("hidden")', app_js)
                self.assertIn('$("#journeyStepper").classList.add("hidden")', app_js)
                self.assertIn("state.bootstrap?.test_capabilities?.browser_regression === true", app_js)
                self.assertIn('const section = ["diff", "integration"].includes(name) ? "changes" : "evidence";', app_js)
                self.assertNotIn("const [run, diff] = await Promise.all", app_js)

                with urllib.request.urlopen(f"{base}/odysseus-icon.svg") as response:
                    icon = response.read().decode()
                    self.assertEqual(response.headers.get_content_type(), "image/svg+xml")
                self.assertIn("<svg", icon)

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
                self.assertIn("temporary scratch working directory", local_call.call_args.args[2])
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

    def test_integration_candidate_and_disposition_endpoints_are_token_protected(self) -> None:
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
            runs = []
            for title in ("Backend", "Frontend"):
                run = store.create({"title": title, "task": title, "project_path": str(repo), "status": "review"})
                runs.append(
                    store.update(
                        run["id"],
                        status="accepted",
                        base_ref="main",
                        base_sha=base_sha,
                        artifact_sha=base_sha,
                        artifact_files=[f"{title.lower()}.txt"],
                        artifact_created_at="2026-08-16T00:00:00Z",
                        delivery={**run["delivery"], "status": "not_applied", "target_branch": "main"},
                    )
                )
            app = OdysseusApp(store, host="127.0.0.1", port=0, scheduler=DummyScheduler())
            host, port = app.start()
            thread = threading.Thread(target=app.httpd.serve_forever, daemon=True)
            thread.start()
            base = f"http://{host}:{port}"
            try:
                with urllib.request.urlopen(f"{base}/api/bootstrap") as response:
                    token = json.load(response)["token"]
                with urllib.request.urlopen(f"{base}/api/runs/{runs[0]['id']}/integration-candidates") as response:
                    preview = json.load(response)
                self.assertEqual({item["id"] for item in preview["candidates"]}, {run["id"] for run in runs})

                forbidden = urllib.request.Request(
                    f"{base}/api/runs/{runs[0]['id']}/integration",
                    data=json.dumps({"dispositions": {}}).encode(),
                    headers={"Content-Type": "application/json"},
                )
                with self.assertRaises(urllib.error.HTTPError) as caught:
                    urllib.request.urlopen(forbidden)
                self.assertEqual(caught.exception.code, 403)
                caught.exception.close()

                request = urllib.request.Request(
                    f"{base}/api/runs/{runs[0]['id']}/integration",
                    data=json.dumps(
                        {
                            "dispositions": {
                                runs[0]["id"]: {"decision": "integrate_now"},
                                runs[1]["id"]: {"decision": "integrate_now"},
                            }
                        }
                    ).encode(),
                    headers={"Content-Type": "application/json", "X-Odysseus-Token": token},
                )
                with urllib.request.urlopen(request) as response:
                    result = json.load(response)
                self.assertEqual(result["integration_run"]["task_key"], "integration-delivery")
                self.assertEqual(set(result["integration_run"]["depends_on"]), {run["id"] for run in runs})
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
