from __future__ import annotations

import unittest
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from odysseus.tmux import TmuxBridge


class TmuxTests(unittest.TestCase):
    def test_managed_worktree_resolves_to_source_without_registering_it(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "odysseus"
            worktree = root / "state" / "worktrees" / "task"
            source.mkdir()
            worktree.mkdir(parents=True)
            bridge = TmuxBridge(SimpleNamespace(), receipts_dir=root / "receipts")
            bridge._managed_worktrees = {str(worktree.resolve()): str(source.resolve())}
            with patch("odysseus.tmux._run", return_value=SimpleNamespace(returncode=0, stdout=str(worktree))):
                resolved = bridge._canonical_project_path(str(worktree))

            self.assertEqual(resolved, str(source.resolve()))

    def test_pane_status_uses_only_tmux_visible_signals(self) -> None:
        self.assertEqual(TmuxBridge._pane_status("[ ! ] Action Required | QJ_REPO"), "waiting")
        self.assertEqual(TmuxBridge._pane_status("Working"), "working")
        self.assertEqual(TmuxBridge._pane_status("⠹ QJ_REPO"), "working")
        self.assertEqual(TmuxBridge._pane_status("QJ_REPO"), "unknown")

    def test_pane_title_prefers_window_name_without_guessing_prompt(self) -> None:
        pane = {"window_name": "qj-data", "pane_title": "Working", "path": "/tmp/QJ_REPO", "target": "%14"}
        self.assertEqual(TmuxBridge._pane_display_title(pane, "codex"), "qj-data")
        generic = {"window_name": "Working", "pane_title": "Working", "path": "/tmp/Working", "target": "%18"}
        self.assertEqual(TmuxBridge._pane_display_title(generic, "codex"), "Codex pane %18")
        spinner = {"window_name": "tmux", "pane_title": "⠦ jakub", "path": "/Users/jakub", "target": "%3"}
        self.assertEqual(TmuxBridge._pane_display_title(spinner, "codex"), "Codex pane %3")
        claude = {"window_name": "web", "pane_title": "✳ Create security pages", "path": "/tmp/repo", "target": "%57"}
        self.assertEqual(TmuxBridge._pane_display_title(claude, "claude"), "Create security pages")

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

    def test_missing_tracked_pane_never_guesses_a_saved_agent_thread(self) -> None:
        bridge = TmuxBridge(object())
        bridge.list = lambda: []  # type: ignore[method-assign]
        with self.assertRaisesRegex(ValueError, "will not guess"):
            bridge.takeover(
                {
                    "id": "tracked-pane",
                    "kind": "tmux",
                    "lane": "codex",
                    "tmux_session": "14",
                    "tmux_target": "%37",
                    "agent_session_id": "heuristic-id-must-not-be-used",
                }
            )


if __name__ == "__main__":
    unittest.main()
