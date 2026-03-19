# ==========================================
# Author: Hieu Nguyen - Codev Team
# Email: hieuit095@gmail.com
# Project: ZeroCode - Autonomous Multi-Agent IDE
# ==========================================
"""
Settings API — Secure API Key Vault.

Provides CRUD for LLM provider API keys. Keys are stored encrypted in the
database using Fernet symmetric encryption. The decrypted key is NEVER returned
to the frontend — only provider metadata and a masked preview.

Endpoints:
  - GET  /api/settings/keys          — list configured providers (masked)
  - POST /api/settings/keys          — store or update a provider key
  - DELETE /api/settings/keys/{provider} — remove a provider key
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from ..db.database import async_session
from ..db.models import APIKeyModel, LLMRoutingModel, encrypt_key, decrypt_key

router = APIRouter(prefix="/api/settings", tags=["settings"])


# ─── Request / Response Models ────────────────────────────────────────────────


class StoreKeyRequest(BaseModel):
    provider: str = Field(..., min_length=1)
    key: str = Field(..., min_length=1)
    label: str | None = None
    base_url: str | None = Field(default=None, alias="baseUrl")

    model_config = {"populate_by_name": True}


class KeyInfo(BaseModel):
    provider: str
    label: str | None
    base_url: str | None = Field(default=None, alias="baseUrl")
    masked_key: str = Field(alias="maskedKey")
    configured: bool = True

    model_config = {"populate_by_name": True}


class StoreKeyResponse(BaseModel):
    success: bool
    message: str
    provider: str


class LLMRoutingRequest(BaseModel):
    leader_model: str = Field(default="gpt-4o", alias="leaderModel")
    leader_provider: str = Field(default="openai", alias="leaderProvider")
    dev_model: str = Field(default="gpt-4o", alias="devModel")
    dev_provider: str = Field(default="openai", alias="devProvider")
    qa_model: str = Field(default="gpt-4o", alias="qaModel")
    qa_provider: str = Field(default="openai", alias="qaProvider")

    model_config = {"populate_by_name": True}


class LLMRoutingResponse(BaseModel):
    leader_model: str = Field(alias="leaderModel")
    leader_provider: str = Field(alias="leaderProvider")
    dev_model: str = Field(alias="devModel")
    dev_provider: str = Field(alias="devProvider")
    qa_model: str = Field(alias="qaModel")
    qa_provider: str = Field(alias="qaProvider")

    model_config = {"populate_by_name": True}


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _mask_key(key_preview: str) -> str:
    """Mask an API key for safe display: show first 8 chars + dots."""
    if len(key_preview) <= 8:
        return "•" * len(key_preview)
    return key_preview[:8] + "•" * min(len(key_preview) - 8, 20)


# ─── Key Vault Endpoints ─────────────────────────────────────────────────────


@router.get("/keys", response_model=list[KeyInfo])
async def list_keys() -> list[KeyInfo]:
    """Return all configured providers with masked key previews."""
    async with async_session() as session:
        result = await session.execute(select(APIKeyModel))
        rows = result.scalars().all()

    return [
        KeyInfo(
            provider=row.provider,
            label=row.label,
            baseUrl=row.base_url,
            # AUDIT FIX: Decrypt the actual key for masking preview,
            # not the provider name. The decrypted value never leaves
            # _mask_key() — only the masked prefix is returned.
            maskedKey=_mask_key(decrypt_key(row.encrypted_key)),
        )
        for row in rows
    ]


@router.post("/keys", response_model=StoreKeyResponse)
async def store_key(payload: StoreKeyRequest) -> StoreKeyResponse:
    """
    Store or update a provider API key (encrypted).

    If a key for this provider already exists, it is overwritten.
    """
    encrypted = encrypt_key(payload.key)

    async with async_session() as session:
        # Upsert: check if provider exists
        result = await session.execute(
            select(APIKeyModel).where(APIKeyModel.provider == payload.provider)
        )
        existing = result.scalar_one_or_none()

        if existing:
            existing.encrypted_key = encrypted
            existing.label = payload.label or existing.label
            existing.base_url = payload.base_url or existing.base_url
        else:
            session.add(APIKeyModel(
                provider=payload.provider,
                encrypted_key=encrypted,
                label=payload.label,
                base_url=payload.base_url,
            ))

        await session.commit()

    return StoreKeyResponse(
        success=True,
        message=f"Key for {payload.provider} stored securely.",
        provider=payload.provider,
    )


@router.delete("/keys/{provider}")
async def delete_key(provider: str) -> dict[str, Any]:
    """Remove a provider's API key from the vault."""
    async with async_session() as session:
        result = await session.execute(
            select(APIKeyModel).where(APIKeyModel.provider == provider)
        )
        existing = result.scalar_one_or_none()

        if not existing:
            raise HTTPException(status_code=404, detail=f"No key found for {provider}")

        await session.delete(existing)
        await session.commit()

    return {"success": True, "message": f"Key for {provider} removed."}


# ─── LLM Routing Endpoints ───────────────────────────────────────────────────


@router.get("/llm", response_model=LLMRoutingResponse)
async def get_llm_routing() -> LLMRoutingResponse:
    """Return the current agent-to-model routing configuration."""
    async with async_session() as session:
        result = await session.execute(select(LLMRoutingModel))
        row = result.scalar_one_or_none()

    if row is None:
        # Return defaults if no config exists yet
        return LLMRoutingResponse(
            leaderModel="gpt-4o", leaderProvider="openai",
            devModel="gpt-4o", devProvider="openai",
            qaModel="gpt-4o", qaProvider="openai",
        )

    return LLMRoutingResponse(
        leaderModel=row.leader_model, leaderProvider=row.leader_provider,
        devModel=row.dev_model, devProvider=row.dev_provider,
        qaModel=row.qa_model, qaProvider=row.qa_provider,
    )


@router.post("/llm", response_model=LLMRoutingResponse)
async def save_llm_routing(payload: LLMRoutingRequest) -> LLMRoutingResponse:
    """Save or update the agent-to-model routing (singleton upsert)."""
    async with async_session() as session:
        result = await session.execute(select(LLMRoutingModel))
        row = result.scalar_one_or_none()

        if row:
            row.leader_model = payload.leader_model
            row.leader_provider = payload.leader_provider
            row.dev_model = payload.dev_model
            row.dev_provider = payload.dev_provider
            row.qa_model = payload.qa_model
            row.qa_provider = payload.qa_provider
        else:
            session.add(LLMRoutingModel(
                id=1,
                leader_model=payload.leader_model,
                leader_provider=payload.leader_provider,
                dev_model=payload.dev_model,
                dev_provider=payload.dev_provider,
                qa_model=payload.qa_model,
                qa_provider=payload.qa_provider,
            ))

        await session.commit()

    return LLMRoutingResponse(
        leaderModel=payload.leader_model, leaderProvider=payload.leader_provider,
        devModel=payload.dev_model, devProvider=payload.dev_provider,
        qaModel=payload.qa_model, qaProvider=payload.qa_provider,
    )
