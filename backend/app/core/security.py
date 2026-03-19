# ==========================================
# Author: Hieu Nguyen - Codev Team
# Email: hieuit095@gmail.com
# Project: ZeroCode - Autonomous Multi-Agent IDE
# ==========================================
"""
Run-scoped JWT authentication for the internal MCP facade.

Tokens are:
  - Long-lived enough for the full mentorship loop (12 hours by default)
  - Scoped to a single run_id
  - Service-to-service only (NEVER sent to the frontend — Rule 1)

Flow:
  RunManager → generates JWT with run_id claim
  Agent → sends JWT as Bearer token to MCP facade
  MCP facade → validates JWT and extracts run_id

SECURITY FIX: JWT secret is loaded from a shared environment variable
(MCP_JWT_SECRET) via pydantic-settings. Both the API server and the
background worker share the same secret, eliminating the split-brain
where each process generated a different random secret.

SECURITY FIX: Run-active validation is done against the DATABASE,
not an in-memory set. This eliminates the split-brain where the
worker added runs to its in-memory set but the API process had
an empty set, rejecting all MCP tool calls with 401.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from ..config import get_settings
from ..db.database import async_session
from ..db.models import RunModel

# ─── Configuration ────────────────────────────────────────────────────────────

_JWT_ALGORITHM = "HS256"
_JWT_EXPIRY_MINUTES = 720


def _get_jwt_secret() -> str:
    """Load the JWT secret from shared pydantic-settings config."""
    return get_settings().mcp_jwt_secret


# ─── Token Generation ────────────────────────────────────────────────────────


def generate_mcp_token(
    run_id: str,
    *,
    workspace_id: str | None = None,
    expiry_minutes: int = _JWT_EXPIRY_MINUTES,
) -> str:
    """
    Generate a short-lived JWT scoped to a specific run.

    Claims:
      - sub: run_id
      - purpose: "mcp_facade"
      - workspace_id: optional run-scoped workspace identifier
      - iat: issued at
      - exp: expiry time
    """
    secret = _get_jwt_secret()
    now = datetime.now(UTC)
    payload = {
        "sub": run_id,
        "purpose": "mcp_facade",
        "workspace_id": workspace_id,
        "iat": now,
        "exp": now + timedelta(minutes=expiry_minutes),
    }
    return jwt.encode(payload, secret, algorithm=_JWT_ALGORITHM)


def revoke_run_token(run_id: str) -> None:
    """
    No-op placeholder — revocation is now implicit via DB status.

    A run is considered inactive when its status is 'completed', 'failed',
    or 'cancelled' in the database. No in-memory set needed.
    """
    pass


# ─── Token Validation ────────────────────────────────────────────────────────


def validate_mcp_token(token: str) -> dict[str, Any]:
    """
    Validate a JWT and return the decoded claims.

    Raises:
      HTTPException 401 if token is invalid, expired, or malformed.
    """
    secret = _get_jwt_secret()
    try:
        payload = jwt.decode(token, secret, algorithms=[_JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="MCP token expired")
    except jwt.InvalidTokenError as e:
        raise HTTPException(status_code=401, detail=f"Invalid MCP token: {e}")

    # Verify purpose
    if payload.get("purpose") != "mcp_facade":
        raise HTTPException(status_code=401, detail="Token not scoped to MCP facade")

    # Verify run_id claim exists
    run_id = payload.get("sub")
    if not run_id:
        raise HTTPException(status_code=401, detail="Token missing run_id claim")

    return payload


# ─── DB-Backed Run Validation ─────────────────────────────────────────────────

_ACTIVE_STATUSES = {
    "queued",
    "planning",
    "delegating",
    "developing",
    "verifying",
    "retrying",
    "leader-review",
}


async def _verify_run_is_active(run_id: str) -> None:
    """
    Check the DATABASE to verify that the run exists and is in an active state.

    Raises HTTPException 401 if the run is not found or is in a terminal state.
    This replaces the broken in-memory `_active_runs: set` that caused
    split-brain failures between the API and worker processes.
    """
    async with async_session() as session:
        run = await session.get(RunModel, run_id)

    if run is None:
        raise HTTPException(status_code=401, detail=f"Run {run_id} not found in database")

    if run.status not in _ACTIVE_STATUSES:
        raise HTTPException(
            status_code=401,
            detail=f"Run {run_id} is not active (status: {run.status})",
        )


# ─── FastAPI Dependency ───────────────────────────────────────────────────────

_bearer_scheme = HTTPBearer(auto_error=False)


async def require_mcp_auth(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> str:
    """
    FastAPI dependency that extracts and validates the MCP JWT.

    SECURITY: JWT Bearer token is STRICTLY REQUIRED. The legacy X-Run-Id
    header fallback has been removed to close the authentication bypass.

    SECURITY: Run-active validation is done against the DATABASE,
    not an in-memory set. Both the API server and background worker
    share the same DB, making this check consistent across processes.

    Returns:
      The validated run_id.

    Raises:
      HTTPException 401 if the token is missing, invalid, or expired.
    """
    if not credentials or not credentials.credentials:
        raise HTTPException(
            status_code=401,
            detail="MCP facade requires a valid Bearer token. No token provided.",
        )

    payload = validate_mcp_token(credentials.credentials)
    run_id = payload["sub"]

    # Verify run is active in the DATABASE (not in-memory)
    await _verify_run_is_active(run_id)

    return run_id
