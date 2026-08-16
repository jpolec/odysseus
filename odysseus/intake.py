"""Normalized external-signal intake into approval-gated Odysseus Epics."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Mapping

from .events import now_iso


INTAKE_SCHEMA_VERSION = 1

SUPPORTED_CONNECTORS: dict[str, dict[str, Any]] = {
    "github_issue": {
        "status": "reference_adapter",
        "source": "github",
        "signals": ["issue"],
        "read_capabilities": ["issues:read", "metadata:read"],
        "write_capabilities": [],
        "credential_storage": "external:gh",
        "unsupported": ["webhooks", "comments:write", "labels:write", "merge", "automerge"],
    },
    "jira_issue": {"status": "boundary_only", "source": "jira", "signals": ["issue"]},
    "linear_issue": {"status": "boundary_only", "source": "linear", "signals": ["issue"]},
    "sentry_issue": {"status": "boundary_only", "source": "sentry", "signals": ["error", "incident"]},
    "datadog_signal": {"status": "boundary_only", "source": "datadog", "signals": ["monitor", "incident"]},
    "slack_message": {"status": "boundary_only", "source": "slack", "signals": ["message"]},
}

SECRET_PATTERN = re.compile(
    r"(?i)(bearer\s+)[A-Za-z0-9._~+/-]+=*|\b(?:sk|ghp|github_pat|xox[baprs]|dd[a-z]?)[-_A-Za-z0-9]{12,}\b"
)
EMAIL_PATTERN = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")


def redacted_text(value: Any, *, limit: int = 8000) -> str:
    text = str(value or "")
    text = SECRET_PATTERN.sub(lambda match: (match.group(1) if match.group(1) else "") + "[REDACTED]", text)
    text = EMAIL_PATTERN.sub("[REDACTED_EMAIL]", text)
    return text[:limit]


def severity_from_labels(labels: list[Mapping[str, Any]]) -> str:
    names = {str(label.get("name") or "").strip().lower() for label in labels}
    if names & {"sev0", "sev-0", "severity:critical", "critical", "p0", "priority:critical"}:
        return "critical"
    if names & {"sev1", "sev-1", "severity:high", "high", "p1", "priority:high"}:
        return "high"
    if names & {"sev2", "sev-2", "severity:medium", "medium", "p2", "priority:medium"}:
        return "medium"
    if names & {"sev3", "sev-3", "severity:low", "low", "p3", "priority:low"}:
        return "low"
    return "unknown"


def github_issue_signal(issue: Mapping[str, Any], project: Mapping[str, Any]) -> dict[str, Any]:
    number = str(issue.get("number") or "").strip()
    url = str(issue.get("url") or "").strip()
    title = redacted_text(issue.get("title"), limit=300).strip() or f"GitHub issue {number or url}"
    labels = [item for item in issue.get("labels") or [] if isinstance(item, dict)]
    source_id = f"{project.get('github_url') or project.get('path')}#issue-{number or url}"
    identity = {
        "provider": "github",
        "connector": "github_issue",
        "repository": str(project.get("github_url") or project.get("path") or ""),
        "external_id": number,
        "url": url,
        "state": str(issue.get("state") or "open"),
        "updated_at": str(issue.get("updatedAt") or ""),
        "source_id": source_id,
    }
    evidence = {
        "title": title,
        "body_excerpt": redacted_text(issue.get("body"), limit=5000),
        "labels": [redacted_text(label.get("name"), limit=100) for label in labels],
        "assignees": [
            redacted_text(item.get("login") or item.get("name"), limit=100)
            for item in issue.get("assignees") or []
            if isinstance(item, dict)
        ],
    }
    dedupe_basis = json.dumps(
        {
            "provider": identity["provider"],
            "repository": identity["repository"],
            "external_id": identity["external_id"],
            "url": identity["url"],
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return {
        "schema_version": INTAKE_SCHEMA_VERSION,
        "kind": "external_signal",
        "received_at": now_iso(),
        "identity": identity,
        "permissions": {
            "read": ["issues:read", "metadata:read"],
            "write": [],
            "auth_ref": "gh-cli-user",
            "credential_storage": "external:gh",
            "secrets_persisted": False,
        },
        "dedupe_key": hashlib.sha256(dedupe_basis.encode("utf-8")).hexdigest(),
        "severity": severity_from_labels(labels),
        "links": [url] if url else [],
        "evidence": evidence,
        "redaction": {
            "applied": True,
            "rules": ["secret-token-patterns", "email-addresses", "length-limits"],
        },
        "connector_boundary": SUPPORTED_CONNECTORS["github_issue"],
    }


def plan_for_signal(signal: Mapping[str, Any], *, lane: str = "", review_lane: str = "", checks: list[str] | None = None) -> dict[str, Any]:
    identity = signal.get("identity") if isinstance(signal.get("identity"), dict) else {}
    evidence = signal.get("evidence") if isinstance(signal.get("evidence"), dict) else {}
    title = str(evidence.get("title") or "External signal").strip()
    url = str(identity.get("url") or "")
    severity = str(signal.get("severity") or "unknown")
    source = f"{identity.get('provider', 'external')} {identity.get('external_id') or url}".strip()
    body = str(evidence.get("body_excerpt") or "")
    link_line = f"\nSource link: {url}" if url else ""
    task_context = (
        f"Intake source: {source}\nSeverity: {severity}{link_line}\n\n"
        f"Redacted evidence:\n{body or '(no body provided)'}"
    )
    default_checks = list(checks or [])
    return {
        "summary": f"Approval-gated intake plan for {title}",
        "tasks": [
            {
                "task_key": "diagnosis",
                "title": f"Diagnose: {title}"[:100],
                "task": "Preserve the intake evidence, reproduce or narrow the incident, identify the likely root cause, and document the diagnostic conclusion before changing behavior.\n\n" + task_context,
                "role": "implementer",
                "depends_on": [],
                "parallelizable": False,
                "lane": lane,
                "review_lane": review_lane,
                "checks": [],
            },
            {
                "task_key": "repair",
                "title": f"Repair: {title}"[:100],
                "task": "Implement the narrowest fix supported by the diagnosis. Preserve public contracts unless the approved plan explicitly calls for a migration.\n\n" + task_context,
                "role": "implementer",
                "depends_on": ["diagnosis"],
                "parallelizable": False,
                "lane": lane,
                "review_lane": review_lane,
                "checks": default_checks,
            },
            {
                "task_key": "checks",
                "title": "Run regression and project checks",
                "task": "Add or run regression coverage for the incident boundary, run the configured checks, and fix only failures caused by this change.",
                "role": "implementer",
                "depends_on": ["repair"],
                "parallelizable": False,
                "lane": lane,
                "review_lane": review_lane,
                "checks": default_checks,
            },
            {
                "task_key": "review",
                "title": "Independent review",
                "task": "Review the diagnosis, patch, tests, redaction, and source links. Report findings without applying or merging changes.",
                "role": "reviewer",
                "depends_on": ["checks"],
                "parallelizable": False,
                "lane": review_lane or lane,
                "review_lane": review_lane or lane,
                "checks": [],
            },
            {
                "task_key": "draft-pr",
                "title": "Prepare reviewed draft PR",
                "task": "Prepare a draft pull request only after review is accepted. Do not auto-merge, mark ready, or claim unsupported connector write-back.",
                "role": "implementer",
                "depends_on": ["review"],
                "parallelizable": False,
                "lane": lane,
                "review_lane": review_lane,
                "checks": [],
            },
        ],
    }


class IntakeCoordinator:
    """Convert normalized signals into proposed Epics without starting agents."""

    def __init__(self, store: Any) -> None:
        self.store = store

    def connector_capabilities(self) -> dict[str, Any]:
        return {"schema_version": INTAKE_SCHEMA_VERSION, "connectors": SUPPORTED_CONNECTORS}

    def propose(
        self,
        signal: Mapping[str, Any],
        *,
        project_path: str,
        lane: str = "",
        review_lane: str = "",
        checks: list[str] | None = None,
        gate_policy: str = "human_review",
    ) -> dict[str, Any]:
        dedupe_key = str(signal.get("dedupe_key") or "")
        for epic in self.store.epics.list():
            intake = epic.get("intake") if isinstance(epic.get("intake"), dict) else {}
            if dedupe_key and intake.get("dedupe_key") == dedupe_key:
                # A repeated signal is not a no-op: keep one Epic identity, but
                # refresh its authoritative evidence and record that the source
                # was observed again. Proposed plans are regenerated; approved
                # work is never silently rewritten underneath running agents.
                previous_observations = intake.get("observations") if isinstance(intake.get("observations"), list) else []
                evidence = signal.get("evidence") if isinstance(signal.get("evidence"), dict) else {}
                identity = signal.get("identity") if isinstance(signal.get("identity"), dict) else {}
                evidence_digest = hashlib.sha256(
                    json.dumps(evidence, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
                ).hexdigest()
                observation = {
                    "received_at": str(signal.get("received_at") or now_iso()),
                    "source_updated_at": str(identity.get("updated_at") or ""),
                    "severity": str(signal.get("severity") or "unknown"),
                    "evidence_sha256": evidence_digest,
                }
                observations = [*previous_observations, observation][-20:]
                refreshed_intake = {
                    **dict(signal),
                    "gate_policy": str(intake.get("gate_policy") or gate_policy),
                    "starts_agents": False,
                    "materialization": "requires configured policy or explicit human approval",
                    "first_seen_at": str(intake.get("first_seen_at") or intake.get("received_at") or signal.get("received_at") or now_iso()),
                    "last_seen_at": observation["received_at"],
                    "seen_count": max(1, int(intake.get("seen_count") or 1)) + 1,
                    "observations": observations,
                }
                changes: dict[str, Any] = {"intake": refreshed_intake}
                if str(epic.get("status") or "") == "proposed" and not epic.get("approved"):
                    refreshed_plan = plan_for_signal(signal, lane=lane, review_lane=review_lane, checks=checks or [])
                    changes.update(
                        {
                            "title": str(evidence.get("title") or identity.get("source_id") or epic.get("title") or "External signal")[:100],
                            "description": refreshed_plan["summary"],
                            "plan": refreshed_plan,
                        }
                    )
                return {**self.store.epics.update(str(epic["id"]), **changes), "duplicate": True}

        plan = plan_for_signal(signal, lane=lane, review_lane=review_lane, checks=checks or [])
        evidence = signal.get("evidence") if isinstance(signal.get("evidence"), dict) else {}
        identity = signal.get("identity") if isinstance(signal.get("identity"), dict) else {}
        title = str(evidence.get("title") or identity.get("source_id") or "External signal")
        epic = self.store.epics.create(
            {
                "title": title[:100],
                "description": plan["summary"],
                "project_path": project_path,
                "status": "proposed",
                "plan": plan,
                "evidence_class": "observed",
                "gate_policy": gate_policy,
                "intake": {
                    **dict(signal),
                    "gate_policy": gate_policy,
                    "starts_agents": False,
                    "materialization": "requires configured policy or explicit human approval",
                    "first_seen_at": str(signal.get("received_at") or now_iso()),
                    "last_seen_at": str(signal.get("received_at") or now_iso()),
                    "seen_count": 1,
                    "observations": [
                        {
                            "received_at": str(signal.get("received_at") or now_iso()),
                            "source_updated_at": str(identity.get("updated_at") or ""),
                            "severity": str(signal.get("severity") or "unknown"),
                            "evidence_sha256": hashlib.sha256(
                                json.dumps(evidence, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
                            ).hexdigest(),
                        }
                    ],
                },
            }
        )
        return {**epic, "duplicate": False}
