# ==========================================
# Author: Hieu Nguyen - Codev Team
# Email: hieuit095@gmail.com
# Project: ZeroCode - Autonomous Multi-Agent IDE
# ==========================================
"""
QA Agent — Strict Verification Nanobot (OpenHands SDK).

Responsibilities:
- Receives a workspace to verify after the Dev agent has made changes
- Runs linting, typechecking, and/or tests via tools
- Outputs a STRUCTURED JSON payload with 4 DIMENSIONAL SCORES (0-100)
- Emits either `qa:report` (failure) or `qa:passed` (success)

ARCHITECTURE: Uses the OpenHands SDK Conversation lifecycle:
  LLM → Agent(tools, agent_context) → Conversation(agent, workspace) → send_message → run()

The QA agent uses AgentContext + Skills for dynamic capability injection.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..config import get_settings
from .llm_utils import (
    build_sdk_llm,
    extract_message_text,
    extract_last_assistant_text,
    summarize_message_trace,
)

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
    from openhands.sdk.llm import Message, TextContent
    from openhands.sdk.context import Skill
    from openhands.sdk.context.condenser import LLMSummarizingCondenser
    _SDK_AVAILABLE = True
except ImportError:
    logger.warning(
        "OpenHands SDK not installed — QaAgent will operate in degraded stub mode. "
        "Install with: pip install openhands-sdk openhands-tools"
    )

# ─── Scoring Thresholds (used by orchestrator) ───────────────────────────────

SCORE_THRESHOLDS = {
    "code_quality": 70,
    "requirements": 80,
    "robustness": 70,
    "security": 90,
}

# ─── System Prompt ────────────────────────────────────────────────────────────

QA_SYSTEM_PROMPT = """\
You are **QA**, the strict verification system in a multi-agent coding IDE.

## Your Role
After the Dev agent has made changes, you verify them by running checks
(lint, typecheck, tests) and reporting results with DIMENSIONAL SCORES.
You are NOT a developer — you NEVER modify source code files.

## Available Tools
1. **workspace_read_file(path)** — inspect file content (read-only)
2. **workspace_write_file(path, content)** — write the critique report artifact
3. **workspace_exec(command, cwd)** — run verification commands (lint, typecheck, test)

## Verification Steps
1. Read the list of changed files provided in your input.
2. For each changed file, inspect it to understand the changes.
3. Run relevant verification commands:
   - For Python: `python -m py_compile <file>`, `python -m pytest` (if tests exist)
   - For TypeScript: `npx tsc --noEmit`, `npx eslint <file>`
   - For general: any build or test command appropriate to the project
4. Analyze the output of each command.
5. **Score the code on 4 strict dimensions (0-100 each).**
6. **Write your FULL detailed critique to `/workspace/critique_report.md`** (see below).
7. Output a LEAN JSON verdict to the orchestrator.

## MANDATORY: 4 Dimensional Scores (0-100)
You MUST evaluate and assign a score for EACH of these dimensions:

### 1. `code_quality` (0-100)
- 90-100: Clean, well-structured, follows best practices
- 70-89: Acceptable, minor style issues
- 50-69: Significant issues (dead code, poor naming, no comments)
- 0-49: Unacceptable (spaghetti code, massive functions, copy-paste)

### 2. `requirements` (0-100)
- 90-100: All acceptance criteria fully met
- 70-89: Most criteria met, minor gaps
- 50-69: Partial implementation, key features missing
- 0-49: Does not address the stated goal

### 3. `robustness` (0-100)
- 90-100: Handles edge cases, has error handling, tests pass
- 70-89: Basic error handling, most edge cases covered
- 50-69: Missing error handling for common failure modes
- 0-49: Crashes on basic input, no error handling

### 4. `security` (0-100)
- 90-100: No vulnerabilities, input validated, secrets safe
- 70-89: Minor issues (hardcoded values, missing validation)
- 50-69: Moderate vulnerabilities (SQL injection possible, XSS)
- 0-49: Critical vulnerabilities (arbitrary code exec, path traversal)

## Step 6: Write Critique Report
You MUST use `workspace_write_file` to save a detailed critique to `/workspace/critique_report.md`
in this EXACT format:

```
# QA Critique Report

## Summary
[Brief overall assessment]

## Dimensional Scores
- **Code Quality**: [score]/100 - [brief explanation]
- **Requirements**: [score]/100 - [brief explanation]
- **Robustness**: [score]/100 - [brief explanation]
- **Security**: [score]/100 - [brief explanation]

## File Evaluations
### [filename]
- **Issues Found**:
  - [specific issue 1 with line number]
  - [specific issue 2 with line number]

## Command Results
- `[command]` → exit code [code]: [brief result]

## Priority Improvements
1. [Most critical improvement needed]
2. [Second priority]
3. [Third priority]
```

## Step 7: JSON Output Format
After writing the critique report, output EXACTLY this LEAN JSON
(no markdown fences, no extra text):
{
  "status": "passed" | "failed",
  "taskId": "<current_task_id>",
  "attempt": <attempt_number>,
  "scores": {
    "code_quality": <0-100>,
    "requirements": <0-100>,
    "robustness": <0-100>,
    "security": <0-100>
  },
  "critiqueFile": "/workspace/critique_report.md",
  "commands": [
    {"command": "<cmd>", "exitCode": <code>}
  ],
  "summary": "One-line summary of the verdict.",
  "errors": [
    {
      "kind": "syntax|typecheck|lint|test|security",
      "file": "path/to/file",
      "line": 42,
      "message": "Specific error description"
    }
  ],
  "retryable": true
}

## Pass/Fail Rules
- Set "status": "passed" ONLY if ALL scores >= their thresholds:
  code_quality >= 70, requirements >= 80, robustness >= 70, security >= 90
- Set "status": "failed" if ANY score is below its threshold or ANY command fails.
- ALWAYS include the "scores" object regardless of pass/fail status.

## Rules
- NEVER output raw text. Your output MUST be valid JSON matching the schema above.
- You MUST write the detailed critique to `/workspace/critique_report.md` BEFORE outputting JSON.
- NEVER modify source code files. You may ONLY write to `critique_report.md`.
- Run at least ONE verification command.
- Be thorough: check syntax, types, AND tests if available.
- The "scores" object is MANDATORY in every response.
- Use ONLY the MCP workspace tools. Do not assume any host-local tools exist.
"""

# ─── Skills for Dynamic Injection ─────────────────────────────────────────────

PYTHON_SECURITY_SKILL = {
    "name": "python-security-review",
    "content": (
        "When reviewing Python code, check for:\n"
        "- os.system / subprocess.call with shell=True (command injection)\n"
        "- open() without proper path validation (path traversal)\n"
        "- pickle.loads on untrusted data (insecure deserialization)\n"
        "- eval() / exec() usage (arbitrary code execution)\n"
        "- SQL string formatting instead of parameterized queries\n"
        "- Hardcoded secrets or API keys\n"
        "- Missing input validation on user-facing endpoints"
    ),
}

TYPESCRIPT_SECURITY_SKILL = {
    "name": "typescript-security-review",
    "content": (
        "When reviewing TypeScript/JavaScript code, check for:\n"
        "- innerHTML / dangerouslySetInnerHTML without sanitization (XSS)\n"
        "- Dynamic import() with user input\n"
        "- Missing CSRF tokens on state-changing requests\n"
        "- Exposed API keys in client-side code\n"
        "- Missing Content-Security-Policy headers\n"
        "- Use of any type defeating type safety"
    ),
}

# ─── Data Structures ─────────────────────────────────────────────────────────


@dataclass
class QaScores:
    """The 4 mandatory dimensional scores (0-100)."""

    code_quality: int = 0
    requirements: int = 0
    robustness: int = 0
    security: int = 0

    def passes_thresholds(self) -> bool:
        """Check if all scores meet their minimum thresholds."""
        return (
            self.code_quality >= SCORE_THRESHOLDS["code_quality"]
            and self.requirements >= SCORE_THRESHOLDS["requirements"]
            and self.robustness >= SCORE_THRESHOLDS["robustness"]
            and self.security >= SCORE_THRESHOLDS["security"]
        )

    def failing_dimensions(self) -> list[str]:
        """Return names of dimensions that fail their threshold."""
        failures = []
        if self.code_quality < SCORE_THRESHOLDS["code_quality"]:
            failures.append(f"code_quality={self.code_quality} (min {SCORE_THRESHOLDS['code_quality']})")
        if self.requirements < SCORE_THRESHOLDS["requirements"]:
            failures.append(f"requirements={self.requirements} (min {SCORE_THRESHOLDS['requirements']})")
        if self.robustness < SCORE_THRESHOLDS["robustness"]:
            failures.append(f"robustness={self.robustness} (min {SCORE_THRESHOLDS['robustness']})")
        if self.security < SCORE_THRESHOLDS["security"]:
            failures.append(f"security={self.security} (min {SCORE_THRESHOLDS['security']})")
        return failures

    def to_dict(self) -> dict[str, int]:
        return {
            "code_quality": self.code_quality,
            "requirements": self.requirements,
            "robustness": self.robustness,
            "security": self.security,
        }


@dataclass
class QaAgentConfig:
    """Configuration for the QA agent."""

    system_prompt: str = QA_SYSTEM_PROMPT
    model: str = ""
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

    kind: str  # "syntax" | "typecheck" | "lint" | "test" | "internal" | "security"
    file: str
    line: int
    message: str


@dataclass
class QaAgentResult:
    """Structured result with MANDATORY dimensional scores."""

    status: str  # "passed" | "failed"
    task_id: str = ""
    attempt: int = 1
    summary: str = ""
    scores: QaScores = field(default_factory=QaScores)
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
        """Serialize to the qa:report event data shape (with scores)."""
        return {
            "taskId": self.task_id,
            "attempt": self.attempt,
            "status": "failed",
            "scores": self.scores.to_dict(),
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
        """Serialize to the qa:passed event data shape (with scores)."""
        return {
            "taskId": self.task_id,
            "attempt": self.attempt,
            "scores": self.scores.to_dict(),
            "commands": [
                {"command": c.command, "exitCode": c.exit_code}
                for c in self.commands
            ],
            "summary": self.summary,
        }


# ─── Skill Injection Logic ───────────────────────────────────────────────────


def _build_qa_skills(changed_files: list[str]) -> list[Any]:
    """
    Dynamically create Skill objects based on the file extensions
    in the changed files list. This injects specialized security
    review guidance tailored to the workspace context.
    """
    if not _SDK_AVAILABLE:
        return []

    skills_list = []
    extensions = {f.rsplit(".", 1)[-1].lower() for f in changed_files if "." in f}

    if extensions & {"py", "pyw"}:
        skills_list.append(Skill(
            name=PYTHON_SECURITY_SKILL["name"],
            content=PYTHON_SECURITY_SKILL["content"],
            trigger=None,  # Always loaded for this run
        ))

    if extensions & {"ts", "tsx", "js", "jsx"}:
        skills_list.append(Skill(
            name=TYPESCRIPT_SECURITY_SKILL["name"],
            content=TYPESCRIPT_SECURITY_SKILL["content"],
            trigger=None,
        ))

    return skills_list


# ─── Agent ────────────────────────────────────────────────────────────────────


class QaAgent:
    """
    QA agent with mandatory 4-dimensional scoring and AgentContext.

    Uses the SDK Conversation lifecycle with dynamically injected Skills
    based on the file types modified by the Dev agent.
    """

    def __init__(self, config: QaAgentConfig | None = None) -> None:
        self.config = config or QaAgentConfig()
        self._last_llm: Any = None  # Exposed for SDK metrics extraction

    async def run(
        self,
        run_id: str,
        task_id: str,
        attempt: int,
        changed_files: list[str],
        context: dict[str, Any] | None = None,
        llm_config: dict[str, Any] | None = None,
    ) -> QaAgentResult:
        """
        Execute the QA agent with dimensional scoring.

        Returns:
            QaAgentResult with scores, status, and structured error details.
        """
        if not _SDK_AVAILABLE:
            return QaAgentResult(
                status="failed",
                task_id=task_id,
                attempt=attempt,
                scores=QaScores(0, 0, 0, 0),
                failing_command="qa_agent_internal",
                exit_code=1,
                summary="OpenHands SDK is not installed.",
                errors=[QaError(kind="internal", file="", line=0, message="SDK_NOT_AVAILABLE")],
                retryable=False,
            )

        ctx = context or {}
        workspace_id = str(ctx.get("workspace_id", "repo-main"))
        llm: Any | None = None

        try:
            # ── Build LLM from dynamic config ──────────────────────────
            llm = build_sdk_llm(
                llm_config,
                default_model="gpt-4o",
                default_provider="openai",
                usage_id=f"qa-{run_id}",
            )
            self._last_llm = llm  # Expose for metrics extraction

            # ── Context Condenser (prevents token explosion on retries) ─
            llm_condenser = llm.model_copy(update={"usage_id": f"qa-condenser-{run_id}"})
            condenser = LLMSummarizingCondenser(
                llm=llm_condenser, max_size=10, keep_first=2,
            )

            # ── Build dynamic AgentContext with Skills ─────────────────
            qa_skills = _build_qa_skills(changed_files)
            agent_context = AgentContext(
                skills=qa_skills,
                system_message_suffix=(
                    f"{self.config.system_prompt}\n\n"
                    "Remember: You MUST include the 'scores' object with all 4 "
                    "dimensions (code_quality, requirements, robustness, security) "
                    "in EVERY response. Scores are integers 0-100."
                ),
            )

            # ── Create Agent with MCP Facade tools + context + condenser
            # PHASE 2: Tools are discovered via the internal MCP server,
            # NOT via native SDK ToolDefinition bindings.
            from ..config import get_settings
            settings = get_settings()
            mcp_headers: dict[str, str] = {}
            if ctx.get("mcp_token"):
                mcp_headers["Authorization"] = f"Bearer {ctx['mcp_token']}"
            mcp_config = {
                "mcpServers": {
                    "sandbox": {
                        "url": f"http://127.0.0.1:{settings.port}/internal/mcp/qa/sse",
                        "headers": mcp_headers,
                    },
                }
            }

            agent = Agent(
                llm=llm,
                agent_context=agent_context,
                condenser=condenser,
                mcp_config=mcp_config,
            )

            # ── Resolve workspace path ─────────────────────────────────
            settings = get_settings()
            workspace_path = str(settings.workspace_path / workspace_id)
            critique_path = Path(workspace_path) / "critique_report.md"
            force_assisted_review = self._should_force_assisted_review(
                changed_files=changed_files,
                context=ctx,
            )

            # Prevent stale verdict recovery from a previous task/attempt.
            try:
                critique_path.unlink(missing_ok=True)
            except OSError:
                logger.warning(
                    "Unable to clear stale critique report at %s before QA run",
                    critique_path,
                    exc_info=True,
                )

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
                max_iteration_per_run=self.config.max_iterations,
                visualizer=None,
            )

            files_list = "\n".join(f"  - {f}" for f in changed_files)
            user_message = (
                f"[Run: {run_id} | Task: {task_id} | Attempt: {attempt}]\n\n"
                f"The Dev agent has made changes to the following files:\n{files_list}\n\n"
                f"Please verify these changes by:\n"
                f"1. Inspecting each changed file\n"
                f"2. Running appropriate verification commands\n"
                f"3. Scoring on ALL 4 dimensions (code_quality, requirements, robustness, security)\n"
                f"4. Output your structured JSON verdict with scores."
            )

            conversation.send_message(user_message)
            try:
                conversation.run()
            except Exception as exc:
                logger.warning(
                    "QA agent conversation failed for run=%s task=%s attempt=%s; "
                    "attempting deterministic assisted review",
                    run_id,
                    task_id,
                    attempt,
                    exc_info=True,
                )
                assisted = await self._run_assisted_review(
                    llm=llm,
                    workspace_id=workspace_id,
                    workspace_path=workspace_path,
                    task_id=task_id,
                    attempt=attempt,
                    changed_files=changed_files,
                    context=ctx,
                    prior_result=QaAgentResult(
                        status="failed",
                        task_id=task_id,
                        attempt=attempt,
                        scores=QaScores(0, 0, 0, 0),
                        failing_command="qa_agent_internal",
                        exit_code=1,
                        summary=f"QA agent conversation failed: {exc}",
                        errors=[QaError(
                            kind="internal",
                            file="",
                            line=0,
                            message=str(exc),
                        )],
                        retryable=False,
                    ),
                    force=True,
                )
                if assisted is not None:
                    logger.warning(
                        "Recovered QA result via assisted review after conversation failure "
                        "for run=%s task=%s attempt=%s",
                        run_id,
                        task_id,
                        attempt,
                    )
                    return assisted
                raise

            # ── Extract structured result from LLM output ──────────────
            raw_output = extract_last_assistant_text(llm_messages)
            if not raw_output:
                logger.warning(
                    "QA agent returned no assistant output for run=%s task=%s attempt=%s. "
                    "event_types=%s recent_messages=%s",
                    run_id,
                    task_id,
                    attempt,
                    [type(event).__name__ for event in conversation.state.events[-12:]],
                    summarize_message_trace(llm_messages),
                )

            parsed_result = self._parse_result(raw_output, task_id, attempt)
            scores_are_zero = parsed_result.scores.to_dict() == {
                "code_quality": 0,
                "requirements": 0,
                "robustness": 0,
                "security": 0,
            }
            if parsed_result.failing_command == "qa_output_parse" or scores_are_zero:
                recovered = self._recover_from_critique_report(
                    critique_path=critique_path,
                    task_id=task_id,
                    attempt=attempt,
                    raw_output=raw_output,
                )
                if recovered is not None:
                    logger.warning(
                        "Recovered QA result from critique report for run=%s task=%s attempt=%s",
                        run_id,
                        task_id,
                        attempt,
                    )
                    return recovered

            assisted = await self._run_assisted_review(
                llm=llm,
                workspace_id=workspace_id,
                workspace_path=workspace_path,
                task_id=task_id,
                attempt=attempt,
                changed_files=changed_files,
                context=ctx,
                prior_result=parsed_result,
                force=force_assisted_review,
            )
            if assisted is not None:
                logger.warning(
                    "Recovered QA result via assisted review for run=%s task=%s attempt=%s",
                    run_id,
                    task_id,
                    attempt,
                )
                return assisted

            return parsed_result

        except Exception as e:
            if llm is not None:
                try:
                    from ..config import get_settings

                    workspace_path = str(get_settings().workspace_path / workspace_id)
                    assisted = await self._run_assisted_review(
                        llm=llm,
                        workspace_id=workspace_id,
                        workspace_path=workspace_path,
                        task_id=task_id,
                        attempt=attempt,
                        changed_files=changed_files,
                        context=ctx,
                        prior_result=QaAgentResult(
                            status="failed",
                            task_id=task_id,
                            attempt=attempt,
                            scores=QaScores(0, 0, 0, 0),
                            failing_command="qa_agent_internal",
                            exit_code=1,
                            summary=f"QA agent internal error: {e}",
                            errors=[QaError(
                                kind="internal",
                                file="",
                                line=0,
                                message=str(e),
                            )],
                            retryable=False,
                        ),
                        force=True,
                    )
                    if assisted is not None:
                        logger.warning(
                            "Recovered QA result via assisted review after exception "
                            "for run=%s task=%s attempt=%s",
                            run_id,
                            task_id,
                            attempt,
                        )
                        return assisted
                except Exception:
                    logger.warning(
                        "Assisted QA recovery failed after exception for run=%s task=%s attempt=%s",
                        run_id,
                        task_id,
                        attempt,
                        exc_info=True,
                    )
            logger.exception("QaAgent.run() failed for run %s", run_id)
            return QaAgentResult(
                status="failed",
                task_id=task_id,
                attempt=attempt,
                scores=QaScores(0, 0, 0, 0),
                failing_command="qa_agent_internal",
                exit_code=1,
                summary=f"QA agent internal error: {e}",
                errors=[QaError(kind="internal", file="", line=0, message=str(e))],
                retryable=False,
            )

    def _parse_result(
        self, raw_output: str, task_id: str, attempt: int,
    ) -> QaAgentResult:
        """
        Parse the LLM's raw output into a QaAgentResult with dimensional scores.
        """
        json_str = raw_output

        # Strip markdown fences
        if "```json" in json_str:
            start = json_str.index("```json") + 7
            end = json_str.index("```", start)
            json_str = json_str[start:end].strip()
        elif "```" in json_str:
            start = json_str.index("```") + 3
            end = json_str.index("```", start)
            json_str = json_str[start:end].strip()

        # Find JSON object boundaries
        brace_start = json_str.find("{")
        brace_end = json_str.rfind("}")
        if brace_start != -1 and brace_end != -1:
            json_str = json_str[brace_start : brace_end + 1]

        try:
            parsed = json.loads(json_str)

            # ── Extract dimensional scores (MANDATORY) ─────────────────
            scores_data = parsed.get("scores", {})
            scores = QaScores(
                code_quality=int(scores_data.get("code_quality", 0)),
                requirements=int(scores_data.get("requirements", 0)),
                robustness=int(scores_data.get("robustness", 0)),
                security=int(scores_data.get("security", 0)),
            )

            # ── Determine status based on scores + explicit status ─────
            explicit_status = parsed.get("status", "failed")
            # Override: even if LLM says "passed", if scores fail thresholds → failed
            if not scores.passes_thresholds():
                explicit_status = "failed"

            # ── Parse errors ───────────────────────────────────────────
            errors = []
            for err_data in parsed.get("errors", []):
                errors.append(QaError(
                    kind=err_data.get("kind", "unknown"),
                    file=err_data.get("file", ""),
                    line=err_data.get("line", 0),
                    message=err_data.get("message", ""),
                ))

            # ── Parse commands ─────────────────────────────────────────
            commands = []
            for cmd_data in parsed.get("commands", []):
                commands.append(QaCheckResult(
                    command=cmd_data.get("command", "unknown"),
                    exit_code=cmd_data.get("exitCode", 0),
                ))

            # ── Build result ───────────────────────────────────────────
            summary = parsed.get("summary", "")
            if explicit_status == "failed" and not scores.passes_thresholds():
                failing = scores.failing_dimensions()
                summary += f" | Failing dimensions: {', '.join(failing)}"

            return QaAgentResult(
                status=explicit_status,
                task_id=parsed.get("taskId", task_id),
                attempt=parsed.get("attempt", attempt),
                scores=scores,
                summary=summary,
                commands=commands,
                errors=errors,
                retryable=parsed.get("retryable", attempt < 3),
                failing_command=parsed.get("failingCommand", ""),
                exit_code=parsed.get("exitCode", 0),
                raw_log_tail=parsed.get("rawLogTail", []),
                raw_output=raw_output,
            )

        except (json.JSONDecodeError, ValueError) as e:
            logger.warning(
                "Failed to parse QA output: %s. Raw: %s", e, raw_output[:300],
            )
            return QaAgentResult(
                status="failed",
                task_id=task_id,
                attempt=attempt,
                scores=QaScores(0, 0, 0, 0),
                failing_command="qa_output_parse",
                exit_code=1,
                summary=f"QA agent produced unparseable output: {e}",
                errors=[QaError(kind="internal", file="", line=0, message=f"JSON parse error: {e}")],
                retryable=False,
                raw_output=raw_output,
            )

    def _recover_from_critique_report(
        self,
        critique_path: Path,
        task_id: str,
        attempt: int,
        raw_output: str,
    ) -> QaAgentResult | None:
        """Recover a structured QA result from the generated critique report."""
        if not critique_path.exists():
            return None

        try:
            report_text = critique_path.read_text(encoding="utf-8")
        except OSError:
            logger.warning("Unable to read critique report at %s", critique_path, exc_info=True)
            return None

        def _extract_score(label: str) -> int | None:
            pattern = rf"- \*\*{re.escape(label)}\*\*: (\d+)(?:/100)?\b"
            match = re.search(pattern, report_text, re.IGNORECASE)
            return int(match.group(1)) if match else None

        code_quality = _extract_score("Code Quality")
        requirements = _extract_score("Requirements")
        robustness = _extract_score("Robustness")
        security = _extract_score("Security")
        if None in {code_quality, requirements, robustness, security}:
            return None

        scores = QaScores(
            code_quality=code_quality or 0,
            requirements=requirements or 0,
            robustness=robustness or 0,
            security=security or 0,
        )

        summary_match = re.search(r"## Summary\s*(.*?)(?:\n## |\Z)", report_text, re.S)
        summary = " ".join(summary_match.group(1).split()) if summary_match else ""

        commands: list[QaCheckResult] = []
        for match in re.finditer(
            r"- `([^`]+)`\s*[→\x1a]\s*exit code\s+(-?\d+):\s*(.+)",
            report_text,
        ):
            commands.append(
                QaCheckResult(
                    command=match.group(1).strip(),
                    exit_code=int(match.group(2)),
                    stdout=match.group(3).strip(),
                )
            )

        status = "passed" if scores.passes_thresholds() else "failed"
        failing_command = ""
        exit_code = 0
        for command in commands:
            if command.exit_code != 0:
                failing_command = command.command
                exit_code = command.exit_code
                break

        if not failing_command and commands:
            failing_command = commands[0].command if status == "failed" else ""

        if not summary:
            summary = "Recovered QA verdict from critique_report.md"

        return QaAgentResult(
            status=status,
            task_id=task_id,
            attempt=attempt,
            summary=summary,
            scores=scores,
            failing_command=failing_command,
            exit_code=exit_code,
            commands=commands,
            retryable=(status != "passed" and attempt < 3),
            raw_output=raw_output or report_text,
        )

    async def _run_assisted_review(
        self,
        llm: Any,
        workspace_id: str,
        workspace_path: str,
        task_id: str,
        attempt: int,
        changed_files: list[str],
        context: dict[str, Any],
        prior_result: QaAgentResult,
        force: bool = False,
    ) -> QaAgentResult | None:
        """
        Fallback QA path:
        1. Run deterministic sandbox checks through the OpenHands runtime.
        2. Ask the real QA model to score those concrete results in one shot.
        3. Persist critique_report.md and recover a structured verdict from it.
        """
        scores_are_zero = prior_result.scores.to_dict() == {
            "code_quality": 0,
            "requirements": 0,
            "robustness": 0,
            "security": 0,
        }
        should_recover = force or (
            prior_result.failing_command == "qa_output_parse"
            or (prior_result.status == "failed" and scores_are_zero)
        )
        if not should_recover:
            return None

        critique_path = Path(workspace_path) / "critique_report.md"

        from ..services.openhands_client import get_openhands_client

        runtime = get_openhands_client().get_runtime(workspace_id)

        expected_files = self._extract_expected_workspace_files(context)
        file_payloads: list[tuple[str, str]] = []
        for path in dict.fromkeys(changed_files + expected_files):
            try:
                content = await asyncio.to_thread(runtime.read_file, path)
            except Exception:
                logger.warning("Assisted QA could not read %s", path, exc_info=True)
                continue
            file_payloads.append((path, content[:12000]))

        commands = self._select_assisted_commands(
            workspace_path=workspace_path,
            changed_files=changed_files,
            context=context,
        )
        command_results: list[QaCheckResult] = []
        for command in commands:
            observation = await asyncio.to_thread(
                runtime.execute_terminal,
                command,
                "/workspace",
            )
            command_results.append(
                QaCheckResult(
                    command=command,
                    exit_code=observation.exit_code,
                    stdout=(observation.stdout or observation.text or "")[:8000],
                    stderr=(observation.stderr or "")[:4000],
                    duration_ms=getattr(observation, "duration_ms", 0),
                )
            )

        report_text = self._generate_assisted_report(
            llm=llm,
            task_id=task_id,
            attempt=attempt,
            changed_files=changed_files,
            file_payloads=file_payloads,
            command_results=command_results,
            context=context,
        )
        if not report_text:
            return None

        write_result = await asyncio.to_thread(
            runtime.write_file,
            "/workspace/critique_report.md",
            report_text,
        )
        if "successfully" not in write_result.lower():
            logger.warning("Assisted QA could not write critique report: %s", write_result)
            return None

        recovered = self._recover_from_critique_report(
            critique_path=critique_path,
            task_id=task_id,
            attempt=attempt,
            raw_output=report_text,
        )
        if recovered is None:
            return None

        recovered.commands = command_results
        for command in command_results:
            if command.exit_code != 0:
                recovered.failing_command = command.command
                recovered.exit_code = command.exit_code
                break
        return recovered

    def _should_force_assisted_review(
        self,
        *,
        changed_files: list[str],
        context: dict[str, Any],
    ) -> bool:
        """
        Force deterministic QA checks for test-oriented tasks.

        This prevents the model from hallucinating pytest targets when the task
        explicitly requires executing tests.
        """
        task_label = str(context.get("task_label", "") or "").lower()
        task_acceptance = str(context.get("task_acceptance", "") or "").lower()

        if "pytest" in task_label or "pytest" in task_acceptance:
            return True
        if "test_" in task_label or "test_" in task_acceptance:
            return True
        return any(
            path.lower().endswith(".py") and "/test" in path.lower()
            for path in changed_files
        )

    def _select_assisted_commands(
        self,
        *,
        workspace_path: str,
        changed_files: list[str],
        context: dict[str, Any],
    ) -> list[str]:
        """Choose deterministic verification commands for the assisted QA fallback."""
        commands: list[str] = []
        expected_files = self._extract_expected_workspace_files(context)
        expected_rel_files = [
            path[len("/workspace/"):]
            for path in expected_files
            if path.startswith("/workspace/")
        ]

        if expected_rel_files:
            quoted_files = ", ".join(repr(path) for path in expected_rel_files)
            commands.append(
                'python -c "from pathlib import Path; import sys; '
                f'files=[{quoted_files}]; '
                "missing=[f for f in files if not Path(f).exists()]; "
                "print('ALL_PRESENT' if not missing else 'MISSING:' + ','.join(missing)); "
                "raise SystemExit(1 if missing else 0)\""
            )

        changed_python = [
            path for path in changed_files
            if path.lower().endswith(".py")
        ]
        if changed_python:
            commands.append(
                "python -m py_compile " + " ".join(changed_python)
            )

        workspace_root = Path(workspace_path)
        pytest_targets = sorted(
            f"/workspace/{path.name}"
            for path in workspace_root.glob("test*.py")
            if path.is_file()
        )
        task_label = str(context.get("task_label", "") or "").lower()
        task_acceptance = str(context.get("task_acceptance", "") or "").lower()
        requires_pytest = (
            "pytest" in task_label
            or "pytest" in task_acceptance
            or "test_" in task_label
            or "test_" in task_acceptance
            or any(path.lower().startswith("/workspace/test") for path in expected_files)
        )
        if requires_pytest:
            commands.append("python -m pytest -q")
        elif pytest_targets:
            commands.append("python -m pytest -q " + " ".join(pytest_targets))

        return commands

    def _extract_expected_workspace_files(
        self,
        context: dict[str, Any],
    ) -> list[str]:
        """Parse expected root-level filenames from the task label/acceptance."""
        filenames: list[str] = []
        for text in (
            str(context.get("task_label", "") or ""),
            str(context.get("task_acceptance", "") or ""),
        ):
            for candidate in re.findall(r"\b[A-Za-z0-9_.-]+\.[A-Za-z0-9]+\b", text):
                if "/" in candidate or "\\" in candidate:
                    continue
                workspace_file = f"/workspace/{candidate}"
                if workspace_file not in filenames:
                    filenames.append(workspace_file)
        return filenames

    def _generate_assisted_report(
        self,
        *,
        llm: Any,
        task_id: str,
        attempt: int,
        changed_files: list[str],
        file_payloads: list[tuple[str, str]],
        command_results: list[QaCheckResult],
        context: dict[str, Any],
    ) -> str:
        """Ask the real QA model for a markdown critique based on executed evidence."""
        task_label = context.get("task_label", "")
        task_acceptance = context.get("task_acceptance", "")
        overall_goal = context.get("goal", "")

        files_block = "\n\n".join(
            f"### {path}\n```python\n{content}\n```"
            for path, content in file_payloads
        ) or "No changed file content could be read."

        commands_block = "\n\n".join(
            (
                f"Command: {result.command}\n"
                f"Exit code: {result.exit_code}\n"
                f"STDOUT:\n{result.stdout or '(empty)'}\n"
                f"STDERR:\n{result.stderr or '(empty)'}"
            )
            for result in command_results
        ) or "No verification commands were executed."

        messages = [
            Message(
                role="system",
                content=[TextContent(text=(
                    "You are QA, the strict verification system in a multi-agent coding IDE. "
                    "You are given real changed files and real sandbox command results. "
                    "Write ONLY a Markdown critique report in this exact structure:\n\n"
                    "# QA Critique Report\n\n"
                    "## Summary\n"
                    "[Brief overall assessment]\n\n"
                    "## Dimensional Scores\n"
                    "- **Code Quality**: [score]/100 - [brief explanation]\n"
                    "- **Requirements**: [score]/100 - [brief explanation]\n"
                    "- **Robustness**: [score]/100 - [brief explanation]\n"
                    "- **Security**: [score]/100 - [brief explanation]\n\n"
                    "## File Evaluations\n"
                    "### [filename]\n"
                    "- **Issues Found**:\n"
                    "  - [issue or 'None']\n\n"
                    "## Command Results\n"
                    "- `[command]` → exit code [code]: [brief result]\n\n"
                    "## Priority Improvements\n"
                    "1. [Most critical improvement]\n"
                    "2. [Second priority]\n"
                    "3. [Third priority]\n\n"
                    "Rules:\n"
                    "- Do not use code fences around the full report.\n"
                    "- Base scores only on the evidence provided.\n"
                    "- If a required filename or testing approach is wrong, penalize Requirements and Robustness.\n"
                    "- If pytest output shows failures or no tests collected, do not pass Requirements/Robustness.\n"
                    "- Use integer scores only."
                ))]
            ),
            Message(
                role="user",
                content=[TextContent(text=(
                    f"Task ID: {task_id}\n"
                    f"Attempt: {attempt}\n"
                    f"Task Label: {task_label}\n"
                    f"Task Acceptance Criteria: {task_acceptance}\n"
                    f"Overall Goal: {overall_goal}\n"
                    f"Changed Files: {', '.join(changed_files) or '(none)'}\n\n"
                    f"Changed File Contents:\n{files_block}\n\n"
                    f"Actual Sandbox Command Results:\n{commands_block}"
                ))]
            ),
        ]

        try:
            response = llm.completion(messages=messages, tools=[])
        except Exception:
            logger.warning("Assisted QA LLM completion failed", exc_info=True)
            return ""

        return extract_message_text(response.message)
