"""
Read-only workspace filesystem service for UI endpoints.

PHASE 1 REFACTOR: This module replaces the old OpenHandsClient that spawned
competing LocalRuntime instances. The UI only needs read-only access to the
host-side workspace directory — it does NOT need a full SDK Runtime.

All agent-side sandbox operations (write_file, exec, etc.) are handled
exclusively by the worker-spawned Conversation/Runtime in the agent modules
(dev_agent.py, qa_agent.py). This eliminates the redundant-runtime problem.

SECURITY:
  - All paths are jail-validated using os.path.realpath() to prevent
    symlink escapes and directory traversal (same pattern as mcp_tools._jail_path).
  - Only read operations are exposed. No writes, no command execution.
  - The frontend NEVER touches OpenHands directly (Rule 1 preserved).
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

# ─── Noisy directories to exclude from tree listings ─────────────────────────

_EXCLUDED_DIRS: set[str] = {
    "node_modules", ".git", "__pycache__", ".venv", "venv",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", ".tox",
    "dist", "build", ".next", ".nuxt", ".turbo",
}


# ─── Path Jailing ─────────────────────────────────────────────────────────────


def _jail_path(workspace_root: str, requested_path: str) -> str:
    """
    Resolve a user-supplied path against workspace_root and verify
    the result doesn't escape the jail using os.path.realpath().

    Handles both /workspace/-prefixed paths (container convention) and
    plain relative paths from the UI.

    Raises ValueError on traversal attempts or null-byte injection.
    """
    if "\x00" in requested_path:
        raise ValueError("Path contains null bytes")

    abs_root = os.path.realpath(workspace_root)

    # Normalize requested path against the conceptual "/workspace" container root
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

    # Join and resolve real path on the host
    full_path = os.path.join(abs_root, os.path.normpath(relative))
    real_full_path = os.path.realpath(full_path)

    # Ensure the resolved path remains within the workspace root
    if not real_full_path.startswith(abs_root) and real_full_path != abs_root:
        raise ValueError(
            f"Path traversal blocked: '{requested_path}' escapes workspace jail"
        )

    return real_full_path


# ─── WorkspaceFS Service ─────────────────────────────────────────────────────


class WorkspaceFS:
    """
    Read-only filesystem service for serving workspace content to the UI.

    Does NOT spawn any OpenHands Runtime. All operations use the host
    filesystem anchored to the configured WORKSPACE_ROOT, with path-jail
    validation on every access.
    """

    def __init__(self, settings: Settings) -> None:
        self._workspace_base = settings.workspace_path

    def _resolve_workspace_dir(self, workspace_id: str) -> Path:
        """Return the host-side directory for a workspace, or raise 404."""
        workspace_dir = self._workspace_base / workspace_id
        if not workspace_dir.is_dir():
            raise HTTPException(
                status_code=404,
                detail=f"Workspace '{workspace_id}' not found.",
            )
        return workspace_dir

    # ─── File Tree ────────────────────────────────────────────────────────

    async def list_tree(
        self, workspace_id: str, max_depth: int = 5,
    ) -> list[dict[str, Any]]:
        """
        List the workspace file tree by walking the host directory.

        Returns a flat list of dicts with keys: id, name, type, path.
        Excludes noisy directories (node_modules, .git, __pycache__, etc.).
        Uses asyncio.to_thread to avoid blocking the event loop.
        """
        workspace_dir = self._resolve_workspace_dir(workspace_id)
        return await asyncio.to_thread(
            self._walk_tree_sync, str(workspace_dir), max_depth,
        )

    @staticmethod
    def _walk_tree_sync(
        root: str, max_depth: int,
    ) -> list[dict[str, Any]]:
        """Synchronous recursive directory walker (run in thread pool)."""
        entries: list[dict[str, Any]] = []
        abs_root = os.path.realpath(root)

        def _scan(directory: str, depth: int) -> None:
            if depth > max_depth:
                return
            try:
                with os.scandir(directory) as scanner:
                    for entry in sorted(scanner, key=lambda e: e.name):
                        # Skip hidden files/dirs
                        if entry.name.startswith("."):
                            continue
                        # Skip noisy directories
                        if entry.is_dir(follow_symlinks=False) and entry.name in _EXCLUDED_DIRS:
                            continue

                        # Build a /workspace-relative path for the frontend
                        rel = os.path.relpath(entry.path, abs_root)
                        virtual_path = f"/workspace/{rel}".replace("\\", "/")

                        entry_type = "folder" if entry.is_dir(follow_symlinks=False) else "file"
                        entries.append({
                            "id": virtual_path,
                            "name": entry.name,
                            "type": entry_type,
                            "path": virtual_path,
                        })

                        if entry.is_dir(follow_symlinks=False):
                            _scan(entry.path, depth + 1)
            except PermissionError:
                logger.warning("Permission denied scanning %s", directory)

        _scan(abs_root, 1)
        return entries

    # ─── Read File ────────────────────────────────────────────────────────

    async def read_file(self, workspace_id: str, path: str) -> str:
        """
        Read a file from the workspace using host-side pathlib.

        Path is jail-validated to prevent traversal / symlink escapes.
        Uses asyncio.to_thread to avoid blocking on large files.
        """
        workspace_dir = self._resolve_workspace_dir(workspace_id)

        try:
            safe_path = _jail_path(str(workspace_dir), path)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

        host_path = Path(safe_path)
        if not host_path.is_file():
            raise HTTPException(
                status_code=404,
                detail=f"File not found: {path}",
            )

        return await asyncio.to_thread(host_path.read_text, "utf-8")


# ─── Singleton ────────────────────────────────────────────────────────────────

_workspace_fs: WorkspaceFS | None = None


def get_workspace_fs() -> WorkspaceFS:
    global _workspace_fs
    if _workspace_fs is None:
        _workspace_fs = WorkspaceFS(settings=get_settings())
    return _workspace_fs


# ─── Backward-compatible aliases ─────────────────────────────────────────────
# Any module that still imports the old names will get the new service.

OpenHandsClient = WorkspaceFS
SandboxUnavailableError = HTTPException
get_openhands_client = get_workspace_fs
