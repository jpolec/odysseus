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


if __name__ == "__main__":
    unittest.main()
