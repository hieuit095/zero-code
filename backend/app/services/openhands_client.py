"""
OpenSandbox-native workspace client.

MIGRATION: Replaces the previous OpenHands SDK-based pseudo-sandbox with
a genuine Alibaba OpenSandbox integration that provisions real Docker
containers for each workspace, providing true filesystem and process
isolation.

Lifecycle model
───────────────
  create_workspace(workspace_id)
      → provisions a Docker container via ``Sandbox.create()``
  read_file(workspace_id, path)
      → reads via ``sandbox.files.read_file()``
  write_file(workspace_id, path, content)
      → writes via ``sandbox.files.write_files()``
  run_command(workspace_id, command)
      → executes via ``sandbox.commands.run()``
  list_tree(workspace_id)
      → lists via ``sandbox.commands.run("find ...")``
  destroy_workspace(workspace_id)
      → kills the sandbox container.

SECURITY:
  - Each workspace runs inside an isolated Docker container managed by
    OpenSandbox. There is NO host-side path jailing — the container
    boundary IS the jail.
  - ``SandboxUnavailableError`` is raised whenever the OpenSandbox SDK
    is not installed or the sandbox server is unreachable.
"""

from __future__ import annotations

import asyncio
import atexit
import logging
import os
import signal
from datetime import timedelta
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from ..config import Settings, get_settings

logger = logging.getLogger(__name__)

# ─── SDK Import Guard ─────────────────────────────────────────────────────────

_SDK_AVAILABLE = False

try:
    from opensandbox import Sandbox
    from opensandbox.models import WriteEntry
    _SDK_AVAILABLE = True
except ImportError:
    logger.warning(
        "OpenSandbox SDK not installed — OpenSandboxClient will operate in "
        "degraded stub mode. Install with: pip install opensandbox opensandbox-server"
    )

# ─── Noisy directories to exclude from tree listings ─────────────────────────

_EXCLUDED_DIRS: frozenset[str] = frozenset({
    "node_modules", ".git", "__pycache__", ".venv", "venv",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", ".tox",
    "dist", "build", ".next", ".nuxt", ".turbo",
})

# ─── Default sandbox image & resource limits ─────────────────────────────────

_DEFAULT_SANDBOX_IMAGE = os.getenv(
    "OPENSANDBOX_IMAGE", "opensandbox/code-interpreter:v1.0.2"
)
_SANDBOX_TIMEOUT_MINUTES = int(os.getenv("OPENSANDBOX_TIMEOUT_MINUTES", "60"))
_SANDBOX_CPU_COUNT = int(os.getenv("OPENSANDBOX_CPU_COUNT", "2"))
_SANDBOX_MEMORY_MB = int(os.getenv("OPENSANDBOX_MEMORY_MB", "1024"))
_SANDBOX_NETWORK_ENABLED = os.getenv("OPENSANDBOX_NETWORK_ENABLED", "false").lower() == "true"

# Catastrophic score threshold — scores below this trigger a full
# snapshot rollback instead of incremental patching.
CATASTROPHIC_SCORE_THRESHOLD = int(os.getenv("OPENSANDBOX_CATASTROPHIC_THRESHOLD", "40"))

# PHASE 1 HARDENING: Reaper interval for background zombie pruning.
_SANDBOX_REAPER_INTERVAL_SECONDS = int(os.getenv(
    "OPENSANDBOX_REAPER_INTERVAL_SECONDS", "300",  # 5 minutes
))


# ─── Global Sandbox Registry & Cleanup ────────────────────────────────────────
# Every provisioned Sandbox instance is tracked here so that we can
# force-kill orphaned containers on process exit (normal or crash).

_ACTIVE_SANDBOXES: dict[str, Any] = {}   # workspace_id → Sandbox instance


def _cleanup_all_sandboxes() -> None:
    """Best-effort synchronous cleanup of ALL active sandbox containers.

    Called by ``atexit`` and emergency signal handlers.  Because we are
    in a teardown context the event loop may or may not still be running,
    so we try multiple strategies:
      1. Schedule ``sandbox.kill()`` on the running loop.
      2. If no loop is running, spin up a temporary loop to drain kills.
      3. PHASE 1 HARDENING: Use the Docker SDK directly as a last-resort
         fallback to kill containers that the async path cannot reach
         (e.g., after SIGKILL / OOM where the process is force-terminated).
    """
    if not _ACTIVE_SANDBOXES:
        return

    sandbox_ids = list(_ACTIVE_SANDBOXES.keys())
    logger.warning(
        "Process exit detected — force-killing %d orphaned sandbox(es): %s",
        len(sandbox_ids), sandbox_ids,
    )

    async def _drain() -> None:
        for wid, sb in list(_ACTIVE_SANDBOXES.items()):
            try:
                await sb.kill()
                logger.info("Killed orphaned sandbox: %s", wid)
            except Exception:
                logger.warning(
                    "Failed to kill orphaned sandbox %s", wid, exc_info=True,
                )
        _ACTIVE_SANDBOXES.clear()

    # Strategy 1: attach to running loop
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_drain())
        return
    except RuntimeError:
        pass

    # Strategy 2: create a throwaway loop
    try:
        asyncio.run(_drain())
    except Exception:
        logger.warning("Fallback cleanup loop failed", exc_info=True)

    # Strategy 3 (PHASE 1 HARDENING): Docker SDK sync fallback.
    # If atexit fires after a hard crash, try to kill containers
    # directly via the Docker API.  This catches orphans that the
    # async SDK path could not reach.
    try:
        import docker  # type: ignore[import-untyped]
        client = docker.from_env()
        # Kill containers created by the OpenSandbox SDK image.
        containers = client.containers.list(
            filters={"ancestor": _DEFAULT_SANDBOX_IMAGE, "status": "running"}
        )
        for container in containers:
            try:
                container.kill()
                logger.info(
                    "Docker SDK killed orphaned container: %s (%s)",
                    container.short_id, container.name,
                )
            except Exception:
                logger.warning(
                    "Docker SDK failed to kill container %s",
                    container.short_id, exc_info=True,
                )
    except ImportError:
        # docker SDK not installed — skip fallback silently.
        pass
    except Exception:
        logger.warning("Docker SDK fallback cleanup failed", exc_info=True)


# Register the hook immediately at import time.
atexit.register(_cleanup_all_sandboxes)

# Also catch SIGTERM (e.g. Docker stop / k8s pod termination).
# SIGINT is already handled by Python's default KeyboardInterrupt.
try:
    signal.signal(signal.SIGTERM, lambda _sig, _frame: _cleanup_all_sandboxes())
except (OSError, ValueError):
    # signal.signal() can fail when called from a non-main thread.
    pass


# ─── Background Reaper Task (Phase 1 Hardening) ──────────────────────────────


async def start_sandbox_reaper() -> asyncio.Task:
    """Start a background asyncio task that periodically prunes unhealthy sandboxes.

    PHASE 1 HARDENING: The ``atexit`` handler only fires on normal
    process exit.  If the worker is SIGKILL'd, OOM-killed, or crashes
    hard, sandbox containers leak indefinitely.  This reaper runs
    every ``_SANDBOX_REAPER_INTERVAL_SECONDS`` seconds and:
      1. Iterates all registered sandboxes.
      2. Health-checks each with a lightweight ``true`` command.
      3. Kills and deregisters any sandbox that fails the health check.

    Returns the asyncio.Task so callers can cancel it on shutdown.
    """
    async def _reaper_loop() -> None:
        while True:
            await asyncio.sleep(_SANDBOX_REAPER_INTERVAL_SECONDS)
            if not _ACTIVE_SANDBOXES:
                continue

            stale: list[str] = []
            for wid, sb in list(_ACTIVE_SANDBOXES.items()):
                try:
                    # Lightweight health probe
                    await asyncio.wait_for(
                        sb.commands.run("true"),
                        timeout=10.0,
                    )
                except Exception:
                    logger.warning(
                        "Reaper: sandbox '%s' is unresponsive — marking for cleanup",
                        wid,
                    )
                    stale.append(wid)

            for wid in stale:
                sb = _ACTIVE_SANDBOXES.pop(wid, None)
                if sb is not None:
                    try:
                        await sb.kill()
                        logger.info("Reaper: killed stale sandbox '%s'", wid)
                    except Exception:
                        logger.warning(
                            "Reaper: failed to kill stale sandbox '%s'",
                            wid, exc_info=True,
                        )

            if stale:
                logger.info(
                    "Reaper cycle complete: pruned %d stale sandbox(es)",
                    len(stale),
                )

    task = asyncio.create_task(_reaper_loop(), name="sandbox-reaper")
    logger.info(
        "Sandbox reaper started (interval: %ds)",
        _SANDBOX_REAPER_INTERVAL_SECONDS,
    )
    return task


# ─── Custom Errors ────────────────────────────────────────────────────────────


class SandboxUnavailableError(RuntimeError):
    """Raised when the OpenSandbox SDK is not available or the server is down.

    There is **no** subprocess fallback.  If this error surfaces it means
    either the SDK is not installed or ``create_workspace()`` was never called.
    """


# ─── Workspace Runtime Handle ─────────────────────────────────────────────────


class _WorkspaceRuntime:
    """Holds the OpenSandbox container instance for a single workspace.

    PHASE 3 HARDENING: Added snapshot/restore capability for fast
    rollbacks and catastrophic failure recovery.
    """

    __slots__ = ("workspace_id", "sandbox", "_alive", "_snapshot_id")

    def __init__(self, workspace_id: str, sandbox: Any) -> None:
        self.workspace_id = workspace_id
        self.sandbox = sandbox
        self._alive = True
        self._snapshot_id: str | None = None

        logger.info(
            "Workspace runtime created (OpenSandbox container): %s",
            workspace_id,
        )

    # ── In-Container Path Resolution (Phase 1 Symlink Hardening) ───────

    async def _resolve_in_container(self, container_path: str) -> str:
        """Execute ``realpath`` inside the sandbox to resolve symlinks.

        PHASE 1 HARDENING: Lexical ``posixpath.normpath`` checks cannot
        detect symlinks created inside the container that point outside
        ``/workspace``.  This method runs the actual ``realpath`` binary
        inside the container and verifies the resolved path is still
        within the ``/workspace`` jail.

        Falls back to the lexical path if the in-container command fails
        (e.g., container not yet started, binary missing).

        Raises:
            ValueError: If the resolved path escapes ``/workspace``.
        """
        try:
            execution = await self.sandbox.commands.run(
                f"realpath -m '{container_path}'"
            )
            # Extract stdout from the SDK execution result
            resolved = ""
            if execution.logs and execution.logs.stdout:
                for entry in execution.logs.stdout:
                    resolved += entry.text
            resolved = resolved.strip()

            if not resolved:
                # realpath produced no output — fall back to lexical
                logger.debug(
                    "realpath returned empty for '%s' — using lexical path",
                    container_path,
                )
                return container_path

            # Verify the resolved path is still inside the jail
            if resolved != "/workspace" and not resolved.startswith("/workspace/"):
                raise ValueError(
                    f"SYMLINK ESCAPE BLOCKED: '{container_path}' resolved to "
                    f"'{resolved}' inside the container, which escapes the "
                    f"/workspace boundary."
                )

            return resolved

        except ValueError:
            # Re-raise ValueError (our own security check)
            raise
        except Exception:
            # Container not started, realpath binary missing, etc.
            # Fall back to the lexical path (already validated by _normalize_path).
            logger.debug(
                "In-container realpath failed for '%s' — using lexical path",
                container_path,
                exc_info=True,
            )
            return container_path

    # ── File Operations ───────────────────────────────────────────────

    async def read_file(self, path: str) -> str:
        """Read a file from the sandbox container."""
        if not self._alive:
            raise SandboxUnavailableError("Workspace runtime has been destroyed")

        # Pass 1: Lexical normalization (fast, catches obvious traversal)
        container_path = _normalize_path(path)

        # Pass 2: In-container realpath (catches symlink escapes)
        container_path = await self._resolve_in_container(container_path)

        try:
            content = await self.sandbox.files.read_file(container_path)
            return content
        except Exception as e:
            raise FileNotFoundError(f"File not found or unreadable: {path}") from e

    async def write_file(self, path: str, content: str) -> str:
        """Write a file inside the sandbox container."""
        if not self._alive:
            raise SandboxUnavailableError("Workspace runtime has been destroyed")

        # Pass 1: Lexical normalization (fast, catches obvious traversal)
        container_path = _normalize_path(path)

        # Pass 2: In-container realpath (catches symlink escapes)
        container_path = await self._resolve_in_container(container_path)

        # Ensure parent directories exist
        parent = os.path.dirname(container_path)
        if parent and parent != "/workspace":
            await self.sandbox.commands.run(f"mkdir -p '{parent}'")

        await self.sandbox.files.write_files([
            WriteEntry(path=container_path, data=content, mode=644)
        ])
        return "File written successfully."

    async def run_command(self, command: str, cwd: str = "/workspace") -> Any:
        """Execute a shell command inside the sandbox container."""
        if not self._alive:
            raise SandboxUnavailableError("Workspace runtime has been destroyed")

        # Prepend cd if a custom cwd is specified
        if cwd and cwd != "/workspace":
            full_command = f"cd '{cwd}' && {command}"
        else:
            full_command = command

        return await self.sandbox.commands.run(full_command)

    async def list_tree(self, max_depth: int = 5) -> list[dict[str, Any]]:
        """List the workspace tree using ``find`` inside the container."""
        if not self._alive:
            raise SandboxUnavailableError("Workspace runtime has been destroyed")

        # Build exclusion flags for find
        excludes = " ".join(
            f"-not -path '*/{d}' -not -path '*/{d}/*'"
            for d in sorted(_EXCLUDED_DIRS)
        )

        cmd = (
            f"find /workspace "
            f"-maxdepth {max_depth} "
            f"-not -name '.*' {excludes} "
            f"-printf '%y %P\\n' 2>/dev/null || true"
        )
        execution = await self.sandbox.commands.run(cmd)
        output_text = ""
        if execution.logs and execution.logs.stdout:
            output_text = execution.logs.stdout[0].text if execution.logs.stdout else ""

        entries: list[dict[str, Any]] = []
        for line in output_text.strip().splitlines():
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

    async def destroy(self) -> None:
        """Kill the sandbox container and deregister from the global registry."""
        if not self._alive:
            return
        self._alive = False
        try:
            await self.sandbox.kill()
        except Exception:
            logger.warning(
                "Error killing sandbox for workspace %s", self.workspace_id,
                exc_info=True,
            )
        # Remove from global orphan registry so atexit won't double-kill.
        _ACTIVE_SANDBOXES.pop(self.workspace_id, None)
        logger.info("Workspace runtime destroyed (container killed): %s", self.workspace_id)

    # ── Snapshot / Restore (Phase 3) ──────────────────────────────────

    async def snapshot(self) -> str | None:
        """Commit the current container state as a fast-snapshot.

        Returns the snapshot image ID on success, or None on failure.
        The ID is also cached as ``self._snapshot_id`` for later
        ``restore_snapshot()`` calls.
        """
        if not self._alive:
            raise SandboxUnavailableError("Workspace runtime has been destroyed")
        try:
            snapshot_id = await self.sandbox.commit()
            self._snapshot_id = snapshot_id
            logger.info(
                "Snapshot created for workspace %s: %s",
                self.workspace_id, snapshot_id,
            )
            return snapshot_id
        except Exception:
            logger.warning(
                "Failed to create snapshot for workspace %s",
                self.workspace_id, exc_info=True,
            )
            return None

    async def restore_snapshot(self) -> bool:
        """Restore the container to the last committed snapshot.

        Kills the current sandbox, re-provisions from the snapshot
        image with the same resource constraints, and updates the
        global registry.

        Returns True on success, False on failure.
        """
        if self._snapshot_id is None:
            logger.warning(
                "No snapshot available for workspace %s — cannot restore",
                self.workspace_id,
            )
            return False

        try:
            # Kill the corrupted container
            await self.sandbox.kill()

            # Re-provision from the snapshot image
            new_sandbox = await Sandbox.create(
                self._snapshot_id,
                timeout=timedelta(minutes=_SANDBOX_TIMEOUT_MINUTES),
                cpu_count=_SANDBOX_CPU_COUNT,
                memory_mb=_SANDBOX_MEMORY_MB,
                network_enabled=_SANDBOX_NETWORK_ENABLED,
            )

            self.sandbox = new_sandbox
            self._alive = True
            _ACTIVE_SANDBOXES[self.workspace_id] = new_sandbox

            logger.info(
                "Workspace %s restored from snapshot %s",
                self.workspace_id, self._snapshot_id,
            )
            return True

        except Exception:
            logger.exception(
                "Failed to restore workspace %s from snapshot %s",
                self.workspace_id, self._snapshot_id,
            )
            self._alive = False
            return False


def _normalize_path(path: str) -> str:
    """Ensure path is strictly jailed inside ``/workspace``.

    SECURITY FIX (Phase 1): The previous implementation blindly used
    ``lstrip('/')`` which allowed ``../../`` sequences to escape the
    ``/workspace`` boundary (e.g. ``../../etc/shadow`` resolved to
    ``/workspace/../../etc/shadow`` → ``/etc/shadow``).

    The new implementation:
      1. Joins the raw path against ``/workspace`` (POSIX convention).
      2. Resolves ``..`` and ``.`` components via ``posixpath.normpath``.
      3. Validates the resolved path starts with ``/workspace/`` or
         equals ``/workspace``.
      4. Raises ``ValueError`` on any escape attempt — the caller
         surfaces this as a ``FileNotFoundError`` or ``SandboxUnavailableError``.
    """
    import posixpath

    # Step 1: If path is already absolute, resolve it directly.
    #         If relative, join it under /workspace.
    if path.startswith("/"):
        resolved = posixpath.normpath(path)
    else:
        resolved = posixpath.normpath(posixpath.join("/workspace", path))

    # Step 2: Strict jail check — the resolved path MUST be /workspace
    #         or start with /workspace/ (a proper child).
    if resolved != "/workspace" and not resolved.startswith("/workspace/"):
        raise ValueError(
            f"Path traversal blocked: '{path}' resolved to '{resolved}' "
            f"which escapes the /workspace boundary."
        )

    return resolved


# ─── OpenSandboxClient ───────────────────────────────────────────────────────


class OpenSandboxClient:
    """
    OpenSandbox-native workspace client.

    Manages one or more ``_WorkspaceRuntime`` instances, each backed by a
    real Docker container via the Alibaba OpenSandbox SDK.  All file and
    command operations flow through the containerized sandbox — there is
    **zero** host-side file I/O or subprocess execution.

    Lifecycle:
        client = OpenSandboxClient(settings)
        await client.create_workspace("repo-main")
        tree = await client.list_tree("repo-main")
        content = await client.read_file("repo-main", "/workspace/src/main.py")
        await client.destroy_workspace("repo-main")
    """

    def __init__(self, settings: Settings) -> None:
        self._workspace_base = settings.workspace_path
        self._runtimes: dict[str, _WorkspaceRuntime] = {}

    # ─── Lifecycle ────────────────────────────────────────────────────────

    async def create_workspace(self, workspace_id: str) -> _WorkspaceRuntime:
        """Provision an OpenSandbox container for this workspace.

        Spins up a real Docker container using the configured sandbox image.

        Raises ``SandboxUnavailableError`` if the SDK is not installed.
        """
        if not _SDK_AVAILABLE:
            raise SandboxUnavailableError(
                "OpenSandbox SDK is not installed. Cannot create workspace runtime. "
                "Install with: pip install opensandbox opensandbox-server"
            )

        # Create the sandbox container with explicit resource limits.
        # PHASE 1 HARDENING: cpu_count and memory_mb prevent a rogue
        # Dev-agent script from OOM-killing or CPU-starving the host.
        # PHASE 3 HARDENING: network_enabled defaults to False for
        # zero-trust isolation — agents cannot make external requests.
        sandbox = await Sandbox.create(
            _DEFAULT_SANDBOX_IMAGE,
            timeout=timedelta(minutes=_SANDBOX_TIMEOUT_MINUTES),
            cpu_count=_SANDBOX_CPU_COUNT,
            memory_mb=_SANDBOX_MEMORY_MB,
            network_enabled=_SANDBOX_NETWORK_ENABLED,
        )

        # Register in the global orphan-safety-net registry.
        _ACTIVE_SANDBOXES[workspace_id] = sandbox

        runtime = _WorkspaceRuntime(workspace_id, sandbox)
        self._runtimes[workspace_id] = runtime
        return runtime

    async def setup_dependencies(
        self,
        workspace_id: str,
        install_commands: list[str],
    ) -> _WorkspaceRuntime:
        """Install dependencies with temporary network access, then lock down.

        PHASE 3 — Zero-Trust Networking:
          1. Provision a sandbox WITH network access.
          2. Run each install command (npm install, pip install, etc.).
          3. Commit the container state as a snapshot.
          4. Kill the network-enabled container.
          5. Re-provision from the snapshot with network DISABLED.

        This ensures agent cognition loops NEVER have egress access.
        """
        if not _SDK_AVAILABLE:
            raise SandboxUnavailableError(
                "OpenSandbox SDK is not installed. Cannot setup dependencies."
            )

        # ── Step 1: Provision with network enabled ────────────────────
        net_sandbox = await Sandbox.create(
            _DEFAULT_SANDBOX_IMAGE,
            timeout=timedelta(minutes=_SANDBOX_TIMEOUT_MINUTES),
            cpu_count=_SANDBOX_CPU_COUNT,
            memory_mb=_SANDBOX_MEMORY_MB,
            network_enabled=True,
        )
        logger.info(
            "Dependency sandbox provisioned (network=ON) for %s",
            workspace_id,
        )

        # ── Step 2: Run install commands ──────────────────────────────
        for cmd in install_commands:
            try:
                await net_sandbox.commands.run(cmd)
                logger.info("Dependency install OK: %s", cmd)
            except Exception:
                logger.warning(
                    "Dependency install failed: %s", cmd, exc_info=True,
                )

        # ── Step 3: Commit the fully-installed state ─────────────────
        snapshot_id = await net_sandbox.commit()
        logger.info(
            "Dependency snapshot committed for %s: %s",
            workspace_id, snapshot_id,
        )

        # ── Step 4: Kill the network-enabled container ───────────────
        await net_sandbox.kill()

        # ── Step 5: Re-provision from snapshot with network OFF ──────
        isolated_sandbox = await Sandbox.create(
            snapshot_id,
            timeout=timedelta(minutes=_SANDBOX_TIMEOUT_MINUTES),
            cpu_count=_SANDBOX_CPU_COUNT,
            memory_mb=_SANDBOX_MEMORY_MB,
            network_enabled=False,
        )

        _ACTIVE_SANDBOXES[workspace_id] = isolated_sandbox

        runtime = _WorkspaceRuntime(workspace_id, isolated_sandbox)
        runtime._snapshot_id = snapshot_id  # Pre-seed for rollback
        self._runtimes[workspace_id] = runtime

        logger.info(
            "Isolated workspace ready (network=OFF, deps installed): %s",
            workspace_id,
        )
        return runtime

    def destroy_workspace_sync(self, workspace_id: str) -> None:
        """Schedule async destruction — called from sync contexts."""
        runtime = self._runtimes.pop(workspace_id, None)
        if runtime is not None:
            asyncio.ensure_future(runtime.destroy())

    async def destroy_workspace(self, workspace_id: str) -> None:
        """Tear down the sandbox container for *workspace_id*."""
        runtime = self._runtimes.pop(workspace_id, None)
        if runtime is not None:
            await runtime.destroy()

    async def get_runtime(self, workspace_id: str) -> _WorkspaceRuntime:
        """Return the live runtime, auto-creating if necessary."""
        if workspace_id not in self._runtimes:
            await self.create_workspace(workspace_id)
        return self._runtimes[workspace_id]

    # ─── Convenience Methods (UI-facing) ──────────────────────────────────

    async def list_tree(
        self, workspace_id: str, max_depth: int = 5,
    ) -> list[dict[str, Any]]:
        """List the workspace file tree via the sandbox container."""
        runtime = await self.get_runtime(workspace_id)
        return await runtime.list_tree(max_depth)

    async def read_file(self, workspace_id: str, path: str) -> str:
        """Read a file via the sandbox container.

        Raises ``HTTPException`` 404 on missing files.
        """
        runtime = await self.get_runtime(workspace_id)
        try:
            return await runtime.read_file(path)
        except FileNotFoundError as e:
            raise HTTPException(status_code=404, detail=str(e))


# ─── Singleton ────────────────────────────────────────────────────────────────

_client: OpenSandboxClient | None = None


async def get_opensandbox_client() -> OpenSandboxClient:
    global _client
    if _client is None:
        _client = OpenSandboxClient(settings=get_settings())
    return _client


# ─── Backward-compatible aliases ──────────────────────────────────────────────
# Modules that still import the old names will get the new OpenSandbox service.

OpenHandsClient = OpenSandboxClient
WorkspaceFS = OpenSandboxClient
get_openhands_client = get_opensandbox_client
get_workspace_fs = get_opensandbox_client
