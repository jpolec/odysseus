from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from odysseus.scheduler import Scheduler
from odysseus.store import RunStore


class SkillRegistryTests(unittest.TestCase):
    def test_catalog_combines_generic_and_project_local_skills(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / "service"
            local = project / ".agents" / "skills" / "domain-boundaries"
            local.mkdir(parents=True)
            (local / "SKILL.md").write_text(
                "---\n"
                "name: domain-boundaries\n"
                "description: Preserve this project's domain boundaries.\n"
                "triggers: domain, boundary, aggregate\n"
                "---\n\n# Domain boundaries\n\nKeep aggregates independent.\n",
                encoding="utf-8",
            )
            store = RunStore(root / "state")
            registered = store.projects.upsert(project)

            catalog = store.skills.catalog(registered["id"])
            by_name = {skill["name"]: skill for skill in catalog["skills"]}

            self.assertEqual(by_name["domain-boundaries"]["scope"], "project")
            self.assertEqual(by_name["security-review"]["scope"], "bundled")
            self.assertNotIn("content", by_name["security-review"])

    def test_policy_selection_is_persisted_and_injected_into_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / "service"
            project.mkdir()
            store = RunStore(root / "state")
            registered = store.projects.upsert(project)
            store.skills.update_policy(registered["id"], {"policies": {"test-strategy": "required"}})

            run = store.create({"task": "Audit authentication security", "project_path": str(project)})
            names = {skill["name"] for skill in run["skills_selected"]}

            self.assertIn("security-review", names)
            self.assertIn("test-strategy", names)
            self.assertIn("skill.selected", {event["type"] for event in store.events(run["id"])})
            prompt = Scheduler._implementation_prompt(run, 1, 0, "")
            self.assertIn("SKILL security-review", prompt)
            self.assertIn("SKILL test-strategy", prompt)

    def test_manual_selection_respects_disabled_policy(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / "service"
            project.mkdir()
            store = RunStore(root / "state")
            registered = store.projects.upsert(project)
            store.skills.update_policy(registered["id"], {"policies": {"database-change": "disabled"}})

            with self.assertRaisesRegex(ValueError, "disabled"):
                store.create(
                    {
                        "task": "Change a column",
                        "project_path": str(project),
                        "skill_mode": "manual",
                        "skills": ["database-change"],
                    }
                )

    def test_create_local_skill_writes_only_a_project_skill(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / "service"
            project.mkdir()
            store = RunStore(root / "state")
            registered = store.projects.upsert(project)

            catalog = store.skills.create_local(
                registered["id"],
                {
                    "name": "domain-boundaries",
                    "description": "Preserve this project's domain boundaries.",
                    "triggers": ["domain", "aggregate"],
                    "content": "# Domain boundaries\n\nKeep aggregates independent.",
                },
            )

            skill_path = project / ".agents" / "skills" / "domain-boundaries" / "SKILL.md"
            by_name = {skill["name"]: skill for skill in catalog["skills"]}
            self.assertTrue(skill_path.exists())
            self.assertEqual(by_name["domain-boundaries"]["scope"], "project")
            self.assertEqual(by_name["domain-boundaries"]["mode"], "auto")
            self.assertIn("triggers: domain, aggregate", skill_path.read_text(encoding="utf-8"))

            with self.assertRaises(ValueError):
                store.skills.create_local(
                    registered["id"],
                    {"name": "../escape", "description": "No", "content": "No"},
                )

    def test_catalog_reports_project_specific_outcome_economics(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / "service"
            project.mkdir()
            store = RunStore(root / "state")
            run = store.create({"task": "Review authentication security", "project_path": str(project)})
            store.append_event(run["id"], "agent.question", "codex", {"message": "Choose session lifetime"})
            store.update(
                run["id"],
                status="accepted",
                metrics={"input_tokens": 800, "output_tokens": 200, "cost_usd": 0.25, "cost_observed": True},
            )

            catalog = store.skills.catalog(run["project_id"])
            security = next(skill for skill in catalog["skills"] if skill["name"] == "security-review")

            self.assertEqual(security["effectiveness"]["runs"], 1)
            self.assertEqual(security["effectiveness"]["success_rate"], 1.0)
            self.assertEqual(security["effectiveness"]["avg_tokens"], 1000)
            self.assertEqual(security["effectiveness"]["avg_cost_usd"], 0.25)
            self.assertEqual(security["effectiveness"]["cost_coverage"], 1)
            self.assertEqual(security["effectiveness"]["interventions"], 1)

    def test_router_explains_task_signals_and_project_history(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / "service"
            project.mkdir()
            store = RunStore(root / "state")
            for suffix in ("one", "two"):
                run = store.create({"task": f"Authentication security audit {suffix}", "project_path": str(project)})
                store.update(run["id"], status="accepted")

            recommendation = store.skills.recommend(run["project_id"], "Fix authentication security")
            security = next(item for item in recommendation["recommendations"] if item["name"] == "security-review")

            self.assertEqual(recommendation["algorithm"], "project-skill-router-v1")
            self.assertTrue(security["selected"])
            self.assertIn("authentication", security["signals"])
            self.assertTrue(any("2/2 observed successes" in reason and "low sample" in reason for reason in security["reasons"]))


if __name__ == "__main__":
    unittest.main()
