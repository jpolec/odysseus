"""Execution environment profiles for host, Docker, and devcontainers."""

from __future__ import annotations

import os
import re
import shutil
import socket
import subprocess
from pathlib import Path
from typing import Any, Mapping, Sequence


VALID_PROFILES = frozenset({"host", "docker", "devcontainer"})
VALID_NETWORKS = frozenset({"bridge", "none"})
ENV_NAME = re.compile(r"^[A-Z_][A-Z0-9_]{0,127}$")
SENSITIVE_ENV_NAME = re.compile(r"(?:TOKEN|SECRET|PASSWORD|PASSWD|API_KEY|CREDENTIAL|COOKIE)", re.I)
MEMORY_LIMIT = re.compile(r"^[1-9][0-9]*(?:[bkmgBKMG])?$")
HOST_INHERITED_ENV_NAMES = frozenset(
    {
        "CI",
        "COLORTERM",
        "DISPLAY",
        "EDITOR",
        "GIT_EDITOR",
        "GIT_PAGER",
        "HOME",
        "LANG",
        "LESS",
        "LOGNAME",
        "NO_COLOR",
        "PAGER",
        "PATH",
        "SHELL",
        "SSH_TTY",
        "TERM",
        "TMP",
        "TMPDIR",
        "TEMP",
        "TZ",
        "USER",
        "VISUAL",
        "XDG_CACHE_HOME",
        "XDG_CONFIG_HOME",
        "XDG_DATA_HOME",
        "XDG_RUNTIME_DIR",
        "XDG_STATE_HOME",
    }
)
HOST_INHERITED_ENV_PREFIXES = ("LC_",)


def _string_list(value: Any, label: str, *, limit: int = 64) -> list[str]:
    raw = value or []
    if not isinstance(raw, list) or not all(isinstance(item, str) for item in raw):
        raise ValueError(f"{label} must be a list of strings")
    return [item.strip() for item in raw[:limit] if item.strip()]


def normalize_environment_request(value: Any) -> dict[str, Any]:
    """Validate an operator/project profile without resolving host secrets."""

    if value in (None, ""):
        return {}
    if isinstance(value, str):
        value = {"profile": value}
    if not isinstance(value, Mapping):
        raise ValueError("environment must be an object or profile name")
    result: dict[str, Any] = {}
    if "profile" in value and str(value.get("profile") or ""):
        profile = str(value["profile"]).strip().lower()
        if profile not in VALID_PROFILES:
            raise ValueError("environment profile must be host, docker, or devcontainer")
        result["profile"] = profile
    if "image" in value and str(value.get("image") or "").strip():
        result["image"] = str(value["image"]).strip()
    if "network" in value and str(value.get("network") or "").strip():
        network = str(value["network"]).strip().lower()
        if network not in VALID_NETWORKS:
            raise ValueError("environment network must be bridge or none")
        result["network"] = network
    raw_env = value.get("env") or {}
    if not isinstance(raw_env, Mapping):
        raise ValueError("environment env must be an object")
    env: dict[str, str] = {}
    for raw_name, raw_value in list(raw_env.items())[:128]:
        name = str(raw_name).strip()
        text = str(raw_value)
        if not ENV_NAME.fullmatch(name):
            raise ValueError(f"invalid environment variable name: {name}")
        if SENSITIVE_ENV_NAME.search(name):
            raise ValueError(f"{name} looks secret; pass its name through allow_env instead of storing its value")
        if "\n" in text or "\r" in text or len(text) > 8_000:
            raise ValueError(f"invalid value for environment variable: {name}")
        env[name] = text
    if env:
        result["env"] = env
    if "allow_env" in value:
        allow_env = _string_list(value.get("allow_env"), "environment allow_env")
        invalid = [name for name in allow_env if not ENV_NAME.fullmatch(name)]
        if invalid:
            raise ValueError(f"invalid allowed environment variable: {invalid[0]}")
        result["allow_env"] = list(dict.fromkeys(allow_env))
    raw_ports = value.get("ports") or {}
    if not isinstance(raw_ports, Mapping):
        raise ValueError("environment ports must map variable names to container ports")
    ports: dict[str, int] = {}
    for raw_name, raw_port in list(raw_ports.items())[:32]:
        name = str(raw_name).strip()
        if not ENV_NAME.fullmatch(name):
            raise ValueError(f"invalid port variable name: {name}")
        try:
            port = int(raw_port)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"invalid container port for {name}") from exc
        if port < 1 or port > 65535:
            raise ValueError(f"container port out of range for {name}")
        ports[name] = port
    if ports:
        result["ports"] = ports
    if "setup" in value:
        result["setup"] = _string_list(value.get("setup"), "environment setup commands", limit=20)
    if "cpus" in value and value.get("cpus") not in (None, "", 0, 0.0):
        try:
            cpus = float(value["cpus"])
        except (TypeError, ValueError) as exc:
            raise ValueError("environment cpus must be numeric") from exc
        if cpus <= 0 or cpus > 64:
            raise ValueError("environment cpus must be between 0 and 64")
        result["cpus"] = cpus
    if "memory" in value and str(value.get("memory") or "").strip():
        memory = str(value["memory"]).strip()
        if not MEMORY_LIMIT.fullmatch(memory):
            raise ValueError("environment memory must look like 512m or 4g")
        result["memory"] = memory.lower()
    return result


def _allocate_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as candidate:
        candidate.bind(("127.0.0.1", 0))
        return int(candidate.getsockname()[1])


def _read_env_file(path: str) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError:
        return values
    for line in lines:
        name, separator, value = line.partition("=")
        if separator and ENV_NAME.fullmatch(name):
            values[name] = value
    return values


def _scoped_process_env(plan: Mapping[str, Any] | None) -> dict[str, str]:
    environment = {
        name: value
        for name, value in os.environ.items()
        if name in HOST_INHERITED_ENV_NAMES or any(name.startswith(prefix) for prefix in HOST_INHERITED_ENV_PREFIXES)
    }
    if plan:
        environment.update(_read_env_file(str(plan.get("env_file") or "")))
        for name in plan.get("credential_env_names") or []:
            value = os.environ.get(str(name))
            if value is not None:
                environment[str(name)] = value
    return environment


class EnvironmentManager:
    """Resolve, prepare, and wrap commands for one run environment."""

    def __init__(self, state_root: Path) -> None:
        self.runtime_root = state_root / "runtime"
        self.runtime_root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def resolve(run: Mapping[str, Any], project_options: Mapping[str, Any]) -> dict[str, Any]:
        project = normalize_environment_request(project_options.get("environment"))
        # A repository may describe non-secret runtime settings, but it may not
        # opt itself into receiving credentials from the operator process.
        project.pop("allow_env", None)
        requested = normalize_environment_request(run.get("environment_request"))
        resolved = {**project, **requested}
        if "env" in project or "env" in requested:
            resolved["env"] = {**project.get("env", {}), **requested.get("env", {})}
        if "ports" in project or "ports" in requested:
            resolved["ports"] = {**project.get("ports", {}), **requested.get("ports", {})}
        resolved.setdefault("profile", "host")
        resolved.setdefault("network", "bridge")
        resolved.setdefault("env", {})
        resolved.setdefault("ports", {})
        resolved.setdefault("setup", [])
        resolved.setdefault("allow_env", [])
        if resolved["profile"] == "docker" and not resolved.get("image"):
            raise ValueError("docker environment requires an image")
        if resolved["profile"] == "docker" and resolved["network"] == "none" and resolved["ports"]:
            raise ValueError("docker network none cannot publish preview ports")
        if resolved["profile"] == "devcontainer" and resolved.get("allow_env"):
            raise ValueError("devcontainer credential passthrough must be configured inside devcontainer.json")
        return resolved

    def prepare(
        self,
        run: Mapping[str, Any],
        worktree: Path,
        project_options: Mapping[str, Any],
        emit: Any,
    ) -> dict[str, Any]:
        resolved = self.resolve(run, project_options)
        profile = str(resolved["profile"])
        if run.get("untrusted_project") and profile != "docker":
            raise ValueError(
                "untrusted projects require the Docker profile; host and repository-defined "
                "devcontainers are not a security boundary"
            )
        if profile == "docker" and not shutil.which("docker"):
            raise ValueError("docker environment selected but Docker is not installed")
        if profile == "devcontainer":
            if not shutil.which("devcontainer"):
                raise ValueError("devcontainer environment selected but the devcontainer CLI is not installed")
            candidates = [worktree / ".devcontainer" / "devcontainer.json", worktree / ".devcontainer.json"]
            if not any(path.is_file() for path in candidates):
                raise ValueError("devcontainer environment selected but no devcontainer.json was found")

        runtime_dir = self.runtime_root / str(run["id"])
        runtime_dir.mkdir(parents=True, exist_ok=True)
        home_dir = runtime_dir / "home"
        home_dir.mkdir(exist_ok=True)
        git_dir = runtime_dir / "git"
        if profile == "docker" and not git_dir.is_dir():
            source = Path(str(run.get("project_path") or ""))
            clone = subprocess.run(
                ["git", "clone", "--bare", "--no-hardlinks", "--", str(source), str(git_dir)],
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=300,
            )
            if clone.returncode != 0:
                raise ValueError(f"cannot prepare isolated Git metadata: {clone.stdout[-8_000:]}")
            branch = str(run.get("branch") or "")
            base = branch or str(run.get("base_sha") or "HEAD")
            if branch:
                head = subprocess.run(
                    ["git", "--git-dir", str(git_dir), "symbolic-ref", "HEAD", f"refs/heads/{branch}"],
                    check=False,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    timeout=30,
                )
                if head.returncode != 0:
                    raise ValueError(f"cannot select isolated task branch: {head.stdout[-8_000:]}")
            index = subprocess.run(
                ["git", "--git-dir", str(git_dir), "read-tree", base],
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=60,
            )
            if index.returncode != 0:
                raise ValueError(f"cannot prepare isolated Git index: {index.stdout[-8_000:]}")
        allocated: dict[str, dict[str, int]] = {}
        env = dict(resolved.get("env") or {})
        for name, container_port in (resolved.get("ports") or {}).items():
            host_port = _allocate_port()
            allocated[name] = {"host": host_port, "container": int(container_port)}
            env[name] = str(container_port if profile == "docker" else host_port)
            env[f"ODYSSEUS_HOST_{name}"] = str(host_port)
        env.update(
            {
                "ODYSSEUS_RUN_ID": str(run["id"]),
                "ODYSSEUS_ENVIRONMENT": profile,
                "ODYSSEUS_WORKTREE": "/workspace" if profile == "docker" else str(worktree),
            }
        )
        if profile == "docker":
            env.update({"GIT_DIR": "/odysseus/git", "GIT_WORK_TREE": "/workspace"})
        env_file = runtime_dir / "environment.env"
        env_file.write_text("".join(f"{name}={value}\n" for name, value in sorted(env.items())), encoding="utf-8")
        os.chmod(env_file, 0o600)
        first_port = next(iter(allocated.values()), None)
        plan = {
            "version": "environment-plan-v1",
            "profile": profile,
            "status": "ready",
            "image": str(resolved.get("image") or ""),
            "network": str(resolved.get("network") or "bridge"),
            "cpus": resolved.get("cpus"),
            "memory": str(resolved.get("memory") or ""),
            "ports": allocated,
            "env_names": sorted(env),
            "credential_env_names": sorted(
                name for name in resolved.get("allow_env") or [] if os.environ.get(name) is not None
            ),
            "missing_credential_env_names": sorted(
                name for name in resolved.get("allow_env") or [] if os.environ.get(name) is None
            ),
            "setup": list(resolved.get("setup") or []),
            "runtime_dir": str(runtime_dir),
            "home_dir": str(home_dir),
            "git_dir": str(git_dir) if profile == "docker" else "",
            "env_file": str(env_file),
            "preview_url": f"http://127.0.0.1:{first_port['host']}/" if first_port else "",
            "isolation": (
                "container filesystem, resources, network mode, and scoped environment"
                if profile == "docker"
                else "repository-defined devcontainer"
                if profile == "devcontainer"
                else "none; host user permissions apply"
            ),
        }
        emit(
            "environment.prepared",
            "odysseus",
            {
                key: plan[key]
                for key in (
                    "version", "profile", "image", "network", "cpus", "memory", "ports",
                    "env_names", "credential_env_names", "missing_credential_env_names", "preview_url", "isolation",
                )
            },
        )
        return plan

    @staticmethod
    def activate(plan: Mapping[str, Any], worktree: Path, emit: Any) -> None:
        if plan.get("profile") != "devcontainer":
            return
        emit("environment.starting", "devcontainer", {"profile": "devcontainer"})
        result = subprocess.run(
            ["devcontainer", "up", "--workspace-folder", str(worktree), "--log-format", "json"],
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=900,
        )
        if result.returncode != 0:
            raise ValueError(f"devcontainer startup failed: {result.stdout[-8_000:]}")
        emit("environment.started", "devcontainer", {"profile": "devcontainer"})


def wrap_command(
    plan: Mapping[str, Any] | None,
    args: Sequence[str],
    worktree: Path,
    *,
    phase: str,
) -> tuple[list[str], Path, dict[str, str] | None]:
    """Return the host command, cwd, and optional process environment."""

    if not plan or plan.get("profile") == "host":
        return list(args), worktree, _scoped_process_env(plan)
    if plan.get("profile") == "devcontainer":
        replaced = [str(value).replace(str(worktree), ".") for value in args]
        command = ["devcontainer", "exec", "--workspace-folder", str(worktree)]
        for name, value in _read_env_file(str(plan.get("env_file") or "")).items():
            command.extend(["--remote-env", f"{name}={value}"])
        command.extend(replaced)
        return command, worktree, _scoped_process_env(plan)

    replaced = [str(value).replace(str(worktree), "/workspace") for value in args]
    readonly = ",readonly" if phase == "review" else ""
    command = [
        "docker", "run", "--rm", "--init", "--read-only", "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges", "--tmpfs", "/tmp:rw,nosuid,nodev,size=512m",
        "--workdir", "/workspace", "--user", f"{os.getuid()}:{os.getgid()}",
        "--mount", f"type=bind,src={worktree},dst=/workspace{readonly}",
        "--mount", f"type=bind,src={plan['home_dir']},dst=/home/odysseus",
        "--mount", f"type=bind,src={plan['git_dir']},dst=/odysseus/git{readonly}",
        "--env", "HOME=/home/odysseus", "--env-file", str(plan["env_file"]),
        "--network", str(plan.get("network") or "bridge"), "--entrypoint", "",
    ]
    if plan.get("cpus"):
        command.extend(["--cpus", str(plan["cpus"])])
    if plan.get("memory"):
        command.extend(["--memory", str(plan["memory"])])
    for mapping in (plan.get("ports") or {}).values():
        command.extend(["--publish", f"127.0.0.1:{mapping['host']}:{mapping['container']}"])
    for name in plan.get("credential_env_names") or []:
        command.extend(["--env", str(name)])
    command.append(str(plan["image"]))
    command.extend(replaced)
    return command, worktree, _scoped_process_env(plan)
