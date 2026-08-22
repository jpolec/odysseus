#!/usr/bin/env python3
"""Create a disposable, deterministic Odysseus 0.8 product-tour state."""

from __future__ import annotations

import argparse
import subprocess
import tempfile
import webbrowser
from pathlib import Path
import sys


REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPOSITORY_ROOT))

from odysseus.evaluation import EvaluationEngine  # noqa: E402
from odysseus.server import OdysseusApp  # noqa: E402
from odysseus.store import RunStore  # noqa: E402


def _init_sample_repository(path: Path) -> None:
    """Make each demo codebase behave like a real repository in the UI."""
    subprocess.run(
        ["git", "init", "-q", str(path)],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def seed(state_dir: Path, project: Path) -> RunStore:
    if state_dir.exists() and any(state_dir.iterdir()):
        raise ValueError(f"demo state directory is not empty: {state_dir}")
    store = RunStore(state_dir)
    store.update_config(
        {
            "ci": {"watch": False, "auto_resume": True, "max_attempts": 2, "poll_seconds": 30}
        }
    )

    # The demo is deliberately multi-repository so the first screen documents
    # the real repository -> task hierarchy instead of a flat task list.
    sample_root = state_dir / "sample-projects"
    atlas = sample_root / "atlas-payments"
    quasar = sample_root / "quasar-data"
    atlas.mkdir(parents=True)
    quasar.mkdir(parents=True)
    (atlas / "README.md").write_text("# Atlas Payments\n\nIdempotent payment and ledger services.\n", encoding="utf-8")
    (atlas / "AGENTS.md").write_text("Run webhook and ledger compatibility tests before review.\n", encoding="utf-8")
    (quasar / "README.md").write_text("# Quasar Data\n\nResearch pipelines with temporal safety gates.\n", encoding="utf-8")
    _init_sample_repository(atlas)
    _init_sample_repository(quasar)
    store.projects.upsert(atlas, {"name": "Atlas Payments", "tags": ["demo", "payments"]})
    store.projects.upsert(quasar, {"name": "Quasar Data", "tags": ["demo", "research"]})
    primary = store.projects.upsert(project, {"name": "Odysseus", "tags": ["demo", "orchestration"]})
    store.knowledge.update_profile(
        primary["id"],
        {
            "summary": "A local-first delivery system for coding agents and tmux sessions.",
            "notes": "The demo keeps terminal control explicit and never spends model tokens.",
        },
    )
    store.knowledge.update_item(
        primary["id"],
        {
            "title": "Checkout browser contract",
            "content": "Retry-flow changes must preserve the visible 429 banner and pass the Chromium checkout scenario.",
            "triggers": ["checkout", "retry", "429"],
            "folders": ["web/", "tests/checkout"],
            "enabled": True,
        },
    )

    atlas_run = store.create(
        {
            "title": "Make webhook delivery idempotent",
            "task": "Prevent duplicate payment webhooks from creating duplicate ledger entries.",
            "project_path": str(atlas),
            "lane": "codex",
            "checks": ["python3 -m unittest tests.test_webhooks"],
            "evidence_class": "demo",
            "origin": "demo",
        }
    )
    store.transition(
        atlas_run["id"],
        "accepted",
        event_type="run.accepted",
        started_at="2026-08-14T08:00:00Z",
        finished_at="2026-08-14T08:12:00Z",
        check_results=[{"command": "python3 -m unittest tests.test_webhooks", "returncode": 0, "output": "12 tests passed"}],
        confidence=0.97,
        policy_decision="accept",
        environment={
            "version": "environment-plan-v1", "profile": "host", "status": "active",
            "network": "bridge", "ports": {}, "isolation": "none; host user permissions apply",
        },
        metrics={
            "input_tokens": 18_206,
            "cached_input_tokens": 12_844,
            "output_tokens": 3_108,
            "reasoning_output_tokens": 604,
            "tool_calls": 24,
            "cost_usd": 1.126,
            "session_usage": {},
        },
    )

    quasar_run = store.create(
        {
            "title": "Guard the factor pipeline against look-ahead bias",
            "task": "Add a deterministic temporal-boundary check to the daily factor build.",
            "project_path": str(quasar),
            "lane": "claude",
            "checks": ["python3 -m unittest tests.test_temporal_boundaries"],
            "evidence_class": "demo",
            "origin": "demo",
        }
    )
    store.transition(
        quasar_run["id"],
        "review",
        event_type="run.review_ready",
        started_at="2026-08-14T08:20:00Z",
        check_results=[{"command": "python3 -m unittest tests.test_temporal_boundaries", "returncode": 0, "output": "9 tests passed"}],
        review_status="waiting",
        review_summary="Temporal checks pass. Confirm the accepted lag policy before approving.",
        confidence=0.91,
        policy_decision="human_review",
        environment={
            "version": "environment-plan-v1", "profile": "docker", "status": "active",
            "image": "ghcr.io/example/python-research-agent:2026-08", "network": "none",
            "cpus": 2, "memory": "4g", "ports": {}, "credential_env_names": [],
            "isolation": "container filesystem, resources, network mode, and scoped environment",
        },
        metrics={
            "input_tokens": 27_940,
            "cached_input_tokens": 19_102,
            "output_tokens": 4_016,
            "reasoning_output_tokens": 788,
            "tool_calls": 31,
            "cost_usd": 1.742,
            "session_usage": {},
        },
    )

    epic = store.epics.create(
        {
            "title": "Passkey authentication",
            "description": "Add passkey registration and login with independent security review.",
            "project_path": str(project),
            "status": "planning",
            "evidence_class": "demo",
            "source_documents": [{
                "kind": "specification", "path": "odysseus://demo/passkey-spec", "title": "Passkey authentication specification",
                "content": "Existing password login must remain unchanged.\n\nAdd WebAuthn registration and authentication endpoints.\n\nAdd browser registration and login flows.\n\nRequire independent security validation before delivery.",
            }],
        }
    )
    epic = store.epics.save_plan(
        epic["id"],
        {
            "summary": "Parallel backend and frontend work converge in independently validated integration.",
            "constraints": ["Password login remains compatible", "No implementation starts before approval"],
            "tasks": [
                    {
                        "task_key": "auth-api",
                        "title": "WebAuthn backend",
                        "task": "Implement WebAuthn challenge and verification endpoints.",
                        "role": "implementer",
                        "depends_on": [],
                        "parallelizable": True,
                        "lane": "codex",
                        "review_lane": "claude",
                        "project_path": str(project),
                        "outcome": "WebAuthn challenge and verification endpoints are production-ready.",
                        "source_refs": ["S1", "S2"],
                        "acceptance_criteria": ["Password login remains unchanged", "WebAuthn challenge and verification succeed"],
                        "required_evidence": ["API contract checks", "Authentication unit and integration tests"],
                        "execution_profile": {"mode": "auto", "harness": "auto", "skills": ["api-contracts", "security-review"], "environment": "isolated_worktree", "policy": "standard", "reason": "Backend authentication task; route from repository outcomes"},
                        "estimate": {"cost_usd_min": 2, "cost_usd_max": 4, "duration_minutes_min": 12, "duration_minutes_max": 24, "confidence": "low", "basis": "Small comparable backend cohort"},
                    },
                    {
                        "task_key": "passkey-ui",
                        "title": "Passkey registration UI",
                        "task": "Implement the browser registration and login flows.",
                        "role": "implementer",
                        "depends_on": [],
                        "parallelizable": True,
                        "lane": "claude",
                        "review_lane": "codex",
                        "project_path": str(project),
                        "outcome": "Users can register and use a passkey in supported browsers.",
                        "source_refs": ["S1", "S3"],
                        "acceptance_criteria": ["Registration and sign-in user flows complete", "Password sign-in remains available"],
                        "required_evidence": ["Browser E2E recording", "Accessibility checks"],
                        "execution_profile": {"mode": "auto", "harness": "auto", "skills": ["frontend-accessibility"], "environment": "isolated_worktree", "policy": "standard", "reason": "Browser flow; route from frontend delivery history"},
                        "estimate": {"cost_usd_min": 2, "cost_usd_max": 5, "duration_minutes_min": 15, "duration_minutes_max": 30, "confidence": "low", "basis": "Small comparable frontend cohort"},
                    },
                    {
                        "task_key": "integration",
                        "title": "Integration and security review",
                        "task": "Integrate both flows and complete the independent security review.",
                        "role": "reviewer",
                        "depends_on": ["auth-api", "passkey-ui"],
                        "parallelizable": False,
                        "lane": "claude",
                        "review_lane": "codex",
                        "project_path": str(project),
                        "outcome": "The immutable integrated candidate satisfies the passkey contract and security review.",
                        "source_refs": ["S1", "S2", "S3", "S4"],
                        "acceptance_criteria": ["Backend and browser flows interoperate", "Independent reviewer reports no blocking finding"],
                        "required_evidence": ["Integrated regression suite", "Independent security review"],
                        "execution_profile": {"mode": "override", "harness": "claude", "skills": ["security-review"], "environment": "isolated_worktree", "policy": "strict", "review_policy": "independent_provider", "reason": "Independent provider validates the combined artifact"},
                        "estimate": {"cost_usd_min": 1, "cost_usd_max": 3, "duration_minutes_min": 8, "duration_minutes_max": 18, "confidence": "low", "basis": "Small independent review cohort"},
                    },
                ],
        }
    )
    mapping = store.epics.create_task_batch(epic["id"], epic["plan"]["tasks"])

    backend_id = mapping["auth-api"]
    store.update(
        backend_id,
        status="review",
        started_at="2026-08-14T08:30:00Z",
        review_status="waiting",
        check_results=[
            {"command": "python3 -m unittest", "returncode": 0, "output": "42 tests passed"},
            {"command": "semgrep --config auto", "returncode": 0, "output": "No findings"},
        ],
        metrics={
            "input_tokens": 34_812,
            "cached_input_tokens": 21_406,
            "output_tokens": 6_904,
            "reasoning_output_tokens": 1_221,
            "tool_calls": 47,
            "cost_usd": 2.184,
            "session_usage": {},
        },
        review_summary="No critical findings. One cookie-hardening decision remains with the operator.",
        environment={
            "version": "environment-plan-v1", "profile": "docker", "status": "active",
            "image": "ghcr.io/example/codex-node:2026-08", "network": "bridge",
            "cpus": 2, "memory": "4g",
            "ports": {"APP_PORT": {"host": 43172, "container": 3000}},
            "credential_env_names": ["OPENAI_API_KEY"],
            "preview_url": "http://127.0.0.1:43172/",
            "isolation": "container filesystem, resources, network mode, and scoped environment",
        },
    )
    evaluation = EvaluationEngine.evaluate(
        store.get(backend_id),
        store.get(backend_id)["check_results"],
        'ODYSSEUS_EVALUATION: {"score":0.94,"verdict":"pass","findings":[]}',
        verifier_results=[{"id": "security", "kind": "static", "returncode": 0, "score": 0.96, "weight": 0.3}],
        policy={"min_confidence": 0.9, "require_human_review": True},
    )
    store.update(
        backend_id,
        evaluation=evaluation,
        confidence=evaluation["confidence"],
        policy_decision=evaluation["decision"],
    )
    store.append_event(backend_id, "agent.session", "codex", {"phase": "agent", "session_id": "demo-thread-auth"})
    store.append_event(backend_id, "agent.tool.started", "codex", {"tool": "shell", "command": "python3 -m unittest"})
    store.append_event(backend_id, "agent.tool.completed", "codex", {"tool": "shell", "exit_code": 0})
    store.append_event(backend_id, "evaluation.completed", "odysseus", {"confidence": evaluation["confidence"], "decision": evaluation["decision"]})
    store.append_event(backend_id, "run.review_ready", "odysseus", {"message": "Implementation and independent review are ready."})

    frontend_id = mapping["passkey-ui"]
    store.update(
        frontend_id,
        status="attention",
        started_at="2026-08-14T08:35:00Z",
        worker_pid=None,
        environment={
            "version": "environment-plan-v1", "profile": "devcontainer", "status": "active",
            "network": "bridge", "ports": {}, "isolation": "repository-defined devcontainer",
        },
    )
    store.append_event(
        frontend_id,
        "agent.question",
        "claude",
        {
            "title": "Choose fallback UX",
            "message": "When the platform authenticator is unavailable, should login offer a magic link or stop with an explanation?",
            "options": [
                {"id": "magic-link", "label": "Offer magic link"},
                {"id": "explain", "label": "Explain and stop"},
                {"id": "takeover", "label": "Continue in terminal"},
            ],
            "priority": "medium",
        },
    )
    store.append_event(frontend_id, "run.attention", "odysseus", {"message": "Agent needs an operator decision."})

    ci_run = store.create(
        {
            "title": "Stabilize checkout retry flow",
            "task": "Compose the API and web retry artifacts, publish the draft PR, and keep repairing it until GitHub CI is green.",
            "project_path": str(project),
            "lane": "codex",
            "review_lane": "claude",
            "priority": 90,
            "checks": ["python3 -m unittest", "npm test"],
            "budgets": {"timeout_seconds": 1800, "stall_seconds": 300, "max_tokens": 80_000, "max_tool_calls": 120, "max_cost_usd": 8.0},
            "evidence_class": "demo",
            "origin": "demo",
        }
    )
    ci_id = ci_run["id"]
    store.update(
        ci_id,
        status="pr_created",
        started_at="2026-08-14T08:42:00Z",
        finished_at="2026-08-14T09:18:00Z",
        branch=f"odysseus/{ci_id}",
        base_ref="main",
        base_sha="1" * 40,
        artifact_sha="d8c45b1ea66e7b9a3ca26e64070e8c475d9f4512",
        artifact_files=["api/checkout.py", "web/checkout.js", "tests/test_checkout.py"],
        artifact_created_at="2026-08-14T09:18:00Z",
        integration_sources=[
            {"run_id": "checkout-api", "artifact_sha": "a4f2a2a729c7fe106f8a6e84d07dfa21f9135a91"},
            {"run_id": "checkout-web", "artifact_sha": "b8077bbfab31dde9d6e7648f74f3c1d8ce41b521"},
        ],
        integration_head="c70a83fcda480d79874a78024d4bf3011b261c4f",
        merge_analysis={
            "risk": "high",
            "source_count": 2,
            "overlaps": [
                {"left": "checkout-api", "right": "checkout-web", "files": ["contracts/checkout.json"]}
            ],
            "files": ["api/checkout.py", "contracts/checkout.json", "web/checkout.js"],
        },
        pull_request_url="https://github.com/jpolec/odysseus/pull/42",
        check_results=[
            {"command": "python3 -m unittest", "returncode": 0, "output": "67 tests passed"},
            {"command": "npm test", "returncode": 0, "output": "18 browser tests passed"},
        ],
        ci={
            "status": "failed",
            "attempt": 1,
            "summary": "1 failed, 0 pending, 3 passed",
            "updated_at": "2026-08-14T09:24:00Z",
            "checks": [
                {"workflow": "Quality", "name": "unit / python", "bucket": "pass"},
                {"workflow": "Quality", "name": "browser / chromium", "bucket": "fail"},
                {"workflow": "Security", "name": "semgrep", "bucket": "pass"},
                {"workflow": "Build", "name": "package", "bucket": "pass"},
            ],
            "logs": "browser / chromium\nAssertionError: expected retry banner after 429 response\n  at tests/checkout.spec.ts:118",
        },
        metrics={
            "input_tokens": 61_220,
            "cached_input_tokens": 39_804,
            "output_tokens": 9_118,
            "reasoning_output_tokens": 2_106,
            "tool_calls": 83,
            "cost_usd": 4.612,
            "cost_observed": True,
            "session_usage": {},
        },
        review_summary="Independent review passed. GitHub browser CI exposed one behavioral retry regression.",
        confidence=0.93,
        policy_decision="ci_repair",
        review_status="ci_repair_pushed",
        stage="ci",
        last_heartbeat="2026-08-14T09:23:45Z",
        environment={
            "version": "environment-plan-v1", "profile": "docker", "status": "active",
            "image": "ghcr.io/example/codex-node:2026-08", "network": "bridge",
            "cpus": 2, "memory": "4g",
            "ports": {"APP_PORT": {"host": 43184, "container": 3000}},
            "credential_env_names": ["OPENAI_API_KEY", "GH_TOKEN"],
            "preview_url": "http://127.0.0.1:43184/",
            "isolation": "container filesystem, resources, network mode, and scoped environment",
        },
    )
    store.append_event(ci_id, "integration.started", "git", {"risk": "high", "source_count": 2})
    store.append_event(ci_id, "integration.artifact_applied", "git", {"dependency_run_id": "checkout-api"})
    store.append_event(ci_id, "integration.artifact_applied", "git", {"dependency_run_id": "checkout-web"})
    store.append_event(ci_id, "integration.completed", "git", {"risk": "high", "integration_head": "c70a83fcda48"})
    store.append_event(ci_id, "pr.created", "git", {"url": "https://github.com/jpolec/odysseus/pull/42"})
    store.append_event(
        ci_id,
        "ci.failed",
        "github",
        {
            "message": "Chromium retry-flow test failed; the original Codex session is ready to resume.",
            "attempt": 1,
            "max_attempts": 2,
            "options": [
                {"id": "resume", "label": "Resume original agent"},
                {"id": "takeover", "label": "Continue in terminal"},
            ],
            "priority": "high",
        },
    )
    store.append_event(
        ci_id,
        "attention.answered",
        "user",
        {"answer": "Resume the saved Codex thread with the Chromium failure and preserve the retry contract."},
    )
    store.append_event(
        ci_id,
        "agent.message",
        "codex",
        {"text": "I reproduced the failed retry banner assertion and will patch only the bounded browser recovery path."},
    )
    store.append_event(
        ci_id,
        "agent.tool.completed",
        "codex",
        {
            "tool": "shell",
            "command": "npm test -- tests/checkout.spec.ts",
            "exit_code": 0,
            "aggregated_output": "PASS checkout retry banner after 429 response\n1 test passed",
        },
    )
    for run_id in (backend_id, ci_id):
        store.append_event(
            run_id,
            "review.sent_back",
            "operator",
            {"message": "Keep the browser retry contract visible and run the Chromium checkout scenario before review."},
        )
    release_epic = store.epics.create(
        {
            "title": "Durable release delivery",
            "description": "Make release publication retry-safe and independently verifiable.",
            "project_path": str(project),
            "status": "planning",
            "evidence_class": "demo",
            "source_documents": [{"kind": "milestone", "path": "odysseus://demo/release", "title": "Durable release milestone", "content": "Record publication intent before external effects.\n\nReconcile interrupted effects without duplicates.\n\nVerify artifact and receipt lineage independently."}],
        }
    )
    store.epics.save_plan(
        release_epic["id"],
        {
                "summary": "Record publication intent before the external effect, then reconcile and verify the receipt.",
                "tasks": [
                    {
                        "task_key": "release-intent",
                        "title": "Persist publication intent",
                        "task": "Add an idempotent durable publication request.",
                        "role": "implementer",
                        "depends_on": [],
                        "parallelizable": True,
                        "lane": "codex",
                        "review_lane": "claude",
                        "project_path": str(project),
                        "source_refs": ["S1"],
                        "execution_profile": {"mode": "auto", "harness": "auto", "environment": "isolated_worktree", "policy": "standard", "reason": "Auto routes durable backend work from repository outcomes"},
                        "estimate": {"cost_usd_min": 1, "cost_usd_max": 3, "duration_minutes_min": 8, "duration_minutes_max": 18, "confidence": "low", "basis": "Small comparable durability cohort"},
                    },
                    {
                        "task_key": "release-reconcile",
                        "title": "Reconcile external receipt",
                        "task": "Recover an interrupted publication without duplicating it.",
                        "role": "implementer",
                        "depends_on": ["release-intent"],
                        "parallelizable": False,
                        "lane": "codex",
                        "review_lane": "claude",
                        "project_path": str(project),
                        "source_refs": ["S2"],
                        "execution_profile": {"mode": "auto", "harness": "auto", "environment": "isolated_worktree", "policy": "standard", "reason": "Auto routes recovery work from repository outcomes"},
                        "estimate": {"cost_usd_min": 1, "cost_usd_max": 4, "duration_minutes_min": 10, "duration_minutes_max": 25, "confidence": "low", "basis": "Small comparable recovery cohort"},
                    },
                    {
                        "task_key": "release-proof",
                        "title": "Verify release lineage",
                        "task": "Validate the artifact and external receipt independently.",
                        "role": "reviewer",
                        "depends_on": ["release-reconcile"],
                        "parallelizable": False,
                        "lane": "claude",
                        "review_lane": "codex",
                        "project_path": str(project),
                        "source_refs": ["S3"],
                        "execution_profile": {"mode": "auto", "harness": "auto", "environment": "isolated_worktree", "policy": "strict", "review_policy": "independent_provider", "reason": "Independent validation is selected separately from implementation"},
                        "estimate": {"cost_usd_min": 1, "cost_usd_max": 2, "duration_minutes_min": 6, "duration_minutes_max": 14, "confidence": "low", "basis": "Small independent review cohort"},
                    },
                ],
        }
    )
    adr_path = project / "_ADR" / "0002-versioned-plan-sources.md"
    adr_content = adr_path.read_text(encoding="utf-8") if adr_path.is_file() else "# ADR: Versioned Plan sources\n\nBind every task to an immutable requirement source."
    source_examples = [
        (
            "ADR source contract",
            {"kind": "adr", "path": "_ADR/0002-versioned-plan-sources.md", "title": "Bind plans to versioned requirement sources", "content": adr_content},
            "Map ADR requirements to task contracts",
        ),
        (
            "GitHub issue intake",
            {"kind": "github_issue", "path": "github://issue/42", "source_url": "https://github.com/jpolec/odysseus/issues/42", "title": "Issue #42 · Preserve source lineage", "content": "# Preserve source lineage\n\nA task created from GitHub must retain the issue number, immutable text digest, and required evidence."},
            "Freeze an authoritative GitHub issue",
        ),
    ]
    for title, source, task_title in source_examples:
        example = store.epics.create(
            {
                "title": title,
                "description": source["content"].splitlines()[-1],
                "project_path": str(project),
                "status": "planning",
                "evidence_class": "demo",
                "source_documents": [source],
            }
        )
        store.epics.save_plan(
            example["id"],
            {
                "summary": f"Demonstrate {title.lower()} without starting an agent.",
                "tasks": [
                    {
                        "task_key": f"demo-{source['kind'].replace('_', '-')}",
                        "title": task_title,
                        "task": task_title,
                        "outcome": "The frozen source is linked to an explicit, independently reviewable task contract.",
                        "role": "implementer",
                        "depends_on": [],
                        "parallelizable": True,
                        "lane": "codex",
                        "review_lane": "claude",
                        "project_path": str(project),
                        "source_refs": ["S1"],
                        "acceptance_criteria": ["Source path and digest remain visible", "Nothing executes before approval"],
                        "required_evidence": ["Plan source receipt", "Independent review"],
                        "execution_profile": {"mode": "auto", "harness": "auto", "environment": "isolated_worktree", "policy": "standard", "reason": "Demo of source-aware Auto routing"},
                        "estimate": {"cost_usd_min": 0.5, "cost_usd_max": 2, "duration_minutes_min": 4, "duration_minutes_max": 12, "confidence": "low", "basis": "Illustrative demo range, not calibrated"},
                    }
                ],
            },
        )
        store.epics.update(example["id"], status="proposed")
    return store


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", type=Path)
    parser.add_argument("--project", type=Path, default=REPOSITORY_ROOT)
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--open", action="store_true")
    parser.add_argument("--port", type=int, default=8742)
    args = parser.parse_args()
    state_dir = args.state_dir or Path(tempfile.mkdtemp(prefix="odysseus-demo-"))
    store = seed(state_dir.resolve(), args.project.resolve())
    print(f"Demo state: {store.root}")
    print(f"Start later: bin/odysseus --state-dir {store.root} serve --port {args.port}")
    if not args.serve:
        return 0
    app = OdysseusApp(store, host="127.0.0.1", port=args.port)
    url = f"http://127.0.0.1:{args.port}/"
    print(f"Odysseus demo: {url}")
    app.start()
    if args.open:
        webbrowser.open(url)
    try:
        app.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        app.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
