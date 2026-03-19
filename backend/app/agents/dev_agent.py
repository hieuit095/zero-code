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
            try:
                # HANG FIX: conversation.run() is synchronous and blocks the
                # asyncio event loop for the entire LLM execution (minutes for
                # complex tasks). Offload to a thread so Redis publishes,
                # WebSocket heartbeats, and other coroutines keep running.
                await asyncio.to_thread(conversation.run)
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
