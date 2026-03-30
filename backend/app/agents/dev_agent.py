# ==========================================
# Author: Hieu Nguyen - Codev Team
# Email: hieuit095@gmail.com
# Project: ZeroCode - Autonomous Multi-Agent IDE
# ==========================================
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
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..config import get_settings
from .llm_utils import build_sdk_llm, extract_last_assistant_text

logger = logging.getLogger(__name__)

from uuid import uuid4  # Ralph-loop temp file naming

_RUNTIME_DIR_NAMES = {
    ".git",
    ".pytest_cache",
    "__pycache__",
    "bash_events",
    "conversations",
    "memory",
    "sessions",
}

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
You have the following MCP tools at your disposal:

1. **workspace_read_file(path)** — inspect existing files inside `/workspace`
2. **workspace_write_file(path, content)** — create or fully rewrite files inside `/workspace`
3. **workspace_exec(command, cwd)** — run shell commands inside the sandboxed workspace
4. **finish(message)** — signal completion of the task

## Workflow
1. Analyze the goal or defect report.
2. Read the existing files you plan to change before editing them.
3. Plan your changes (think step-by-step).
4. Use `workspace_write_file` to create or update files.
5. Use `workspace_exec` to verify your changes compile/run.
6. As soon as the verification command succeeds, call `finish(message)` with the structured JSON summary below.

## Output Format
When you finish, use the `finish` tool and pass EXACTLY this JSON as the `message` value
(no markdown fences, no extra text):
{
  "status": "done",
  "filesChanged": ["path/to/file1.py", "path/to/file2.ts"],
  "summary": "Brief description of what was implemented or fixed."
}

## Rules
- NEVER skip reading a file before modifying it — always inspect first.
- On retry with a QA report, fix EVERY issue in the report before finishing.
- Keep your changes minimal and focused on the goal.
- Use ONLY the MCP workspace tools. Do not assume any host-local tools exist.
- Do NOT keep re-reading files or re-running tests after you already have a passing verification result.
- Once the task is complete, call `finish` immediately.
"""

# ─── Agent Definition ─────────────────────────────────────────────────────────


@dataclass
class DevAgentConfig:
    """Configuration for the Dev agent."""

    system_prompt: str = DEV_SYSTEM_PROMPT
    model: str = ""  # Filled from settings at runtime
    max_iterations: int = 12
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
    ) -> DevAgentResult:
        """
        Execute the Dev agent for a given goal.

        Args:
            run_id: The current run ID (used for MCP X-Run-Id scoping)
            goal: The user's goal or QA defect report JSON
            context: Optional additional context (workspace files, etc.)
            llm_config: Dynamic LLM configuration from the database:
                        {"model": str, "provider": str, "api_key": str, "base_url": str | None}

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
            llm = build_sdk_llm(
                llm_config,
                default_model="gpt-4o",
                default_provider="openai",
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
            ctx = context or {}
            mcp_headers: dict[str, str] = {}
            if ctx.get("mcp_token"):
                mcp_headers["Authorization"] = f"Bearer {ctx['mcp_token']}"
            mcp_config = {
                "mcpServers": {
                    "sandbox": {
                        "url": f"http://127.0.0.1:{settings.port}/internal/mcp/dev/sse",
                        "headers": mcp_headers,
                    },
                }
            }

            agent = Agent(
                llm=llm,
                agent_context=AgentContext(system_message_suffix=self.config.system_prompt),
                condenser=condenser,
                mcp_config=mcp_config,
            )

            # ── Resolve workspace path ─────────────────────────────────
            settings = get_settings()
            workspace_id = ctx.get("workspace_id", "repo-main")
            workspace_path = str(settings.workspace_path / workspace_id)
            workspace_root = Path(workspace_path)
            before_snapshot = self._snapshot_workspace(workspace_root)

            # ── Collect LLM messages via callback ──────────────────────
            llm_messages: list[Any] = []

            def _on_event(event: Event) -> None:
                if isinstance(event, LLMConvertibleEvent):
                    llm_messages.append(event.to_llm_message())

            attempt = ctx.get("attempt", 1)
            task_id = ctx.get("task_id", "unknown")
            conversation_error: Exception | None = None

            # ── Start Conversation lifecycle ───────────────────────────
            conversation = Conversation(
                agent=agent,
                callbacks=[_on_event],
                workspace=workspace_path,
                max_iteration_per_run=self.config.max_iterations,
                visualizer=None,
            )

            # Build the user message with context
            user_message = (
                f"[Run: {run_id} | Task: {task_id} | Attempt: {attempt}]\n\n"
                f"{goal}"
            )

            conversation.send_message(user_message)
            # P0-C FIX: Record message count before conversation.run().
            # If LLM produces no new messages (empty response), return immediately.
            prev_msg_count = len(llm_messages)
            try:
                # HANG FIX: conversation.run() is synchronous and blocks the
                # asyncio event loop for the entire LLM execution (minutes for
                # complex tasks). Offload to a thread so Redis publishes,
                # WebSocket heartbeats, and other coroutines keep running.
                await asyncio.to_thread(conversation.run)
            except (asyncio.CancelledError, SystemError, MemoryError, KeyboardInterrupt):
                raise
            except Exception as exc:
                conversation_error = exc
                logger.warning(
                    "Dev agent conversation interrupted for run=%s task=%s attempt=%s; "
                    "attempting workspace-state recovery",
                    run_id,
                    task_id,
                    attempt,
                    exc_info=True,
                )

            # P0-C FIX: If LLM produced no new messages, return Ralph_retry_empty immediately.
            if len(llm_messages) == prev_msg_count:
                logger.error(
                    "Ralph initial conversation produced ZERO new LLM messages for run=%s task=%s "
                    "— aborting (LLM returned nothing)",
                    run_id, task_id,
                )
                return DevAgentResult(
                    status="Ralph_retry_empty",
                    summary="Ralph initial run failed: LLM returned no output (content filter or crash)",
                    error="RALPH_NO_OUTPUT: LLM produced no new messages on initial run",
                    files_changed=[],
                )

            # ── Extract structured result from LLM output ──────────────
            raw_output = extract_last_assistant_text(llm_messages)
            after_snapshot = self._snapshot_workspace(workspace_root)

            if conversation_error is not None:
                recovered = self._recover_from_partial_execution(
                    raw_output,
                    before_snapshot=before_snapshot,
                    after_snapshot=after_snapshot,
                    error=conversation_error,
                )
                if recovered is not None:
                    return recovered
                raise conversation_error

            # ── Ralph-loop: syntax check before QA handoff ─────────────────────
            # ATLAS Anti-Silent-Failure: if py_compile finds SyntaxErrors,
            # re-inject them into Dev's context and retry (up to 2 times).
            Ralph_MAX_RETRIES = 2
            Ralph_files_changed: list[str] = []

            for Ralph_attempt in range(Ralph_MAX_RETRIES + 1):
                Ralph_syntax_error = await self._ralph_check_changed_files(
                    workspace_root=workspace_root,
                    files_changed=None,
                    before_snapshot=before_snapshot,
                    after_snapshot=after_snapshot,
                )
                if Ralph_syntax_error is None:
                    break  # Ralph is satisfied — proceed to QA

                if Ralph_attempt < Ralph_MAX_RETRIES:
                    # P0-A FIX: If conversation.run() raises ANY exception,
                    # Ralph must NOT fall through to parse_result() with potentially
                    # corrupted/empty llm_messages. Re-raise explicitly so the
                    # run is marked as failed, not as "Ralph succeeded but found errors."
                    logger.info(
                        "Ralph [%d/%d] syntax error for run=%s task=%s — "
                        "re-injecting into Dev context for self-repair",
                        Ralph_attempt + 1, Ralph_MAX_RETRIES, run_id, task_id,
                    )
                    Ralph_retry_msg = (
                        f"[RALPH SYNTAX CHECK FAILED — Attempt {Ralph_attempt + 1}/{Ralph_MAX_RETRIES}]\n"
                        f"Your submitted code has the following syntax errors:\n"
                        f"{Ralph_syntax_error}\n\n"
                        f"IMPORTANT: Fix all the errors above. Then output the JSON result "
                        f"with corrected files_changed.\n"
                        f"Do not explain the errors — just fix them and re-output the JSON."
                    )
                    conversation.send_message(Ralph_retry_msg)
                    pre_retry_msg_count = len(llm_messages)
                    try:
                        await asyncio.to_thread(conversation.run)
                    except Exception as Ralph_conv_exc:
                        # P0-A: Re-raise so the run is explicitly marked as failed.
                        # Do NOT fall through to parse_result() with empty/partial output.
                        logger.error(
                            "Ralph retry conversation CRASHED for run=%s task=%s attempt=%s — "
                            "re-raising as DevAgentError: %s",
                            run_id, task_id, Ralph_attempt + 1, Ralph_conv_exc,
                            exc_info=True,
                        )
                        return DevAgentResult(
                            status="error",
                            summary=f"Ralph retry crashed: {Ralph_conv_exc}",
                            error=f"RALPH_CONVERSATION_ERROR: {Ralph_conv_exc}",
                            files_changed=[],
                        )

                    # P0-C FIX: Validate that the LLM actually produced new output after the retry.
                    # If llm_messages didn't grow, the LLM returned nothing — treat as Ralph failure.
                    post_retry_msg_count = len(llm_messages)
                    if post_retry_msg_count <= pre_retry_msg_count:
                        logger.error(
                            "Ralph retry produced ZERO new LLM messages for run=%s task=%s "
                            "attempt=%d — aborting (LLM returned nothing)",
                            run_id, task_id, Ralph_attempt + 1,
                        )
                        return DevAgentResult(
                            status="Ralph_retry_empty",
                            summary="Ralph retry failed: LLM returned no output (content filter or crash)",
                            error=f"RALPH_NO_OUTPUT: LLM produced no new messages on attempt {Ralph_attempt + 1}",
                            files_changed=[],
                        )

                    raw_output = extract_last_assistant_text(llm_messages)
                    after_snapshot = self._snapshot_workspace(workspace_root)
                    continue

                # Ralph exhausted — all retries failed
                logger.error(
                    "Ralph FAILED after %d self-repair attempts for run=%s task=%s "
                    "— aborting Dev handoff to QA",
                    Ralph_MAX_RETRIES, run_id, task_id,
                )
                return DevAgentResult(
                    status="ralph_failed",
                    summary=(
                        f"Ralph-loop failed after {Ralph_MAX_RETRIES} self-repair attempts. "
                        f"Syntax errors must be resolved before QA."
                    ),
                    error=f"RALPH_SYNTAX_ERROR: {Ralph_syntax_error}",
                    files_changed=[],
                )

            return self._parse_result(
                raw_output,
                before_snapshot=before_snapshot,
                after_snapshot=after_snapshot,
            )

        except Exception as e:
            logger.exception("DevAgent.run() failed for run %s", run_id)
            return DevAgentResult(
                status="error",
                summary=f"Dev agent failed during execution: {e}",
                error=str(e),
            )

    def _parse_result(
        self,
        raw_output: str,
        *,
        before_snapshot: dict[str, tuple[int, int]],
        after_snapshot: dict[str, tuple[int, int]],
    ) -> DevAgentResult:
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
            files_changed = self._normalize_changed_files(parsed.get("filesChanged", []))
            if not files_changed:
                files_changed = self._infer_changed_files(
                    raw_output,
                    before_snapshot=before_snapshot,
                    after_snapshot=after_snapshot,
                )
            return DevAgentResult(
                status=parsed.get("status", "done"),
                files_changed=files_changed,
                summary=parsed.get("summary", ""),
                raw_output=raw_output,
            )
        except (json.JSONDecodeError, ValueError):
            inferred_files = self._infer_changed_files(
                raw_output,
                before_snapshot=before_snapshot,
                after_snapshot=after_snapshot,
            )
            return DevAgentResult(
                status="done",
                files_changed=inferred_files,
                summary=self._summarize_unstructured_output(raw_output, inferred_files),
                raw_output=raw_output,
            )

    def _snapshot_workspace(self, workspace_root: Path) -> dict[str, tuple[int, int]]:
        """Capture a lightweight snapshot of user-visible workspace files."""
        snapshot: dict[str, tuple[int, int]] = {}
        if not workspace_root.exists():
            return snapshot

        for path in workspace_root.rglob("*"):
            if not path.is_file():
                continue
            try:
                rel_path = path.relative_to(workspace_root)
            except ValueError:
                continue
            if any(part in _RUNTIME_DIR_NAMES for part in rel_path.parts):
                continue
            try:
                stat = path.stat()
            except OSError:
                continue
            snapshot[f"/workspace/{rel_path.as_posix()}"] = (
                stat.st_mtime_ns,
                stat.st_size,
            )
        return snapshot

    def _normalize_changed_files(self, files_changed: list[Any]) -> list[str]:
        normalized: list[str] = []
        for entry in files_changed:
            path = str(entry or "").strip()
            if not path:
                continue
            path = path.replace("\\", "/")
            if re.match(r"^[A-Za-z]:/", path):
                continue
            if path.startswith("./"):
                path = path[2:]
            if not path.startswith("/workspace/"):
                path = f"/workspace/{path.lstrip('/')}"
            normalized.append(path)

        deduped: list[str] = []
        for path in normalized:
            if path not in deduped:
                deduped.append(path)
        return deduped

    def _infer_changed_files(
        self,
        raw_output: str,
        *,
        before_snapshot: dict[str, tuple[int, int]],
        after_snapshot: dict[str, tuple[int, int]],
    ) -> list[str]:
        from_output = [
            path
            for path in self._normalize_changed_files(
                re.findall(r"/workspace/[A-Za-z0-9._/\\-]+", raw_output or ""),
            )
            if path in after_snapshot
        ]
        from_snapshot = sorted(
            path
            for path, metadata in after_snapshot.items()
            if before_snapshot.get(path) != metadata
        )
        return self._normalize_changed_files(from_output + from_snapshot)

    # ── Ralph-loop: fast local syntax/sanity check before QA ─────────────────
    # ATLAS Ralph-loop: runs py_compile on every changed Python file inside
    # the sandbox. On SyntaxError, returns the error string so the orchestrator
    # can retry Dev with the error injected. On success, returns None.
    # P0-B FIX: System errors (TimeoutError, PermissionError, OSError, FileNotFoundError)
    # log ERROR and return DevAgentResult failure immediately. Only SyntaxError triggers retry.
    async def _ralph_check_changed_files(
        self,
        workspace_root: Path,
        files_changed: list[str] | None,
        before_snapshot: dict[str, tuple[int, int]],
        after_snapshot: dict[str, tuple[int, int]],
    ) -> DevAgentResult | None:
        """
        Run Ralph syntax check on all changed Python files.

        Args:
            workspace_root: Absolute path to the workspace root.
            files_changed: Explicit list of file paths, or None to infer from snapshot.
            before_snapshot: Workspace snapshot before the Dev run.
            after_snapshot:  Workspace snapshot after  the Dev run.

        Returns:
            None if all files pass py_compile.
            DevAgentResult with status='ralph_failed' if system errors occur (fatal, no retry).
            str error description if SyntaxError (triggers retry via caller).
        """
        if files_changed is None:
            files_changed = self._infer_changed_files(
                "", before_snapshot=before_snapshot, after_snapshot=after_snapshot
            )
        python_files = [f for f in files_changed if f.endswith(".py")]
        if not python_files:
            return None

        runtime = None
        try:
            from ..services.openhands_client import get_openhands_client
            client = get_openhands_client()
            runtime = client.get_runtime(str(workspace_root))
        except Exception as Ralph_runtime_err:
            logger.warning(
                "Ralph cannot get sandbox runtime for %s — skipping syntax check: %s",
                workspace_root, Ralph_runtime_err,
            )
            return None

        Ralph_errors: list[str] = []
        for py_file in python_files:
            # Strip /workspace prefix for sandbox-relative path
            rel_path = py_file
            for prefix in ("/workspace/", "/workspace"):
                if rel_path.startswith(prefix):
                    rel_path = rel_path[len(prefix):]
                    break

            # P0-B FIX: Catch specific system errors. Log at ERROR and return
            # DevAgentResult immediately — these are fatal, not retryable.
            try:
                exec_result = await asyncio.wait_for(
                    asyncio.to_thread(
                        runtime.execute_command,
                        command=f"python -m py_compile /workspace/{rel_path}",
                        cwd="/workspace",
                        timeout=10.0,
                    ),
                    timeout=15.0,
                )
                stderr = (exec_result.get("error") or "").strip()
                if stderr:
                    Ralph_errors.append(f"  File /workspace/{rel_path}:\n    {stderr.splitlines()[0]}")
            except asyncio.TimeoutError:
                # P0-B: Timeout is a system failure — sandbox may be hung.
                # Log at ERROR and return immediately (no retry).
                logger.error(
                    "Ralph timeout compiling %s — sandbox hung; returning DevAgentResult failure",
                    py_file,
                )
                return DevAgentResult(
                    status="ralph_failed",
                    summary=f"Ralph timeout: sandbox hung while compiling {py_file}",
                    error=f"RALPH_TIMEOUT: /workspace/{rel_path} timed out after 15s",
                    files_changed=[],
                )
            except PermissionError as e:
                logger.error(
                    "Ralph permission denied reading %s — returning DevAgentResult failure",
                    py_file,
                )
                return DevAgentResult(
                    status="ralph_failed",
                    summary=f"Ralph permission denied: {e}",
                    error=f"RALPH_PERMISSION_ERROR: /workspace/{rel_path}: {e}",
                    files_changed=[],
                )
            except OSError as e:
                logger.error(
                    "Ralph OS error checking %s — returning DevAgentResult failure",
                    py_file,
                )
                return DevAgentResult(
                    status="ralph_failed",
                    summary=f"Ralph OS error: {e}",
                    error=f"RALPH_OS_ERROR: /workspace/{rel_path}: {e}",
                    files_changed=[],
                )
            except FileNotFoundError as e:
                logger.error(
                    "Ralph FileNotFoundError checking %s — returning DevAgentResult failure",
                    py_file,
                )
                return DevAgentResult(
                    status="ralph_failed",
                    summary=f"Ralph file not found: {e}",
                    error=f"RALPH_FILE_NOT_FOUND: /workspace/{rel_path}: {e}",
                    files_changed=[],
                )

        if not Ralph_errors:
            return None

        # Only SyntaxErrors reach here — these are retryable (caller handles retry loop).
        return (
            "Ralph syntax check FAILED — the following Python files have errors:\n"
            + "\n".join(Ralph_errors)
            + "\nFix the errors above before proceeding to QA."
        )

    def _summarize_unstructured_output(
        self,
        raw_output: str,
        inferred_files: list[str],
    ) -> str:
        text = (raw_output or "").strip()
        if not text:
            return "Agent completed (no structured output)."

        noisy_markers = (
            "assistantcommentary",
            "assistantanalysis",
            "workspace_read_file",
            "workspace_write_file",
            "workspace_exec",
        )
        if any(marker in text for marker in noisy_markers):
            if inferred_files:
                return "Agent completed with unstructured output; recovered changed files from sandbox state."
            return "Agent completed with unstructured output."

        for line in text.splitlines():
            line = line.strip()
            if line:
                return line[:500]
        return text[:500]

    def _recover_from_partial_execution(
        self,
        raw_output: str,
        *,
        before_snapshot: dict[str, tuple[int, int]],
        after_snapshot: dict[str, tuple[int, int]],
        error: Exception,
    ) -> DevAgentResult | None:
        """
        Recover a usable result after an SDK interruption.

        If the agent already changed real files or emitted assistant output,
        let the orchestrator continue and rely on QA to validate the work.
        """
        inferred_files = self._infer_changed_files(
            raw_output,
            before_snapshot=before_snapshot,
            after_snapshot=after_snapshot,
        )
        if raw_output.strip():
            recovered = self._parse_result(
                raw_output,
                before_snapshot=before_snapshot,
                after_snapshot=after_snapshot,
            )
            if recovered.files_changed or recovered.summary:
                if not recovered.summary:
                    recovered.summary = (
                        "Recovered partial Dev result after SDK interruption."
                    )
                return recovered

        if inferred_files:
            return DevAgentResult(
                status="done",
                files_changed=inferred_files,
                summary=(
                    "Recovered changed files from sandbox state after SDK interruption: "
                    f"{type(error).__name__}"
                ),
                raw_output=raw_output,
            )

        return None
