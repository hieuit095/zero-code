"""
Deterministic Nanobot-to-MCP integration probe.

This module instantiates a real Nanobot AgentLoop with its default host tools
disabled, connects it to the JWT-protected MCP facade, and forces tool calls to:
  - workspace_read_file
  - workspace_exec

Usage:
  python -m app.verification.nanobot_mcp_probe
  python -m app.verification.nanobot_mcp_probe --base-url http://127.0.0.1:8000
"""

from __future__ import annotations

import argparse
import asyncio
import json
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from ..config import get_settings
from ..core.security import generate_mcp_token
from ..db.database import async_session
from ..services.openhands_client import get_openhands_client
from ..services.run_store import RunStore

try:
    from nanobot.agent.loop import AgentLoop
    from nanobot.bus.queue import MessageBus
    from nanobot.providers.base import LLMProvider, LLMResponse, ToolCallRequest
except ImportError as exc:  # pragma: no cover - exercised in runtime verification
    AgentLoop = object  # type: ignore[assignment]
    MessageBus = object  # type: ignore[assignment]
    LLMProvider = object  # type: ignore[assignment]
    LLMResponse = object  # type: ignore[assignment]
    ToolCallRequest = object  # type: ignore[assignment]
    _IMPORT_ERROR = exc
else:
    _IMPORT_ERROR = None


class ScriptedMcpProvider(LLMProvider):
    """A deterministic provider that forces Nanobot to use MCP tools."""

    def __init__(self) -> None:
        super().__init__(api_key=None, api_base=None)
        self.available_tools: list[str] = []
        self._step = 0

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        reasoning_effort: str | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        del model, max_tokens, temperature, reasoning_effort, kwargs

        tool_names = [
            tool["function"]["name"]
            for tool in (tools or [])
            if isinstance(tool, dict) and "function" in tool
        ]
        if tool_names:
            self.available_tools = tool_names

        local_host_tools = [
            name for name in tool_names
            if not name.startswith("mcp_sandbox_")
        ]
        if local_host_tools:
            return LLMResponse(
                content=json.dumps(
                    {
                        "status": "failed",
                        "reason": "host_tools_exposed",
                        "availableTools": tool_names,
                        "unexpectedTools": local_host_tools,
                    }
                ),
                finish_reason="stop",
            )

        read_tool = next(
            (name for name in tool_names if name.endswith("workspace_read_file")),
            None,
        )
        exec_tool = next(
            (name for name in tool_names if name.endswith("workspace_exec")),
            None,
        )
        if not read_tool or not exec_tool:
            return LLMResponse(
                content=json.dumps(
                    {
                        "status": "failed",
                        "reason": "required_mcp_tools_missing",
                        "availableTools": tool_names,
                    }
                ),
                finish_reason="stop",
            )

        if self._step == 0:
            self._step += 1
            return LLMResponse(
                content="Reading probe file via MCP.",
                tool_calls=[
                    ToolCallRequest(
                        id="probe_read",
                        name=read_tool,
                        arguments={"path": "/workspace/step2_probe.txt"},
                    )
                ],
                finish_reason="tool_calls",
            )

        if self._step == 1:
            self._step += 1
            return LLMResponse(
                content="Running probe command via MCP.",
                tool_calls=[
                    ToolCallRequest(
                        id="probe_exec",
                        name=exec_tool,
                        arguments={
                            "command": "python -c \"import sys; print('OUT'); print('ERR', file=sys.stderr)\"",
                            "cwd": "/workspace",
                        },
                    )
                ],
                finish_reason="tool_calls",
            )

        tool_results = [
            msg.get("content", "")
            for msg in messages
            if msg.get("role") == "tool"
        ]
        read_ok = any("nanobot-mcp-step2" in content for content in tool_results)
        exec_ok = any(
            "OUT" in content and "ERR" in content and "EXIT CODE: 0" in content
            for content in tool_results
        )

        return LLMResponse(
            content=json.dumps(
                {
                    "status": "passed" if read_ok and exec_ok else "failed",
                    "readOk": read_ok,
                    "execOk": exec_ok,
                    "availableTools": self.available_tools,
                }
            ),
            finish_reason="stop",
        )

    def get_default_model(self) -> str:
        return "nanobot-mcp-probe"


class SandboxOnlyAgentLoop(AgentLoop):
    """Nanobot loop variant with host tools disabled; only MCP tools are allowed."""

    def _register_default_tools(self) -> None:
        return


async def _create_probe_run(run_id: str) -> None:
    async with async_session() as session:
        await RunStore.create_run(
            session,
            run_id=run_id,
            goal="Deterministic Nanobot MCP probe",
            workspace_id="repo-main",
            status="planning",
        )


async def _finalize_probe_run(run_id: str, status: str) -> None:
    async with async_session() as session:
        await RunStore.update_run(
            session,
            run_id,
            status=status,
            phase=status,
            progress=100 if status == "completed" else 0,
        )


async def run_probe(base_url: str | None = None) -> dict[str, Any]:
    if _IMPORT_ERROR is not None:
        raise RuntimeError(
            "nanobot-ai is not installed. Install backend dependencies first."
        ) from _IMPORT_ERROR

    settings = get_settings()
    run_id = f"nanobot_probe_{uuid.uuid4().hex[:12]}"
    workspace_id = "repo-main"
    workspace_path = settings.workspace_path / workspace_id
    base_url = (base_url or f"http://127.0.0.1:{settings.port}").rstrip("/")

    await _create_probe_run(run_id)
    runtime = get_openhands_client().get_runtime(workspace_id)
    runtime.write_file("/workspace/step2_probe.txt", "nanobot-mcp-step2\n")
    token = generate_mcp_token(run_id)

    provider = ScriptedMcpProvider()
    loop = SandboxOnlyAgentLoop(
        bus=MessageBus(),
        provider=provider,
        workspace=Path(workspace_path),
        model=provider.get_default_model(),
        max_iterations=6,
        restrict_to_workspace=True,
        mcp_servers={
            "sandbox": SimpleNamespace(
                type="sse",
                command="",
                args=[],
                env={},
                url=f"{base_url}/internal/mcp/dev/sse",
                headers={"Authorization": f"Bearer {token}"},
                tool_timeout=30,
                enabled_tools=[
                    "mcp_sandbox_workspace_read_file",
                    "mcp_sandbox_workspace_write_file",
                    "mcp_sandbox_workspace_exec",
                ],
                disabled_tools=[],
            )
        },
    )

    raw_result = ""
    try:
        raw_result = await loop.process_direct(
            "Use the MCP tools to validate the sandbox workspace."
        )
        result = json.loads(raw_result)
        result["runId"] = run_id
        result["baseUrl"] = base_url
        result["workspace"] = str(workspace_path)
        result["tokenTtlMinutes"] = 720
        return result
    finally:
        await loop.close_mcp()
        parsed_status = "failed"
        try:
            if json.loads(raw_result).get("status") == "passed":
                parsed_status = "completed"
        except Exception:
            parsed_status = "failed"
        await _finalize_probe_run(run_id, parsed_status)


async def _async_main(base_url: str | None) -> int:
    try:
        result = await run_probe(base_url=base_url)
    except Exception as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}))
        return 1

    print(json.dumps(result))
    return 0 if result.get("status") == "passed" else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the deterministic Nanobot MCP probe.")
    parser.add_argument(
        "--base-url",
        default=None,
        help="FastAPI base URL hosting /internal/mcp/* (default: local backend port).",
    )
    args = parser.parse_args()
    return asyncio.run(_async_main(base_url=args.base_url))


if __name__ == "__main__":
    raise SystemExit(main())
