from __future__ import annotations

import argparse
import contextlib
import errno
import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from odysseus import __version__
from odysseus.cli import (
    _running_odysseus_url,
    cmd_doctor,
    cmd_export,
    cmd_rebuild_projections,
    cmd_replay,
    cmd_serve,
    cmd_update,
    cmd_version,
    parser,
)


class CLITests(unittest.TestCase):
    class ProbeResponse(io.BytesIO):
        def __init__(self, value: bytes, content_type: str) -> None:
            super().__init__(value)
            self.headers = mock.Mock()
            self.headers.get_content_type.return_value = content_type

        def __enter__(self):  # noqa: ANN204
            return self

        def __exit__(self, *_args):  # noqa: ANN204
            self.close()

    def test_start_is_a_serve_alias_and_version_is_current(self) -> None:
        args = parser().parse_args(["start", "--port", "9911"])
        self.assertEqual(args.port, 9911)
        self.assertEqual(args.func.__name__, "cmd_serve")
        self.assertEqual(__version__, "0.9.2")

    def test_start_chooses_the_next_port_when_the_requested_port_is_busy(self) -> None:
        class FakeHTTPD:
            def serve_forever(self, poll_interval=0.35):  # noqa: ANN001, ARG002
                return None

        class FakeApp:
            attempted_ports: list[int] = []

            def __init__(self, _store, *, host, port, **_options):  # noqa: ANN001
                self.host = host
                self.port = port
                self.httpd = FakeHTTPD()
                self.__class__.attempted_ports.append(port)

            def start(self):  # noqa: ANN201
                if self.port == 9911:
                    raise OSError(errno.EADDRINUSE, "address already in use")
                return self.host, self.port

            def stop(self):  # noqa: ANN201
                return None

        with tempfile.TemporaryDirectory() as temp:
            args = parser().parse_args(["--state-dir", temp, "start", "--port", "9911", "--open"])
            output = io.StringIO()
            fake_store = mock.Mock(root=Path(temp))
            with (
                mock.patch("odysseus.cli.OdysseusApp", FakeApp),
                mock.patch("odysseus.cli._store", return_value=fake_store),
                mock.patch("odysseus.cli.webbrowser.open") as opened,
                contextlib.redirect_stdout(output),
            ):
                self.assertEqual(cmd_serve(args), 0)

        self.assertEqual(FakeApp.attempted_ports, [9911, 9912])
        self.assertIn("Port 9911 is unavailable; trying 9912.", output.getvalue())
        self.assertIn("http://127.0.0.1:9912/", output.getvalue())
        opened.assert_called_once_with("http://127.0.0.1:9912/")

    def test_running_server_probe_requires_the_real_web_ui(self) -> None:
        healthy = self.ProbeResponse(b'{"ok":true,"product":"odysseus"}', "application/json")
        page = self.ProbeResponse(b"<html><title>Odysseus</title></html>", "text/html")
        with mock.patch("odysseus.cli.urllib.request.urlopen", side_effect=[healthy, page]):
            self.assertEqual(_running_odysseus_url("127.0.0.1", 8741), "http://127.0.0.1:8741")

        api_only = self.ProbeResponse(b'{"ok":true,"product":"odysseus"}', "application/json")
        missing_page = self.ProbeResponse(b'{"error":"web asset not found"}', "application/json")
        with mock.patch("odysseus.cli.urllib.request.urlopen", side_effect=[api_only, missing_page]):
            self.assertEqual(_running_odysseus_url("127.0.0.1", 8741), "")

    def test_doctor_has_readable_and_json_modes(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            human_args = argparse.Namespace(state_dir=Path(temp) / "human", json=False)
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                result = cmd_doctor(human_args)
            self.assertIn("Odysseus 0.9.2", output.getvalue())
            self.assertIn("Git", output.getvalue())
            self.assertIn(result, {0, 1})

            json_args = argparse.Namespace(state_dir=Path(temp) / "json", json=True)
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                cmd_doctor(json_args)
            self.assertIn('"state_dir"', output.getvalue())

    def test_version_subcommand_reports_compatibility_markers(self) -> None:
        args = argparse.Namespace(json=True)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(cmd_version(args), 0)
        value = __import__("json").loads(output.getvalue())
        self.assertEqual(value["version"], __version__)
        self.assertGreaterEqual(value["run_schema"], 1)
        self.assertGreaterEqual(value["event_schema"], 1)
        self.assertEqual(value["canonical_event_schema"], 2)
        self.assertEqual(value["command_schema"], 1)

    def test_export_redacts_nested_state_and_events(self) -> None:
        from odysseus.store import RunStore

        secret = "ghp_abcdefghijklmnop1234"
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / "project"
            project.mkdir()
            store = RunStore(root / "state")
            run = store.create({"task": f"Export {secret}", "project_path": str(project)})
            store.append_event(
                run["id"],
                "agent.output",
                "codex",
                {"text": f"OPENAI_API_KEY=sk-abcdefghijklmnop1234\nAuthorization: Bearer abcdefghijklmnop"},
            )
            args = argparse.Namespace(
                state_dir=store.root,
                format="json",
                output=None,
                view="lead",
                privacy="full",
            )
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(cmd_export(args), 0)
            payload = output.getvalue()

        self.assertIn("[REDACTED]", payload)
        for leaked in (secret, "sk-abcdefghijklmnop1234", "abcdefghijklmnop"):
            self.assertNotIn(leaked, payload)

    def test_run_variants_flag_is_explicit_opt_in(self) -> None:
        args = parser().parse_args(
            [
                "run",
                "--variants",
                "2",
                "--variant-lane",
                "codex",
                "--variant-lane",
                "claude",
                "--variant-prompt",
                "small",
                "High value task",
            ]
        )
        self.assertEqual(args.variants, 2)
        self.assertEqual(args.variant_lane, ["codex", "claude"])
        self.assertEqual(args.variant_prompt, ["small"])

    def test_replay_and_rebuild_projection_commands_use_canonical_stream(self) -> None:
        from odysseus.store import RunStore

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / "project"
            project.mkdir()
            store = RunStore(root / "state")
            run = store.create({"task": "CLI replay fixture", "project_path": str(project)})
            replay_args = argparse.Namespace(state_dir=store.root, run_id=run["id"], until_event=None, json=True)
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(cmd_replay(replay_args), 0)
            self.assertEqual(__import__("json").loads(output.getvalue())["id"], run["id"])

            (store.runs_dir / f"{run['id']}.json").unlink()
            rebuild_args = argparse.Namespace(state_dir=store.root, run_id=run["id"], dry_run=False, json=True)
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(cmd_rebuild_projections(rebuild_args), 0)
            self.assertEqual(__import__("json").loads(output.getvalue())["runs"], 1)
            self.assertTrue((store.runs_dir / f"{run['id']}.json").is_file())

    def test_source_checkout_update_defers_to_its_package_manager(self) -> None:
        args = argparse.Namespace(state_dir=Path("/tmp/unused"), check=True, edge=False, target_version=None)
        error = io.StringIO()
        with contextlib.redirect_stderr(error):
            self.assertEqual(cmd_update(args), 2)
        self.assertIn("pipx upgrade", error.getvalue())


if __name__ == "__main__":
    unittest.main()
