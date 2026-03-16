"""
Workspace file system REST endpoints (proxied through OpenHands client).

- GET /api/workspaces/{workspaceId}/tree  — file tree
- GET /api/workspaces/{workspaceId}/file  — single file content
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from ..services.openhands_client import OpenHandsClient, get_openhands_client

router = APIRouter(prefix="/api/workspaces", tags=["workspaces"])


@router.get("/{workspace_id}/tree")
async def get_workspace_tree(
    workspace_id: str,
    client: OpenHandsClient = Depends(get_openhands_client),
) -> dict:
    """Return the file tree of a workspace from the OpenHands sandbox."""

    tree = await client.list_tree(workspace_id)
    return {"workspaceId": workspace_id, "tree": tree}


@router.get("/{workspace_id}/file")
async def get_workspace_file(
    workspace_id: str,
    path: str = Query(..., description="File path relative to workspace root"),
    client: OpenHandsClient = Depends(get_openhands_client),
) -> dict:
    """Return the content of a single file from the OpenHands sandbox."""

    content = await client.read_file(workspace_id, path)
    return {"workspaceId": workspace_id, "path": path, "content": content}
