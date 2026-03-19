# ==========================================
# Author: Hieu Nguyen - Codev Team
# Email: hieuit095@gmail.com
# Project: ZeroCode - Autonomous Multi-Agent IDE
# ==========================================
"""
FastAPI application factory for the Multi-Agent IDE backend.

This is the entry point — run with:
    uvicorn app.main:app --reload --port 8000

All routers are included here. No business logic lives in this file.
"""

from __future__ import annotations

import logging
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.admin import router as admin_router
from .api.mcp import mount_mcp_facade
from .api.runs import router as runs_router
from .api.settings import router as settings_router
from .api.workspaces import router as workspaces_router
from .api.ws import router as ws_router
from .config import get_settings
from .db.database import init_db
from .services.event_broker import get_event_broker

logger = logging.getLogger(__name__)

for stream_name in ("stdout", "stderr"):
    stream = getattr(sys, stream_name, None)
    reconfigure = getattr(stream, "reconfigure", None)
    if callable(reconfigure):
        reconfigure(encoding="utf-8", errors="replace")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize DB and Redis on startup, close Redis on shutdown (Rule 3)."""
    settings = get_settings()
    settings.validate_required_secrets()

    await init_db()

    broker = get_event_broker()
    await broker.connect()
    if broker.has_redis:
        logger.info("Redis event broker connected")
    else:
        logger.warning("Running without Redis; using DB-backed queue/event fallback")

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
    allow_origin_regex=settings.cors_origin_regex or None,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Routers ──────────────────────────────────────────────────────────────────

app.include_router(runs_router)
app.include_router(workspaces_router)
app.include_router(ws_router)
app.include_router(admin_router)
app.include_router(settings_router)
mount_mcp_facade(app)


# ─── Health ───────────────────────────────────────────────────────────────────


@app.get("/health")
async def healthcheck() -> dict[str, str]:
    return {"status": "ok"}
