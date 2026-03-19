# ==========================================
# Author: Hieu Nguyen - Codev Team
# Email: hieuit095@gmail.com
# Project: ZeroCode - Autonomous Multi-Agent IDE
# ==========================================
"""
Internal MCP (Model Context Protocol) facade for Nanobot agents.

PHASE 2 RESTORATION + SECURITY FIX: This module mounts role-scoped FastMCP
servers on the FastAPI application, providing standardized MCP tool discovery
for agents.

Each role (dev, qa, tech-lead) gets a dedicated endpoint with its own
CommandPolicy enforcement:
  - /internal/mcp/dev/sse       — Dev agent (broader file/exec access)
  - /internal/mcp/qa/sse        — QA agent (read-only + linting/testing)
  - /internal/mcp/tech-lead/sse — Tech Lead agent

SECURITY FIX (ALIGNMENT_AUDIT_REPORT §4):
  router.mount() bypasses FastAPI's dependency injection, so a standard
  Depends(require_mcp_auth) on the router would NEVER execute for SSE
  requests hitting the mounted ASGI sub-apps.

  Solution: Each FastMCP SSE app is wrapped in a `JWTAuthMiddleware` —
  a lightweight ASGI middleware that intercepts every request BEFORE it
  reaches the FastMCP layer. It:
    1. Extracts the Authorization Bearer token from the request headers.
    2. Validates signature, expiry, and purpose via `validate_mcp_token()`.
    3. Verifies the run is still active in the DATABASE via
       `_verify_run_is_active()`.
    4. Returns 401 Unauthorized immediately if any check fails.

  This closes the critical vulnerability where MCP endpoints were
  completely unauthenticated.

Agents connect to these endpoints via their `mcp_config` to discover
and invoke sandbox tools (read_file, write_file, exec) through the
standard MCP protocol.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import APIRouter, FastAPI
from starlette.types import ASGIApp, Receive, Scope, Send

from ..agents.mcp_tools import create_mcp_server
from ..config import get_settings
from ..core.security import validate_mcp_token, _verify_run_is_active

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/internal/mcp", tags=["mcp-internal"])


# ─── JWT Authentication ASGI Middleware ───────────────────────────────────────


class JWTAuthMiddleware:
    """
    ASGI middleware that enforces JWT Bearer authentication on every
    request before forwarding to the wrapped FastMCP SSE application.

    Because router.mount() injects raw ASGI sub-apps that bypass
    FastAPI's Depends() system entirely, this middleware is the ONLY
    enforcement point for MCP endpoint authentication.

    Validation chain:
      1. Extract `Authorization: Bearer <token>` header.
      2. Decode and validate JWT (signature, expiry, purpose claim).
      3. Verify the run_id from the token is active in PostgreSQL.
      4. If any step fails → 401 Unauthorized (JSON body).
      5. If all pass → forward request to the inner ASGI app.
    """

    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        # Only gate HTTP and WebSocket requests; let lifespan pass through.
        if scope["type"] not in ("http", "websocket"):
            await self._app(scope, receive, send)
            return

        # ── Extract Bearer token from headers ─────────────────────────
        headers = dict(scope.get("headers", []))
        auth_value = headers.get(b"authorization", b"").decode("utf-8", errors="ignore")

        if not auth_value.lower().startswith("bearer "):
            await self._send_401(send, "MCP facade requires a valid Bearer token. No token provided.")
            return

        token = auth_value[7:].strip()
        if not token:
            await self._send_401(send, "MCP facade requires a valid Bearer token. Token is empty.")
            return

        # ── Validate JWT (signature, expiry, purpose) ─────────────────
        try:
            payload = validate_mcp_token(token)
        except Exception as exc:
            detail = getattr(exc, "detail", str(exc))
            await self._send_401(send, f"JWT validation failed: {detail}")
            return

        # ── Verify run is active in DATABASE ──────────────────────────
        run_id = payload.get("sub", "")
        try:
            await _verify_run_is_active(run_id)
        except Exception as exc:
            detail = getattr(exc, "detail", str(exc))
            await self._send_401(send, f"Run validation failed: {detail}")
            return

        # ── All checks passed — forward to inner FastMCP app ─────────
        await self._app(scope, receive, send)

    @staticmethod
    async def _send_401(send: Send, detail: str) -> None:
        """Send a minimal 401 Unauthorized JSON response."""
        body = json.dumps({"detail": detail}).encode("utf-8")
        await send({
            "type": "http.response.start",
            "status": 401,
            "headers": [
                [b"content-type", b"application/json"],
                [b"content-length", str(len(body)).encode()],
            ],
        })
        await send({
            "type": "http.response.body",
            "body": body,
        })


# ─── Mount Role-Scoped MCP Servers (JWT-Protected) ───────────────────────────

_settings = get_settings()
_workspace_root = str(_settings.workspace_path / "repo-main")

# Each role gets its own FastMCP server with appropriate CommandPolicy scoping.
# The `.sse_app()` method returns a Starlette ASGI app that handles the
# MCP SSE transport protocol.

_dev_mcp = create_mcp_server(_workspace_root, role="dev")
_qa_mcp = create_mcp_server(_workspace_root, role="qa")
_lead_mcp = create_mcp_server(_workspace_root, role="tech-lead")

def mount_mcp_facade(app: FastAPI) -> None:
    """
    Mount the JWT-protected FastMCP sub-apps directly on the FastAPI app.

    APIRouter.mount() is not surfaced by app.include_router(), so these mounts
    must happen at the application level to make /internal/mcp/* reachable.
    """
    app.mount("/internal/mcp/dev", app=JWTAuthMiddleware(_dev_mcp.sse_app()))
    app.mount("/internal/mcp/qa", app=JWTAuthMiddleware(_qa_mcp.sse_app()))
    app.mount("/internal/mcp/tech-lead", app=JWTAuthMiddleware(_lead_mcp.sse_app()))

logger.info(
    "MCP Facade mounted (JWT-protected): /internal/mcp/{dev,qa,tech-lead}/sse "
    "(default workspace fallback: %s)", _workspace_root,
)
