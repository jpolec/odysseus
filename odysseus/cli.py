"""Command-line interface for the Odysseus local agent control plane."""

from __future__ import annotations

import argparse
import errno
import json
import os
import shutil
import signal
import subprocess
import sys
import threading
import webbrowser
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from . import __version__
from .events import EVENT_SCHEMA_VERSION
from .ci import CIWatcher
from .lifecycle import ResourceLifecycle
from .lifecycle import ServerLease
from .planner import EpicPlanner
from .proof import production_proof, proof_markdown
from .resources import resource_path
from .search import search, statistics
from .scheduler import ReviewActions, Scheduler
from .server import OdysseusApp
from .state import verify_state
from .store import RUN_SCHEMA_VERSION, RunStore, default_state_root
from .tmux import TmuxBridge


def _print_json(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def _store(
    args: argparse.Namespace,
    *,
    migrate: bool = True,
    readonly: bool = False,
) -> RunStore:
    return RunStore(args.state_dir, migrate=migrate, readonly=readonly)


def _environment_payload(args: argparse.Namespace) -> dict[str, Any]:
    environment: dict[str, Any] = {}
    if getattr(args, "environment", ""):
        environment["profile"] = args.environment
    for key in ("image", "network", "cpus", "memory"):
        value = getattr(args, key, None)
        if value not in (None, "", 0, 0.0):
            environment[key] = value
    env: dict[str, str] = {}
    for item in getattr(args, "environment_variable", []) or []:
        name, separator, value = item.partition("=")
        if not separator or not name.strip():
            raise ValueError("--env requires NAME=VALUE")
        env[name.strip()] = value
    if env:
        environment["env"] = env
    ports: dict[str, int] = {}
    for item in getattr(args, "environment_port", []) or []:
        name, separator, value = item.partition("=")
        if not separator or not name.strip():
            raise ValueError("--port requires NAME=CONTAINER_PORT")
        try:
            ports[name.strip()] = int(value)
        except ValueError as exc:
            raise ValueError("--port requires a numeric container port") from exc
    if ports:
        environment["ports"] = ports
    if getattr(args, "allow_env", None):
        environment["allow_env"] = args.allow_env
    if getattr(args, "environment_setup", None):
        environment["setup"] = args.environment_setup
    return environment


def _running_odysseus_url(host: str, port: int) -> str:
    probe_host = "127.0.0.1" if host in {"0.0.0.0", "::", "localhost"} else host
    if probe_host not in {"127.0.0.1", "::1"}:
        return ""
    url = f"http://{probe_host}:{port}"
    try:
        with urllib.request.urlopen(f"{url}/api/health", timeout=1.5) as response:
            value = json.load(response)
        with urllib.request.urlopen(f"{url}/", timeout=1.5) as response:
            content_type = response.headers.get_content_type()
            page = response.read(4096)
    except (OSError, urllib.error.URLError, json.JSONDecodeError):
        return ""
    healthy = (
        isinstance(value, dict)
        and value.get("ok") is True
        and value.get("product") == "odysseus"
        and content_type == "text/html"
        and b"<title>Odysseus" in page
    )
    return url if healthy else ""


def cmd_serve(args: argparse.Namespace) -> int:
    lease = ServerLease(args.state_dir)
    try:
        lease.acquire()
    except RuntimeError as exc:
        existing_url = _running_odysseus_url(args.host, args.port)
        if "another Odysseus server" in str(exc) and existing_url:
            print(f"Odysseus is already running at {existing_url}/")
            if args.open:
                webbrowser.open(f"{existing_url}/")
            return 0
        raise
    auth_password = ""
    try:
        store = _store(args)
        if args.auth_password_file:
            try:
                auth_password = Path(args.auth_password_file).expanduser().read_text(encoding="utf-8").strip()
            except OSError as exc:
                raise ValueError(f"cannot read auth password file: {exc}") from exc
            if not auth_password:
                raise ValueError("auth password file is empty")
        if args.allow_remote and not auth_password and not args.insecure_remote:
            raise ValueError("--allow-remote requires --auth-password-file (or explicit --insecure-remote)")
        app: OdysseusApp | None = None
        host = args.host
        port = args.port
        attempts = 1 if args.port == 0 else min(100, 65536 - args.port)
        for offset in range(attempts):
            candidate = args.port + offset
            app = OdysseusApp(
                store,
                host=args.host,
                port=candidate,
                allow_remote=args.allow_remote,
                verbose=args.verbose,
                auth_user=args.auth_user if auth_password else "",
                auth_password=auth_password,
                max_http_connections=args.max_http_connections,
                max_sse_connections=args.max_sse_connections,
            )
            try:
                host, port = app.start()
                break
            except OSError as exc:
                if exc.errno != errno.EADDRINUSE:
                    raise ValueError(f"cannot start the local server: {exc}") from exc
                if offset + 1 >= attempts:
                    raise ValueError(
                        f"ports {args.port}-{candidate} are unavailable; "
                        "choose another starting port with `--port`."
                    ) from exc
                print(f"Port {candidate} is unavailable; trying {candidate + 1}.")
        else:  # pragma: no cover - the loop always starts or raises
            raise ValueError("cannot find an available local port")
        assert app is not None
        lease.update(host=host, port=port)
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
    finally:
        lease.release()
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    task = args.task
    if task == "-":
        task = sys.stdin.read()
    budget_values = {
        "timeout_seconds": args.timeout,
        "stall_seconds": args.stall_timeout,
        "max_tokens": args.max_tokens,
        "max_tool_calls": args.max_tool_calls,
        "max_cost_usd": args.max_cost,
    }
    workflow = "variants" if args.variants else args.workflow
    run = _store(args).create(
        {
            "task": task,
            "title": args.title or "",
            "project_path": args.project,
            "lane": args.lane,
            "review_lane": args.review_lane or args.lane,
            "workflow": workflow,
            "variants": {
                "enabled": bool(args.variants),
                "count": args.variants or 2,
                "lanes": args.variant_lane,
                "prompts": args.variant_prompt,
            },
            "checks": args.check,
            "max_retries": args.max_retries,
            "base_ref": args.base,
            "priority": args.priority,
            "skill_mode": args.skill_mode,
            "skills": args.skill,
            "environment": _environment_payload(args),
            "untrusted_project": args.untrusted_project,
            "origin": "cli",
            "evidence_class": "observed",
            "release": args.release,
            "budgets": {key: value for key, value in budget_values.items() if value is not None},
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


def cmd_epics(args: argparse.Namespace) -> int:
    store = _store(args)
    if args.epic_id:
        epic = store.epics.get(args.epic_id)
        _print_json({**epic, "runs": store.epics.runs(args.epic_id)})
    else:
        _print_json({"epics": store.epics.list()})
    return 0


def cmd_plan(args: argparse.Namespace) -> int:
    requirement = args.requirement if args.requirement != "-" else sys.stdin.read()
    planner = EpicPlanner(_store(args))
    epic = planner.plan(
        requirement,
        args.project,
        lane=args.planner_lane,
        title=args.title or "",
        default_task_lane=args.lane,
        default_review_lane=args.review_lane,
        checks=args.check,
    )
    _print_json(epic)
    print(f"Approve with: bin/odysseus approve-epic {epic['id']}", file=sys.stderr)
    return 0


def cmd_approve_epic(args: argparse.Namespace) -> int:
    _print_json(EpicPlanner(_store(args)).approve(args.epic_id))
    return 0


def cmd_attention(args: argparse.Namespace) -> int:
    _print_json({"items": _store(args).attention.list(status=args.status)})
    return 0


def cmd_answer(args: argparse.Namespace) -> int:
    response = args.response if args.response != "-" else sys.stdin.read()
    _, actions = _actions(args)
    _print_json(actions.answer_attention(args.attention_id, response))
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


def cmd_apply(args: argparse.Namespace) -> int:
    _, actions = _actions(args)
    _print_json(actions.apply(args.run_id))
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


def cmd_variants(args: argparse.Namespace) -> int:
    _, actions = _actions(args)
    selected = [item for value in args.selected_run_id for item in value.split(",") if item]
    payload = {
        "decision": args.decision,
        "selected_run_ids": selected,
        "reason": args.reason or "",
    }
    _print_json(actions.decide_variants(args.run_id, payload))
    return 0


def cmd_resume(args: argparse.Namespace) -> int:
    _, actions = _actions(args)
    prompt = args.prompt if args.prompt != "-" else sys.stdin.read()
    _print_json(actions.resume(args.run_id, prompt, strategy=args.strategy, lane=args.lane or ""))
    return 0


def cmd_sessions(args: argparse.Namespace) -> int:
    sessions = TmuxBridge(_store(args)).list()
    if args.json:
        _print_json({"sessions": sessions})
        return 0
    if not sessions:
        print("No tmux sessions are currently visible.")
        return 0
    print(f"{'STATE':<9} {'LANE':<9} {'ADOPTED':<9} {'TARGET':<30} PROJECT")
    for item in sessions:
        print(
            f"{str(item.get('status', 'unknown')):<9} {str(item.get('lane', '')):<9} "
            f"{('yes' if item.get('adopted_run_id') else 'no'):<9} {str(item.get('id', '')):<30} "
            f"{item.get('project_path', '')}"
        )
    return 0


def cmd_adopt(args: argparse.Namespace) -> int:
    _print_json(TmuxBridge(_store(args)).adopt(args.tmux_session))
    return 0


def cmd_takeover(args: argparse.Namespace) -> int:
    store = _store(args)
    result = TmuxBridge(store).takeover(store.get(args.run_id))
    if args.json:
        _print_json(result)
    else:
        print(result["command"])
    return 0


def cmd_projects(args: argparse.Namespace) -> int:
    store = _store(args)
    if args.add:
        value: Any = store.projects.upsert(args.add, {"name": args.name or "", "tags": args.tag}, require_git=True)
    else:
        value = {"projects": store.projects.list()}
    _print_json(value)
    return 0


def cmd_inbox(args: argparse.Namespace) -> int:
    inbox = _store(args).inbox
    if args.add:
        value: Any = inbox.create({"title": args.title or "", "task": args.add, "project_path": args.project or ""})
    elif args.resolve:
        value = inbox.update(args.resolve, status="resolved")
    else:
        value = {"items": inbox.list(status=args.status)}
    _print_json(value)
    return 0


def cmd_config(args: argparse.Namespace) -> int:
    store = _store(args)
    changes: dict[str, Any] = {}
    if args.max_parallel is not None:
        changes["max_parallel"] = max(1, args.max_parallel)
    value = store.update_config(changes) if changes else store.config()
    _print_json(value)
    return 0


def cmd_ci(args: argparse.Namespace) -> int:
    store, actions = _actions(args)
    watcher = CIWatcher(store, actions)
    changed = watcher.poll_once(force=True, run_id=args.run_id or "")
    _print_json({"checked": args.run_id or "all published runs", "changed": changed})
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    _print_json({"results": search(_store(args), args.query, limit=args.limit)})
    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    _print_json(statistics(_store(args, migrate=False)))
    return 0


def _format_bytes(value: Any) -> str:
    size = float(value or 0)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return f"{size:.1f} GB"


def cmd_resources(args: argparse.Namespace) -> int:
    store = _store(args)
    retention_days = args.retention_days if args.retention_days is not None else store.config().get("resource_retention_days", 14)
    lifecycle = ResourceLifecycle(store)
    if args.reclaim:
        result = lifecycle.reclaim(retention_days=retention_days, force=args.force)
        if args.json:
            _print_json(result)
        else:
            print(
                f"Reclaimed {_format_bytes(result['reclaimed_bytes'])} from "
                f"{len(result['reclaimed'])} resources."
            )
            if result["errors"]:
                print("Some resources could not be reclaimed:", file=sys.stderr)
                for error in result["errors"]:
                    print(f"  - {error['path']}: {error['error']}", file=sys.stderr)
                return 1
        return 0
    result = lifecycle.inspect(retention_days=retention_days)
    if args.json:
        _print_json(result)
    else:
        totals = result["totals"]
        print(f"State: {result['state_root']}")
        print(f"Retention: {result['retention_days']} days")
        print(f"Worktrees: {_format_bytes(totals['worktree_bytes'])} ({totals['worktrees']} retained)")
        print(f"Runtime:   {_format_bytes(totals['runtime_bytes'])} ({totals['runtime_directories']} directories)")
        print(
            f"Reclaimable now: {_format_bytes(totals['reclaimable_bytes'])} "
            f"({totals['reclaimable_worktrees']} worktrees, "
            f"{totals['reclaimable_runtime_directories']} runtime directories)"
        )
    return 0


def cmd_state_verify(args: argparse.Namespace) -> int:
    result = verify_state(args.state_dir)
    if result["valid"] and args.migrate:
        RunStore(args.state_dir)
        result = verify_state(args.state_dir)
        result["migrated"] = True
    else:
        result["migrated"] = False
    if args.json:
        _print_json(result)
    elif result["valid"]:
        print(
            f"State is valid: {result['runs']} runs, {result['events']} events, "
            f"{result['epics']} epics ({result['root']})"
        )
    else:
        print(f"State verification failed: {result['root']}", file=sys.stderr)
        for error in result["errors"]:
            print(f"  - {error}", file=sys.stderr)
    return 0 if result["valid"] else 1


def cmd_proof(args: argparse.Namespace) -> int:
    verified = verify_state(args.state_dir)
    if not verified["valid"]:
        raise RuntimeError("state verification failed; run `odysseus state verify` for details")
    proof = production_proof(
        _store(args, migrate=False, readonly=True),
        release="" if args.all_releases else args.release,
        minimum_runs=args.minimum_runs,
    )
    content = json.dumps(proof, ensure_ascii=False, indent=2, sort_keys=True) + "\n" if args.json else proof_markdown(proof)
    if args.output:
        target = Path(args.output).expanduser()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        print(target)
    else:
        print(content, end="")
    if args.require_sufficient and not proof["sample_sufficient"]:
        return 2
    return 0


def _install_manifest() -> dict[str, Any]:
    for parent in Path(__file__).resolve().parents:
        path = parent / "install.json"
        if not path.is_file():
            continue
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(value, dict) and value.get("format") == "odysseus-install-v1":
            return {**value, "manifest_path": str(path)}
    return {}


def cmd_version(args: argparse.Namespace) -> int:
    manifest = _install_manifest()
    value = {
        "version": __version__,
        "run_schema": RUN_SCHEMA_VERSION,
        "event_schema": EVENT_SCHEMA_VERSION,
        "installation": "managed" if manifest else "package-or-checkout",
        "channel": str(manifest.get("channel") or ""),
        "ref": str(manifest.get("ref") or ""),
        "commit": str(manifest.get("commit") or ""),
        "manifest": str(manifest.get("manifest_path") or ""),
    }
    if args.json:
        _print_json(value)
    else:
        print(f"Odysseus {__version__}")
        print(f"  state schemas  run {RUN_SCHEMA_VERSION}; events {EVENT_SCHEMA_VERSION}")
        if manifest:
            print(f"  install        managed {value['channel']} ({value['ref']})")
        else:
            print("  install        Python package or source checkout")
    return 0


def _installer_script() -> Path:
    try:
        return resource_path("installer", "install.sh")
    except FileNotFoundError:
        source = Path(__file__).resolve().parent.parent / "install.sh"
        if source.is_file():
            return source
        raise ValueError("the lifecycle installer is not available in this installation")


def cmd_update(args: argparse.Namespace) -> int:
    if not _install_manifest():
        print(
            "This copy is managed by a source checkout, uvx, or pipx. "
            "Use `git pull`, rerun uvx, or `pipx upgrade odysseus-agents`; "
            "`odysseus update` is reserved for the versioned shell installer.",
            file=sys.stderr,
        )
        return 2
    command = ["bash", str(_installer_script()), "--state-dir", str(args.state_dir)]
    command.append("--check" if args.check else "--update")
    if args.edge:
        command.append("--edge")
    if args.target_version:
        command.extend(["--version", args.target_version])
    return int(subprocess.run(command, check=False).returncode)


def cmd_rollback(args: argparse.Namespace) -> int:
    if not _install_manifest():
        print("No versioned shell installation is active; there is nothing to roll back.", file=sys.stderr)
        return 2
    command = ["bash", str(_installer_script()), "--rollback", "--state-dir", str(args.state_dir)]
    if args.restore_state:
        command.append("--restore-state")
    return int(subprocess.run(command, check=False).returncode)


def cmd_export(args: argparse.Namespace) -> int:
    store = _store(args)
    payload = {
        "format": "odysseus-state-v1",
        "config": store.config(),
        "projects": store.projects.list(),
        "epics": store.epics.list(),
        "runs": [{**run, "events": store.events(str(run["id"]), limit=100_000)} for run in store.list()],
        "attention": store.attention.list(),
        "inbox": store.inbox.list(),
        "stats": statistics(store),
    }
    encoded = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        target = Path(args.output).expanduser()
        target.write_text(encoded, encoding="utf-8")
        print(target)
    else:
        print(encoded, end="")
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    store = _store(args)
    lanes = store.config().get("lanes", {})
    tools = ["git", "python3", "codex", "claude", "gh", "docker", "devcontainer"]
    result = {name: shutil.which(name) for name in tools}
    result["state_dir"] = str(store.root)
    result["state_writable"] = os.access(store.root, os.W_OK)
    result["custom_lanes"] = sorted(lanes)
    try:
        result["web_assets"] = str(resource_path("web", "index.html"))
        result["bundled_skills"] = len(list(resource_path("skills").glob("*/SKILL.md")))
    except FileNotFoundError:
        result["web_assets"] = None
        result["bundled_skills"] = 0
    if args.json:
        _print_json(result)
    else:
        print(f"Odysseus {__version__}")
        print()
        labels = {
            "git": "Git",
            "python3": "Python 3",
            "codex": "Codex CLI",
            "claude": "Claude Code",
            "gh": "GitHub CLI",
            "docker": "Docker",
            "devcontainer": "Dev Container CLI",
        }
        for name in tools:
            marker = "ready" if result[name] else "missing"
            optional = "" if name in {"git", "python3"} else " (optional)"
            location = result[name] or "not found"
            print(f"  {marker:<7} {labels[name]}{optional}: {location}")
        print()
        print(f"  state   {result['state_dir']} ({'writable' if result['state_writable'] else 'not writable'})")
        print(f"  assets  {'ready' if result['web_assets'] else 'missing'}; {result['bundled_skills']} bundled Skills")
        if result["git"] and result["python3"] and (result["codex"] or result["claude"]):
            print("\nReady. Run `odysseus start` and add a repository.")
        elif result["git"] and result["python3"]:
            print("\nCore is ready. Install and authenticate Codex CLI or Claude Code before running tasks.")
        else:
            print("\nInstall the missing required tools before starting Odysseus.")
    return 0 if result["git"] and result["python3"] else 1


def cmd_demo(args: argparse.Namespace) -> int:
    script = resource_path("scripts", "demo.py")
    if not script.is_file():
        raise ValueError(f"demo script is missing: {script}")
    command = [sys.executable, str(script), "--serve", "--port", str(args.port)]
    if args.open:
        command.append("--open")
    return int(subprocess.run(command, check=False).returncode)


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        prog="odysseus",
        description="Local worktree, queue, workflow, and review control plane for coding agents.",
    )
    root.add_argument("--version", action="version", version=f"Odysseus {__version__}")
    root.add_argument(
        "--state-dir",
        type=Path,
        default=default_state_root(),
        help="state directory (default: $ODYSSEUS_HOME or ~/.odysseus)",
    )
    sub = root.add_subparsers(dest="command", required=True)

    serve = sub.add_parser("serve", aliases=["web", "start"], help="run the scheduler and local web UI")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=int(os.environ.get("ODYSSEUS_PORT", "8741")))
    serve.add_argument("--allow-remote", action="store_true", help="disable loopback Host/Origin checks")
    serve.add_argument("--auth-user", default=os.environ.get("ODYSSEUS_AUTH_USER", "odysseus"))
    serve.add_argument("--auth-password-file", default=os.environ.get("ODYSSEUS_AUTH_PASSWORD_FILE", ""), help="enable HTTP Basic auth using a password read from this file")
    serve.add_argument("--insecure-remote", action="store_true", help="explicitly allow an unauthenticated remote bind (not recommended)")
    serve.add_argument("--open", action="store_true", help="open the UI in the default browser")
    serve.add_argument("--verbose", action="store_true")
    serve.add_argument("--max-http-connections", type=int, default=int(os.environ.get("ODYSSEUS_MAX_HTTP_CONNECTIONS", "64")), help="bound concurrent HTTP clients")
    serve.add_argument("--max-sse-connections", type=int, default=int(os.environ.get("ODYSSEUS_MAX_SSE_CONNECTIONS", "32")), help="bound concurrent live event streams")
    serve.set_defaults(func=cmd_serve)

    run = sub.add_parser("run", help="enqueue an agent-check-review task")
    run.add_argument("task", help="task prompt, or - to read stdin")
    run.add_argument("--title")
    run.add_argument("--project", default=".")
    run.add_argument("--lane", default="codex")
    run.add_argument("--review-lane")
    run.add_argument("--workflow", default="agent-check-review")
    run.add_argument("--variants", type=int, choices=(2, 3), help="explicitly opt into a 2- or 3-candidate variants workflow")
    run.add_argument("--variant-lane", action="append", default=[], help="candidate lane; repeat up to --variants times")
    run.add_argument("--variant-prompt", action="append", default=[], help="candidate-specific instruction; repeat up to --variants times")
    run.add_argument("--check", action="append", default=[], help="check command; repeat as needed")
    run.add_argument("--max-retries", type=int, default=2)
    run.add_argument("--base", default="")
    run.add_argument("--priority", type=int, default=50, help="scheduler priority from 0 to 100")
    run.add_argument("--release", default=__version__, help="release label for dogfooding evidence")
    run.add_argument("--timeout", type=int, help="agent/reviewer timeout in seconds (0 disables)")
    run.add_argument("--stall-timeout", type=int, help="stop after this many seconds without output")
    run.add_argument("--max-tokens", type=int, help="hard token budget (0 disables)")
    run.add_argument("--max-tool-calls", type=int, help="hard tool-call budget (0 disables)")
    run.add_argument("--max-cost", type=float, help="reported USD cost budget (0 disables)")
    run.add_argument("--skill-mode", choices=("auto", "manual", "none"), default="auto", help="automatic, explicit, or disabled task skills")
    run.add_argument("--skill", action="append", default=[], help="skill name for --skill-mode manual; repeatable")
    run.add_argument("--environment", choices=("host", "docker", "devcontainer"), default="", help="execution profile; empty uses the project default")
    run.add_argument("--image", default="", help="container image for --environment docker")
    run.add_argument("--network", choices=("bridge", "none"), default="", help="Docker network mode")
    run.add_argument("--env", dest="environment_variable", action="append", default=[], metavar="NAME=VALUE", help="non-secret task environment value; repeatable")
    run.add_argument("--allow-env", action="append", default=[], metavar="NAME", help="pass one named host credential variable without storing its value")
    run.add_argument("--port", dest="environment_port", action="append", default=[], metavar="NAME=PORT", help="allocate a host port for a container port; repeatable")
    run.add_argument("--cpus", type=float, help="Docker CPU limit")
    run.add_argument("--memory", default="", help="Docker memory limit such as 2g")
    run.add_argument("--setup", dest="environment_setup", action="append", default=[], help="environment setup command; repeatable")
    run.add_argument("--untrusted-project", action="store_true", help="require container isolation and explicit approval of repository-supplied commands")
    run.add_argument("--json", action="store_true")
    run.set_defaults(func=cmd_run)

    runs = sub.add_parser("runs", help="list persisted runs")
    runs.add_argument("--json", action="store_true")
    runs.set_defaults(func=cmd_runs)

    epics = sub.add_parser("epics", help="list epics or show one task DAG")
    epics.add_argument("epic_id", nargs="?")
    epics.set_defaults(func=cmd_epics)

    plan = sub.add_parser("plan", help="decompose a requirement into an approval-gated task DAG")
    plan.add_argument("requirement", help="requirement text, or - to read stdin")
    plan.add_argument("--title")
    plan.add_argument("--project", default=".")
    plan.add_argument("--planner-lane", default="")
    plan.add_argument("--lane", default="")
    plan.add_argument("--review-lane", default="")
    plan.add_argument("--check", action="append", default=[])
    plan.set_defaults(func=cmd_plan)

    approve_epic = sub.add_parser("approve-epic", help="materialize an approved epic proposal")
    approve_epic.add_argument("epic_id")
    approve_epic.set_defaults(func=cmd_approve_epic)

    attention = sub.add_parser("attention", help="list work that needs an operator")
    attention.add_argument("--status", choices=["open", "answered", "resolved"], default="open")
    attention.set_defaults(func=cmd_attention)

    answer = sub.add_parser("answer", help="answer an agent question or permission request")
    answer.add_argument("attention_id")
    answer.add_argument("response", help="operator response, or - to read stdin")
    answer.set_defaults(func=cmd_answer)

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

    apply_result = sub.add_parser(
        "apply",
        help="merge an accepted artifact into its clean source checkout",
    )
    apply_result.add_argument("run_id")
    apply_result.set_defaults(func=cmd_apply)

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

    variants = sub.add_parser("variants", help="record an explicit variants decision")
    variants.add_argument("run_id")
    variants.add_argument("decision", choices=["select", "combine", "reject_all"])
    variants.add_argument("--selected-run-id", action="append", default=[], help="selected candidate run id; repeat or comma-separate")
    variants.add_argument("--reason", default="")
    variants.set_defaults(func=cmd_variants)

    resume = sub.add_parser("resume", help="continue a review/failed run in its existing agent session")
    resume.add_argument("run_id")
    resume.add_argument("prompt", nargs="?", default="", help="continuation prompt, or - to read stdin")
    resume.add_argument("--strategy", choices=["resume", "switch", "clean"], default="resume")
    resume.add_argument("--lane", help="new lane when --strategy switch is selected")
    resume.set_defaults(func=cmd_resume)

    sessions = sub.add_parser("sessions", help="list automatically discovered tmux sessions")
    sessions.add_argument("--json", action="store_true")
    sessions.set_defaults(func=cmd_sessions)

    adopt = sub.add_parser("adopt", help="persist a live tmux session as an Odysseus task")
    adopt.add_argument("tmux_session")
    adopt.set_defaults(func=cmd_adopt)

    takeover = sub.add_parser("takeover", help="resume an autonomous run interactively in tmux")
    takeover.add_argument("run_id")
    takeover.add_argument("--json", action="store_true")
    takeover.set_defaults(func=cmd_takeover)

    projects = sub.add_parser("projects", help="list or register projects")
    projects.add_argument("--add")
    projects.add_argument("--name")
    projects.add_argument("--tag", action="append", default=[])
    projects.set_defaults(func=cmd_projects)

    inbox = sub.add_parser("inbox", help="list, add, or resolve follow-ups")
    inbox.add_argument("--add")
    inbox.add_argument("--title")
    inbox.add_argument("--project")
    inbox.add_argument("--resolve")
    inbox.add_argument("--status", choices=["open", "resolved", "promoted"])
    inbox.set_defaults(func=cmd_inbox)

    config = sub.add_parser("config", help="show or change scheduler configuration")
    config.add_argument("--max-parallel", type=int)
    config.set_defaults(func=cmd_config)

    ci = sub.add_parser("ci", help="poll GitHub checks now and run the configured repair loop")
    ci.add_argument("run_id", nargs="?")
    ci.set_defaults(func=cmd_ci)

    search_parser = sub.add_parser("search", help="search runs, events, epics, projects, attention, and inbox")
    search_parser.add_argument("query")
    search_parser.add_argument("--limit", type=int, default=100)
    search_parser.set_defaults(func=cmd_search)

    stats_parser = sub.add_parser("stats", help="show engineering outcome and agent economics totals")
    stats_parser.set_defaults(func=cmd_stats)

    resources_parser = sub.add_parser("resources", help="inspect and reclaim retained worktrees and runtime directories")
    resources_parser.add_argument("--retention-days", type=int, help="age threshold for automatic reclamation")
    resources_parser.add_argument("--reclaim", action="store_true", help="remove eligible retained resources now")
    resources_parser.add_argument("--force", action="store_true", help="reclaim terminal resources without waiting for the retention window")
    resources_parser.add_argument("--json", action="store_true")
    resources_parser.set_defaults(func=cmd_resources)

    state_parser = sub.add_parser("state", help="verify or migrate durable state")
    state_actions = state_parser.add_subparsers(dest="state_command", required=True)
    state_verify = state_actions.add_parser("verify", help="strictly scan every persisted JSON and NDJSON record")
    state_verify.add_argument("--migrate", action="store_true", help="migrate supported older records after a clean scan")
    state_verify.add_argument("--json", action="store_true")
    state_verify.set_defaults(func=cmd_state_verify)

    proof_parser = sub.add_parser("proof", help="produce an honest receipt from explicitly observed agent runs")
    proof_parser.add_argument("--release", default=__version__, help="release label to aggregate")
    proof_parser.add_argument("--all-releases", action="store_true", help="aggregate observed runs across releases")
    proof_parser.add_argument("--minimum-runs", type=int, default=20, help="sample-size threshold for publication")
    proof_parser.add_argument("--require-sufficient", action="store_true", help="exit 2 when the sample is below threshold")
    proof_parser.add_argument("--json", action="store_true", help="emit the full machine-readable receipt")
    proof_parser.add_argument("--output", help="write the receipt to a file")
    proof_parser.set_defaults(func=cmd_proof)

    version_parser = sub.add_parser("version", help="show version, schemas, and managed install channel")
    version_parser.add_argument("--json", action="store_true")
    version_parser.set_defaults(func=cmd_version)

    update_parser = sub.add_parser("update", help="check or atomically install an Odysseus update")
    update_parser.add_argument("--check", action="store_true")
    update_parser.add_argument("--edge", action="store_true", help="follow main instead of stable releases")
    update_parser.add_argument("--version", dest="target_version", help="install one exact release version")
    update_parser.set_defaults(func=cmd_update)

    rollback_parser = sub.add_parser("rollback", help="switch to the previous managed release")
    rollback_parser.add_argument("--restore-state", action="store_true", help="restore the matching pre-update state backup")
    rollback_parser.set_defaults(func=cmd_rollback)

    export_parser = sub.add_parser("export", help="export inspectable state and event history as JSON")
    export_parser.add_argument("--output")
    export_parser.set_defaults(func=cmd_export)

    demo = sub.add_parser("demo", help="open a populated no-token product tour")
    demo.add_argument("--port", type=int, default=8742)
    demo.add_argument("--open", action=argparse.BooleanOptionalAction, default=True)
    demo.set_defaults(func=cmd_demo)

    doctor = sub.add_parser("doctor", help="show local tool availability")
    doctor.add_argument("--json", action="store_true")
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
