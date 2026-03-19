# ==========================================
# Author: Hieu Nguyen - Codev Team
# Email: hieuit095@gmail.com
# Project: ZeroCode - Autonomous Multi-Agent IDE
# ==========================================
"""
Helpers for constructing OpenHands SDK LLM clients from DB routing config.

LiteLLM cannot infer every provider from the raw model id alone. Together.ai
models are a notable case: a model like `moonshotai/Kimi-K2.5` must be sent as
`together_ai/moonshotai/Kimi-K2.5` for provider routing to work reliably.
"""

from __future__ import annotations

import json
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

    llm = LLM(
        model=llm_model,
        api_key=SecretStr(api_key) if api_key else None,
        base_url=base_url,
        usage_id=usage_id,
    )

    normalized_lower = llm_model.lower()
    if normalized_lower == "together_ai/minimaxai/minimax-m2.5":
        logger.info(
            "Applying Together MiniMax QA overrides: native_tool_calling=False, reasoning_effort=medium"
        )
        llm = llm.model_copy(update={
            "native_tool_calling": False,
            "reasoning_effort": "medium",
        })
    elif normalized_lower == "together_ai/openai/gpt-oss-120b":
        logger.info(
            "Applying Together gpt-oss Dev overrides: reasoning_effort=medium"
        )
        llm = llm.model_copy(update={
            "reasoning_effort": "medium",
        })

    return llm


def extract_message_text(message: Any) -> str:
    """
    Extract plain text from an OpenHands SDK Message-like object.

    The SDK callback yields Message models whose ``str(message)`` is a repr-like
    debug string, not the assistant's raw text. Parse the structured content
    blocks instead so downstream JSON parsing sees the model output itself.
    """
    if message is None:
        return ""

    content = getattr(message, "content", None)
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            text = getattr(item, "text", None)
            if isinstance(text, str) and text:
                parts.append(text)
        if parts:
            return "".join(parts).strip()

    text = getattr(message, "text", None)
    if isinstance(text, str) and text:
        return text.strip()

    tool_calls = getattr(message, "tool_calls", None)
    if isinstance(tool_calls, list):
        for tool_call in tool_calls:
            name = str(getattr(tool_call, "name", "") or "").strip().lower()
            if name != "finish":
                continue

            arguments = getattr(tool_call, "arguments", None)
            if not isinstance(arguments, str) or not arguments.strip():
                continue

            try:
                payload = json.loads(arguments)
            except json.JSONDecodeError:
                continue

            finish_message = payload.get("message")
            if isinstance(finish_message, str) and finish_message.strip():
                return finish_message.strip()

    return str(message).strip()


def extract_last_assistant_text(messages: list[Any]) -> str:
    """
    Return the most recent assistant-authored text block from SDK messages.

    The callback stream may contain user, tool, and assistant messages. For
    downstream JSON parsing we want the assistant's final natural-language
    output, not the latest tool observation.
    """
    for message in reversed(messages):
        role = getattr(message, "role", None)
        role_text = ""
        if role is not None:
            role_text = str(getattr(role, "value", role)).strip().lower()

        if role_text and role_text != "assistant":
            continue

        content = extract_message_text(message)
        if content:
            return content

    for message in reversed(messages):
        content = extract_message_text(message)
        if content:
            return content

    return ""


def summarize_message_trace(messages: list[Any], limit: int = 5) -> list[str]:
    """Return compact role/text previews for recent SDK messages."""
    previews: list[str] = []
    for message in messages[-limit:]:
        role = getattr(message, "role", None)
        role_text = str(getattr(role, "value", role)).strip() if role is not None else "unknown"
        text = extract_message_text(message).replace("\r", " ").replace("\n", " ").strip()
        previews.append(f"{role_text}: {text[:160]}")
    return previews
