from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from odysseus.search import search, statistics
from odysseus.store import RunStore


class SearchTests(unittest.TestCase):
    def test_search_reads_runs_and_events_and_stats_count_outcomes(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / "project"
            project.mkdir()
            store = RunStore(root / "state")
            run = store.create({"task": "Implement lunar cache", "project_path": str(project)})
            store.append_event(run["id"], "agent.message", "codex", {"text": "Detected orbit regression"})
            store.update(run["id"], status="accepted", metrics={**run["metrics"], "input_tokens": 100, "output_tokens": 20, "cost_usd": 1.5})

            run_results = search(store, "lunar")
            event_results = search(store, "orbit regression")
            totals = statistics(store)

            self.assertEqual(run_results[0]["kind"], "run")
            self.assertEqual(event_results[0]["kind"], "event")
            self.assertEqual(totals["successful_changes"], 1)
            self.assertEqual(totals["cost_per_successful_change"], 1.5)


if __name__ == "__main__":
    unittest.main()
