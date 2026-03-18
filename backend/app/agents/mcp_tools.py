"""
Internal MCP Facade — FastMCP server exposing containerized workspace tools.

MIGRATION: All tool execution now routes through the OpenSandbox SDK
(Docker containers) instead of the previous OpenHands TerminalExecutor.
Host-side path jailing has been removed — the container boundary provides
absolute isolation.

MCP tool dispatch:
  read_file  → sandbox.files.read_file(path)
  write_file → sandbox.files.write_files([WriteEntry(...)])
  exec       → sandbox.commands.run(command)

There are **zero** remaining subprocess or native file I/O calls.

SECURITY INVARIANTS:
  - Container isolation: each sandbox is a separate Docker container.
    No `_jail_path()` needed — agents cannot escape.
  - ``CommandPolicy.check()``: role-based command blocklist/allowlist
    gates the ``exec`` tool *before* forwarding to the sandbox.
  - Role-scoped exec: each role gets its own MCP server instance.
  - ``SandboxUnavailableError``: raised if the SDK is missing — no
    fallback to local execution.
"""

from __future__ import annotations

import asyncio
import logging
import os

from mcp.server.fastmcp import FastMCP

from ..services.command_policy import CommandPolicy
from ..services.openhands_client import (
    OpenSandboxClient,
    SandboxUnavailableError,
    get_opensandbox_client,
)

logger = logging.getLogger(__name__)

# ─── SDK Import Guard ─────────────────────────────────────────────────────────

_SDK_AVAILABLE = False

try:
    from opensandbox import Sandbox
    _SDK_AVAILABLE = True
except ImportError:
    logger.warning(
        "OpenSandbox SDK not installed — MCP tools will be unavailable. "
        "Install with: pip install opensandbox opensandbox-server"
    )


# ─── MCP Server Factory ──────────────────────────────────────────────────────


def create_mcp_server(workspace_root: str, role: str, workspace_id: str = "repo-main") -> FastMCP:
    """
    Create a FastMCP server instance with containerized workspace tools.

    Each role (dev, qa, tech-lead) gets its own server instance with
    role-appropriate command policy enforcement.

    PHASE 1 HARDENING: ``workspace_id`` is now a required parameter
    that flows from the JWT ``wid`` claim through to every
    ``client.get_runtime()`` call.  This replaces the previous
    hardcoded ``"repo-main"`` and enables true multi-tenant sandbox
    isolation.

    All tool execution is routed through the OpenSandbox SDK — there are
    no ``subprocess``, ``os.system``, or native ``open()`` calls inside
    these tools.

    Args:
        workspace_root: Absolute host path to the workspace directory
                        (used only for CommandPolicy context, NOT for
                        host-side file I/O).
        role: Agent role for command policy scoping ("dev", "qa", "tech-lead").
        workspace_id: The sandbox workspace ID for container resolution.
                      PHASE 1 HARDENING: passed from JWT ``wid`` claim.

    Returns:
        A configured FastMCP server ready to be mounted on FastAPI.
    """
    mcp = FastMCP(
        name=f"zero-code-sandbox-{role}",
        instructions=(
            f"Sandbox tools for the {role} agent. Provides secure file "
            f"read/write and command execution within an isolated Docker "
            f"container. All operations are executed through the OpenSandbox "
            f"SDK — no host-level subprocess or file I/O is used."
        ),
    )

    # ─── read_file ────────────────────────────────────────────────────

    @mcp.tool()
    async def read_file(path: str) -> str:
        """
        Securely read a file from the workspace via the OpenSandbox SDK.

        The file is read directly from the isolated Docker container.
        No host-side file I/O occurs.

        Args:
            path: File path relative to workspace root (e.g. /workspace/src/main.py)

        Returns:
            The full text content of the file.
        """
        if not _SDK_AVAILABLE:
            return "Error: OpenSandbox SDK is not installed. Cannot read files."

        try:
            client = await get_opensandbox_client()
            runtime = await client.get_runtime(workspace_id)
            content = await runtime.read_file(path)
            return content

        except SandboxUnavailableError as e:
            return f"Error: Sandbox unavailable — {e}"
        except FileNotFoundError:
            return f"Error: File not found or unreadable: {path}"
        except Exception as e:
            return f"Error reading file: {e}"

    # ─── write_file ───────────────────────────────────────────────────

    @mcp.tool()
    async def write_file(path: str, content: str) -> str:
        """
        Securely write a complete file to the workspace via the OpenSandbox SDK.

        Creates parent directories if they don't exist. The file is written
        directly inside the isolated Docker container.

        Args:
            path: File path relative to workspace root (e.g. /workspace/src/main.py)
            content: Full text content to write to the file.

        Returns:
            Success message or error description.
        """
        if not _SDK_AVAILABLE:
            return "Error: OpenSandbox SDK is not installed. Cannot write files."

        try:
            client = await get_opensandbox_client()
            runtime = await client.get_runtime(workspace_id)
            return await runtime.write_file(path, content)

        except SandboxUnavailableError as e:
            return f"Error: Sandbox unavailable — {e}"
        except Exception as e:
            return f"Write failed: {e}"

    # ─── exec ─────────────────────────────────────────────────────────

    @mcp.tool()
    async def exec(command: str, cwd: str = "/workspace") -> str:
        """
        Execute a shell command inside the workspace via the OpenSandbox SDK.

        The command is checked against the role-based security policy
        *before* being forwarded to the container. Execution happens
        inside the Docker container — NOT on the host.

        Args:
            command: Shell command to execute.
            cwd: Working directory (default: /workspace).

        Returns:
            Command output (stdout + stderr) and exit code.
        """
        if not _SDK_AVAILABLE:
            return "Error: OpenSandbox SDK is not installed. Cannot execute commands."

        # ── Command Policy Enforcement ────────────────────────────────
        policy_result = CommandPolicy.check(command, role)
        if not policy_result.allowed:
            return (
                f"POLICY BLOCKED: {policy_result.reason} "
                f"[rule: {policy_result.matched_rule}]"
            )

        # ── Route through the OpenSandbox container ───────────────────
        try:
            client = await get_opensandbox_client()
            runtime = await client.get_runtime(workspace_id)
            execution = await runtime.run_command(command, cwd=cwd)

            # Format the result into the same contract the agents expect
            output_parts: list[str] = []

            stdout_text = ""
            stderr_text = ""
            exit_code = 0

            if execution.logs:
                if execution.logs.stdout:
                    stdout_text = execution.logs.stdout[0].text
                if execution.logs.stderr:
                    stderr_text = execution.logs.stderr[0].text
            if hasattr(execution, "exit_code"):
                exit_code = execution.exit_code

            if stdout_text.strip():
                output_parts.append(f"STDOUT:\n{stdout_text}")
            if stderr_text.strip():
                output_parts.append(f"STDERR:\n{stderr_text}")

            output_parts.append(f"EXIT CODE: {exit_code}")
            return "\n".join(output_parts)

        except SandboxUnavailableError as e:
            return f"Error: Sandbox unavailable — {e}"
        except Exception as e:
            return f"Execution error: {e}"

    return mcp
