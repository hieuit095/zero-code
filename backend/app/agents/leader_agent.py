"""
Leader Agent — Tech Lead / Planner Nanobot (OpenHands SDK).

Responsibilities:
- Receives the raw user goal and workspace context
- Analyzes the existing codebase via read-only tools (terminal, file editor)
- Decomposes the goal into a structured JSON array of sequential tasks
- NEVER writes code — planning and delegation only (Rule 1)

ARCHITECTURE: Uses the OpenHands SDK Conversation lifecycle:
  LLM → Agent(tools) → Conversation(agent, workspace) → send_message → run()

Output:
  A JSON array of AgentTask objects, each with:
    { "id": str, "label": str, "acceptanceCriteria": str }
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from pydantic import SecretStr

from ..config import get_settings

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
        "OpenHands SDK not installed — LeaderAgent will operate in degraded stub mode. "
        "Install with: pip install openhands-sdk openhands-tools"
    )

# ─── System Prompt ────────────────────────────────────────────────────────────

LEADER_SYSTEM_PROMPT = """\
You are **Tech Lead**, the planning agent in a multi-agent coding IDE.

## Your Role
You receive a user's high-level coding goal and decompose it into a sequence
of concrete, implementable tasks for the Dev agent. You DO NOT write code.

## Available Tools
1. **execute_bash(command)** — run read-only commands (e.g., `find`, `ls`, `tree`, `cat`)
2. **str_replace_editor** — inspect existing file content (view mode only)

You may use these to understand the existing workspace structure before planning.

## Planning Process
1. Analyze the user's goal carefully.
2. Inspect the workspace to understand existing code structure.
3. Break the goal into 2–5 sequential tasks. Each task should be:
   - Small enough for one Dev agent iteration
   - Independent enough to be verified by the QA agent after completion
   - Ordered by dependency (foundational changes first)
4. Write clear acceptance criteria for each task so QA knows what to verify.

## Output Format
Output EXACTLY a JSON array (no markdown fences, no extra text):
[
  {
    "id": "task_<unique_8char>",
    "label": "Short description of what to implement",
    "acceptanceCriteria": "Specific, testable criteria for QA to verify"
  },
  {
    "id": "task_<unique_8char>",
    "label": "Next task...",
    "acceptanceCriteria": "..."
  }
]

## Rules
- Output 2–5 tasks. Never more than 5, never fewer than 2.
- Each task label should be action-oriented (e.g., "Create user model", not "User model").
- Acceptance criteria must be specific and verifiable.
- You MUST NOT include implementation details — only WHAT to build, not HOW.
- You MUST NOT write any code or modify any files.
- Output ONLY the JSON array. No preamble, no explanation, no markdown.
"""

# ─── Mentorship Mode Prompt ───────────────────────────────────────────────────

LEADER_MENTORSHIP_PROMPT = """\
You are **Tech Lead**, acting as a senior architectural debugger.

## Context
The Dev agent has FAILED to implement a task after 2 attempts. The QA agent
has generated a detailed critique at `/workspace/critique_report.md`. Your
job is to rescue this task by providing targeted, authoritative guidance.

## Available Tools
1. **execute_bash(command)** — run read-only commands (e.g., `cat`, `find`, `ls`)
2. **str_replace_editor** — inspect existing file content (view mode only)

## Your Process
1. Read `/workspace/critique_report.md` to understand the QA failures.
2. Inspect the broken source files referenced in the critique.
3. Identify the ROOT CAUSE — is it a logic error, a missing import,
   an architectural misunderstanding, or a wrong API usage?
4. Write a concise, step-by-step fix plan that the Dev agent can follow.

## Output Format
Output your guidance as plain Markdown. Structure it as:

### Diagnosis
Brief root cause analysis (2–3 sentences).

### Fix Steps
1. Step one…
2. Step two…
3. …

## Rules
- You MUST NOT write code or modify any files.
- You MUST NOT output JSON task arrays.
- Be specific — reference exact file paths and function names.
- Keep guidance concise (under 500 words).
"""

# ─── Data Structures ─────────────────────────────────────────────────────────


@dataclass
class AgentTask:
    """A single task planned by the Leader agent."""

    id: str
    label: str
    acceptance_criteria: str
    status: str = "pending"  # "pending" | "in-progress" | "completed" | "failed"
    agent: str = "dev"


@dataclass
class LeaderAgentConfig:
    """Configuration for the Leader agent."""

    system_prompt: str = LEADER_SYSTEM_PROMPT
    model: str = ""  # Filled from settings at runtime
    max_iterations: int = 10
    name: str = "tech-lead"
    label: str = "Tech Lead"


@dataclass
class LeaderAgentResult:
    """Structured result from a Leader agent run."""

    status: str  # "done" | "error"
    tasks: list[AgentTask] = field(default_factory=list)
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


# ─── Agent ────────────────────────────────────────────────────────────────────


def _task_id() -> str:
    return f"task_{uuid4().hex[:8]}"


class LeaderAgent:
    """
    Leader agent that decomposes a goal into structured tasks
    via the OpenHands SDK Conversation lifecycle.
    """

    def __init__(self, config: LeaderAgentConfig | None = None) -> None:
        self.config = config or LeaderAgentConfig()
        self._last_llm: Any = None  # Exposed for SDK metrics extraction

    async def run(
        self,
        run_id: str,
        goal: str,
        context: dict[str, Any] | None = None,
        llm_config: dict[str, Any] | None = None,
        mentorship_mode: bool = False,
    ) -> LeaderAgentResult:
        """
        Execute the Leader agent for goal decomposition.

        Args:
            run_id: The current run ID
            goal: The user's high-level goal
            context: Optional workspace context
            llm_config: Dynamic LLM configuration from the database:
                        {"model": str, "provider": str, "api_key": str, "base_url": str | None}

        Returns:
            LeaderAgentResult with a list of AgentTask objects.
        """
        if not _SDK_AVAILABLE:
            return LeaderAgentResult(
                status="error",
                summary="OpenHands SDK is not installed. Cannot run Leader agent.",
                error="SDK_NOT_AVAILABLE",
            )

        try:
            # ── Build LLM from dynamic config ──────────────────────────
            cfg = llm_config or {}
            model = cfg.get("model", "gpt-4o")
            provider = cfg.get("provider", "openai")
            api_key = cfg.get("api_key", "")
            base_url = cfg.get("base_url")

            llm_model = f"{provider}/{model}" if "/" not in model else model

            llm = LLM(
                model=llm_model,
                api_key=SecretStr(api_key) if api_key else None,
                base_url=base_url,
                usage_id=f"leader-{run_id}",
            )
            self._last_llm = llm  # Expose for metrics extraction

            # ── Context Condenser (prevents token explosion on replans) ─
            llm_condenser = llm.model_copy(update={"usage_id": f"leader-condenser-{run_id}"})
            condenser = LLMSummarizingCondenser(
                llm=llm_condenser, max_size=10, keep_first=2,
            )

            # ── Select system prompt based on mode ───────────────────
            active_prompt = (
                LEADER_MENTORSHIP_PROMPT if mentorship_mode
                else self.config.system_prompt
            )

            # ── Create Agent with MCP Facade tools + condenser ────────
            # PHASE 2: Tools are discovered via the internal MCP server,
            # NOT via native SDK ToolDefinition bindings.
            settings = get_settings()
            mcp_config = {
                "mcpServers": {
                    "sandbox": {
                        "url": f"http://127.0.0.1:{settings.port}/internal/mcp/tech-lead/sse",
                    },
                    "fetch": {"command": "uvx", "args": ["mcp-server-fetch"]},
                }
            }

            agent = Agent(
                llm=llm,
                system_prompt=active_prompt,
                condenser=condenser,
                mcp_config=mcp_config,
            )

            # ── Resolve workspace path ─────────────────────────────────
            settings = get_settings()
            workspace_path = str(settings.workspace_path / "repo-main")

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

            user_message = (
                f"[Run: {run_id}]\n\n"
                f"Goal:\n{goal}"
            )

            conversation.send_message(user_message)
            conversation.run()

            # ── Extract structured result from LLM output ──────────────
            raw_output = ""
            if llm_messages:
                for msg in reversed(llm_messages):
                    content = str(msg) if msg else ""
                    if content.strip():
                        raw_output = content
                        break

            # ── Mentorship mode: return raw guidance, skip JSON parsing ─
            if mentorship_mode:
                result = LeaderAgentResult(
                    status="done",
                    tasks=[],
                    summary="Mentorship complete",
                    raw_output=raw_output,
                )
            else:
                result = self._parse_result(raw_output)

            # ── Extract LLM metrics ───────────────────────────────────
            result.cost, result.total_tokens = _extract_llm_metrics(self._last_llm)
            return result

        except Exception as e:
            logger.exception("LeaderAgent.run() failed for run %s", run_id)
            return LeaderAgentResult(
                status="error",
                summary=f"Leader agent failed during planning: {e}",
                error=str(e),
            )

    def _parse_result(self, raw_output: str) -> LeaderAgentResult:
        """
        Parse the LLM's raw output into a LeaderAgentResult.

        Expects a JSON array of task objects. Falls back to generating
        a minimal task list if parsing fails completely.
        """
        # Try to extract a JSON array from the output
        json_str = raw_output

        # Strip markdown fences if present
        if "```json" in json_str:
            start = json_str.index("```json") + 7
            end = json_str.index("```", start)
            json_str = json_str[start:end].strip()
        elif "```" in json_str:
            start = json_str.index("```") + 3
            end = json_str.index("```", start)
            json_str = json_str[start:end].strip()

        # Find the JSON array boundaries
        bracket_start = json_str.find("[")
        bracket_end = json_str.rfind("]")
        if bracket_start != -1 and bracket_end != -1:
            json_str = json_str[bracket_start : bracket_end + 1]

        try:
            parsed = json.loads(json_str)
            if not isinstance(parsed, list) or not parsed:
                raise ValueError("Expected a non-empty JSON array")

            tasks: list[AgentTask] = []
            for item in parsed:
                tasks.append(AgentTask(
                    id=item.get("id", _task_id()),
                    label=item.get("label", "Untitled task"),
                    acceptance_criteria=item.get("acceptanceCriteria", ""),
                ))

            return LeaderAgentResult(
                status="done",
                tasks=tasks,
                summary=f"Decomposed goal into {len(tasks)} tasks.",
                raw_output=raw_output,
            )

        except (json.JSONDecodeError, ValueError, KeyError) as e:
            logger.warning(
                "Failed to parse Leader output as JSON: %s. Raw output: %s",
                e, raw_output[:300],
            )
            return LeaderAgentResult(
                status="error",
                summary=f"Leader agent produced unparseable output: {e}",
                raw_output=raw_output,
                error=f"JSON_PARSE_ERROR: {e}",
            )
