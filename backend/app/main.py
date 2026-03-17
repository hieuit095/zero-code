"""
FastAPI application factory for the Multi-Agent IDE backend.

This is the entry point — run with:
    uvicorn app.main:app --reload --port 8000

All routers are included here. No business logic lives in this file.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.admin import router as admin_router
from .api.mcp import router as mcp_router
from .api.runs import router as runs_router
from .api.settings import router as settings_router
from .api.workspaces import router as workspaces_router
from .api.ws import router as ws_router
from .config import get_settings
from .db.database import init_db
from .services.event_broker import get_event_broker

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize DB and Redis on startup, close Redis on shutdown (Rule 3)."""
    await init_db()

    broker = get_event_broker()
    await broker.connect()
    logger.info("Redis event broker connected")

    yield

    await broker.close()
    logger.info("Redis event broker closed")


app = FastAPI(
    title="Zero Code Backend",
    version="0.4.0",
    description="Transport backend for the Multi-Agent IDE. Manages runs, "
    "WebSocket event streaming, and OpenHands sandbox access.",
    lifespan=lifespan,
)

# ─── CORS ─────────────────────────────────────────────────────────────────────

settings = get_settings()

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Routers ──────────────────────────────────────────────────────────────────

app.include_router(runs_router)
app.include_router(workspaces_router)
app.include_router(ws_router)
app.include_router(mcp_router)
app.include_router(admin_router)
app.include_router(settings_router)


# ─── Health ───────────────────────────────────────────────────────────────────


@app.get("/health")
async def healthcheck() -> dict[str, str]:
    return {"status": "ok"}
