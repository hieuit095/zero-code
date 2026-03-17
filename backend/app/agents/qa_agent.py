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

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from pydantic import SecretStr

from ..config import get_settings

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
1. **read_file(path)** — inspect file content (read-only)
2. **write_file(path, content)** — write the critique report artifact
3. **exec(command, cwd)** — run verification commands (lint, typecheck, test)

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
You MUST use `write_file` to save a detailed critique to `/workspace/critique_report.md`
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
            mcp_config = {
                "mcpServers": {
                    "sandbox": {
                        "url": f"http://127.0.0.1:{settings.port}/internal/mcp/qa/sse",
                    },
                    "fetch": {"command": "uvx", "args": ["mcp-server-fetch"]},
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
            conversation.run()

            # ── Extract structured result from LLM output ──────────────
            raw_output = ""
            if llm_messages:
                for msg in reversed(llm_messages):
                    content = str(msg) if msg else ""
                    if content.strip():
                        raw_output = content
                        break

            return self._parse_result(raw_output, task_id, attempt)

        except Exception as e:
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
