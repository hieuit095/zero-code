# ==========================================
# Author: Hieu Nguyen - Codev Team
# Email: hieuit095@gmail.com
# Project: ZeroCode - Autonomous Multi-Agent IDE
# ==========================================
"""
Internal MCP Facade — FastMCP server exposing jailed workspace tools.

AUDIT REMEDIATION (Phase 2): All tool execution now routes through the
``OpenHandsClient`` SDK layer instead of raw ``subprocess.run()`` and
native Python ``open()`` calls.

MCP tool dispatch:
  read_file  → OpenHandsClient.execute_action(TerminalAction("cat ..."))
  write_file → OpenHandsClient runtime.write_file(path, content)
  exec       → OpenHandsClient.execute_action(TerminalAction(command))

There are **zero** remaining subprocess or native file I/O calls.

SECURITY INVARIANTS PRESERVED:
  - ``_jail_path()``: os.path.realpath()-based symlink jailing on every
    tool invocation *before* the action reaches the SDK executor.
  - ``CommandPolicy.check()``: role-based command blocklist/allowlist
    gates the ``exec`` tool *before* forwarding to the SDK.
  - Role-scoped exec: each role gets its own MCP server instance.
  - ``SandboxUnavailableError``: raised if the SDK is missing — no
    fallback to local execution.
"""

from __future__ import annotations

import logging
import os

from mcp.server.fastmcp import FastMCP

from ..services.command_policy import CommandPolicy
from ..services.openhands_client import (
    OpenHandsClient,
    SandboxUnavailableError,
    get_openhands_client,
)

logger = logging.getLogger(__name__)


# ─── SDK Import Guard ─────────────────────────────────────────────────────────

_SDK_AVAILABLE = False

try:
    from openhands.tools.terminal import TerminalAction
    _SDK_AVAILABLE = True
except ImportError:
    logger.warning(
        "OpenHands SDK not installed — MCP tools will be unavailable. "
        "Install with: pip install openhands-sdk openhands-tools"
    )


# ─── Path Jailing ─────────────────────────────────────────────────────────────


def _jail_path(workspace_root: str, requested_path: str) -> str:
    """
    Resolve a user-supplied path against workspace_root and verify
    the result doesn't escape the jail using os.path.realpath().

    This preserves the required symlink jailing logic.
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


# ─── MCP Server Factory ──────────────────────────────────────────────────────


def create_mcp_server(workspace_root: str, role: str) -> FastMCP:
    """
    Create a FastMCP server instance with jailed workspace tools.

    Each role (dev, qa, tech-lead) gets its own server instance with
    role-appropriate command policy enforcement.

    All tool execution is routed through the ``OpenHandsClient`` SDK
    layer — there are no ``subprocess``, ``os.system``, or native
    ``open()`` calls inside these tools.

    Args:
        workspace_root: Absolute host path to the workspace directory.
        role: Agent role for command policy scoping ("dev", "qa", "tech-lead").

    Returns:
        A configured FastMCP server ready to be mounted on FastAPI.
    """
    mcp = FastMCP(
        name=f"zero-code-sandbox-{role}",
        instructions=(
            f"Sandbox tools for the {role} agent. Provides secure file "
            f"read/write and command execution within the workspace jail. "
            f"All operations are executed through the OpenHands SDK — "
            f"no host-level subprocess or file I/O is used."
        ),
    )
    workspace_id = os.path.basename(os.path.realpath(workspace_root))

    # ─── read_file ────────────────────────────────────────────────────

    @mcp.tool(name="workspace_read_file")
    def read_file(path: str) -> str:
        """
        Securely read a file from the workspace via the OpenHands SDK.

        The path is jail-validated against the workspace root *before*
        the read action reaches the SDK executor.  The actual file read
        is performed by the SDK's ``TerminalExecutor`` (``cat``), NOT by
        a native Python ``open()`` call.

        Args:
            path: File path relative to workspace root (e.g. /workspace/src/main.py)

        Returns:
            The full text content of the file.
        """
        if not _SDK_AVAILABLE:
            return "Error: OpenHands SDK is not installed. Cannot read files."

        try:
            # Validate path stays within the jail BEFORE touching the SDK
            _jail_path(workspace_root, path)

            # Route through the SDK runtime
            client = get_openhands_client()
            runtime = client.get_runtime(workspace_id)
            return runtime.read_file(path)

        except SandboxUnavailableError as e:
            return f"Error: Sandbox unavailable — {e}"
        except ValueError as e:
            return f"Error: {e}"
        except Exception as e:
            return f"Error reading file: {e}"

    # ─── write_file ───────────────────────────────────────────────────

    @mcp.tool(name="workspace_write_file")
    def write_file(path: str, content: str) -> str:
        """
        Securely write a complete file to the workspace via the OpenHands SDK.

        Creates parent directories if they don't exist. The path is
        jail-validated *before* the write action reaches the SDK executor.
        The actual write is performed via the SDK's ``TerminalExecutor``
        using a base64 pipeline — NOT by a native Python ``open()`` call.

        Args:
            path: File path relative to workspace root (e.g. /workspace/src/main.py)
            content: Full text content to write to the file.

        Returns:
            Success message or error description.
        """
        if not _SDK_AVAILABLE:
            return "Error: OpenHands SDK is not installed. Cannot write files."

        try:
            # Validate path stays within the jail BEFORE touching the SDK
            safe_path = _jail_path(workspace_root, path)

            # Route through the SDK runtime
            client = get_openhands_client()
            runtime = client.get_runtime(workspace_id)
            return runtime.write_file(path, content)

        except SandboxUnavailableError as e:
            return f"Error: Sandbox unavailable — {e}"
        except ValueError as e:
            return f"Error: {e}"
        except Exception as e:
            return f"Write failed: {e}"

    # ─── exec ─────────────────────────────────────────────────────────

    @mcp.tool(name="workspace_exec")
    def exec(command: str, cwd: str = "/workspace") -> str:
        """
        Execute a shell command inside the workspace via the OpenHands SDK.

        The command is checked against the role-based security policy
        *before* being forwarded to the SDK executor.  The working
        directory is jail-validated to prevent escapes.

        Execution happens through the SDK's ``TerminalExecutor`` — NOT
        via ``subprocess.run()``.

        Args:
            command: Shell command to execute.
            cwd: Working directory (default: /workspace).

        Returns:
            Command output (stdout + stderr) and exit code.
        """
        if not _SDK_AVAILABLE:
            return "Error: OpenHands SDK is not installed. Cannot execute commands."

        # ── Command Policy Enforcement (unchanged) ────────────────────
        policy_result = CommandPolicy.check(command, role)
        if not policy_result.allowed:
            return (
                f"POLICY BLOCKED: {policy_result.reason} "
                f"[rule: {policy_result.matched_rule}]"
            )

        # ── Jail cwd against traversal / symlinks ─────────────────────
        try:
            _jail_path(workspace_root, cwd)
        except ValueError as e:
            return f"CWD jail escape detected: {e}"

        # Additional traversal guard
        parts = cwd.split("/")
        if ".." in parts or cwd == "/" or cwd.startswith("/etc"):
            return "Error: Invalid cwd inside container"

        # ── Route through the SDK TerminalExecutor ────────────────────
        try:
            client = get_openhands_client()
            runtime = client.get_runtime(workspace_id)
            observation = runtime.execute_terminal(command=command, cwd=cwd)

            # Format the observation into the same contract the agents expect
            output_parts: list[str] = []
            text = observation.text or ""

            if text.strip():
                output_parts.append(f"OUTPUT:\n{text}")

            output_parts.append(f"EXIT CODE: {observation.exit_code}")
            return "\n".join(output_parts)

        except SandboxUnavailableError as e:
            return f"Error: Sandbox unavailable — {e}"
        except Exception as e:
            return f"Execution error: {e}"

    return mcp


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _shell_quote(s: str) -> str:
    """Single-quote a string for safe shell interpolation."""
    return "'" + s.replace("'", "'\\''") + "'"
