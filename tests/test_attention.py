from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from odysseus.attention import AttentionQueue
from odysseus.store import RunStore


class AttentionTests(unittest.TestCase):
    def test_queue_orders_priority_deduplicates_and_records_answer(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            store = RunStore(Path(temp) / "state")
            queue = AttentionQueue(store)
            low = queue.create({"type": "review", "priority": "low", "title": "Review"})
            high = queue.create(
                {
                    "type": "question",
                    "priority": "high",
                    "title": "Choose migration",
                    "options": ["make NOT NULL", {"id": "retain", "label": "Retain NULL"}],
                    "dedupe_key": "run-1:question:1",
                }
            )
            duplicate = queue.create(
                {
                    "type": "question",
                    "priority": "high",
                    "title": "Duplicate",
                    "dedupe_key": "run-1:question:1",
                }
            )

            self.assertEqual(duplicate["id"], high["id"])
            self.assertEqual([item["id"] for item in queue.list(status="open")], [high["id"], low["id"]])
            answered = queue.respond(high["id"], "retain")
            self.assertEqual(answered["status"], "answered")
            self.assertEqual(answered["response"], "retain")

    def test_resolve_for_run_only_closes_matching_open_items(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            store = RunStore(Path(temp) / "state")
            queue = AttentionQueue(store)
            first = queue.create({"type": "review", "run_id": "run-a"})
            second = queue.create({"type": "review", "run_id": "run-b"})

            changed = queue.resolve_for_run("run-a", resolution="accepted")

            self.assertEqual(changed, [first["id"]])
            self.assertEqual(queue.get(first["id"])["status"], "resolved")
            self.assertEqual(queue.get(second["id"])["status"], "open")

    def test_inconclusive_evaluation_creates_review_item_not_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / "repo"
            project.mkdir()
            store = RunStore(root / "state")
            run = store.create({"task": "Evaluate evidence", "project_path": str(project)})

            store.append_event(
                run["id"],
                "evaluation.inconclusive",
                "odysseus",
                {"message": "Evaluation is inconclusive and needs operator review."},
            )

            item = store.attention.list(status="open", run_id=run["id"])[0]
            self.assertEqual(item["type"], "evaluation_review")
            self.assertEqual(item["priority"], "medium")
            self.assertTrue(item["title"].startswith("Evaluation needs review:"))
            self.assertNotIn("failed", item["title"].lower())


if __name__ == "__main__":
    unittest.main()
