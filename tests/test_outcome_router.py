from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from odysseus.store import RunStore


def _stamp(index: int) -> str:
    return f"2026-01-01T00:{index:02d}:00Z"


class OutcomeRouterTests(unittest.TestCase):
    def _run(
        self,
        store: RunStore,
        project: Path,
        *,
        lane: str,
        index: int,
        status: str = "accepted",
        cost: float | None = None,
        intervention: bool = False,
        correction: bool = False,
        ci_repair: bool = False,
        model: str = "",
    ) -> dict[str, object]:
        run = store.create(
            {
                "task": "Outcome router fixture",
                "project_path": str(project),
                "lane": lane,
                "evidence_class": "observed",
                "skills": ["test-strategy"],
                "skill_mode": "manual",
            }
        )
        if intervention:
            store.append_event(run["id"], "agent.question", lane, {"message": "Need input"})
        if correction:
            store.append_event(run["id"], "review.sent_back", "user", {"feedback": "Fix it"})
        if ci_repair:
            store.append_event(run["id"], "ci.retry_pushed", lane, {"attempt": 1})
        if model:
            store.append_event(run["id"], "agent.usage", lane, {"model": model, "input_tokens": 1, "output_tokens": 1})
        metrics = {"input_tokens": 100, "output_tokens": 50, "cost_usd": 0.0, "cost_observed": False}
        if cost is not None:
            metrics.update({"cost_usd": cost, "cost_observed": True})
        return store.update(
            run["id"],
            status=status,
            created_at=_stamp(index),
            started_at=_stamp(index),
            finished_at=f"2026-01-01T00:{index:02d}:10Z",
            metrics=metrics,
        )

    def test_sparse_history_retains_operator_default(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / "repo"
            project.mkdir()
            store = RunStore(root / "state")
            registered = store.projects.upsert(project)
            store.update_config({"outcome_router": {"min_samples": 3}})
            self._run(store, project, lane="claude", index=1)
            self._run(store, project, lane="claude", index=2)

            recommendation = store.outcome_router.recommend(
                registered["id"],
                operator_default="codex",
                request={"skills_selected": [{"name": "test-strategy"}]},
            )

            self.assertEqual(recommendation["recommended_lane"], "codex")
            self.assertEqual(recommendation["reason"], "insufficient_samples")
            claude = next(item for item in recommendation["evidence"] if item["agent"] == "claude")
            self.assertEqual(claude["samples"], 2)
            self.assertIsNone(claude["score"])

    def test_recommendation_explains_evidence_and_counterfactual_without_applying_lane(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / "repo"
            project.mkdir()
            store = RunStore(root / "state")
            registered = store.projects.upsert(project)
            store.update_config({"outcome_router": {"min_samples": 3}})
            for index in range(1, 5):
                self._run(store, project, lane="claude", index=index, cost=0.10)
            for index in range(5, 8):
                self._run(
                    store,
                    project,
                    lane="codex",
                    index=index,
                    status="failed",
                    cost=0.03,
                    intervention=True,
                    correction=True,
                    ci_repair=True,
                )

            first = store.outcome_router.recommend(
                registered["id"],
                operator_default="codex",
                request={"skills_selected": [{"name": "test-strategy"}]},
            )
            second = store.outcome_router.recommend(
                registered["id"],
                operator_default="codex",
                request={"skills_selected": [{"name": "test-strategy"}]},
            )

            self.assertEqual(first["recommended_lane"], "claude")
            self.assertEqual(first["applied_lane"], "codex")
            self.assertFalse(first["autonomous_routing"])
            self.assertFalse(first["prompt_features_enabled"])
            self.assertEqual(first["features"]["task_class"], "implementer-api")
            self.assertEqual(first["counterfactual"]["success_rate_delta"], 1.0)
            self.assertGreater(first["counterfactual"]["avg_cost_usd_delta"], 0)
            self.assertLess(first["counterfactual"]["human_interventions_delta"], 0)
            claude = next(item for item in first["evidence"] if item["agent"] == "claude")
            self.assertEqual(claude["models"][0]["model"], "local-cli")
            self.assertIn("deterministic", first["governance"])
            comparable_keys = ("operator_default", "recommended_lane", "applied_lane", "features", "counterfactual")
            self.assertEqual({key: first[key] for key in comparable_keys}, {key: second[key] for key in comparable_keys})

    def test_shadow_recommendation_is_stored_but_lane_remains_default(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / "repo"
            project.mkdir()
            store = RunStore(root / "state")
            store.update_config({"default_lane": "codex", "outcome_router": {"min_samples": 1}})
            self._run(store, project, lane="claude", index=1)

            run = store.create(
                {
                    "task": "Outcome router fixture",
                    "project_path": str(project),
                    "skill_mode": "manual",
                    "skills": ["test-strategy"],
                }
            )

            self.assertEqual(run["lane"], "codex")
            self.assertEqual(run["outcome_routing"]["recommended_lane"], "claude")
            self.assertEqual(run["outcome_routing"]["applied_lane"], "codex")

    def test_auto_route_applies_eligible_recommendation_and_records_reason(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / "repo"
            project.mkdir()
            store = RunStore(root / "state")
            store.update_config({"default_lane": "codex", "outcome_router": {"min_samples": 1}})
            self._run(store, project, lane="claude", index=1)

            run = store.create(
                {
                    "task": "Outcome router fixture",
                    "project_path": str(project),
                    "lane": "codex",
                    "auto_route": True,
                    "skill_mode": "manual",
                    "skills": ["test-strategy"],
                }
            )

            self.assertEqual(run["lane"], "claude")
            self.assertEqual(run["review_lane"], "claude")
            self.assertEqual(run["outcome_routing"]["mode"], "automatic")
            self.assertEqual(run["outcome_routing"]["applied_lane"], "claude")
            self.assertTrue(run["outcome_routing"]["autonomous_routing"])
            self.assertIn("historical evidence", run["outcome_routing"]["reason"])

    def test_auto_route_transparently_falls_back_when_history_is_sparse(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / "repo"
            project.mkdir()
            store = RunStore(root / "state")
            store.update_config({"default_lane": "codex", "outcome_router": {"min_samples": 3}})

            run = store.create(
                {
                    "task": "Sparse routing fixture",
                    "project_path": str(project),
                    "lane": "codex",
                    "auto_route": True,
                }
            )

            self.assertEqual(run["lane"], "codex")
            self.assertEqual(run["outcome_routing"]["mode"], "automatic_fallback")
            self.assertFalse(run["outcome_routing"]["autonomous_routing"])
            self.assertEqual(run["outcome_routing"]["recommendation_reason"], "insufficient_samples")

    def test_backtest_uses_only_prior_runs(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / "repo"
            project.mkdir()
            store = RunStore(root / "state")
            registered = store.projects.upsert(project)
            store.update_config({"outcome_router": {"min_samples": 2}})
            self._run(store, project, lane="claude", index=1)
            self._run(store, project, lane="claude", index=2)
            self._run(store, project, lane="codex", index=3, status="failed")

            backtest = store.outcome_router.backtest(registered["id"])

            self.assertEqual(backtest["evaluated_runs"], 3)
            self.assertEqual(backtest["decisions"][0]["eligible"], False)
            self.assertTrue(backtest["decisions"][2]["eligible"])
            self.assertIn("before", backtest["leakage_prevention"])

    def test_drift_detection_compares_baseline_to_recent_window(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / "repo"
            project.mkdir()
            store = RunStore(root / "state")
            registered = store.projects.upsert(project)
            store.update_config(
                {"outcome_router": {"min_samples": 2, "drift_min_samples": 2, "drift_window": 2, "drift_success_drop": 0.5}}
            )
            for index in range(1, 5):
                self._run(store, project, lane="codex", index=index)
            for index in range(5, 7):
                self._run(store, project, lane="codex", index=index, status="failed")

            drift = store.outcome_router.detect_drift(registered["id"], agent="codex")

            self.assertEqual(drift[0]["agent"], "codex")
            self.assertEqual(drift[0]["baseline_success_rate"], 1.0)
            self.assertEqual(drift[0]["recent_success_rate"], 0.0)

    def test_export_and_delete_remove_router_records_for_project(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / "repo"
            project.mkdir()
            store = RunStore(root / "state")
            registered = store.projects.upsert(project)
            self._run(store, project, lane="claude", index=1)

            self.assertEqual(len(store.outcome_router.export(registered["id"])["records"]), 1)
            deletion = store.outcome_router.delete(registered["id"])

            self.assertEqual(deletion["project_id"], registered["id"])
            self.assertEqual(len(store.outcome_router.export(registered["id"])["records"]), 0)

    def test_prompt_features_and_string_booleans_do_not_bypass_privacy_default(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / "repo"
            project.mkdir()
            store = RunStore(root / "state")
            registered = store.projects.upsert(project)
            store.update_config({"outcome_router": {"allow_prompt_features": "false", "disabled": "false", "min_samples": 1}})

            recommendation = store.outcome_router.recommend(
                registered["id"],
                task="secret prompt feature",
                operator_default="codex",
                request={"task_class": "injected", "surface": "private", "model": "forced-model", "skills_selected": [{"name": "security"}]},
            )

            self.assertFalse(recommendation["prompt_features_enabled"])
            self.assertEqual(recommendation["features"]["task_class"], "implementer-api")
            self.assertEqual(recommendation["features"]["surface"], "unknown")
            self.assertEqual(recommendation["features"]["model"], "")
            self.assertNotEqual(recommendation["reason"], "disabled")

    def test_model_specific_request_uses_its_own_sample_floor(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / "repo"
            project.mkdir()
            store = RunStore(root / "state")
            registered = store.projects.upsert(project)
            store.update_config({"outcome_router": {"min_samples": 3, "allow_prompt_features": True}})
            self._run(store, project, lane="codex", index=1, model="model-a")
            self._run(store, project, lane="codex", index=2, model="model-a")
            for index in range(3, 7):
                self._run(store, project, lane="codex", index=index, model="model-b")

            recommendation = store.outcome_router.recommend(
                registered["id"],
                operator_default="claude",
                request={"task_class": "test-strategy", "surface": "unknown", "model": "model-a"},
            )

            codex = next(item for item in recommendation["evidence"] if item["agent"] == "codex")
            self.assertEqual(codex["samples"], 2)
            self.assertIsNone(codex["score"])
            self.assertEqual(recommendation["reason"], "insufficient_samples")


if __name__ == "__main__":
    unittest.main()
