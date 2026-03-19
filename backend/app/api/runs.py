# ==========================================
# Author: Hieu Nguyen - Codev Team
# Email: hieuit095@gmail.com
# Project: ZeroCode - Autonomous Multi-Agent IDE
# ==========================================
"""
Run lifecycle REST endpoints.

- POST /api/runs         — create a new run
- GET  /api/runs/{runId}/snapshot — current run status
- POST /api/runs/{runId}/cancel  — cancel an active run
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit, urlunsplit

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ..orchestrator.run_manager import RunManager, get_run_manager

router = APIRouter(prefix="/api/runs", tags=["runs"])


def _normalize_openai_compatible_url(base_url: str | None, default_path: str) -> str:
    """
    Accept either an API root or a full endpoint URL for OpenAI-compatible providers.

    Examples:
      - https://api.together.xyz/v1 -> https://api.together.xyz/v1/chat/completions
      - https://api.together.xyz/v1/chat/completions -> unchanged
    """
    if not base_url:
        return default_path

    parsed = urlsplit(base_url)
    path = parsed.path.rstrip("/")
    if path.endswith("/chat/completions") or path.endswith("/messages"):
        return base_url

    normalized_path = f"{path}/chat/completions" if path else "/chat/completions"
    return urlunsplit((parsed.scheme, parsed.netloc, normalized_path, parsed.query, parsed.fragment))


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
    Return the current status of a run from the DATABASE (single source of truth).
    """
    snapshot = await manager.get_run_snapshot(run_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    return snapshot


@router.post("/{run_id}/cancel", response_model=RunCancelResponse)
async def cancel_run(
    run_id: str,
    body: RunCancelRequest | None = None,
    manager: RunManager = Depends(get_run_manager),
) -> RunCancelResponse:
    """Cancel an active run."""

    reason = body.reason if body else "user_cancelled"
    result = await manager.cancel_run(run_id, reason)
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


# ─── LLM Connection Test ──────────────────────────────────────────────────────


class TestConnectionRequest(BaseModel):
    provider: str = Field(..., min_length=1)
    key: str = Field(..., min_length=1)
    base_url: str | None = Field(default=None, alias="baseUrl")

    model_config = {"populate_by_name": True}


class TestConnectionResponse(BaseModel):
    success: bool
    message: str
    provider: str


@router.post("/test-connection", response_model=TestConnectionResponse)
async def test_connection(payload: TestConnectionRequest) -> TestConnectionResponse:
    """
    Test an LLM provider connection by making a minimal API call.

    Accepts provider credentials, instantiates a lightweight client,
    sends a test query, and returns 200 OK or 400 Bad Request.
    """
    import httpx

    provider = payload.provider.lower()
    api_key = payload.key

    # Map providers to their test endpoints and request formats
    provider_configs: dict[str, dict[str, Any]] = {
        "openai": {
            "url": _normalize_openai_compatible_url(
                payload.base_url,
                "https://api.openai.com/v1/chat/completions",
            ),
            "headers": {"Authorization": f"Bearer {api_key}"},
            "json": {
                "model": "gpt-3.5-turbo",
                "messages": [{"role": "user", "content": "Hi"}],
                "max_tokens": 1,
            },
        },
        "anthropic": {
            "url": payload.base_url or "https://api.anthropic.com/v1/messages",
            "headers": {
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
            },
            "json": {
                "model": "claude-3-haiku-20240307",
                "max_tokens": 1,
                "messages": [{"role": "user", "content": "Hi"}],
            },
        },
        "google": {
            "url": (
                payload.base_url
                or f"https://generativelanguage.googleapis.com/v1beta/models/"
                   f"gemini-1.5-flash:generateContent?key={api_key}"
            ),
            "headers": {},
            "json": {
                "contents": [{"parts": [{"text": "Hi"}]}],
                "generationConfig": {"maxOutputTokens": 1},
            },
        },
        "together": {
            "url": _normalize_openai_compatible_url(
                payload.base_url,
                "https://api.together.xyz/v1/chat/completions",
            ),
            "headers": {"Authorization": f"Bearer {api_key}"},
            "json": {
                "model": "openai/gpt-oss-20b",
                "messages": [{"role": "user", "content": "Hi"}],
                "max_tokens": 1,
            },
        },
        "groq": {
            "url": payload.base_url or "https://api.groq.com/openai/v1/chat/completions",
            "headers": {"Authorization": f"Bearer {api_key}"},
            "json": {
                "model": "llama-3.1-8b-instant",
                "messages": [{"role": "user", "content": "Hi"}],
                "max_tokens": 1,
            },
        },
        "mistral": {
            "url": payload.base_url or "https://api.mistral.ai/v1/chat/completions",
            "headers": {"Authorization": f"Bearer {api_key}"},
            "json": {
                "model": "mistral-small-latest",
                "messages": [{"role": "user", "content": "Hi"}],
                "max_tokens": 1,
            },
        },
    }

    # Default: treat unknown providers as OpenAI-compatible
    config = provider_configs.get(provider, {
        "url": _normalize_openai_compatible_url(
            payload.base_url,
            "https://api.openai.com/v1/chat/completions",
        ),
        "headers": {"Authorization": f"Bearer {api_key}"},
        "json": {
            "model": "gpt-3.5-turbo",
            "messages": [{"role": "user", "content": "Hi"}],
            "max_tokens": 1,
        },
    })

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                config["url"],
                headers=config["headers"],
                json=config["json"],
            )

        if resp.status_code in (200, 201):
            return TestConnectionResponse(
                success=True,
                message="API key valid — connection successful.",
                provider=payload.provider,
            )

        # Parse error detail from response
        try:
            error_body = resp.json()
            detail = (
                error_body.get("error", {}).get("message")
                or error_body.get("message")
                or resp.text[:200]
            )
        except Exception:
            detail = resp.text[:200]

        return TestConnectionResponse(
            success=False,
            message=f"Connection failed ({resp.status_code}): {detail}",
            provider=payload.provider,
        )

    except httpx.TimeoutException:
        return TestConnectionResponse(
            success=False,
            message="Connection timed out after 15 seconds.",
            provider=payload.provider,
        )
    except Exception as e:
        return TestConnectionResponse(
            success=False,
            message=f"Connection error: {str(e)}",
            provider=payload.provider,
        )
