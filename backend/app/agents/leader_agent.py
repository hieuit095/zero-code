# ==========================================
# Author: Hieu Nguyen - Codev Team
# Email: hieuit095@gmail.com
# Project: ZeroCode - Autonomous Multi-Agent IDE
# ==========================================
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
import re
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from ..config import get_settings
from .llm_utils import build_sdk_llm, extract_last_assistant_text

logger = logging.getLogger(__name__)

# ─── SDK Import Guard ─────────────────────────────────────────────────────────

_SDK_AVAILABLE = False

try:
    from openhands.sdk import (
        LLM,
        Agent,
        AgentContext,
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
1. **workspace_read_file(path)** — inspect existing file content inside `/workspace`
2. **workspace_exec(command, cwd)** — run read-only inspection commands inside the sandbox

Use these only to understand the existing workspace structure before planning.

## Planning Process
1. Analyze the user's goal carefully.
2. Inspect the workspace to understand existing code structure.
3. Break the goal into 2–5 sequential tasks. Each task should be:
   - Small enough for one Dev agent iteration
   - Independent enough to be verified by the QA agent after completion
   - Ordered by dependency (foundational changes first)
4. Write clear acceptance criteria for each task so QA knows what to verify.
5. Do NOT create standalone tasks whose only action is running pytest, tests, lint, or typecheck.
   QA owns verification. Fold verification expectations into acceptance criteria for the relevant implementation task instead.

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
- Do NOT emit verification-only tasks such as "Run pytest" or "Verify tests pass" as separate Dev tasks.
- You MUST NOT include implementation details — only WHAT to build, not HOW.
- You MUST NOT write any code or modify any files.
- Output ONLY the JSON array. No preamble, no explanation, no markdown.
- Use ONLY the MCP workspace tools. Do not assume any host-local tools exist.
"""

# ─── Mentorship Mode Prompt ───────────────────────────────────────────────────

LEADER_MENTORSHIP_PROMPT = """\
You are **Tech Lead**, acting as a senior architectural debugger.

## Context
The Dev agent has FAILED to implement a task after 2 attempts. The QA agent
has generated a detailed critique at `/workspace/critique_report.md`. Your
job is to rescue this task by providing targeted, authoritative guidance.

## Available Tools
1. **workspace_read_file(path)** — inspect existing file content inside `/workspace`
2. **workspace_exec(command, cwd)** — run read-only inspection commands inside the sandbox

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
- Use ONLY the MCP workspace tools. Do not assume any host-local tools exist.
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


# ─── Agent ────────────────────────────────────────────────────────────────────


def _task_id() -> str:
    return f"task_{uuid4().hex[:8]}"


def _build_fallback_tasks_from_goal(goal: str) -> list[AgentTask]:
    """
    Derive a minimal task list when the planner model returns malformed output.

    This keeps the orchestration loop moving on transient JSON-format failures
    from the planner LLM instead of failing the entire run at the planning step.
    """
    normalized_goal = re.sub(r"\s+", " ", goal or "").strip()
    clauses = [
        chunk.strip(" ,.")
        for chunk in re.split(r"(?i)\bthen\b|[.;]\s*", normalized_goal)
        if chunk.strip(" ,.")
    ]

    filenames: list[str] = []
    for candidate in re.findall(r"\b[A-Za-z0-9_.-]+\.[A-Za-z0-9]+\b", normalized_goal):
        if "/" in candidate or "\\" in candidate:
            continue
        if candidate not in filenames:
            filenames.append(candidate)

    tasks: list[AgentTask] = []
    for filename in filenames[:5]:
        clause = next((item for item in clauses if filename in item), normalized_goal)
        clause_lower = clause.lower()
        if re.search(r"\b(update|modify|edit|refactor|fix)\b", clause_lower):
            verb = re.search(r"\b(update|modify|edit|refactor|fix)\b", clause_lower).group(1)
            label = f"{verb.capitalize()} {filename}"
        elif filename.startswith("test_") or "pytest" in clause_lower or "test" in filename.lower():
            label = f"Create {filename} with pytest coverage"
        else:
            label = f"Create {filename}"

        acceptance = (
            f"A file named {filename} exists in the workspace root and satisfies "
            f"this goal requirement: {clause}."
        )
        tasks.append(AgentTask(
            id=_task_id(),
            label=label,
            acceptance_criteria=acceptance,
        ))

    if len(tasks) >= 2:
        return tasks[:5]

    if len(tasks) == 1:
        tasks.append(AgentTask(
            id=_task_id(),
            label="Integrate the requested change into the workspace",
            acceptance_criteria=(
                "The requested behavior is fully implemented and any referenced "
                "supporting files or validation steps from the goal are present."
            ),
        ))
        return tasks

    return [
        AgentTask(
            id=_task_id(),
            label="Implement the primary requested change",
            acceptance_criteria=f"The workspace satisfies the requested goal: {normalized_goal}.",
        ),
        AgentTask(
            id=_task_id(),
            label="Add supporting validation for the requested change",
            acceptance_criteria=(
                "Any tests, validation files, or execution paths explicitly requested "
                "in the goal are present and usable."
            ),
        ),
    ]


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
            llm = build_sdk_llm(
                llm_config,
                default_model="gpt-4o",
                default_provider="openai",
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
            ctx = context or {}
            mcp_headers: dict[str, str] = {}
            if ctx.get("mcp_token"):
                mcp_headers["Authorization"] = f"Bearer {ctx['mcp_token']}"
            mcp_config = {
                "mcpServers": {
                    "sandbox": {
                        "url": f"http://127.0.0.1:{settings.port}/internal/mcp/tech-lead/sse",
                        "headers": mcp_headers,
                    },
                }
            }

            agent = Agent(
                llm=llm,
                agent_context=AgentContext(system_message_suffix=active_prompt),
                condenser=condenser,
                mcp_config=mcp_config,
            )

            # ── Resolve workspace path ─────────────────────────────────
            settings = get_settings()
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

            user_message = (
                f"[Run: {run_id}]\n\n"
                f"Goal:\n{goal}"
            )

            conversation.send_message(user_message)
            conversation.run()

            # ── Extract structured result from LLM output ──────────────
            raw_output = extract_last_assistant_text(llm_messages)

            # ── Mentorship mode: return raw guidance, skip JSON parsing ─
            if mentorship_mode:
                return LeaderAgentResult(
                    status="done",
                    tasks=[],
                    summary="Mentorship complete",
                    raw_output=raw_output,
                )

            return self._parse_result(raw_output, goal)

        except Exception as e:
            logger.exception("LeaderAgent.run() failed for run %s", run_id)
            return LeaderAgentResult(
                status="error",
                summary=f"Leader agent failed during planning: {e}",
                error=str(e),
            )

    def _parse_result(self, raw_output: str, goal: str) -> LeaderAgentResult:
        """
        Parse the LLM's raw output into a LeaderAgentResult.

        Expects a JSON array of task objects. Falls back to a deterministic
        task list derived from the goal if parsing fails completely.
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
            fallback_tasks = _build_fallback_tasks_from_goal(goal)
            return LeaderAgentResult(
                status="done",
                tasks=fallback_tasks,
                summary=(
                    "Leader output was unparseable; used deterministic fallback "
                    f"plan with {len(fallback_tasks)} tasks."
                ),
                raw_output=raw_output,
                error=f"JSON_PARSE_ERROR: {e}",
            )
