from __future__ import annotations

import unittest

from odysseus.tmux import TmuxBridge


class TmuxTests(unittest.TestCase):
    def test_attach_commands_validate_session_and_optional_pane(self) -> None:
        self.assertEqual(TmuxBridge.attach_command("agent-1"), "tmux attach-session -t agent-1")
        self.assertEqual(
            TmuxBridge.attach_command("14", "%57"),
            "tmux select-pane -t %57 \\; attach-session -t 14",
        )
        with self.assertRaises(ValueError):
            TmuxBridge.attach_command("bad session")
        with self.assertRaises(ValueError):
            TmuxBridge.attach_command("14", "$(touch nope)")


if __name__ == "__main__":
    unittest.main()
