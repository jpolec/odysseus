from __future__ import annotations

import unittest

from odysseus.events import EVENT_SCHEMA_VERSION, Event


class EventTests(unittest.TestCase):
    def test_normalized_event_shape(self) -> None:
        event = Event(
            run_id="run-1",
            type="agent.output",
            source="codex",
            data={"text": "hello", "vendor_type": "item.completed"},
            seq=3,
        ).to_dict()

        self.assertEqual(event["v"], EVENT_SCHEMA_VERSION)
        self.assertEqual(event["seq"], 3)
        self.assertEqual(event["type"], "agent.output")
        self.assertEqual(event["source"], "codex")

    def test_unknown_event_type_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            Event(run_id="run-1", type="vendor.surprise", source="codex")

    def test_inconclusive_evaluation_is_a_first_class_event(self) -> None:
        event = Event(run_id="run-1", type="evaluation.inconclusive", source="odysseus").to_dict()
        self.assertEqual(event["type"], "evaluation.inconclusive")


if __name__ == "__main__":
    unittest.main()
