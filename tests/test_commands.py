from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

from odysseus.cli import main
from odysseus.commands import CommandBus, CommandOutcomeUnknown, IdempotencyConflict
from odysseus.kernel import ConcurrencyConflict
from odysseus.server import OdysseusApp
from odysseus.state import verify_state
from odysseus.store import RunStore


class PassiveScheduler:
    def start(self) -> None:
        return None

    def stop(self) -> None:
        return None

    def active_count(self) -> int:
        return 0


class CommandBusTests(unittest.TestCase):
    def _run(self, root: Path) -> tuple[RunStore, dict[str, object]]:
        project = root / "repo"
        project.mkdir()
        store = RunStore(root / "state")
        return store, store.create({"task": "Command fixture", "project_path": str(project)})

    def test_duplicate_submission_returns_original_result_and_mutates_once(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            store, run = self._run(Path(temp))
            version = store.kernel.stream_version(str(run["id"]))
            calls = 0

            def change() -> dict[str, object]:
                nonlocal calls
                calls += 1
                return store.update(str(run["id"]), feedback="one durable update")

            first = store.commands.execute(
                "run.update",
                {"feedback": "one durable update"},
                change,
                idempotency_key="same-request",
                target_stream=f"run:{run['id']}",
                expected_version=version,
            )
            duplicate = store.commands.execute(
                "run.update",
                {"feedback": "one durable update"},
                lambda: self.fail("duplicate command executed its handler"),
                idempotency_key="same-request",
                target_stream=f"run:{run['id']}",
                expected_version=version,
            )

            self.assertEqual(calls, 1)
            self.assertFalse(first.duplicate)
            self.assertTrue(duplicate.duplicate)
            self.assertEqual(duplicate.result["feedback"], "one durable update")
            command_id = first.receipt["command"]["command_id"]
            matching = [event for event in store.kernel.read(str(run["id"])) if event["command_id"] == command_id]
            self.assertEqual(len(matching), 1)
            self.assertEqual(matching[0]["idempotency_key"], "same-request")
            self.assertTrue(verify_state(store.root)["valid"])

    def test_expected_version_rejects_stale_write_without_changing_projection(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            store, run = self._run(Path(temp))
            stale = store.kernel.stream_version(str(run["id"]))
            store.update(str(run["id"]), feedback="newer state")

            with self.assertRaisesRegex(ConcurrencyConflict, "expected"):
                store.commands.execute(
                    "run.update",
                    {"feedback": "stale overwrite"},
                    lambda: store.update(str(run["id"]), feedback="stale overwrite"),
                    idempotency_key="stale-request",
                    target_stream=f"run:{run['id']}",
                    expected_version=stale,
                )

            self.assertEqual(store.get(str(run["id"]))["feedback"], "newer state")
            receipt = next(item for item in store.commands.list() if item["command"]["idempotency_key"] == "stale-request")
            self.assertEqual(receipt["state"], "failed")

    def test_same_key_with_different_payload_is_a_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            bus = CommandBus(Path(temp) / "state")
            bus.execute("config.update", {"value": 1}, lambda: {"value": 1}, idempotency_key="fixed")
            with self.assertRaises(IdempotencyConflict):
                bus.execute("config.update", {"value": 2}, lambda: {"value": 2}, idempotency_key="fixed")

    def test_interrupted_command_becomes_unknown_and_is_not_reexecuted(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "state"
            first_process = CommandBus(root)
            ticket = first_process.begin("run.cancel", {"run_id": "r1"}, idempotency_key="interrupted")
            receipt = json.loads(ticket.path.read_text(encoding="utf-8"))
            receipt["owner"]["pid"] = 999_999_999
            ticket.path.write_text(json.dumps(receipt), encoding="utf-8")
            second_process = CommandBus(root)

            with self.assertRaisesRegex(CommandOutcomeUnknown, "unknown outcome"):
                second_process.begin("run.cancel", {"run_id": "r1"}, idempotency_key="interrupted")

            receipt = second_process.get(ticket.command_id)
            self.assertEqual(receipt["state"], "unknown")
            self.assertEqual(receipt["error"]["type"], "process_interrupted")

    def test_duplicate_does_not_mark_a_live_command_unknown(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "state"
            first_process = CommandBus(root)
            ticket = first_process.begin("run.cancel", {"run_id": "r1"}, idempotency_key="live")

            with self.assertRaisesRegex(CommandOutcomeUnknown, "still executing"):
                CommandBus(root).begin("run.cancel", {"run_id": "r1"}, idempotency_key="live")

            self.assertEqual(CommandBus(root, readonly=True).get(ticket.command_id)["state"], "executing")
            first_process.finish(ticket, {"ok": True})

    def test_command_payload_result_and_policy_are_redacted_before_persistence(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "state"
            secret = "sk-command-secret-abcdefghijklmnop"
            bus = CommandBus(root)
            execution = bus.execute(
                "config.update",
                {"authorization": f"Bearer {secret}"},
                lambda: {"message": f"OPENAI_API_KEY={secret}"},
                idempotency_key="redacted",
                policy_context={"credential": secret},
            )

            raw = execution.receipt
            persisted = next((root / "commands").glob("*.json")).read_text(encoding="utf-8")
            self.assertEqual(raw["state"], "completed")
            self.assertNotIn(secret, persisted)
            self.assertIn("[REDACTED]", persisted)

    def test_http_post_and_cli_use_the_same_durable_command_bus(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / "repo"
            project.mkdir()
            store = RunStore(root / "http-state")
            app = OdysseusApp(store, host="127.0.0.1", port=0, scheduler=PassiveScheduler())
            host, port = app.start()
            thread = threading.Thread(target=app.httpd.serve_forever, daemon=True)  # type: ignore[union-attr]
            thread.start()
            try:
                body = json.dumps({"task": "HTTP idempotency", "project_path": str(project)}).encode("utf-8")
                headers = {
                    "Content-Type": "application/json",
                    "X-Odysseus-Token": app.token,
                    "Idempotency-Key": "http-create-once",
                }
                responses: list[tuple[dict[str, object], str, str]] = []
                for _ in range(2):
                    request = urllib.request.Request(
                        f"http://{host}:{port}/api/runs", data=body, headers=headers, method="POST"
                    )
                    with urllib.request.urlopen(request) as response:
                        responses.append(
                            (
                                json.loads(response.read()),
                                response.headers["X-Odysseus-Command-Id"],
                                response.headers["X-Odysseus-Idempotent-Replay"],
                            )
                        )
                command_id = responses[0][1]
                with urllib.request.urlopen(f"http://{host}:{port}/api/commands/{command_id}") as response:
                    receipt = json.loads(response.read())
            finally:
                app.stop()
                thread.join(timeout=2)

            self.assertEqual(responses[0][0]["id"], responses[1][0]["id"])
            self.assertEqual(responses[0][1], responses[1][1])
            self.assertEqual([item[2] for item in responses], ["false", "true"])
            self.assertEqual(len(store.list()), 1)
            self.assertEqual(receipt["state"], "completed")

            cli_state = root / "cli-state"
            argv = [
                "odysseus",
                "--state-dir",
                str(cli_state),
                "--idempotency-key",
                "cli-create-once",
                "run",
                "CLI idempotency",
                "--project",
                str(project),
                "--json",
            ]
            outputs: list[str] = []
            for _ in range(2):
                output = io.StringIO()
                with mock.patch.object(sys, "argv", argv), contextlib.redirect_stdout(output):
                    self.assertEqual(main(), 0)
                outputs.append(output.getvalue())
            self.assertEqual(json.loads(outputs[0])["id"], json.loads(outputs[1])["id"])
            cli_store = RunStore(cli_state)
            self.assertEqual(len(cli_store.list()), 1)
            cli_command_id = cli_store.commands.list()[0]["command"]["command_id"]
            output = io.StringIO()
            with (
                mock.patch.object(
                    sys,
                    "argv",
                    ["odysseus", "--state-dir", str(cli_state), "command", cli_command_id],
                ),
                contextlib.redirect_stdout(output),
            ):
                self.assertEqual(main(), 0)
            self.assertEqual(json.loads(output.getvalue())["state"], "completed")

    def test_rejected_http_delete_finishes_its_command_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            store = RunStore(root / "state")
            app = OdysseusApp(store, host="127.0.0.1", port=0, scheduler=PassiveScheduler())
            host, port = app.start()
            thread = threading.Thread(target=app.httpd.serve_forever, daemon=True)  # type: ignore[union-attr]
            thread.start()
            try:
                request = urllib.request.Request(
                    f"http://{host}:{port}/api/not-a-project",
                    headers={
                        "X-Odysseus-Token": app.token,
                        "Idempotency-Key": "delete-invalid-route",
                    },
                    method="DELETE",
                )
                with self.assertRaises(urllib.error.HTTPError) as raised:
                    urllib.request.urlopen(request)
                error = raised.exception
                self.assertEqual(error.code, 404)
                command_id = error.headers["X-Odysseus-Command-Id"]
                error.close()
            finally:
                app.stop()
                thread.join(timeout=2)

            receipt = store.commands.get(command_id)
            self.assertEqual(receipt["state"], "failed")
            self.assertEqual(receipt["http_status"], 404)
            self.assertEqual(receipt["result"], {"error": "not found"})


if __name__ == "__main__":
    unittest.main()
