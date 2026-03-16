"""
Run lifecycle REST endpoints.

- POST /api/runs         — create a new run
- GET  /api/runs/{runId}/snapshot — current run status
- POST /api/runs/{runId}/cancel  — cancel an active run
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ..orchestrator.run_manager import RunManager, get_run_manager

router = APIRouter(prefix="/api/runs", tags=["runs"])


# ─── Request / Response Models ────────────────────────────────────────────────


class RunCreateRequest(BaseModel):
    goal: str = Field(..., min_length=1)
    workspace_id: str = Field(default="repo-main", min_length=1, alias="workspaceId")
    agent_config: dict[str, dict[str, Any]] | None = Field(default=None, alias="agentConfig")
    limits: dict[str, Any] | None = None

    model_config = {"populate_by_name": True}


class RunCreateResponse(BaseModel):
    run_id: str = Field(alias="runId")
    workspace_id: str = Field(alias="workspaceId")
    status: str
    ws_url: str = Field(alias="wsUrl")

    model_config = {"populate_by_name": True}


class RunSnapshotResponse(BaseModel):
    run_id: str = Field(alias="runId")
    status: str
    phase: str | None = None
    progress: int = 0

    model_config = {"populate_by_name": True}


class RunCancelRequest(BaseModel):
    reason: str = "user_cancelled"


class RunCancelResponse(BaseModel):
    run_id: str = Field(alias="runId")
    status: str
    message: str

    model_config = {"populate_by_name": True}


# ─── Endpoints ────────────────────────────────────────────────────────────────


@router.post("", response_model=RunCreateResponse)
async def create_run(
    payload: RunCreateRequest,
    request: Request,
    manager: RunManager = Depends(get_run_manager),
) -> RunCreateResponse:
    """Create a new run, launch the orchestration loop, return the WS URL."""

    run = await manager.create_run(
        goal=payload.goal,
        workspace_id=payload.workspace_id,
        agent_config=payload.agent_config,
    )

    # Enqueue to Redis for the background worker (Rule 2: no blocking in API)
    from ..services.event_broker import get_event_broker
    broker = get_event_broker()
    await broker.enqueue_run(run["run_id"])

    ws_url = request.url_for("run_websocket", run_id=run["run_id"])
    ws_scheme = "wss" if ws_url.scheme == "https" else "ws"

    return RunCreateResponse(
        runId=run["run_id"],
        workspaceId=run["workspace_id"],
        status=run["status"],
        wsUrl=str(ws_url.replace(scheme=ws_scheme)),
    )


@router.get("/{run_id}/snapshot")
async def get_run_snapshot(
    run_id: str,
    manager: RunManager = Depends(get_run_manager),
) -> dict:
    """
    Return the current status of a run.

    Tries in-memory first (active run), then falls back to DB
    (for rehydration after browser refresh or server restart).
    """
    # 1. Try in-memory (active run)
    snapshot = manager.get_run_snapshot(run_id)
    if snapshot is not None:
        return {
            "runId": snapshot["run_id"],
            "status": snapshot["status"],
            "phase": snapshot.get("phase"),
            "progress": snapshot.get("progress", 0),
            "tasks": snapshot.get("tasks", []),
        }

    # 2. Fall back to DB
    from ..db.database import async_session
    from ..services.run_store import RunStore

    async with async_session() as session:
        db_snapshot = await RunStore.get_run_snapshot(session, run_id)

    if db_snapshot is None:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

    return db_snapshot


@router.post("/{run_id}/cancel", response_model=RunCancelResponse)
async def cancel_run(
    run_id: str,
    body: RunCancelRequest | None = None,
    manager: RunManager = Depends(get_run_manager),
) -> RunCancelResponse:
    """Cancel an active run."""

    reason = body.reason if body else "user_cancelled"
    result = manager.cancel_run(run_id, reason)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

    return RunCancelResponse(
        runId=run_id,
        status=result["status"],
        message=result["message"],
    )


@router.get("/{run_id}/metrics")
async def get_run_metrics(run_id: str) -> dict:
    """
    Return summary metrics for a run.

    Queries EventLog and Task tables for:
    - totalDurationMs, qaFailureCount, totalCommandsExecuted, tasksCompleted
    """
    from ..db.database import async_session
    from ..services.run_store import RunStore

    async with async_session() as session:
        metrics = await RunStore.get_run_metrics(session, run_id)

    if metrics is None:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

    return metrics
