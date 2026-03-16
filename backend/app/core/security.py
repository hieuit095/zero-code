"""
Run-scoped JWT authentication for the internal MCP facade.

Tokens are:
  - Short-lived (5 min default, renewable by the orchestrator)
  - Scoped to a single run_id
  - Service-to-service only (NEVER sent to the frontend — Rule 1)

Flow:
  RunManager → generates JWT with run_id claim
  Agent → sends JWT as Bearer token to MCP facade
  MCP facade → validates JWT and extracts run_id
"""

from __future__ import annotations

import os
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

# ─── Configuration ────────────────────────────────────────────────────────────

# Secret key — generated once per process (or set via env var for multi-process)
_JWT_SECRET = os.environ.get("MCP_JWT_SECRET", secrets.token_urlsafe(32))
_JWT_ALGORITHM = "HS256"
_JWT_EXPIRY_MINUTES = 5

# Track active run IDs for extra validation
_active_runs: set[str] = set()


# ─── Token Generation ────────────────────────────────────────────────────────


def generate_mcp_token(run_id: str, expiry_minutes: int = _JWT_EXPIRY_MINUTES) -> str:
    """
    Generate a short-lived JWT scoped to a specific run.

    Claims:
      - sub: run_id
      - purpose: "mcp_facade"
      - iat: issued at
      - exp: expiry time
    """
    now = datetime.now(UTC)
    payload = {
        "sub": run_id,
        "purpose": "mcp_facade",
        "iat": now,
        "exp": now + timedelta(minutes=expiry_minutes),
    }
    _active_runs.add(run_id)
    return jwt.encode(payload, _JWT_SECRET, algorithm=_JWT_ALGORITHM)


def revoke_run_token(run_id: str) -> None:
    """Mark a run as inactive (tokens for it will be rejected)."""
    _active_runs.discard(run_id)


# ─── Token Validation ────────────────────────────────────────────────────────


def validate_mcp_token(token: str) -> dict[str, Any]:
    """
    Validate a JWT and return the decoded claims.

    Raises:
      HTTPException 401 if token is invalid, expired, or for an inactive run.
    """
    try:
        payload = jwt.decode(token, _JWT_SECRET, algorithms=[_JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="MCP token expired")
    except jwt.InvalidTokenError as e:
        raise HTTPException(status_code=401, detail=f"Invalid MCP token: {e}")

    # Verify purpose
    if payload.get("purpose") != "mcp_facade":
        raise HTTPException(status_code=401, detail="Token not scoped to MCP facade")

    # Verify run is still active
    run_id = payload.get("sub")
    if not run_id:
        raise HTTPException(status_code=401, detail="Token missing run_id claim")

    if run_id not in _active_runs:
        raise HTTPException(status_code=401, detail=f"Run {run_id} is not active")

    return payload


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
    return payload["sub"]
