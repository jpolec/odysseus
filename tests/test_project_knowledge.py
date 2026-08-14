from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from odysseus.store import RunStore


class ProjectKnowledgeTests(unittest.TestCase):
    def test_overview_discovers_docs_stack_commits_and_project_activity(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / "service"
            project.mkdir()
            (project / "README.md").write_text("# Billing Service\n\nOwns invoice and payment state.\n", encoding="utf-8")
            (project / "AGENTS.md").write_text("Run unit tests before changing invoice logic.\n", encoding="utf-8")
            (project / "pyproject.toml").write_text("[project]\nname='billing'\n", encoding="utf-8")
            subprocess.run(["git", "init", "-q", str(project)], check=True)
            subprocess.run(["git", "-C", str(project), "add", "."], check=True)
            subprocess.run(
                ["git", "-C", str(project), "-c", "user.name=Odysseus", "-c", "user.email=odysseus@example.test", "commit", "-qm", "Initial billing service"],
                check=True,
            )
            store = RunStore(root / "state")
            run = store.create({"task": "Document invoice retries", "project_path": str(project)})
            store.append_event(run["id"], "run.started", "odysseus", {})
            project_id = run["project_id"]

            overview = store.knowledge.overview(project_id)
            self.assertIn("Billing Service", overview["about"])
            self.assertEqual(overview["readme"]["path"], "README.md")
            self.assertEqual(overview["instructions"][0]["path"], "AGENTS.md")
            self.assertIn("Python", overview["stack"])
            self.assertEqual(overview["commits"][0]["subject"], "Initial billing service")
            self.assertIn("run.started", {item["type"] for item in overview["activity"]})

            store.knowledge.update_profile(project_id, {"summary": "Operator-owned summary", "notes": "Keep invoice ids stable."})
            updated = store.knowledge.overview(project_id)
            self.assertEqual(updated["about"], "Operator-owned summary")
            self.assertEqual(updated["profile"]["notes"], "Keep invoice ids stable.")

    def test_context_receipt_freezes_exact_project_and_skill_snapshots(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / "service"
            project.mkdir()
            (project / "README.md").write_text("# Identity\n\nAuthentication service.\n", encoding="utf-8")
            (project / "AGENTS.md").write_text("Never log access tokens.\n", encoding="utf-8")
            store = RunStore(root / "state")

            run = store.create({"task": "Review authentication security", "project_path": str(project)})
            receipt = run["context_receipt"]
            source_kinds = {source["kind"] for source in receipt["sources"]}

            self.assertEqual(receipt["version"], "context-receipt-v1")
            self.assertEqual(receipt["source_count"], len(receipt["sources"]))
            self.assertIn("readme", source_kinds)
            self.assertIn("agent_instructions", source_kinds)
            self.assertIn("skill", source_kinds)
            self.assertIn("context.receipt.created", {event["type"] for event in store.events(run["id"])})
            prompt = __import__("odysseus.scheduler", fromlist=["Scheduler"]).Scheduler._implementation_prompt(run, 1, 0, "")
            self.assertIn("Authentication service", prompt)
            self.assertIn("Never log access tokens", prompt)
            self.assertIn("SKILL security-review", prompt)

            (project / "README.md").write_text("# Replaced after queueing\n", encoding="utf-8")
            persisted = store.get(run["id"])
            self.assertIn("Authentication service", persisted["context_bundle"][0]["content"])


if __name__ == "__main__":
    unittest.main()
