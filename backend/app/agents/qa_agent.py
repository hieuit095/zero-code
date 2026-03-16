"""
QA Agent — Strict Verification Nanobot.

Responsibilities:
- Receives a workspace to verify after the Dev agent has made changes
- Runs linting, typechecking, and/or tests via MCP exec
- Outputs a STRUCTURED JSON payload — never raw text (Rule 2)
- Emits either `qa:report` (failure) or `qa:passed` (success)

The QA agent is called by the orchestrator after each Dev cycle.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from .mcp_tools import mcp_exec, mcp_read_file

# ─── System Prompt ────────────────────────────────────────────────────────────

QA_SYSTEM_PROMPT = """\
You are **QA**, the strict verification system in a multi-agent coding IDE.

## Your Role
After the Dev agent has made changes, you verify them by running checks
(lint, typecheck, tests) and reporting results in a structured format.
You are NOT a developer — you NEVER write or modify code.

## Available Tools (MCP Facade)
You have two tools, scoped to the current run's workspace:

1. **read_file(path)** → inspect file content
2. **exec(command)** → run verification commands (lint, typecheck, test)

## Verification Steps
1. Read the list of changed files provided in your input.
2. For each changed file, inspect it with `read_file` to understand the changes.
3. Run relevant verification commands with `exec`:
   - For Python: `python -m py_compile <file>`, `python -m pytest` (if tests exist)
   - For TypeScript: `npx tsc --noEmit`, `npx eslint <file>`
   - For general: any build or test command appropriate to the project
4. Analyze the output of each command.
5. Output your verdict as structured JSON.

## Output Format — FAILURE
If ANY check fails, output EXACTLY this JSON (no markdown, no extra text):
{
  "status": "failed",
  "taskId": "<current_task_id>",
  "attempt": <attempt_number>,
  "failingCommand": "<the command that failed>",
  "exitCode": <exit_code>,
  "summary": "Human-readable summary of all failures.",
  "rawLogTail": ["<last few lines of error output>"],
  "errors": [
    {
      "kind": "syntax|typecheck|lint|test",
      "file": "path/to/file.py",
      "line": 42,
      "message": "Specific error description"
    }
  ],
  "retryable": true
}

## Output Format — SUCCESS
If ALL checks pass, output EXACTLY this JSON:
{
  "status": "passed",
  "taskId": "<current_task_id>",
  "attempt": <attempt_number>,
  "commands": [
    {"command": "<cmd>", "exitCode": 0}
  ],
  "summary": "All checks passed. Brief description of what was verified."
}

## Rules
- NEVER output raw text. Your output MUST be valid JSON matching one of the schemas above.
- NEVER modify files. You are read-only + exec-only.
- Run at least ONE verification command. Do not skip verification.
- If a command times out, treat it as a failure with exitCode 124.
- Be thorough: check syntax, types, AND tests if available.
"""

# ─── Agent Definition ─────────────────────────────────────────────────────────


@dataclass
class QaAgentConfig:
    """Configuration for the QA agent."""

    system_prompt: str = QA_SYSTEM_PROMPT
    model: str = ""  # Filled from settings at runtime
    max_iterations: int = 10
    name: str = "qa"
    label: str = "QA"


@dataclass
class QaCheckResult:
    """Result of a single verification command."""

    command: str
    exit_code: int
    stdout: str = ""
    stderr: str = ""
    duration_ms: int = 0


@dataclass
class QaError:
    """A single error found during verification."""

    kind: str  # "syntax" | "typecheck" | "lint" | "test"
    file: str
    line: int
    message: str


@dataclass
class QaAgentResult:
    """Structured result from a QA agent run — always one of 'passed' or 'failed'."""

    status: str  # "passed" | "failed"
    task_id: str = ""
    attempt: int = 1
    summary: str = ""
    # Failure fields
    failing_command: str = ""
    exit_code: int = 0
    raw_log_tail: list[str] = field(default_factory=list)
    errors: list[QaError] = field(default_factory=list)
    retryable: bool = True
    # Success fields
    commands: list[QaCheckResult] = field(default_factory=list)
    # Debug
    raw_output: str = ""

    def to_report_dict(self) -> dict[str, Any]:
        """Serialize to the qa:report event data shape."""
        return {
            "taskId": self.task_id,
            "attempt": self.attempt,
            "status": "failed",
            "failingCommand": self.failing_command,
            "exitCode": self.exit_code,
            "summary": self.summary,
            "rawLogTail": self.raw_log_tail,
            "errors": [
                {"kind": e.kind, "file": e.file, "line": e.line, "message": e.message}
                for e in self.errors
            ],
            "retryable": self.retryable,
        }

    def to_passed_dict(self) -> dict[str, Any]:
        """Serialize to the qa:passed event data shape."""
        return {
            "taskId": self.task_id,
            "attempt": self.attempt,
            "commands": [
                {"command": c.command, "exitCode": c.exit_code}
                for c in self.commands
            ],
            "summary": self.summary,
        }


class QaAgent:
    """
    QA agent that verifies workspace changes via MCP tools.

    The agent is invoked by the orchestrator after each Dev cycle.
    It runs verification commands and returns structured results.
    """

    def __init__(self, config: QaAgentConfig | None = None) -> None:
        self.config = config or QaAgentConfig()

    async def run(
        self,
        run_id: str,
        task_id: str,
        attempt: int,
        changed_files: list[str],
        context: dict[str, Any] | None = None,
    ) -> QaAgentResult:
        """
        Execute the QA agent to verify workspace changes.

        Args:
            run_id: The current run ID (MCP scoping)
            task_id: The task being verified
            attempt: Current attempt number
            changed_files: List of files the Dev agent changed
            context: Optional additional context

        Returns:
            QaAgentResult with either 'passed' or 'failed' status.

        @ai-integration-point: Replace this stub with real LLM-backed agent
        execution. The conversation should use the QA system prompt, receive
        the changed files list as input, run verification commands via MCP
        exec, and output structured JSON.
        """
        try:
            check_results: list[QaCheckResult] = []
            all_errors: list[QaError] = []

            # ── Verify each changed file ──────────────────────────────
            for file_path in changed_files:
                # 1. Read the file to confirm it exists
                content = await mcp_read_file(run_id, file_path)

                # 2. Run syntax check based on file extension
                if file_path.endswith(".py"):
                    result = await mcp_exec(run_id, f"python -m py_compile {file_path}")
                    check_results.append(QaCheckResult(
                        command=f"python -m py_compile {file_path}",
                        exit_code=result["exitCode"],
                        stdout=result["stdout"],
                        stderr=result["stderr"],
                        duration_ms=result["durationMs"],
                    ))

                    if result["exitCode"] != 0:
                        # Parse errors from stderr
                        stderr_lines = result["stderr"].strip().splitlines()
                        for line in stderr_lines[-5:]:  # Last 5 lines
                            all_errors.append(QaError(
                                kind="syntax",
                                file=file_path,
                                line=0,
                                message=line.strip(),
                            ))

                elif file_path.endswith((".ts", ".tsx", ".js", ".jsx")):
                    result = await mcp_exec(run_id, f"npx tsc --noEmit {file_path}")
                    check_results.append(QaCheckResult(
                        command=f"npx tsc --noEmit {file_path}",
                        exit_code=result["exitCode"],
                        stdout=result["stdout"],
                        stderr=result["stderr"],
                        duration_ms=result["durationMs"],
                    ))

                    if result["exitCode"] != 0:
                        output = result["stdout"] + result["stderr"]
                        for line in output.strip().splitlines()[-5:]:
                            all_errors.append(QaError(
                                kind="typecheck",
                                file=file_path,
                                line=0,
                                message=line.strip(),
                            ))

            # ── Aggregate results ─────────────────────────────────────
            if all_errors:
                first_failure = next(
                    (c for c in check_results if c.exit_code != 0),
                    check_results[0] if check_results else QaCheckResult(command="unknown", exit_code=1),
                )
                return QaAgentResult(
                    status="failed",
                    task_id=task_id,
                    attempt=attempt,
                    failing_command=first_failure.command,
                    exit_code=first_failure.exit_code,
                    summary=f"Found {len(all_errors)} error(s) in {len(changed_files)} file(s).",
                    raw_log_tail=[e.message for e in all_errors[:10]],
                    errors=all_errors,
                    retryable=attempt < 3,
                    commands=check_results,
                )

            return QaAgentResult(
                status="passed",
                task_id=task_id,
                attempt=attempt,
                summary=f"All {len(check_results)} check(s) passed for {len(changed_files)} file(s).",
                commands=check_results,
            )

        except Exception as e:
            return QaAgentResult(
                status="failed",
                task_id=task_id,
                attempt=attempt,
                failing_command="qa_agent_internal",
                exit_code=1,
                summary=f"QA agent internal error: {e}",
                errors=[QaError(kind="internal", file="", line=0, message=str(e))],
                retryable=False,
            )
