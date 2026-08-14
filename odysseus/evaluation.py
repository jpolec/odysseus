"""Independent evaluation aggregation and the first policy decision layer."""

from __future__ import annotations

import json
from typing import Any, Mapping, Sequence


REVIEW_MARKER = "ODYSSEUS_EVALUATION:"


def _bounded_score(value: Any, default: float = 0.0) -> float:
    try:
        return round(min(1.0, max(0.0, float(value))), 4)
    except (TypeError, ValueError):
        return default


def parse_review_evaluation(summary: str) -> dict[str, Any]:
    """Parse a structured reviewer verdict, retaining a conservative fallback."""

    marker_value = ""
    for line in reversed(summary.splitlines()):
        if REVIEW_MARKER in line:
            marker_value = line.split(REVIEW_MARKER, 1)[1].strip()
            break
    if marker_value:
        try:
            parsed = json.loads(marker_value)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict):
            verdict = str(parsed.get("verdict") or "needs_review")
            findings = parsed.get("findings") if isinstance(parsed.get("findings"), list) else []
            return {
                "id": "independent_review",
                "kind": "agent",
                "score": _bounded_score(parsed.get("score"), 0.5),
                "verdict": verdict,
                "findings": [str(item)[:2_000] for item in findings[:50]],
                "structured": True,
            }

    lowered = summary.lower()
    if any(term in lowered for term in ("critical", "privilege escalation", "data loss")):
        score, verdict = 0.15, "fail"
    elif any(term in lowered for term in ("high severity", "material concern", "must fix")):
        score, verdict = 0.4, "fail"
    elif any(term in lowered for term in ("no material concerns", "approve", "looks good")):
        score, verdict = 0.9, "pass"
    else:
        score, verdict = 0.6, "needs_review"
    return {
        "id": "independent_review",
        "kind": "agent",
        "score": score,
        "verdict": verdict,
        "findings": [],
        "structured": False,
    }


class EvaluationEngine:
    """Combine deterministic and independent signals into an explainable score."""

    DEFAULT_WEIGHTS = {
        "tests": 0.45,
        "independent_review": 0.4,
        "review_independence": 0.15,
    }

    @classmethod
    def evaluate(
        cls,
        run: Mapping[str, Any],
        checks: Sequence[Mapping[str, Any]],
        review_summary: str,
        *,
        verifier_results: Sequence[Mapping[str, Any]] = (),
        policy: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        configured = dict(policy or {})
        weights = dict(cls.DEFAULT_WEIGHTS)
        raw_weights = configured.get("weights")
        if isinstance(raw_weights, dict):
            for key, value in raw_weights.items():
                score = _bounded_score(value, -1)
                if score >= 0:
                    weights[str(key)] = score

        check_values = list(checks)
        passed = sum(1 for item in check_values if int(item.get("returncode", 1)) == 0)
        tests_score = passed / len(check_values) if check_values else 0.5
        review = parse_review_evaluation(review_summary)
        independent = str(run.get("lane") or "") != str(run.get("review_lane") or "")
        components: list[dict[str, Any]] = [
            {
                "id": "tests",
                "kind": "deterministic",
                "score": round(tests_score, 4),
                "weight": weights["tests"],
                "verdict": "pass" if tests_score == 1 else "fail",
                "detail": f"{passed}/{len(check_values)} checks passed",
            },
            {
                **review,
                "weight": weights["independent_review"],
            },
            {
                "id": "review_independence",
                "kind": "policy",
                "score": 1.0 if independent else 0.5,
                "weight": weights["review_independence"],
                "verdict": "pass" if independent else "warn",
                "detail": "different implementation and review lanes" if independent else "same lane used for implementation and review",
            },
        ]
        for result in verifier_results:
            verifier_id = str(result.get("id") or "verifier")
            weight = _bounded_score(result.get("weight"), 0.2)
            score = _bounded_score(
                result.get("score"),
                1.0 if int(result.get("returncode", 1)) == 0 else 0.0,
            )
            components.append(
                {
                    "id": verifier_id,
                    "kind": str(result.get("kind") or "verifier"),
                    "score": score,
                    "weight": weight,
                    "verdict": "pass" if score >= 0.8 else "fail",
                    "detail": str(result.get("output") or "")[-4_000:],
                }
            )

        denominator = sum(float(item.get("weight", 0)) for item in components)
        confidence = (
            sum(float(item["score"]) * float(item.get("weight", 0)) for item in components)
            / denominator
            if denominator
            else 0.0
        )
        confidence = round(confidence, 4)
        threshold = _bounded_score(configured.get("min_confidence"), 0.85)
        required = configured.get("required_evaluators") or []
        if not isinstance(required, list):
            required = []
        component_ids = {str(item["id"]) for item in components}
        missing = [str(item) for item in required if str(item) not in component_ids]
        failing = [
            str(item["id"])
            for item in components
            if item.get("verdict") == "fail" and float(item.get("weight", 0)) > 0
        ]
        eligible = confidence >= threshold and not missing and not failing
        human_review_required = bool(configured.get("require_human_review", True)) or not eligible
        return {
            "version": 1,
            "confidence": confidence,
            "threshold": threshold,
            "components": components,
            "missing_evaluators": missing,
            "failing_evaluators": failing,
            "eligible": eligible,
            "human_review_required": human_review_required,
            "decision": "human_review" if human_review_required else "auto_accept_eligible",
        }

