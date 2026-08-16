from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from odysseus.runners import AgentRunner, CheckRunner, _VendorNormalizer, _attention_from_text, _sanitize


class RunnerTests(unittest.TestCase):
    def test_explicit_attention_marker_becomes_normalized_question(self) -> None:
        parsed = _attention_from_text(
            'I need a decision.\nODYSSEUS_ATTENTION: {"type":"question","title":"Schema","message":"Allow NULL?","options":["yes","no"]}'
        )
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed[0], "agent.question")
        self.assertEqual(parsed[1]["options"], ["yes", "no"])

    def test_vendor_json_becomes_normalized_agent_output(self) -> None:
        script = (
            "import json; "
            "print(json.dumps({'type':'assistant','message':{'content':[{'text':'hello'}]}}))"
        )
        runner = AgentRunner({"fake": [sys.executable, "-c", script]})
        events = []
        with tempfile.TemporaryDirectory() as temp:
            result = runner.run(
                "fake",
                Path(temp),
                "task",
                review=False,
                emit=lambda event_type, source, data: events.append((event_type, source, data)),
                cancelled=lambda: False,
            )

        self.assertEqual(result.returncode, 0)
        self.assertEqual(events[0][0], "agent.output")
        self.assertEqual(events[0][1], "fake")
        self.assertEqual(events[0][2]["vendor_type"], "assistant")
        self.assertEqual(events[0][2]["text"], "hello")

    def test_builtin_review_modes_are_read_only(self) -> None:
        runner = AgentRunner()
        codex = runner.command("codex", Path("/tmp/worktree"), "review", review=True)
        claude = runner.command("claude", Path("/tmp/worktree"), "review", review=True)

        self.assertEqual(codex[codex.index("--sandbox") + 1], "read-only")
        self.assertEqual(claude[claude.index("--permission-mode") + 1], "plan")

    def test_codex_resume_and_typed_telemetry(self) -> None:
        runner = AgentRunner()
        worktree = Path("/tmp/worktree")
        command = runner.command(
            "codex",
            worktree,
            "continue",
            review=False,
            resume_session_id="0199a213-81c0-7800-8aa1-bbab2a035a53",
        )
        self.assertEqual(command[:3], ["codex", "exec", "--json"])
        self.assertEqual(command[command.index("-C") + 1], str(worktree))
        self.assertLess(command.index("--sandbox"), command.index("resume"))
        self.assertEqual(
            command[command.index("resume") + 1],
            "0199a213-81c0-7800-8aa1-bbab2a035a53",
        )
        normalizer = _VendorNormalizer("codex", "agent", True)
        events = normalizer.events(
            {"type": "thread.started", "thread_id": "0199a213-81c0-7800-8aa1-bbab2a035a53"}
        )
        events += normalizer.events(
            {"type": "item.started", "item": {"id": "1", "type": "command_execution", "command": "git status"}}
        )
        events += normalizer.events(
            {"type": "turn.completed", "usage": {"input_tokens": 20, "cached_input_tokens": 12, "output_tokens": 4}}
        )
        self.assertEqual([item[0] for item in events], ["agent.session", "agent.tool.started", "agent.usage"])
        self.assertEqual(events[-1][1]["cached_input_tokens"], 12)

    def test_host_checks_preserve_server_path_without_a_login_shell(self) -> None:
        runner = CheckRunner()
        with tempfile.TemporaryDirectory() as temp, mock.patch.dict(
            os.environ,
            {"PATH": "/opt/odysseus-test-bin:/usr/bin:/bin", "OPENAI_API_KEY": "server-only"},
            clear=False,
        ), mock.patch("odysseus.runners._stream_process") as stream:
            runner.run(
                "python3 --version",
                Path(temp),
                emit=lambda *_args: None,
                cancelled=lambda: False,
                execution={"profile": "host"},
            )

        self.assertEqual(stream.call_args.args[0], ["/bin/sh", "-c", "python3 --version"])
        self.assertEqual(
            stream.call_args.kwargs["process_env"]["PATH"],
            "/opt/odysseus-test-bin:/usr/bin:/bin",
        )
        self.assertNotIn("OPENAI_API_KEY", stream.call_args.kwargs["process_env"])

    def test_claude_denied_tool_becomes_permission_request(self) -> None:
        normalizer = _VendorNormalizer("claude", "agent", False)
        normalizer.events(
            {
                "type": "assistant",
                "session_id": "thread-1",
                "message": {
                    "content": [
                        {"type": "tool_use", "id": "tool-1", "name": "Bash", "input": {}}
                    ]
                },
            }
        )
        events = normalizer.events(
            {
                "type": "user",
                "session_id": "thread-1",
                "message": {
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "tool-1",
                            "is_error": True,
                            "content": "This command requires approval",
                        }
                    ]
                },
            }
        )
        self.assertEqual([item[0] for item in events], ["agent.tool.completed", "agent.permission_request"])
        self.assertEqual(events[-1][1]["tool"], "Bash")

    def test_telemetry_redacts_common_secrets(self) -> None:
        value = _sanitize({"api_key": "secret", "command": "curl -H 'Authorization: Bearer abcdefghijklmnop'"})
        self.assertEqual(value["api_key"], "[REDACTED]")
        self.assertNotIn("abcdefghijklmnop", value["command"])

    def test_allowlisted_runtime_value_is_redacted_from_events_and_result(self) -> None:
        credential = "ordinary-value-not-matching-a-token-pattern"
        events = []
        with tempfile.TemporaryDirectory() as temp, mock.patch.dict(
            os.environ, {"RUNTIME_CREDENTIAL": credential}, clear=False
        ):
            result = CheckRunner().run(
                "printf '%s\\n' \"$RUNTIME_CREDENTIAL\"",
                Path(temp),
                emit=lambda event_type, source, data: events.append((event_type, source, data)),
                cancelled=lambda: False,
                execution={"profile": "host", "credential_env_names": ["RUNTIME_CREDENTIAL"]},
            )

        self.assertEqual(result.returncode, 0)
        self.assertNotIn(credential, result.output)
        self.assertEqual(result.output, "[REDACTED]")
        self.assertNotIn(credential, str(events))

    def test_usage_counters_are_not_mistaken_for_credentials(self) -> None:
        value = _sanitize(
            {
                "input_tokens": 123,
                "cached_input_tokens": 80,
                "output_tokens": 17,
                "token": "credential-value",
            }
        )
        self.assertEqual(value["input_tokens"], 123)
        self.assertEqual(value["cached_input_tokens"], 80)
        self.assertEqual(value["output_tokens"], 17)
        self.assertEqual(value["token"], "[REDACTED]")

    def test_agent_timeout_emits_liveness_event_and_stops_process_group(self) -> None:
        runner = AgentRunner({"slow": [sys.executable, "-c", "import time; time.sleep(10)"]})
        events = []
        with tempfile.TemporaryDirectory() as temp:
            result = runner.run(
                "slow",
                Path(temp),
                "task",
                review=False,
                emit=lambda event_type, source, data: events.append((event_type, source, data)),
                cancelled=lambda: False,
                timeout_seconds=0.1,
            )

        self.assertTrue(result.cancelled)
        self.assertEqual(result.stop_reason, "timeout")
        self.assertIn("run.stalled", [event[0] for event in events])


if __name__ == "__main__":
    unittest.main()
