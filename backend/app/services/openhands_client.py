# ==========================================
# Author: Hieu Nguyen - Codev Team
# Email: hieuit095@gmail.com
# Project: ZeroCode - Autonomous Multi-Agent IDE
# ==========================================
"""
OpenHands SDK-backed workspace client.

On Unix-like hosts, this uses the local OpenHands TerminalExecutor directly.
On Windows hosts, this prefers the SDK LocalWorkspace and layers a
compatibility adapter over it so the agents can keep using the Linux-style
``/workspace`` contract exposed by the MCP facade.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import os
import re
import shlex
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from ..config import Settings, get_settings

logger = logging.getLogger(__name__)

_SDK_AVAILABLE = False
_DOCKER_WORKSPACE_AVAILABLE = False
_LOCAL_WORKSPACE_AVAILABLE = False

try:
    from openhands.tools.terminal import (
        TerminalAction,
        TerminalExecutor,
        TerminalObservation,
    )

    _SDK_AVAILABLE = True
except ImportError:
    logger.warning(
        "OpenHands SDK not installed - OpenHandsClient is unavailable. "
        "Install with: pip install openhands-sdk openhands-tools"
    )

try:
    from openhands.workspace import DockerWorkspace

    _DOCKER_WORKSPACE_AVAILABLE = True
except ImportError:
    DockerWorkspace = None  # type: ignore[assignment]

try:
    from openhands.sdk.workspace.local import LocalWorkspace

    _LOCAL_WORKSPACE_AVAILABLE = True
except ImportError:
    LocalWorkspace = None  # type: ignore[assignment]


_EXCLUDED_DIRS: frozenset[str] = frozenset(
    {
        "node_modules",
        ".git",
        "__pycache__",
        ".venv",
        "venv",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
        "dist",
        "build",
        ".next",
        ".nuxt",
        ".turbo",
    }
)


class SandboxUnavailableError(RuntimeError):
    """Raised when the SDK sandbox/runtime cannot be created."""


@dataclass
class _TerminalResult:
    """Minimal observation contract used by the MCP facade."""

    exit_code: int
    text: str
    stdout: str = ""
    stderr: str = ""
    duration_ms: int = 0


class _DockerTerminalAdapter:
    """Expose DockerWorkspace.execute_command() as a TerminalExecutor-like callable."""

    def __init__(self, workspace: "DockerWorkspace") -> None:
        self._workspace = workspace

    def __call__(self, action: "TerminalAction") -> _TerminalResult:
        started = time.perf_counter()
        timeout = float(getattr(action, "timeout", 30.0) or 30.0)
        result = self._workspace.execute_command(
            command=action.command,
            cwd="/workspace",
            timeout=timeout,
        )
        duration_ms = int((time.perf_counter() - started) * 1000)
        combined = result.stdout or ""
        if result.stderr:
            combined = f"{combined}\n{result.stderr}" if combined else result.stderr
        return _TerminalResult(
            exit_code=result.exit_code,
            text=combined,
            stdout=result.stdout,
            stderr=result.stderr,
            duration_ms=duration_ms,
        )


def _jail_path(workspace_root: str, requested_path: str) -> str:
    """
    Resolve *requested_path* against *workspace_root* and verify it stays inside
    the workspace jail.

    AUDIT FIX: Replaced startswith-based check with pathlib.Path.is_relative_to()
    which correctly handles symlinks in both abs_root and the final resolved path.
    Previously, a symlink inside the workspace (e.g. /workspace/link -> /) could
    cause startswith() to silently pass while escaping the jail.
    """
    import pathlib

    if "\x00" in requested_path:
        raise ValueError("Path contains null bytes")

    abs_root = pathlib.Path(workspace_root).resolve()

    if requested_path.startswith("/workspace/"):
        relative = requested_path[len("/workspace/") :]
    elif requested_path == "/workspace":
        relative = "."
    elif requested_path.startswith("/"):
        raise ValueError(
            f"Path traversal blocked: absolute path '{requested_path}' outside workspace"
        )
    else:
        relative = requested_path

    full_path = (abs_root / pathlib.Path(relative)).resolve()

    # is_relative_to() returns False if path is outside abs_root (resolves symlinks)
    if not full_path.is_relative_to(abs_root):
        raise ValueError(
            f"Path traversal blocked: '{requested_path}' escapes workspace jail. "
            f"Resolved to '{full_path}' which is not inside '{abs_root}'"
        )

    return str(full_path)


class _WorkspaceRuntime:
    """Holds the executor backend for a single workspace."""

    __slots__ = (
        "workspace_id",
        "root_dir",
        "terminal",
        "_alive",
        "_executor_root",
        "_docker_workspace",
        "_local_workspace",
    )

    def __init__(self, workspace_id: str, root_dir: str) -> None:
        if not _SDK_AVAILABLE:
            raise SandboxUnavailableError(
                "OpenHands SDK is not installed. Install with: "
                "pip install openhands-sdk openhands-tools"
            )

        self.workspace_id = workspace_id
        self.root_dir = os.path.realpath(root_dir)
        self._executor_root = self.root_dir
        self._docker_workspace: DockerWorkspace | None = None
        self._local_workspace: LocalWorkspace | None = None

        if os.name == "nt":
            if not _LOCAL_WORKSPACE_AVAILABLE or LocalWorkspace is None:
                if not _DOCKER_WORKSPACE_AVAILABLE or DockerWorkspace is None:
                    raise SandboxUnavailableError(
                        "No usable OpenHands workspace backend is available on Windows. "
                        "Install openhands-workspace or ensure the SDK LocalWorkspace is available."
                    )

                self._docker_workspace = DockerWorkspace(
                    volumes=[f"{self.root_dir}:/workspace"],
                    detach_logs=False,
                )
                self._executor_root = "/workspace"
                self.terminal = _DockerTerminalAdapter(self._docker_workspace)
            else:
                self._local_workspace = LocalWorkspace(working_dir=self.root_dir)
                self.terminal = None
        else:
            self.terminal = TerminalExecutor(working_dir=self.root_dir)

        self._alive = True
        logger.info(
            "Workspace runtime created: %s (root=%s, executor_root=%s, docker=%s, local=%s)",
            self.workspace_id,
            self.root_dir,
            self._executor_root,
            self._docker_workspace is not None,
            self._local_workspace is not None,
        )

    def _executor_path(self, requested_path: str) -> str:
        """Translate a jailed host path to the executor-visible path."""
        safe_host_path = _jail_path(self.root_dir, requested_path)
        if self._docker_workspace is None:
            return safe_host_path

        rel = os.path.relpath(safe_host_path, self.root_dir).replace("\\", "/")
        if rel in (".", ""):
            return self._executor_root
        return f"{self._executor_root}/{rel}"

    def execute_terminal(
        self,
        command: str,
        cwd: str | None = None,
    ) -> "_TerminalResult | TerminalObservation":
        """Run a shell command through the active OpenHands runtime."""
        if not self._alive:
            raise SandboxUnavailableError("Workspace runtime has been destroyed")

        if self._local_workspace is not None:
            safe_cwd = _jail_path(self.root_dir, cwd or "/workspace")
            translated_command = command
            if os.name == "nt":
                translated_command = _translate_windows_local_command(
                    command=command,
                    workspace_root=self.root_dir,
                    cwd=safe_cwd,
                )
            started = time.perf_counter()
            result = self._local_workspace.execute_command(
                command=translated_command,
                cwd=safe_cwd,
                timeout=30.0,
            )
            duration_ms = int((time.perf_counter() - started) * 1000)
            combined = result.stdout or ""
            if result.stderr:
                combined = f"{combined}\n{result.stderr}" if combined else result.stderr
            return _TerminalResult(
                exit_code=result.exit_code,
                text=combined,
                stdout=result.stdout,
                stderr=result.stderr,
                duration_ms=duration_ms,
            )

        executor_cwd = self._executor_path(cwd or "/workspace")
        action = TerminalAction(command=f"cd {_shell_quote(executor_cwd)} && {command}")
        return self.terminal(action)

    def read_file(self, path: str) -> str:
        """Read a file through the OpenHands executor."""
        if not self._alive:
            raise SandboxUnavailableError("Workspace runtime has been destroyed")

        if self._local_workspace is not None:
            safe_host_path = _jail_path(self.root_dir, path)
            script = (
                f"$ErrorActionPreference = 'Stop'; "
                f"if (-not (Test-Path {_powershell_quote(safe_host_path)} -PathType Leaf)) "
                "{ exit 1 }; "
                f"Get-Content -Raw -Path {_powershell_quote(safe_host_path)}"
            )
            obs = self._run_local_powershell(script, cwd=self.root_dir)
            if obs.exit_code != 0:
                raise FileNotFoundError(f"File not found or unreadable: {path}")
            return obs.text

        executor_path = self._executor_path(path)
        obs = self.terminal(TerminalAction(command=f"cat {_shell_quote(executor_path)}"))
        if obs.exit_code != 0:
            raise FileNotFoundError(f"File not found or unreadable: {path}")
        return obs.text

    def write_file(self, path: str, content: str) -> str:
        """Write a file through the OpenHands executor using a base64 pipeline."""
        if not self._alive:
            raise SandboxUnavailableError("Workspace runtime has been destroyed")

        if self._local_workspace is not None:
            safe_host_path = _jail_path(self.root_dir, path)
            parent_dir = str(Path(safe_host_path).parent)
            encoded = base64.b64encode(content.encode("utf-8")).decode("ascii")
            script = (
                "$ErrorActionPreference = 'Stop'; "
                f"New-Item -ItemType Directory -Force -Path {_powershell_quote(parent_dir)} | Out-Null; "
                f"$content = [System.Text.Encoding]::UTF8.GetString([System.Convert]::FromBase64String('{encoded}')); "
                f"[System.IO.File]::WriteAllText({_powershell_quote(safe_host_path)}, $content, [System.Text.Encoding]::UTF8)"
            )
            obs = self._run_local_powershell(script, cwd=self.root_dir)
            if obs.exit_code != 0:
                return f"Write failed: {obs.text}"
            return "File written successfully."

        executor_path = self._executor_path(path)
        parent_dir = os.path.dirname(executor_path)
        self.terminal(TerminalAction(command=f"mkdir -p {_shell_quote(parent_dir)}"))

        b64 = base64.b64encode(content.encode("utf-8")).decode("ascii")
        cmd = f"echo {_shell_quote(b64)} | base64 -d > {_shell_quote(executor_path)}"
        obs = self.terminal(TerminalAction(command=cmd))
        if obs.exit_code != 0:
            return f"Write failed: {obs.text}"
        return "File written successfully."

    def list_tree(self, max_depth: int = 5) -> list[dict[str, Any]]:
        """List the workspace tree via the OpenHands executor."""
        if not self._alive:
            raise SandboxUnavailableError("Workspace runtime has been destroyed")

        if self._local_workspace is not None:
            entries: list[dict[str, Any]] = []
            root_path = Path(self.root_dir)
            for current_root, dirnames, filenames in os.walk(root_path):
                rel_dir = os.path.relpath(current_root, self.root_dir)
                depth = 0 if rel_dir == "." else rel_dir.count(os.sep) + 1
                dirnames[:] = [
                    name
                    for name in dirnames
                    if name not in _EXCLUDED_DIRS and not name.startswith(".")
                ]
                if depth > max_depth:
                    dirnames[:] = []
                    continue

                for dirname in dirnames:
                    rel = os.path.relpath(os.path.join(current_root, dirname), self.root_dir).replace("\\", "/")
                    entries.append(
                        {
                            "id": f"/workspace/{rel}",
                            "name": dirname,
                            "type": "folder",
                            "path": f"/workspace/{rel}",
                        }
                    )

                for filename in filenames:
                    if filename.startswith("."):
                        continue
                    rel = os.path.relpath(os.path.join(current_root, filename), self.root_dir).replace("\\", "/")
                    entries.append(
                        {
                            "id": f"/workspace/{rel}",
                            "name": filename,
                            "type": "file",
                            "path": f"/workspace/{rel}",
                        }
                    )
            return entries

        excludes = " ".join(
            f"-not -path '*/{d}' -not -path '*/{d}/*'"
            for d in sorted(_EXCLUDED_DIRS)
        )

        cmd = (
            f"find {_shell_quote(self._executor_root)} "
            f"-maxdepth {max_depth} "
            f"-not -name '.*' {excludes} "
            f"-printf '%y %P\\n' 2>/dev/null || true"
        )
        obs = self.terminal(TerminalAction(command=cmd))

        entries: list[dict[str, Any]] = []
        for line in obs.text.strip().splitlines():
            if not line or len(line) < 3:
                continue
            kind = line[0]
            rel = line[2:]
            if not rel:
                continue

            virtual_path = f"/workspace/{rel}"
            entries.append(
                {
                    "id": virtual_path,
                    "name": os.path.basename(rel),
                    "type": "folder" if kind == "d" else "file",
                    "path": virtual_path,
                }
            )

        return entries

    def destroy(self) -> None:
        """Tear down the runtime."""
        if not self._alive:
            return

        self._alive = False
        try:
            if self._docker_workspace is not None:
                # P1-J FIX: wrap Docker cleanup with asyncio.wait_for timeout=30s
                # so a hung container cannot become a zombie.
                try:
                    asyncio.wait_for(
                        asyncio.to_thread(self._docker_workspace.cleanup),
                        timeout=30.0,
                    )
                except asyncio.TimeoutError:
                    logger.critical(
                        "Docker container cleanup timed out after 30s for runtime %s — force-killing",
                        self.workspace_id,
                    )
                    raise SystemError(
                        f"Docker container cleanup timeout for workspace {self.workspace_id}"
                    )
            elif self._local_workspace is not None:
                pass
            else:
                close = getattr(self.terminal, "close", None)
                if callable(close):
                    close()
        except Exception:
            logger.warning(
                "Failed to destroy workspace runtime %s",
                self.workspace_id,
                exc_info=True,
            )

        logger.info("Workspace runtime destroyed: %s", self.workspace_id)

    def _run_local_powershell(self, script: str, cwd: str) -> _TerminalResult:
        """Execute a PowerShell script through LocalWorkspace."""
        if self._local_workspace is None:
            raise SandboxUnavailableError("Local workspace backend is not active")

        wrapped = (
            "powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass "
            f"-Command \"{script}\""
        )
        started = time.perf_counter()
        result = self._local_workspace.execute_command(
            command=wrapped,
            cwd=cwd,
            timeout=30.0,
        )
        duration_ms = int((time.perf_counter() - started) * 1000)
        combined = result.stdout or ""
        if result.stderr:
            combined = f"{combined}\n{result.stderr}" if combined else result.stderr
        return _TerminalResult(
            exit_code=result.exit_code,
            text=combined,
            stdout=result.stdout,
            stderr=result.stderr,
            duration_ms=duration_ms,
        )


def _shell_quote(value: str) -> str:
    """Single-quote a string for safe shell interpolation."""
    return "'" + value.replace("'", "'\\''") + "'"


def _powershell_quote(value: str) -> str:
    """Single-quote a string for safe PowerShell interpolation."""
    return "'" + value.replace("'", "''") + "'"


def _workspace_path_to_host(workspace_root: str, value: str) -> str:
    """Translate a conceptual /workspace path into a jailed host path."""
    if value == "/workspace" or value.startswith("/workspace/"):
        return _jail_path(workspace_root, value)
    return value


def _powershell_join_native(command: str, args: list[str]) -> str:
    """Build a native-command invocation for PowerShell."""
    parts = [command]
    for arg in args:
        if re.fullmatch(r"-?[A-Za-z0-9_./:=+]+", arg):
            parts.append(arg)
        else:
            parts.append(_powershell_quote(arg))
    return " ".join(parts)


def _split_posix_command_chain(command: str) -> list[str]:
    """Split a simple POSIX command chain on && outside of quotes."""
    segments: list[str] = []
    current: list[str] = []
    quote: str | None = None
    index = 0

    while index < len(command):
        char = command[index]
        if quote is None and char in {"'", '"'}:
            quote = char
            current.append(char)
            index += 1
            continue
        if quote is not None and char == quote:
            quote = None
            current.append(char)
            index += 1
            continue
        if quote is None and command[index : index + 2] == "&&":
            segments.append("".join(current).strip())
            current = []
            index += 2
            continue
        current.append(char)
        index += 1

    tail = "".join(current).strip()
    if tail:
        segments.append(tail)
    return segments


def _split_top_level_operator(
    command: str,
    operator: str,
) -> tuple[str, str] | None:
    """Split a command once on a top-level shell operator outside of quotes."""
    quote: str | None = None
    index = 0

    while index < len(command):
        char = command[index]
        if quote is None and char in {"'", '"'}:
            quote = char
            index += 1
            continue
        if quote is not None and char == quote:
            quote = None
            index += 1
            continue
        if quote is None and command[index : index + len(operator)] == operator:
            left = command[:index].strip()
            right = command[index + len(operator) :].strip()
            if left and right:
                return left, right
            return None
        index += 1

    return None


def _is_interactive_python_invocation(command: str, args: list[str]) -> bool:
    """Detect Python invocations that would open an interactive shell."""
    if command not in {"python", "python3", "py"}:
        return False
    if not args:
        return True
    if any(arg in {"-i", "--interactive"} for arg in args):
        return True

    for arg in args:
        if arg in {"-c", "-m", "-"}:
            return False
        if arg.startswith("-"):
            continue
        return False
    return True


def _translate_windows_local_segment(
    segment: str,
    workspace_root: str,
    cwd: str,
) -> str:
    """Translate a simple POSIX-style command segment into PowerShell."""
    try:
        tokens = shlex.split(segment, posix=True)
    except ValueError:
        return segment.replace("/workspace", workspace_root.replace("\\", "\\\\"))

    if not tokens:
        return "$null"

    command = tokens[0]
    translated_args = [
        _workspace_path_to_host(workspace_root, token)
        for token in tokens[1:]
    ]

    if _is_interactive_python_invocation(command, tokens[1:]):
        return (
            "[Console]::Error.WriteLine("
            "'Interactive Python shells are not supported in this sandbox. "
            "Use python -c, python -m <module>, or python <script>.'); "
            "exit 2"
        )

    if command == "pwd":
        return "Get-Location"

    if command == "ls":
        flags = [token for token in tokens[1:] if token.startswith("-")]
        targets = [
            _workspace_path_to_host(workspace_root, token)
            for token in tokens[1:]
            if not token.startswith("-")
        ]
        if not targets:
            targets = [cwd]
        parts = ["Get-ChildItem"]
        if any("a" in flag for flag in flags):
            parts.append("-Force")
        parts.append("-Path")
        parts.extend(_powershell_quote(target) for target in targets)
        return " ".join(parts)

    if command == "cat":
        if not translated_args:
            return "Get-Content"
        return "Get-Content " + " ".join(_powershell_quote(arg) for arg in translated_args)

    if command == "mkdir" and len(tokens) >= 2 and tokens[1] == "-p":
        paths = [
            _workspace_path_to_host(workspace_root, token)
            for token in tokens[2:]
        ]
        if not paths:
            return "$null"
        return "; ".join(
            f"New-Item -ItemType Directory -Force -Path {_powershell_quote(path)} | Out-Null"
            for path in paths
        )

    if command == "rm":
        flags = "".join(
            token.lstrip("-")
            for token in tokens[1:]
            if token.startswith("-")
        )
        paths = [
            _workspace_path_to_host(workspace_root, token)
            for token in tokens[1:]
            if not token.startswith("-")
        ]
        if not paths:
            return "$null"
        if "r" in flags.lower():
            return "; ".join(
                f"if (Test-Path {_powershell_quote(path)}) {{ Remove-Item -Recurse -Force {_powershell_quote(path)} }}"
                for path in paths
            )
        return "; ".join(
            f"if (Test-Path {_powershell_quote(path)}) {{ Remove-Item -Force {_powershell_quote(path)} }}"
            for path in paths
        )

    if command == "test" and len(tokens) == 3 and tokens[1] == "-f":
        return (
            f"if (Test-Path {_powershell_quote(_workspace_path_to_host(workspace_root, tokens[2]))} "
            "-PathType Leaf) { exit 0 } else { exit 1 }"
        )

    if command == "pytest":
        return _powershell_join_native("python", ["-m", "pytest", *translated_args])

    return _powershell_join_native(command, translated_args)


def _translate_windows_local_command(
    command: str,
    workspace_root: str,
    cwd: str,
) -> str:
    """Wrap a Linux-style workspace command in a PowerShell-compatible adapter."""
    or_chain = None
    if "&&" not in command and "||" in command:
        or_chain = _split_top_level_operator(command, "||")
    if or_chain is not None:
        left_segment = _translate_windows_local_segment(
            or_chain[0],
            workspace_root,
            cwd,
        )
        right_segment = _translate_windows_local_segment(
            or_chain[1],
            workspace_root,
            cwd,
        )
        script_parts = [
            "$ErrorActionPreference = 'Stop'",
            "$env:PYTHON_BASIC_REPL = '1'",
            "$global:LASTEXITCODE = 0",
            left_segment,
            "if (-not $?) { $__zcExit = 1 } else { $__zcExit = $LASTEXITCODE }",
            "if ($__zcExit -eq 0) { exit 0 }",
            "$global:LASTEXITCODE = 0",
            right_segment,
            "if (-not $?) { exit 1 }",
            "if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }",
        ]
        script = "; ".join(script_parts)
        return (
            "powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass "
            f"-Command \"{script}\""
        )

    segments = _split_posix_command_chain(command)
    if not segments:
        return command

    translated_segments = [
        _translate_windows_local_segment(segment, workspace_root, cwd)
        for segment in segments
    ]

    script_parts = ["$ErrorActionPreference = 'Stop'", "$env:PYTHON_BASIC_REPL = '1'"]
    for segment in translated_segments:
        script_parts.append("$global:LASTEXITCODE = 0")
        script_parts.append(segment)
        script_parts.append("if (-not $?) { exit 1 }")
        script_parts.append("if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }")

    script = "; ".join(script_parts)
    return (
        "powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass "
        f"-Command \"{script}\""
    )


class OpenHandsClient:
    """Workspace client that exposes SDK-backed read/write/exec helpers."""

    def __init__(self, settings: Settings) -> None:
        self._workspace_base = settings.workspace_path
        self._runtimes: dict[str, _WorkspaceRuntime] = {}

    def create_workspace(self, workspace_id: str) -> _WorkspaceRuntime:
        workspace_dir = self._workspace_base / workspace_id
        workspace_dir.mkdir(parents=True, exist_ok=True)

        runtime = _WorkspaceRuntime(workspace_id, str(workspace_dir))
        self._runtimes[workspace_id] = runtime
        return runtime

    def destroy_workspace(self, workspace_id: str) -> None:
        runtime = self._runtimes.pop(workspace_id, None)
        if runtime is not None:
            runtime.destroy()

    def get_runtime(self, workspace_id: str) -> _WorkspaceRuntime:
        if workspace_id not in self._runtimes:
            self.create_workspace(workspace_id)
        return self._runtimes[workspace_id]

    async def execute_action(self, workspace_id: str, action: Any) -> Any:
        if not _SDK_AVAILABLE:
            raise SandboxUnavailableError(
                "OpenHands SDK is not installed. Install with: "
                "pip install openhands-sdk openhands-tools"
            )

        runtime = self.get_runtime(workspace_id)

        if isinstance(action, TerminalAction):
            return await asyncio.to_thread(runtime.execute_terminal, action.command)

        raise TypeError(
            f"Unsupported action type: {type(action).__name__}. "
            f"Use TerminalAction for command execution."
        )

    async def list_tree(
        self,
        workspace_id: str,
        max_depth: int = 5,
    ) -> list[dict[str, Any]]:
        runtime = self.get_runtime(workspace_id)
        return await asyncio.to_thread(runtime.list_tree, max_depth)

    async def read_file(self, workspace_id: str, path: str) -> str:
        runtime = self.get_runtime(workspace_id)
        try:
            return await asyncio.to_thread(runtime.read_file, path)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc))


_client: OpenHandsClient | None = None


def get_openhands_client() -> OpenHandsClient:
    global _client
    if _client is None:
        _client = OpenHandsClient(settings=get_settings())
    return _client


WorkspaceFS = OpenHandsClient
get_workspace_fs = get_openhands_client
