"""
Internal MCP (Model Context Protocol) facade for Nanobot agents.

Security layers:
  1. JWT authentication via require_mcp_auth (core/security.py)
  2. Command policy enforcement (services/command_policy.py)
  3. Audit logging for every operation (db/models.py AuditLogModel)

These endpoints are NOT for the frontend client (Rule 1, Rule 2).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Header
from pydantic import BaseModel, Field

from ..core.security import require_mcp_auth
from ..db.database import async_session
from ..db.models import AuditLogModel
from ..orchestrator.run_manager import RunManager, get_run_manager
from ..services.command_policy import CommandPolicy
from ..services.openhands_client import OpenHandsClient, get_openhands_client

router = APIRouter(prefix="/internal/mcp", tags=["mcp-internal"])
logger = logging.getLogger(__name__)


# ─── Request / Response Models ────────────────────────────────────────────────


class MCPReadFileRequest(BaseModel):
    path: str = Field(..., description="File path relative to workspace root")


class MCPReadFileResponse(BaseModel):
    path: str
    content: str
    workspace_id: str = Field(alias="workspaceId")

    model_config = {"populate_by_name": True}


class MCPWriteFileRequest(BaseModel):
    path: str = Field(..., description="File path relative to workspace root")
    content: str


class MCPWriteFileResponse(BaseModel):
    path: str
    success: bool
    workspace_id: str = Field(alias="workspaceId")

    model_config = {"populate_by_name": True}


class MCPExecRequest(BaseModel):
    command: str
    cwd: str = "/workspace"
    agent_role: str = Field(default="dev", alias="agentRole")

    model_config = {"populate_by_name": True}


class MCPExecResponse(BaseModel):
    exit_code: int = Field(alias="exitCode")
    stdout: str
    stderr: str
    duration_ms: int = Field(alias="durationMs")

    model_config = {"populate_by_name": True}


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _resolve_workspace_id(
    run_id: str,
    manager: RunManager,
) -> str:
    """Extract workspace_id from a run. Raises 404 if run not found."""
    snapshot = manager.get_run_snapshot(run_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    return snapshot.get("workspace_id", "repo-main")


async def _audit_log(
    run_id: str, agent_role: str, action: str, target: str,
    status: str, reason: str | None = None,
) -> None:
    """Persist an audit log entry (fire-and-forget)."""
    try:
        async with async_session() as session:
            entry = AuditLogModel(
                run_id=run_id, agent_role=agent_role, action=action,
                target=target, status=status, reason=reason,
            )
            session.add(entry)
            await session.commit()
    except Exception:
        logger.exception("Failed to write audit log for run %s", run_id)


# ─── Endpoints ────────────────────────────────────────────────────────────────


@router.post("/read_file", response_model=MCPReadFileResponse)
async def mcp_read_file(
    body: MCPReadFileRequest,
    run_id: str = Depends(require_mcp_auth),
    manager: RunManager = Depends(get_run_manager),
    client: OpenHandsClient = Depends(get_openhands_client),
) -> MCPReadFileResponse:
    """Read a file from the run's workspace."""
    workspace_id = _resolve_workspace_id(run_id, manager)
    content = await client.read_file(workspace_id, body.path)

    await _audit_log(run_id, "unknown", "read_file", body.path, "allowed")

    return MCPReadFileResponse(
        path=body.path,
        content=content,
        workspaceId=workspace_id,
    )


@router.post("/write_file", response_model=MCPWriteFileResponse)
async def mcp_write_file(
    body: MCPWriteFileRequest,
    run_id: str = Depends(require_mcp_auth),
    manager: RunManager = Depends(get_run_manager),
    client: OpenHandsClient = Depends(get_openhands_client),
) -> MCPWriteFileResponse:
    """Write a file to the run's workspace."""
    workspace_id = _resolve_workspace_id(run_id, manager)
    success = await client.write_file(workspace_id, body.path, body.content)

    await _audit_log(run_id, "unknown", "write_file", body.path, "allowed")

    return MCPWriteFileResponse(
        path=body.path,
        success=success,
        workspaceId=workspace_id,
    )


@router.post("/exec", response_model=MCPExecResponse)
async def mcp_exec(
    body: MCPExecRequest,
    run_id: str = Depends(require_mcp_auth),
    manager: RunManager = Depends(get_run_manager),
    client: OpenHandsClient = Depends(get_openhands_client),
) -> MCPExecResponse:
    """Execute a command in the run's workspace with safety enforcement."""

    # ── Command Policy Check ─────────────────────────────────
    policy_result = CommandPolicy.check(body.command, body.agent_role)

    if not policy_result.allowed:
        logger.warning(
            "BLOCKED command for run=%s role=%s: %s (reason: %s)",
            run_id, body.agent_role, body.command, policy_result.reason,
        )
        await _audit_log(
            run_id, body.agent_role, "exec", body.command,
            "blocked", policy_result.reason,
        )

        # Return structured error matching tool format (Rule 3)
        error = policy_result.to_exec_error()
        return MCPExecResponse(
            exitCode=error["exitCode"],
            stdout=error["stdout"],
            stderr=error["stderr"],
            durationMs=error["durationMs"],
        )

    # ── Execute ──────────────────────────────────────────────
    workspace_id = _resolve_workspace_id(run_id, manager)
    result = await client.execute_command(workspace_id, body.command, body.cwd)

    await _audit_log(run_id, body.agent_role, "exec", body.command, "allowed")

    return MCPExecResponse(
        exitCode=result["exit_code"],
        stdout=result["stdout"],
        stderr=result["stderr"],
        durationMs=result["duration_ms"],
    )
