from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from odysseus.store import RunStore


class ProjectKnowledgeTests(unittest.TestCase):
    def test_project_decisions_link_adr_to_epic_tasks_context_and_economics(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / "service"
            decisions = project / "_ADR"
            decisions.mkdir(parents=True)
            (decisions / "README.md").write_text("# ADR catalog\n", encoding="utf-8")
            adr = decisions / "0001-passkeys.md"
            adr.write_text(
                "---\nstatus: Accepted\ndate: 2026-08-16\n---\n"
                "# ADR-0001: Use passkeys\n\nAdopt WebAuthn while preserving password login.\n",
                encoding="utf-8",
            )
            store = RunStore(root / "state")
            registered = store.projects.upsert(project)

            discovered = store.knowledge.overview(registered["id"])["decisions"]
            self.assertEqual(len(discovered), 1)
            self.assertEqual(discovered[0]["path"], "_ADR/0001-passkeys.md")
            self.assertEqual(discovered[0]["title"], "Use passkeys")
            self.assertEqual(discovered[0]["status"], "accepted")
            self.assertEqual(discovered[0]["implementation"]["state"], "unplanned")

            sources = store.knowledge.decision_sources(registered["id"], [discovered[0]["path"]])
            epic = store.epics.create(
                {
                    "title": "Implement passkeys",
                    "project_path": str(project),
                    "status": "proposed",
                    "source_documents": sources,
                }
            )
            mapping = store.epics.create_task_batch(
                epic["id"],
                [{"task_key": "passkeys", "title": "Passkeys", "task": "Implement passkeys"}],
            )
            run_id = mapping["passkeys"]
            run = store.get(run_id)
            self.assertEqual(run["source_documents"][0]["sha256"], discovered[0]["sha256"])
            self.assertIn("architecture_decision", {item["kind"] for item in run["context_bundle"]})
            store.update(
                run_id,
                status="accepted",
                metrics={
                    **run["metrics"],
                    "input_tokens": 1200,
                    "output_tokens": 300,
                    "cost_usd": 1.25,
                    "cost_observed": True,
                },
            )
            store.epics.update(epic["id"], status="completed")

            linked = store.knowledge.overview(registered["id"])["decisions"][0]
            self.assertEqual(linked["implementation"]["state"], "completed")
            self.assertEqual(linked["implementation"]["completed_tasks"], 1)
            self.assertEqual(linked["implementation"]["tokens"], 1500)
            self.assertEqual(linked["implementation"]["cost_usd"], 1.25)
            self.assertEqual(linked["epic_ids"], [epic["id"]])
            summary = store.knowledge.overview(registered["id"])["decision_summary"]
            self.assertEqual(summary["tasks"], 1)
            self.assertEqual(summary["tokens"], 1500)
            self.assertEqual(summary["cost_usd"], 1.25)

    def test_decision_source_rejects_paths_outside_supported_catalogs(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / "service"
            project.mkdir()
            (project / "random.md").write_text("# Not an ADR\n", encoding="utf-8")
            store = RunStore(root / "state")
            registered = store.projects.upsert(project)
            with self.assertRaisesRegex(ValueError, "supported ADR directory"):
                store.knowledge.decision_sources(registered["id"], ["random.md"])

    def test_planning_source_catalog_classifies_documents_and_marks_completed_sources(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / "service"
            (project / "_ADR").mkdir(parents=True)
            (project / "docs" / "specs").mkdir(parents=True)
            (project / "node_modules" / "ignored").mkdir(parents=True)
            adr = project / "_ADR" / "0002-events.md"
            adr.write_text("# ADR-0002: Durable events\n\nStatus: Accepted\n\nAppend events before projection.\n", encoding="utf-8")
            spec = project / "docs" / "specs" / "billing-prd.md"
            spec.write_text("# Billing requirements\n\nInvoices remain idempotent.\n", encoding="utf-8")
            (project / "node_modules" / "ignored" / "fake-spec.md").write_text("# Ignore me\n", encoding="utf-8")
            store = RunStore(root / "state")
            registered = store.projects.upsert(project)
            sources = store.knowledge.planning_sources(registered["id"])

            by_path = {item["path"]: item for item in sources}
            self.assertEqual(by_path["_ADR/0002-events.md"]["kind"], "adr")
            self.assertEqual(by_path["docs/specs/billing-prd.md"]["kind"], "specification")
            self.assertNotIn("node_modules/ignored/fake-spec.md", by_path)
            self.assertIn("Invoices remain idempotent", by_path["docs/specs/billing-prd.md"]["preview"])

            frozen = store.knowledge.decision_sources(registered["id"], ["_ADR/0002-events.md"])
            epic = store.epics.create({"title": "Durable events", "project_path": str(project), "status": "completed", "source_documents": frozen})
            completed = {item["path"]: item for item in store.knowledge.planning_sources(registered["id"])}
            self.assertEqual(completed["_ADR/0002-events.md"]["implementation"]["state"], "completed")
            self.assertEqual(completed["_ADR/0002-events.md"]["epic_ids"], [epic["id"]])

            selected = store.knowledge.planning_source_documents(registered["id"], ["docs/specs/billing-prd.md"])
            self.assertEqual(selected[0]["kind"], "specification")
            self.assertIn("Invoices remain idempotent", selected[0]["content"])

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

    def test_project_memory_is_triggered_and_repeated_feedback_is_suggested(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / "service"
            project.mkdir()
            store = RunStore(root / "state")
            registered = store.projects.upsert(project)
            catalog = store.knowledge.update_item(
                registered["id"],
                {
                    "title": "Billing migration rule",
                    "content": "Run the billing compatibility fixture before changing invoice data.",
                    "triggers": ["billing", "invoice"],
                    "folders": ["migrations/"],
                    "enabled": True,
                },
            )
            item_id = catalog["items"][0]["id"]

            selected = store.create({"task": "Change the billing invoice schema", "project_path": str(project)})
            self.assertEqual(selected["knowledge_selected"][0]["id"], item_id)
            self.assertIn("project_memory", {source["kind"] for source in selected["context_receipt"]["sources"]})
            self.assertIn("knowledge.selected", {event["type"] for event in store.events(selected["id"])})

            for suffix in ("one", "two"):
                run = store.create({"task": f"Small correction {suffix}", "project_path": str(project)})
                store.append_event(
                    run["id"],
                    "review.sent_back",
                    "operator",
                    {"message": "Always run the billing compatibility fixture before review."},
                )
            suggestions = store.knowledge.items(registered["id"])["suggestions"]
            self.assertEqual(suggestions[0]["evidence_count"], 2)
            self.assertEqual(suggestions[0]["source"], "history")


if __name__ == "__main__":
    unittest.main()
