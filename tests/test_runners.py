from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

from odysseus.runners import AgentRunner, _VendorNormalizer, _sanitize


class RunnerTests(unittest.TestCase):
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
        command = runner.command(
            "codex",
            Path("/tmp/worktree"),
            "continue",
            review=False,
            resume_session_id="0199a213-81c0-7800-8aa1-bbab2a035a53",
        )
        self.assertEqual(command[:3], ["codex", "exec", "resume"])
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

    def test_telemetry_redacts_common_secrets(self) -> None:
        value = _sanitize({"api_key": "secret", "command": "curl -H 'Authorization: Bearer abcdefghijklmnop'"})
        self.assertEqual(value["api_key"], "[REDACTED]")
        self.assertNotIn("abcdefghijklmnop", value["command"])


if __name__ == "__main__":
    unittest.main()
