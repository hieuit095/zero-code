"""
Workspace file system REST endpoints (read-only, containerized).

OPENSANDBOX MIGRATION: These endpoints now use OpenSandboxClient which
provisions real Docker containers per workspace. All file operations are
routed through the container — no host-side file I/O occurs.

- GET /api/workspaces/{workspaceId}/tree  — file tree
- GET /api/workspaces/{workspaceId}/file  — single file content
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from ..services.openhands_client import get_opensandbox_client

router = APIRouter(prefix="/api/workspaces", tags=["workspaces"])


@router.get("/{workspace_id}/tree")
async def get_workspace_tree(
    workspace_id: str,
) -> dict:
    """Return the file tree of a workspace from the sandbox container."""
    client = await get_opensandbox_client()
    tree = await client.list_tree(workspace_id)
    return {"workspaceId": workspace_id, "tree": tree}


@router.get("/{workspace_id}/file")
async def get_workspace_file(
    workspace_id: str,
    path: str = Query(..., description="File path relative to workspace root"),
) -> dict:
    """Return the content of a single file from the workspace container."""
    client = await get_opensandbox_client()
    content = await client.read_file(workspace_id, path)
    return {"workspaceId": workspace_id, "path": path, "content": content}

