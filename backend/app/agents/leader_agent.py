"""
Leader Agent — Tech Lead / Planner Nanobot.

Responsibilities:
- Receives the raw user goal and workspace context
- Analyzes the existing codebase via read-only MCP tools (list_tree, read_file)
- Decomposes the goal into a structured JSON array of sequential tasks
- NEVER writes code — planning and delegation only (Rule 1)

Output:
  A JSON array of AgentTask objects, each with:
    { "id": str, "label": str, "acceptanceCriteria": str }
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from .mcp_tools import mcp_exec, mcp_read_file

# ─── System Prompt ────────────────────────────────────────────────────────────

LEADER_SYSTEM_PROMPT = """\
You are **Tech Lead**, the planning agent in a multi-agent coding IDE.

## Your Role
You receive a user's high-level coding goal and decompose it into a sequence
of concrete, implementable tasks for the Dev agent. You DO NOT write code.

## Available Tools (MCP Facade — Read-Only)
1. **read_file(path)** → inspect existing file content
2. **exec(command)** → run read-only commands (e.g., `find`, `ls`, `tree`, `cat`)

You may use these to understand the existing workspace structure before planning.

## Planning Process
1. Analyze the user's goal carefully.
2. Optionally inspect the workspace to understand existing code structure.
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
- Acceptance criteria must be specific and verifiable (e.g., "File user.py exists and contains a User class with name and email fields").
- You MUST NOT include implementation details in your output — only WHAT to build, not HOW.
- You MUST NOT write any code or modify any files.
- Output ONLY the JSON array. No preamble, no explanation, no markdown.
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


class LeaderAgent:
    """
    Leader agent that decomposes a goal into structured tasks.

    The agent is invoked by the orchestrator before the Dev→QA loop begins.
    It uses read-only MCP tools to analyze the workspace, then outputs
    a JSON array of tasks.
    """

    def __init__(self, config: LeaderAgentConfig | None = None) -> None:
        self.config = config or LeaderAgentConfig()

    async def run(
        self,
        run_id: str,
        goal: str,
        context: dict[str, Any] | None = None,
    ) -> LeaderAgentResult:
        """
        Execute the Leader agent for goal decomposition.

        Args:
            run_id: The current run ID (used for MCP X-Run-Id scoping)
            goal: The user's high-level goal
            context: Optional workspace context

        Returns:
            LeaderAgentResult with a list of AgentTask objects.

        @ai-integration-point: Replace this stub with real LLM-backed planning.
        The conversation should use LEADER_SYSTEM_PROMPT, receive the goal,
        optionally call read_file/exec to inspect the workspace, and output
        the structured JSON task array.
        """
        try:
            # ── Stub: Generate 2–3 tasks from the goal ────────────────
            # In production, the LLM will analyze the goal + workspace
            # and produce a real task decomposition.

            # Optionally inspect workspace (demonstrates read-only MCP usage)
            try:
                listing = await mcp_exec(run_id, "dir /b" if _is_windows() else "ls -la")
                workspace_info = listing.get("stdout", "").strip()
            except Exception:
                workspace_info = "(unable to inspect workspace)"

            # Generate stub tasks based on goal keywords
            tasks = self._decompose_goal(goal, workspace_info)

            return LeaderAgentResult(
                status="done",
                tasks=tasks,
                summary=f"Decomposed goal into {len(tasks)} tasks.",
                raw_output=json.dumps(
                    [{"id": t.id, "label": t.label, "acceptanceCriteria": t.acceptance_criteria}
                     for t in tasks],
                    indent=2,
                ),
            )

        except Exception as e:
            return LeaderAgentResult(
                status="error",
                summary="Leader agent failed during planning.",
                error=str(e),
            )

    def _decompose_goal(self, goal: str, workspace_info: str) -> list[AgentTask]:
        """
        Stub task decomposition. Splits the goal into 2–3 concrete tasks.
        In production, this is replaced by LLM output parsing.
        """
        goal_lower = goal.lower()

        # Heuristic: extract action keywords and create tasks
        tasks: list[AgentTask] = []

        # Task 1: Always start with scaffolding / setup
        tasks.append(AgentTask(
            id=_task_id(),
            label=f"Set up project structure for: {goal[:60]}",
            acceptance_criteria=(
                "Project files and directories are created. "
                "All created files have valid syntax and no import errors."
            ),
        ))

        # Task 2: Core implementation
        tasks.append(AgentTask(
            id=_task_id(),
            label=f"Implement core logic: {goal[:60]}",
            acceptance_criteria=(
                "Core functionality is implemented as described in the goal. "
                "All code compiles/parses without errors."
            ),
        ))

        # Task 3: If the goal mentions testing, UI, or API — add a third task
        if any(kw in goal_lower for kw in ("test", "api", "ui", "form", "page", "endpoint", "route")):
            tasks.append(AgentTask(
                id=_task_id(),
                label=f"Add integration layer for: {goal[:50]}",
                acceptance_criteria=(
                    "Integration code connects the core logic to the target surface "
                    "(API route, UI component, or test suite). No runtime errors."
                ),
            ))

        return tasks


def _is_windows() -> bool:
    import sys
    return sys.platform == "win32"
