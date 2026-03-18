"""
Probe the current DB-backed LLM routing with the OpenHands SDK client.

Usage:
  python -m app.verification.llm_routing_probe
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from openhands.sdk.llm import Message, TextContent

from ..agents.llm_utils import build_sdk_llm
from ..orchestrator.run_manager import get_run_manager


async def _probe_role(role: str, cfg: dict[str, Any]) -> dict[str, Any]:
    llm = build_sdk_llm(
        cfg,
        default_model="gpt-4o",
        default_provider="openai",
        usage_id=f"probe-{role}",
    )
    response = llm.completion(
        [
            Message(
                role="user",
                content=[TextContent(text="Reply with exactly OK")],
            )
        ]
    )

    text_parts: list[str] = []
    for item in response.message.content:
        if isinstance(item, TextContent):
            text_parts.append(item.text)

    return {
        "role": role,
        "model": cfg.get("model"),
        "provider": cfg.get("provider"),
        "resolvedModel": llm.model,
        "reply": "".join(text_parts).strip(),
    }


async def main() -> None:
    configs = await get_run_manager()._load_llm_configs()
    results = []
    for role in ("leader", "dev", "qa"):
        results.append(await _probe_role(role, configs[role]))

    print(json.dumps({"status": "passed", "results": results}, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
