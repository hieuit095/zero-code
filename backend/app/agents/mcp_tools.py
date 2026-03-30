# ==========================================
# Author: Hieu Nguyen - Codev Team
# Email: hieuit095@gmail.com
# Project: ZeroCode - Autonomous Multi-Agent IDE
# ==========================================
"""
Internal MCP facade exposing jailed workspace tools through OpenHands.

Each mounted MCP server is role-scoped, but the workspace is resolved per
request from the authenticated MCP token. This preserves run-scoped sandbox
isolation even though the FastMCP apps are mounted once at API startup.
"""

from __future__ import annotations

import logging
import os

from mcp.server.fastmcp import Context, FastMCP

from ..config import get_settings
from ..core.security import validate_mcp_token
from ..services.command_policy import CommandPolicy
from ..services.openhands_client import (
    SandboxUnavailableError,
    get_openhands_client,
)

logger = logging.getLogger(__name__)

_SDK_AVAILABLE = False

# P1-D FIX: Per-workspace MCP tool call counter for rate limiting.
# Tracks calls per workspace_id. Resets when a new run uses a fresh workspace.
# Limit: 15 MCP tool calls per workspace per planning loop.
_MCP_CALL_COUNTER: dict[str, int] = {}
_MCP_RATE_LIMIT = 15

try:
    from openhands.tools.terminal import TerminalAction  # noqa: F401

    _SDK_AVAILABLE = True
except ImportError:
    logger.warning(
        "OpenHands SDK not installed - MCP tools will be unavailable. "
        "Install with: pip install openhands-sdk openhands-tools"
    )


def _jail_path(workspace_root: str, requested_path: str) -> str:
    """Resolve a workspace path and verify it remains within the jail."""
    if "\x00" in requested_path:
        raise ValueError("Path contains null bytes")

    abs_root = os.path.realpath(workspace_root)

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

    full_path = os.path.join(abs_root, os.path.normpath(relative))
    real_full_path = os.path.realpath(full_path)

    if not real_full_path.startswith(abs_root) and real_full_path != abs_root:
        raise ValueError(
            f"Path traversal blocked: '{requested_path}' escapes workspace jail"
        )

    return real_full_path


def create_mcp_server(workspace_root: str, role: str) -> FastMCP:
    """
    Create a role-scoped FastMCP server with secure workspace tools.

    The passed workspace_root is only the fallback workspace for legacy tokens.
    Real runs should resolve their workspace from the authenticated JWT claim.
    """
    mcp = FastMCP(
        name=f"zero-code-sandbox-{role}",
        instructions=(
            f"Sandbox tools for the {role} agent. Provides secure file "
            f"read/write and command execution within the workspace jail. "
            f"All operations are executed through the OpenHands SDK."
        ),
    )
    default_workspace_id = os.path.basename(os.path.realpath(workspace_root))
    workspace_base = get_settings().workspace_path

    def _extract_auth_token(ctx: Context | None) -> str | None:
        if ctx is None:
            return None

        request = getattr(ctx.request_context, "request", None)
        headers = getattr(request, "headers", None)
        auth_value: str | None = None

        if headers is not None:
            auth_value = headers.get("authorization")
        elif request is not None:
            scope = getattr(request, "scope", {}) or {}
            raw_headers = dict(scope.get("headers", []))
            raw_auth = raw_headers.get(b"authorization", b"")
            auth_value = raw_auth.decode("utf-8", errors="ignore")

        if not auth_value or not auth_value.lower().startswith("bearer "):
            return None

        token = auth_value[7:].strip()
        return token or None

    def _normalize_workspace_id(workspace_id: str | None) -> str:
        candidate = (workspace_id or "").strip()
        if not candidate:
            return default_workspace_id

        normalized = candidate.replace("\\", "/")
        if normalized in {".", ".."} or "/" in normalized:
            raise ValueError(f"Invalid workspace_id in MCP token: {candidate}")
        return normalized

    def _resolve_workspace(workspace_ctx: Context | None) -> tuple[str, str]:
        workspace_id = default_workspace_id
        token = _extract_auth_token(workspace_ctx)
        if token:
            payload = validate_mcp_token(token)
            workspace_id = _normalize_workspace_id(payload.get("workspace_id"))

        return workspace_id, str(workspace_base / workspace_id)

    @mcp.tool(name="workspace_read_file")
    def read_file(path: str, ctx: Context | None = None) -> str:
        if not _SDK_AVAILABLE:
            return "Error: OpenHands SDK is not installed. Cannot read files."

        try:
            workspace_id, resolved_workspace_root = _resolve_workspace(ctx)

            # P1-D FIX: Rate limit check — abort if workspace exceeded 15 calls.
            # Also reset counter for a fresh workspace (new run).
            _MCP_CALL_COUNTER[workspace_id] = _MCP_CALL_COUNTER.get(workspace_id, 0) + 1
            if _MCP_CALL_COUNTER[workspace_id] > _MCP_RATE_LIMIT:
                raise RuntimeError(
                    f"Rate limit exceeded for MCP tools: {workspace_id} made "
                    f"{_MCP_CALL_COUNTER[workspace_id]} calls (max={_MCP_RATE_LIMIT}). "
                    f"Halt to prevent prompt-injection abuse."
                )

            # P1-D FIX: Audit log before executing.
            logger.info(
                "AUDIT: Leader executed workspace_read_file with path=%s workspace_id=%s",
                path, workspace_id,
            )

            _jail_path(resolved_workspace_root, path)
            runtime = get_openhands_client().get_runtime(workspace_id)
            return runtime.read_file(path)
        except SandboxUnavailableError as e:
            return f"Error: Sandbox unavailable - {e}"
        except ValueError as e:
            return f"Error: {e}"
        except RuntimeError:
            raise  # Rate limit error — re-raise to stop the planning loop
        except Exception as e:
            return f"Error reading file: {e}"

    @mcp.tool(name="workspace_write_file")
    def write_file(path: str, content: str, ctx: Context | None = None) -> str:
        if not _SDK_AVAILABLE:
            return "Error: OpenHands SDK is not installed. Cannot write files."

        try:
            workspace_id, resolved_workspace_root = _resolve_workspace(ctx)
            _jail_path(resolved_workspace_root, path)

            runtime = get_openhands_client().get_runtime(workspace_id)
            return runtime.write_file(path, content)
        except SandboxUnavailableError as e:
            return f"Error: Sandbox unavailable - {e}"
        except ValueError as e:
            return f"Error: {e}"
        except Exception as e:
            return f"Write failed: {e}"

    @mcp.tool(name="workspace_exec")
    def exec(command: str, cwd: str = "/workspace", ctx: Context | None = None) -> str:
        if not _SDK_AVAILABLE:
            return "Error: OpenHands SDK is not installed. Cannot execute commands."

        policy_result = CommandPolicy.check(command, role)
        if not policy_result.allowed:
            return (
                f"POLICY BLOCKED: {policy_result.reason} "
                f"[rule: {policy_result.matched_rule}]"
            )

        try:
            workspace_id, resolved_workspace_root = _resolve_workspace(ctx)

            # P1-D FIX: Rate limit check — abort if workspace exceeded 15 calls.
            _MCP_CALL_COUNTER[workspace_id] = _MCP_CALL_COUNTER.get(workspace_id, 0) + 1
            if _MCP_CALL_COUNTER[workspace_id] > _MCP_RATE_LIMIT:
                raise RuntimeError(
                    f"Rate limit exceeded for MCP tools: {workspace_id} made "
                    f"{_MCP_CALL_COUNTER[workspace_id]} calls (max={_MCP_RATE_LIMIT}). "
                    f"Halt to prevent prompt-injection abuse."
                )

            # P1-D FIX: Audit log BEFORE executing.
            logger.info(
                "AUDIT: Leader executed workspace_exec with command=%s cwd=%s workspace_id=%s",
                command, cwd, workspace_id,
            )

            _jail_path(resolved_workspace_root, cwd)
        except ValueError as e:
            return f"CWD jail escape detected: {e}"
        except RuntimeError:
            raise  # Rate limit error — re-raise to stop planning loop

        parts = cwd.split("/")
        if ".." in parts or cwd == "/" or cwd.startswith("/etc"):
            return "Error: Invalid cwd inside container"

        try:
            runtime = get_openhands_client().get_runtime(workspace_id)
            observation = runtime.execute_terminal(command=command, cwd=cwd)

            output_parts: list[str] = []
            if (observation.text or "").strip():
                output_parts.append(f"OUTPUT:\n{observation.text}")
            output_parts.append(f"EXIT CODE: {observation.exit_code}")
            return "\n".join(output_parts)
        except SandboxUnavailableError as e:
            return f"Error: Sandbox unavailable - {e}"
        except Exception as e:
            return f"Execution error: {e}"

    return mcp
