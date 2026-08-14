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


if __name__ == "__main__":
    unittest.main()

