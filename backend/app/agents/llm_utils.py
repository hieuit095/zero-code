"""
Helpers for constructing OpenHands SDK LLM clients from DB routing config.

LiteLLM cannot infer every provider from the raw model id alone. Together.ai
models are a notable case: a model like `moonshotai/Kimi-K2.5` must be sent as
`together_ai/moonshotai/Kimi-K2.5` for provider routing to work reliably.
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import SecretStr

logger = logging.getLogger(__name__)

_PROVIDER_PREFIXES = {
    "together": "together_ai",
    "together_ai": "together_ai",
}


def normalize_litellm_model(
    model: str,
    provider: str | None,
    base_url: str | None = None,
) -> str:
    """
    Return a LiteLLM-compatible model id.

    For providers LiteLLM cannot infer from the bare model string, prepend the
    provider namespace. This keeps OpenHands SDK routing stable across agents.
    """
    normalized_model = model.strip()
    if not normalized_model:
        return normalized_model

    normalized_provider = _PROVIDER_PREFIXES.get((provider or "").strip().lower())
    if not normalized_provider:
        return normalized_model

    expected_prefix = f"{normalized_provider}/"
    if normalized_model.startswith(expected_prefix):
        return normalized_model

    try:
        from openhands.sdk.llm.utils.litellm_provider import infer_litellm_provider

        inferred = infer_litellm_provider(model=normalized_model, api_base=base_url)
    except Exception:
        inferred = None

    if inferred == normalized_provider:
        return normalized_model

    rewritten_model = f"{expected_prefix}{normalized_model}"
    logger.info(
        "Normalized LiteLLM model for provider %s: %s -> %s",
        provider,
        normalized_model,
        rewritten_model,
    )
    return rewritten_model


def build_sdk_llm(
    cfg: dict[str, Any] | None,
    *,
    default_model: str,
    default_provider: str,
    usage_id: str,
):
    """
    Build an OpenHands SDK LLM instance from DB routing config.
    """
    from openhands.sdk import LLM

    config = cfg or {}
    model = str(config.get("model", default_model))
    provider = str(config.get("provider", default_provider))
    api_key = str(config.get("api_key", ""))
    base_url = config.get("base_url")

    llm_model = normalize_litellm_model(model, provider, base_url)

    return LLM(
        model=llm_model,
        api_key=SecretStr(api_key) if api_key else None,
        base_url=base_url,
        usage_id=usage_id,
    )
