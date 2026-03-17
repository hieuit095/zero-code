"""
Internal MCP Facade — FastMCP server exposing jailed workspace tools.

PHASE 2 REFACTOR: This module implements the mandated MCP service boundary.
Instead of tightly-coupled native SDK ToolDefinitions, workspace tools
(read_file, write_file, exec) are exposed as a proper MCP server over SSE.

Agents discover and invoke these tools through standard MCP protocol
via their `mcp_config`, enforcing the architectural boundary between
agent cognition and sandbox operations.

SECURITY INVARIANTS PRESERVED:
  - `_jail_path()`: os.path.realpath()-based symlink jailing
  - `CommandPolicy.check()`: role-based command blocklist/allowlist
  - Role-scoped exec: each role gets its own MCP server instance
"""

from __future__ import annotations

import logging
import os
import posixpath
import subprocess

from mcp.server.fastmcp import FastMCP

from ..services.command_policy import CommandPolicy

logger = logging.getLogger(__name__)


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
            f"read/write and command execution within the workspace jail."
        ),
    )

    # ─── read_file ────────────────────────────────────────────────────

    @mcp.tool()
    def read_file(path: str) -> str:
        """
        Securely read a file from the workspace.

        Path is validated against the workspace jail to prevent symlink
        escapes and directory traversal. Use /workspace/... paths.

        Args:
            path: File path relative to workspace root (e.g. /workspace/src/main.py)

        Returns:
            The full text content of the file.
        """
        try:
            safe_path = _jail_path(workspace_root, path)
            with open(safe_path, "r", encoding="utf-8") as f:
                return f.read()
        except ValueError as e:
            return f"Error: {e}"
        except FileNotFoundError:
            return f"Error: File not found: {path}"
        except Exception as e:
            return f"Error reading file: {e}"

    # ─── write_file ───────────────────────────────────────────────────

    @mcp.tool()
    def write_file(path: str, content: str) -> str:
        """
        Securely write a complete file to the workspace.

        Creates parent directories if they don't exist. Path is validated
        against the workspace jail to prevent symlink escapes.

        Args:
            path: File path relative to workspace root (e.g. /workspace/src/main.py)
            content: Full text content to write to the file.

        Returns:
            Success message or error description.
        """
        try:
            safe_path = _jail_path(workspace_root, path)
            os.makedirs(os.path.dirname(safe_path), exist_ok=True)
            with open(safe_path, "w", encoding="utf-8") as f:
                f.write(content)
            return "File written successfully."
        except ValueError as e:
            return f"Error: {e}"
        except Exception as e:
            return f"Write failed: {e}"

    # ─── exec ─────────────────────────────────────────────────────────

    @mcp.tool()
    def exec(command: str, cwd: str = "/workspace") -> str:
        """
        Execute a shell command inside the workspace with policy enforcement.

        The command is checked against the role-based security policy before
        execution. Destructive commands (rm -rf /, sudo, etc.) are blocked.
        The working directory is jail-validated to prevent escapes.

        Args:
            command: Shell command to execute.
            cwd: Working directory (default: /workspace).

        Returns:
            Command output (stdout + stderr) and exit code.
        """
        # Command Policy Enforcement
        policy_result = CommandPolicy.check(command, role)
        if not policy_result.allowed:
            return f"POLICY BLOCKED: {policy_result.reason} [rule: {policy_result.matched_rule}]"

        # Jail cwd against traversal/symlinks
        try:
            _jail_path(workspace_root, cwd)
        except ValueError as e:
            return f"CWD jail escape detected: {e}"

        # Resolve host-side cwd
        if cwd.startswith("/workspace/"):
            relative_cwd = cwd[len("/workspace/"):]
        elif cwd == "/workspace":
            relative_cwd = "."
        else:
            relative_cwd = cwd

        host_cwd = os.path.join(
            os.path.realpath(workspace_root),
            os.path.normpath(relative_cwd),
        )

        # Additional traversal guard
        parts = cwd.split("/")
        if ".." in parts or cwd == "/" or cwd.startswith("/etc"):
            return "Error: Invalid cwd inside container"

        # Execute via subprocess (within the jailed host directory)
        try:
            result = subprocess.run(
                command,
                shell=True,
                cwd=host_cwd,
                capture_output=True,
                text=True,
                timeout=120,
            )
            output_parts = []
            if result.stdout.strip():
                output_parts.append(f"STDOUT:\n{result.stdout}")
            if result.stderr.strip():
                output_parts.append(f"STDERR:\n{result.stderr}")
            output_parts.append(f"EXIT CODE: {result.returncode}")
            return "\n".join(output_parts)
        except subprocess.TimeoutExpired:
            return "Error: Command timed out after 120 seconds"
        except Exception as e:
            return f"Execution error: {e}"

    return mcp
