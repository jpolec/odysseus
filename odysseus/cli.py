"""Command-line interface for the Odysseus local agent control plane."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import sys
import threading
import webbrowser
from pathlib import Path
from typing import Any

from .scheduler import ReviewActions, Scheduler
from .server import OdysseusApp
from .store import RunStore, default_state_root


def _print_json(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def _store(args: argparse.Namespace) -> RunStore:
    return RunStore(args.state_dir)


def cmd_serve(args: argparse.Namespace) -> int:
    store = _store(args)
    app = OdysseusApp(
        store,
        host=args.host,
        port=args.port,
        allow_remote=args.allow_remote,
        verbose=args.verbose,
    )
    host, port = app.start()
    display_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
    url = f"http://{display_host}:{port}/"
    print(f"Odysseus is listening on {url}")
    print(f"State: {store.root}")
    if args.open:
        webbrowser.open(url)

    stopped = threading.Event()

    def stop(_signum: int, _frame: Any) -> None:
        if not stopped.is_set():
            stopped.set()
            threading.Thread(target=app.stop, daemon=True).start()

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    try:
        assert app.httpd is not None
        app.httpd.serve_forever(poll_interval=0.35)
    finally:
        if not stopped.is_set():
            app.stop()
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    task = args.task
    if task == "-":
        task = sys.stdin.read()
    run = _store(args).create(
        {
            "task": task,
            "title": args.title or "",
            "project_path": args.project,
            "lane": args.lane,
            "review_lane": args.review_lane or args.lane,
            "workflow": args.workflow,
            "checks": args.check,
            "max_retries": args.max_retries,
            "base_ref": args.base,
        }
    )
    if args.json:
        _print_json(run)
    else:
        print(f"Queued {run['id']}: {run['title']}")
        print("The persistent scheduler will pick it up while `odysseus serve` is running.")
    return 0


def cmd_runs(args: argparse.Namespace) -> int:
    runs = _store(args).list()
    if args.json:
        _print_json({"runs": runs})
        return 0
    if not runs:
        print("No Odysseus runs yet.")
        return 0
    print(f"{'STATUS':<12} {'LANE':<9} {'RUN':<54} TITLE")
    for run in runs:
        print(
            f"{str(run.get('status', '')):<12} {str(run.get('lane', '')):<9} "
            f"{str(run.get('id', '')):<54} {run.get('title', '')}"
        )
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    _print_json(_store(args).get(args.run_id))
    return 0


def cmd_events(args: argparse.Namespace) -> int:
    events = _store(args).events(args.run_id, after=args.after)
    for event in events:
        print(json.dumps(event, ensure_ascii=False, separators=(",", ":")))
    return 0


def _actions(args: argparse.Namespace) -> tuple[RunStore, ReviewActions]:
    store = _store(args)
    scheduler = Scheduler(store)
    return store, ReviewActions(store, scheduler)


def cmd_accept(args: argparse.Namespace) -> int:
    _, actions = _actions(args)
    _print_json(actions.accept(args.run_id))
    return 0


def cmd_send_back(args: argparse.Namespace) -> int:
    _, actions = _actions(args)
    feedback = args.feedback if args.feedback != "-" else sys.stdin.read()
    _print_json(actions.send_back(args.run_id, feedback))
    return 0


def cmd_cancel(args: argparse.Namespace) -> int:
    _print_json(_store(args).request_cancel(args.run_id))
    return 0


def cmd_draft_pr(args: argparse.Namespace) -> int:
    _, actions = _actions(args)
    _print_json(actions.draft_pr(args.run_id))
    return 0


def cmd_config(args: argparse.Namespace) -> int:
    store = _store(args)
    changes: dict[str, Any] = {}
    if args.max_parallel is not None:
        changes["max_parallel"] = max(1, args.max_parallel)
    value = store.update_config(changes) if changes else store.config()
    _print_json(value)
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    store = _store(args)
    lanes = store.config().get("lanes", {})
    tools = ["git", "python3", "codex", "claude", "gh"]
    result = {name: shutil.which(name) for name in tools}
    result["state_dir"] = str(store.root)
    result["state_writable"] = os.access(store.root, os.W_OK)
    result["custom_lanes"] = sorted(lanes)
    _print_json(result)
    return 0 if result["git"] and result["python3"] else 1


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        prog="odysseus",
        description="Local worktree, queue, workflow, and review control plane for coding agents.",
    )
    root.add_argument(
        "--state-dir",
        type=Path,
        default=default_state_root(),
        help="state directory (default: $ODYSSEUS_HOME or ~/.odysseus)",
    )
    sub = root.add_subparsers(dest="command", required=True)

    serve = sub.add_parser("serve", aliases=["web"], help="run the scheduler and local web UI")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=int(os.environ.get("ODYSSEUS_PORT", "8741")))
    serve.add_argument("--allow-remote", action="store_true", help="disable loopback Host/Origin checks")
    serve.add_argument("--open", action="store_true", help="open the UI in the default browser")
    serve.add_argument("--verbose", action="store_true")
    serve.set_defaults(func=cmd_serve)

    run = sub.add_parser("run", help="enqueue an agent-check-review task")
    run.add_argument("task", help="task prompt, or - to read stdin")
    run.add_argument("--title")
    run.add_argument("--project", default=".")
    run.add_argument("--lane", default="codex")
    run.add_argument("--review-lane")
    run.add_argument("--workflow", default="agent-check-review")
    run.add_argument("--check", action="append", default=[], help="check command; repeat as needed")
    run.add_argument("--max-retries", type=int, default=2)
    run.add_argument("--base", default="")
    run.add_argument("--json", action="store_true")
    run.set_defaults(func=cmd_run)

    runs = sub.add_parser("runs", help="list persisted runs")
    runs.add_argument("--json", action="store_true")
    runs.set_defaults(func=cmd_runs)

    show = sub.add_parser("show", help="show one run record")
    show.add_argument("run_id")
    show.set_defaults(func=cmd_show)

    events = sub.add_parser("events", help="print a run's NDJSON history")
    events.add_argument("run_id")
    events.add_argument("--after", type=int, default=0)
    events.set_defaults(func=cmd_events)

    accept = sub.add_parser("accept", help="accept a run at the review gate")
    accept.add_argument("run_id")
    accept.set_defaults(func=cmd_accept)

    send_back = sub.add_parser("send-back", help="return a run to the agent with feedback")
    send_back.add_argument("run_id")
    send_back.add_argument("feedback", help="feedback text, or - to read stdin")
    send_back.set_defaults(func=cmd_send_back)

    cancel = sub.add_parser("cancel", help="request cancellation")
    cancel.add_argument("run_id")
    cancel.set_defaults(func=cmd_cancel)

    draft = sub.add_parser("draft-pr", help="commit, push, and open a draft pull request")
    draft.add_argument("run_id")
    draft.set_defaults(func=cmd_draft_pr)

    config = sub.add_parser("config", help="show or change scheduler configuration")
    config.add_argument("--max-parallel", type=int)
    config.set_defaults(func=cmd_config)

    doctor = sub.add_parser("doctor", help="show local tool availability")
    doctor.set_defaults(func=cmd_doctor)
    return root


def main() -> int:
    try:
        args = parser().parse_args()
        return int(args.func(args))
    except KeyboardInterrupt:
        return 130
    except (KeyError, ValueError, RuntimeError) as exc:
        print(f"odysseus: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
