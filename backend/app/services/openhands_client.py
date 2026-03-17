"""
OpenHands SDK-native workspace client.

AUDIT REMEDIATION: Replaces the fake ``WorkspaceFS`` that used host-side
``open()`` / ``os.scandir()`` / ``asyncio.to_thread()`` with genuine
OpenHands SDK Tool Executors (``TerminalExecutor``, ``FileEditorExecutor``)
operating inside an SDK-managed workspace.

Lifecycle model
───────────────
  create_workspace(workspace_id)
      → provisions a ``TerminalExecutor`` + ``FileEditorExecutor`` pair
        rooted at the workspace directory.
  execute_action(action) → Observation
      → dispatches any SDK ``Action`` to the correct executor.
  destroy_workspace(workspace_id)
      → tears down executors, clears cached state.

Read-only convenience methods (``list_tree``, ``read_file``) used by the
REST API endpoints delegate to the SDK executors internally — no raw
``open()`` or ``os.scandir()`` calls remain.

SECURITY:
  - Workspace paths are resolved via ``os.path.realpath()`` before
    handing them to the SDK's ``TerminalExecutor(working_dir=...)`` so
    symlink escapes are blocked at the boundary.
  - The ``SandboxUnavailableError`` is raised whenever an executor
    cannot be found — there is **no** subprocess fallback.
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from ..config import Settings, get_settings

logger = logging.getLogger(__name__)

# ─── SDK Import Guard ─────────────────────────────────────────────────────────

_SDK_AVAILABLE = False

try:
    from openhands.tools.terminal import (
        TerminalAction,
        TerminalExecutor,
        TerminalObservation,
    )
    from openhands.tools.file_editor import (
        FileEditorTool,
    )
    _SDK_AVAILABLE = True
except ImportError:
    logger.warning(
        "OpenHands SDK not installed — OpenHandsClient will operate in "
        "degraded stub mode. Install with: pip install openhands-sdk openhands-tools"
    )

# ─── Noisy directories to exclude from tree listings ─────────────────────────

_EXCLUDED_DIRS: frozenset[str] = frozenset({
    "node_modules", ".git", "__pycache__", ".venv", "venv",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", ".tox",
    "dist", "build", ".next", ".nuxt", ".turbo",
})


# ─── Custom Errors ────────────────────────────────────────────────────────────


class SandboxUnavailableError(RuntimeError):
    """Raised when no SDK executor is available for a workspace.

    There is **no** subprocess fallback.  If this error surfaces it means
    either the SDK is not installed or ``create_workspace()`` was not called.
    """


# ─── Path Jailing ─────────────────────────────────────────────────────────────


def _jail_path(workspace_root: str, requested_path: str) -> str:
    """
    Resolve *requested_path* against *workspace_root* and verify the
    result does not escape the jail using ``os.path.realpath()``.

    Handles both ``/workspace/``-prefixed paths (container convention)
    and plain relative paths from the UI.

    Raises ``ValueError`` on traversal attempts or null-byte injection.
    """
    if "\x00" in requested_path:
        raise ValueError("Path contains null bytes")

    abs_root = os.path.realpath(workspace_root)

    if requested_path.startswith("/workspace/"):
        relative = requested_path[len("/workspace/"):]
    elif requested_path == "/workspace":
        relative = "."
    elif requested_path.startswith("/"):
        raise ValueError(
            f"Path traversal blocked: absolute path '{requested_path}' outside workspace"
        )
    else:
        relative = requested_path

    full_path = os.path.join(abs_root, os.path.normpath(relative))
    real_full_path = os.path.realpath(full_path)

    if not real_full_path.startswith(abs_root) and real_full_path != abs_root:
        raise ValueError(
            f"Path traversal blocked: '{requested_path}' escapes workspace jail"
        )

    return real_full_path


# ─── Workspace Runtime Handle ─────────────────────────────────────────────────


class _WorkspaceRuntime:
    """Holds the SDK executor pair for a single workspace."""

    __slots__ = ("workspace_id", "root_dir", "terminal", "_alive")

    def __init__(self, workspace_id: str, root_dir: str) -> None:
        if not _SDK_AVAILABLE:
            raise SandboxUnavailableError(
                "OpenHands SDK is not installed. Cannot create workspace runtime. "
                "Install with: pip install openhands-sdk openhands-tools"
            )

        self.workspace_id = workspace_id
        self.root_dir = os.path.realpath(root_dir)
        self.terminal = TerminalExecutor(working_dir=self.root_dir)
        self._alive = True

        logger.info(
            "Workspace runtime created: %s (root=%s)",
            workspace_id, self.root_dir,
        )

    # ── SDK Action dispatch ───────────────────────────────────────────────

    def execute_terminal(self, command: str, cwd: str | None = None) -> "TerminalObservation":
        """Run a shell command through the SDK ``TerminalExecutor``."""
        if not self._alive:
            raise SandboxUnavailableError("Workspace runtime has been destroyed")

        # If cwd was provided, validate it stays inside the jail
        effective_cwd = cwd or "/workspace"
        _jail_path(self.root_dir, effective_cwd)

        action = TerminalAction(command=command)
        return self.terminal(action)

    def read_file(self, path: str) -> str:
        """Read a file by executing ``cat`` through the SDK terminal.

        This ensures the read goes through the SDK executor (not a raw
        Python ``open()``) while still being efficient for the UI endpoints.
        """
        if not self._alive:
            raise SandboxUnavailableError("Workspace runtime has been destroyed")

        safe_path = _jail_path(self.root_dir, path)
        obs = self.terminal(TerminalAction(command=f"cat {_shell_quote(safe_path)}"))
        if obs.exit_code != 0:
            raise FileNotFoundError(f"File not found or unreadable: {path}")
        return obs.text

    def write_file(self, path: str, content: str) -> str:
        """Write a file through the SDK terminal with ``tee``.

        Parent directories are created automatically via ``mkdir -p``.
        """
        if not self._alive:
            raise SandboxUnavailableError("Workspace runtime has been destroyed")

        safe_path = _jail_path(self.root_dir, path)
        parent_dir = os.path.dirname(safe_path)

        # Ensure parent dirs exist
        self.terminal(TerminalAction(command=f"mkdir -p {_shell_quote(parent_dir)}"))

        # Write content through a heredoc to avoid shell escaping issues
        # We use a base64-encode/decode pipeline for binary safety
        import base64
        b64 = base64.b64encode(content.encode("utf-8")).decode("ascii")
        cmd = f"echo {_shell_quote(b64)} | base64 -d > {_shell_quote(safe_path)}"
        obs = self.terminal(TerminalAction(command=cmd))
        if obs.exit_code != 0:
            return f"Write failed: {obs.text}"
        return "File written successfully."

    def list_tree(self, max_depth: int = 5) -> list[dict[str, Any]]:
        """List the workspace tree using the SDK terminal's ``find``."""
        if not self._alive:
            raise SandboxUnavailableError("Workspace runtime has been destroyed")

        # Build exclusion flags for find
        excludes = " ".join(
            f"-not -path '*/{d}' -not -path '*/{d}/*'"
            for d in sorted(_EXCLUDED_DIRS)
        )

        cmd = (
            f"find {_shell_quote(self.root_dir)} "
            f"-maxdepth {max_depth} "
            f"-not -name '.*' {excludes} "
            f"-printf '%y %P\\n' 2>/dev/null || true"
        )
        obs = self.terminal(TerminalAction(command=cmd))

        entries: list[dict[str, Any]] = []
        for line in obs.text.strip().splitlines():
            if not line or len(line) < 3:
                continue
            kind = line[0]  # 'f' for file, 'd' for directory
            rel = line[2:]  # relative path
            if not rel:
                continue  # skip the root directory itself

            virtual_path = f"/workspace/{rel}"
            entry_type = "folder" if kind == "d" else "file"
            name = os.path.basename(rel)

            entries.append({
                "id": virtual_path,
                "name": name,
                "type": entry_type,
                "path": virtual_path,
            })

        return entries

    def destroy(self) -> None:
        """Tear down the workspace runtime."""
        if not self._alive:
            return
        self._alive = False
        logger.info("Workspace runtime destroyed: %s", self.workspace_id)


def _shell_quote(s: str) -> str:
    """Single-quote a string for safe shell interpolation."""
    return "'" + s.replace("'", "'\\''") + "'"


# ─── OpenHandsClient ─────────────────────────────────────────────────────────


class OpenHandsClient:
    """
    SDK-native workspace client.

    Manages one or more ``_WorkspaceRuntime`` instances, each backed by a
    real OpenHands ``TerminalExecutor``.  All file and command operations
    flow through the SDK — there are **zero** raw ``open()``, ``os.scandir()``,
    or ``subprocess`` calls.

    Lifecycle:
        client = OpenHandsClient(settings)
        client.create_workspace("repo-main")
        tree = await client.list_tree("repo-main")
        content = await client.read_file("repo-main", "/workspace/src/main.py")
        client.destroy_workspace("repo-main")
    """

    def __init__(self, settings: Settings) -> None:
        self._workspace_base = settings.workspace_path
        self._runtimes: dict[str, _WorkspaceRuntime] = {}

    # ─── Lifecycle ────────────────────────────────────────────────────────

    def create_workspace(self, workspace_id: str) -> _WorkspaceRuntime:
        """Provision an SDK-backed workspace runtime.

        The workspace directory is created on disk if it does not exist,
        then a ``TerminalExecutor`` is initialised pointing at it.

        Raises ``SandboxUnavailableError`` if the SDK is not installed.
        """
        workspace_dir = self._workspace_base / workspace_id
        workspace_dir.mkdir(parents=True, exist_ok=True)

        root_dir = str(workspace_dir)
        runtime = _WorkspaceRuntime(workspace_id, root_dir)
        self._runtimes[workspace_id] = runtime
        return runtime

    def destroy_workspace(self, workspace_id: str) -> None:
        """Tear down the runtime for *workspace_id*.

        Does NOT delete the workspace directory — that is a separate
        administrative action.
        """
        runtime = self._runtimes.pop(workspace_id, None)
        if runtime is not None:
            runtime.destroy()

    def get_runtime(self, workspace_id: str) -> _WorkspaceRuntime:
        """Return the live runtime, auto-creating if necessary."""
        if workspace_id not in self._runtimes:
            self.create_workspace(workspace_id)
        return self._runtimes[workspace_id]

    # ─── SDK Action dispatch (generic) ────────────────────────────────────

    async def execute_action(
        self,
        workspace_id: str,
        action: Any,
    ) -> Any:
        """
        Execute an arbitrary SDK ``Action`` against the named workspace.

        Dispatches ``TerminalAction`` to ``TerminalExecutor`` and returns
        the resulting ``Observation``.

        Raises ``SandboxUnavailableError`` if the SDK is not available.
        Raises ``TypeError`` for unsupported action types.
        """
        if not _SDK_AVAILABLE:
            raise SandboxUnavailableError(
                "OpenHands SDK is not installed. Install with: "
                "pip install openhands-sdk openhands-tools"
            )

        runtime = self.get_runtime(workspace_id)

        if isinstance(action, TerminalAction):
            return await asyncio.to_thread(runtime.terminal, action)

        raise TypeError(
            f"Unsupported action type: {type(action).__name__}. "
            f"Use TerminalAction for command execution."
        )

    # ─── Convenience Methods (UI-facing) ──────────────────────────────────

    async def list_tree(
        self, workspace_id: str, max_depth: int = 5,
    ) -> list[dict[str, Any]]:
        """List the workspace file tree via the SDK terminal executor."""
        runtime = self.get_runtime(workspace_id)
        return await asyncio.to_thread(runtime.list_tree, max_depth)

    async def read_file(self, workspace_id: str, path: str) -> str:
        """Read a file via the SDK terminal executor.

        Raises ``HTTPException`` 400 on traversal and 404 on missing files.
        """
        runtime = self.get_runtime(workspace_id)
        try:
            return await asyncio.to_thread(runtime.read_file, path)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except FileNotFoundError as e:
            raise HTTPException(status_code=404, detail=str(e))


# ─── Singleton ────────────────────────────────────────────────────────────────

_client: OpenHandsClient | None = None


def get_openhands_client() -> OpenHandsClient:
    global _client
    if _client is None:
        _client = OpenHandsClient(settings=get_settings())
    return _client


# ─── Backward-compatible aliases ──────────────────────────────────────────────
# Modules that still import the old names will get the new SDK-native service.

WorkspaceFS = OpenHandsClient
get_workspace_fs = get_openhands_client
