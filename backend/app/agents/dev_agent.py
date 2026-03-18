"""
Dev Agent — Expert Developer Nanobot (OpenHands SDK).

Responsibilities:
- Receives a user goal (or a QA defect report on retry)
- Inspects files via MCP read_file
- Writes/patches code via MCP write_file
- Operates EXCLUSIVELY through MCP tools (Rule 1: no local host tools)

ARCHITECTURE: Uses the OpenHands SDK Conversation lifecycle:
  LLM → Agent(tools) → Conversation(agent, workspace) → send_message → run()

The Dev agent is called by the orchestrator with either:
  1. The initial user goal string (first attempt)
  2. A structured QA defect report JSON (retry attempt)
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import SecretStr

from ..config import Settings, get_settings

logger = logging.getLogger(__name__)

# ─── SDK Import Guard ─────────────────────────────────────────────────────────

_SDK_AVAILABLE = False

try:
    from openhands.sdk import (
        LLM,
        Agent,
        Conversation,
        Event,
        LLMConvertibleEvent,
    )
    from openhands.sdk.context.condenser import LLMSummarizingCondenser
    _SDK_AVAILABLE = True
except ImportError:
    logger.warning(
        "OpenHands SDK not installed — DevAgent will operate in degraded stub mode. "
        "Install with: pip install openhands-sdk openhands-tools"
    )

# ─── System Prompt ────────────────────────────────────────────────────────────

DEV_SYSTEM_PROMPT = """\
You are **Dev**, the expert developer in a multi-agent coding IDE.

## Your Role
You receive a coding goal from the orchestrator and implement it by reading,
writing, and patching files in the workspace. On retry, you receive a structured
QA defect report — you must fix the exact issues listed.

## Available Tools
You have the following tools at your disposal:

1. **execute_bash(command)** — run shell commands (install deps, run tests, etc.)
2. **str_replace_editor** — view, create, and edit files with surgical precision

## Workflow
1. Analyze the goal or defect report.
2. Use the editor to inspect existing code.
3. Plan your changes (think step-by-step).
4. Use the editor to create or update files.
5. Use bash to verify your changes compile/run.
6. Output a structured JSON summary of what you changed.

## Output Format
When you finish, output EXACTLY this JSON (no markdown fences, no extra text):
{
  "status": "done",
  "filesChanged": ["path/to/file1.py", "path/to/file2.ts"],
  "summary": "Brief description of what was implemented or fixed."
}

## Rules
- NEVER skip reading a file before modifying it — always inspect first.
- On retry with a QA report, fix EVERY issue in the report before finishing.
- Keep your changes minimal and focused on the goal.
"""

# ─── Agent Definition ─────────────────────────────────────────────────────────


@dataclass
class DevAgentConfig:
    """Configuration for the Dev agent."""

    system_prompt: str = DEV_SYSTEM_PROMPT
    model: str = ""  # Filled from settings at runtime
    max_iterations: int = 20
    name: str = "dev"
    label: str = "Dev"


@dataclass
class DevAgentResult:
    """Structured result from a Dev agent run."""

    status: str  # "done" | "error"
    files_changed: list[str] = field(default_factory=list)
    summary: str = ""
    raw_output: str = ""
    error: str | None = None
    cost: float = 0.0
    total_tokens: int = 0


# ─── LLM Metrics Extraction ───────────────────────────────────────────────────


def _extract_llm_metrics(llm_handle: Any) -> tuple[float, int]:
    """Safely extract accumulated cost and total tokens from an SDK LLM.

    Returns:
        (cost, total_tokens) — defaults to (0.0, 0) on any failure.
    """
    cost = 0.0
    total_tokens = 0
    if llm_handle is None:
        return cost, total_tokens
    metrics = getattr(llm_handle, "metrics", None)
    if metrics is None:
        return cost, total_tokens
    cost = float(getattr(metrics, "accumulated_cost", 0.0) or 0.0)
    token_usage = getattr(metrics, "accumulated_token_usage", None)
    if token_usage is not None:
        prompt = int(getattr(token_usage, "prompt_tokens", 0) or 0)
        completion = int(getattr(token_usage, "completion_tokens", 0) or 0)
        total_tokens = prompt + completion
    return cost, total_tokens


class DevAgent:
    """
    Dev agent that implements code changes via the OpenHands SDK.

    Uses the SDK Conversation lifecycle to drive real LLM cognition:
      LLM → Agent(tools) → Conversation(workspace) → send_message → run()
    """

    def __init__(self, config: DevAgentConfig | None = None) -> None:
        self.config = config or DevAgentConfig()
        self._last_llm: Any = None  # Exposed for SDK metrics extraction

    async def run(
        self,
        run_id: str,
        goal: str,
        context: dict[str, Any] | None = None,
        llm_config: dict[str, Any] | None = None,
        mentorship_context: dict[str, Any] | None = None,
    ) -> DevAgentResult:
        """
        Execute the Dev agent for a given goal.

        Args:
            run_id: The current run ID (used for MCP X-Run-Id scoping)
            goal: The user's goal or QA defect report JSON
            context: Optional additional context (workspace files, etc.)
            llm_config: Dynamic LLM configuration from the database:
                        {"model": str, "provider": str, "api_key": str, "base_url": str | None}
            mentorship_context: PHASE 2 FIX (Task 2) - Structured mentorship
                               context dict from MentorshipMessage.to_context_dict().
                               If provided, injected as a separate conversation
                               message before the goal to give the Dev agent
                               formal context about the Tech Lead's guidance.

        Returns:
            DevAgentResult with status, changed files, and summary.
        """
        if not _SDK_AVAILABLE:
            return DevAgentResult(
                status="error",
                summary="OpenHands SDK is not installed. Cannot run Dev agent.",
                error="SDK_NOT_AVAILABLE",
            )

        try:
            # ── Build LLM from dynamic config ──────────────────────────
            cfg = llm_config or {}
            model = cfg.get("model", "gpt-4o")
            provider = cfg.get("provider", "openai")
            api_key = cfg.get("api_key", "")
            base_url = cfg.get("base_url")

            # LiteLLM convention: provider/model_name
            llm_model = f"{provider}/{model}" if "/" not in model else model

            llm = LLM(
                model=llm_model,
                api_key=SecretStr(api_key) if api_key else None,
                base_url=base_url,
                usage_id=f"dev-{run_id}",
            )
            self._last_llm = llm  # Expose for metrics extraction

            # ── Context Condenser (prevents token explosion on retries) ─
            llm_condenser = llm.model_copy(update={"usage_id": f"dev-condenser-{run_id}"})
            condenser = LLMSummarizingCondenser(
                llm=llm_condenser, max_size=10, keep_first=2,
            )

            # ── Create Agent with MCP Facade tools + condenser ────────
            # PHASE 2: Tools are discovered via the internal MCP server,
            # NOT via native SDK ToolDefinition bindings.
            settings = get_settings()
            mcp_config = {
                "mcpServers": {
                    "sandbox": {
                        "url": f"http://127.0.0.1:{settings.port}/internal/mcp/dev/sse",
                    },
                    "fetch": {"command": "uvx", "args": ["mcp-server-fetch"]},
                }
            }

            agent = Agent(
                llm=llm,
                condenser=condenser,
                mcp_config=mcp_config,
            )

            # ── Resolve workspace path ─────────────────────────────────
            settings = get_settings()
            ctx = context or {}
            workspace_id = ctx.get("workspace_id", "repo-main")
            workspace_path = str(settings.workspace_path / workspace_id)

            # ── Collect LLM messages via callback ──────────────────────
            llm_messages: list[Any] = []

            def _on_event(event: Event) -> None:
                if isinstance(event, LLMConvertibleEvent):
                    llm_messages.append(event.to_llm_message())

            # ── Start Conversation lifecycle ───────────────────────────
            conversation = Conversation(
                agent=agent,
                callbacks=[_on_event],
                workspace=workspace_path,
            )

            # Build the user message with context
            attempt = ctx.get("attempt", 1)
            task_id = ctx.get("task_id", "unknown")
            user_message = (
                f"[Run: {run_id} | Task: {task_id} | Attempt: {attempt}]\n\n"
                f"{goal}"
            )

            # PHASE 2 FIX (Task 2): If mentorship context is provided,
            # inject it as a separate structured message BEFORE the goal.
            # This gives the Dev agent formal context from the Tech Lead's
            # guidance without flattening it into the goal string.
            if mentorship_context:
                mentor_msg = (
                    f"[MENTORSHIP CONTEXT from {mentorship_context.get('source_agent', 'tech-lead')}]\n"
                    f"Failed attempts: {mentorship_context.get('failed_attempts', 0)}\n"
                    f"Critique: {mentorship_context.get('critique_artifact', '')}\n"
                    f"Guidance: {mentorship_context.get('reference_artifact', '')}\n\n"
                    f"Read BOTH artifacts before implementing fixes."
                )
                conversation.send_message(mentor_msg)

            conversation.send_message(user_message)
            conversation.run()

            # ── Extract structured result from LLM output ──────────────
            raw_output = ""
            if llm_messages:
                # The last assistant message is our structured JSON output
                for msg in reversed(llm_messages):
                    content = str(msg) if msg else ""
                    if content.strip():
                        raw_output = content
                        break

            # Attempt to parse structured JSON from the output
            result = self._parse_result(raw_output, llm)

            # ── Extract LLM metrics ───────────────────────────────────
            result.cost, result.total_tokens = _extract_llm_metrics(self._last_llm)
            return result

        except Exception as e:
            logger.exception("DevAgent.run() failed for run %s", run_id)
            return DevAgentResult(
                status="error",
                summary=f"Dev agent failed during execution: {e}",
                error=str(e),
            )

    def _parse_result(self, raw_output: str, llm: Any) -> DevAgentResult:
        """
        Extract structured DevAgentResult from the LLM's raw output.

        Tries to find and parse the JSON block. Falls back to treating
        the entire output as a summary if JSON parsing fails.
        """
        # Try to find a JSON block in the output
        json_str = raw_output
        if "```json" in raw_output:
            start = raw_output.index("```json") + 7
            end = raw_output.index("```", start)
            json_str = raw_output[start:end].strip()
        elif "```" in raw_output:
            start = raw_output.index("```") + 3
            end = raw_output.index("```", start)
            json_str = raw_output[start:end].strip()

        # Try to find raw JSON object
        brace_start = json_str.find("{")
        brace_end = json_str.rfind("}")
        if brace_start != -1 and brace_end != -1:
            json_str = json_str[brace_start : brace_end + 1]

        try:
            parsed = json.loads(json_str)
            return DevAgentResult(
                status=parsed.get("status", "done"),
                files_changed=parsed.get("filesChanged", []),
                summary=parsed.get("summary", ""),
                raw_output=raw_output,
            )
        except (json.JSONDecodeError, ValueError):
            # Fallback: return the raw output as summary
            return DevAgentResult(
                status="done",
                files_changed=[],
                summary=raw_output[:500] if raw_output else "Agent completed (no structured output).",
                raw_output=raw_output,
            )
