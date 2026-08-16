from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from odysseus.intake import IntakeCoordinator, github_issue_signal
from odysseus.store import RunStore


class IntakeTests(unittest.TestCase):
    def test_github_issue_normalizes_redacts_and_proposes_gated_epic(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / "project"
            project.mkdir()
            store = RunStore(root / "state")
            project_record = {"github_url": "https://github.com/acme/app", "path": str(project)}
            signal = github_issue_signal(
                {
                    "number": 42,
                    "title": "Production login incident",
                    "body": "User alice@example.com saw bearer ghp_abcdefghijklmnop1234 in logs.",
                    "url": "https://github.com/acme/app/issues/42",
                    "labels": [{"name": "sev1"}, {"name": "bug"}],
                    "assignees": [{"login": "ops"}],
                    "state": "open",
                },
                project_record,
            )

            self.assertEqual(signal["severity"], "high")
            self.assertEqual(signal["identity"]["external_id"], "42")
            self.assertEqual(signal["permissions"]["credential_storage"], "external:gh")
            self.assertFalse(signal["permissions"]["secrets_persisted"])
            self.assertNotIn("alice@example.com", signal["evidence"]["body_excerpt"])
            self.assertNotIn("ghp_abcdefghijklmnop1234", signal["evidence"]["body_excerpt"])

            intake = IntakeCoordinator(store)
            epic = intake.propose(
                signal,
                project_path=str(project),
                lane="codex",
                review_lane="claude",
                checks=["python3 -m unittest"],
            )
            duplicate = intake.propose(signal, project_path=str(project))

            self.assertEqual(epic["status"], "proposed")
            self.assertFalse(epic["approved"])
            self.assertFalse(epic["intake"]["starts_agents"])
            self.assertEqual(epic["intake"]["dedupe_key"], signal["dedupe_key"])
            self.assertEqual([task["task_key"] for task in epic["plan"]["tasks"]], ["diagnosis", "repair", "checks", "review", "draft-pr"])
            self.assertEqual(store.list(), [])
            self.assertTrue(duplicate["duplicate"])
            self.assertEqual(duplicate["id"], epic["id"])
            self.assertEqual(duplicate["intake"]["seen_count"], 2)
            self.assertEqual(len(duplicate["intake"]["observations"]), 2)


if __name__ == "__main__":
    unittest.main()
