# ==========================================
# Author: Hieu Nguyen - Codev Team
# Email: hieuit095@gmail.com
# Project: ZeroCode - Autonomous Multi-Agent IDE
# ==========================================
"""
Workspace file system REST endpoints (read-only, host-side).

PHASE 1 REFACTOR: These endpoints now use WorkspaceFS (a lightweight,
read-only host filesystem service) instead of OpenHandsClient (which
previously spawned a competing LocalRuntime). Only the background worker
orchestrator manages SDK Runtimes.

- GET /api/workspaces/{workspaceId}/tree  — file tree
- GET /api/workspaces/{workspaceId}/file  — single file content
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from ..services.openhands_client import WorkspaceFS, get_workspace_fs

router = APIRouter(prefix="/api/workspaces", tags=["workspaces"])


@router.get("/{workspace_id:path}/tree")
async def get_workspace_tree(
    workspace_id: str,
    fs: WorkspaceFS = Depends(get_workspace_fs),
) -> dict:
    """Return the file tree of a workspace from the host filesystem."""

    tree = await fs.list_tree(workspace_id)
    return {"workspaceId": workspace_id, "tree": tree}


@router.get("/{workspace_id:path}/file")
async def get_workspace_file(
    workspace_id: str,
    path: str = Query(..., description="File path relative to workspace root"),
    fs: WorkspaceFS = Depends(get_workspace_fs),
) -> dict:
    """Return the content of a single file from the workspace."""

    content = await fs.read_file(workspace_id, path)
    return {"workspaceId": workspace_id, "path": path, "content": content}
