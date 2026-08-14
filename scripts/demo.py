#!/usr/bin/env python3
"""Create a disposable, deterministic-looking Odysseus 0.3 demo control plane."""

from __future__ import annotations

import argparse
import tempfile
from pathlib import Path
import sys


REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPOSITORY_ROOT))

from odysseus.evaluation import EvaluationEngine  # noqa: E402
from odysseus.server import OdysseusApp  # noqa: E402
from odysseus.store import RunStore  # noqa: E402


def seed(state_dir: Path, project: Path) -> RunStore:
    if state_dir.exists() and any(state_dir.iterdir()):
        raise ValueError(f"demo state directory is not empty: {state_dir}")
    store = RunStore(state_dir)
    epic = store.epics.create(
        {
            "title": "Passkey authentication",
            "description": "Add passkey registration and login with independent security review.",
            "project_path": str(project),
            "status": "proposed",
            "plan": {
                "summary": "Parallel backend and frontend work converge in an integration task.",
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
                    },
                ],
            },
        }
    )
    mapping = store.epics.create_task_batch(epic["id"], epic["plan"]["tasks"])

    backend_id = mapping["auth-api"]
    store.update(
        backend_id,
        status="review",
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
    store.update(frontend_id, status="attention", worker_pid=None)
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
                {"id": "takeover", "label": "Take over in tmux"},
            ],
            "priority": "medium",
        },
    )
    store.append_event(frontend_id, "run.attention", "odysseus", {"message": "Agent needs an operator decision."})
    return store


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", type=Path)
    parser.add_argument("--project", type=Path, default=REPOSITORY_ROOT)
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--port", type=int, default=8742)
    args = parser.parse_args()
    state_dir = args.state_dir or Path(tempfile.mkdtemp(prefix="odysseus-demo-"))
    store = seed(state_dir.resolve(), args.project.resolve())
    print(f"Demo state: {store.root}")
    print(f"Start later: bin/odysseus --state-dir {store.root} serve --port {args.port}")
    if not args.serve:
        return 0
    app = OdysseusApp(store, host="127.0.0.1", port=args.port)
    print(f"Odysseus demo: http://127.0.0.1:{args.port}/")
    try:
        app.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        app.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
