"""
Run manager with SDK-native task delegation orchestrating the full
Leader → Dev → QA pipeline.

States:
  QUEUED → PLANNING → DELEGATING → DEVELOPING → VERIFYING → (next task or DONE)
                                       ↑            ↓
                                       └── RETRYING ┘  (max 2 retries per task)
                                                       → FAILED (if exhausted)

PHASE 4 REFACTOR: Manual `while` loops have been replaced with a
`TaskDelegator` class that encapsulates the Dev→QA handoff as a
structured SDK delegation unit. The outer task dispatch uses an
async generator pattern with replan escalation. All DB persistence
and event emission are preserved via callback hooks.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from ..agents.dev_agent import DevAgent, DevAgentResult
from ..agents.leader_agent import AgentTask, LeaderAgent, LeaderAgentResult
from ..agents.qa_agent import QaAgent, QaAgentResult
from ..core.security import generate_mcp_token, revoke_run_token
from ..db.database import async_session
from ..services.event_broker import EventBroker, get_event_broker
from ..db.models import APIKeyModel, LLMRoutingModel, decrypt_key
from ..services.run_store import RunStore

logger = logging.getLogger(__name__)

MAX_QA_RETRIES = 2
MAX_LEADER_REPLANS = 2


# ─── Run States ───────────────────────────────────────────────────────────────


class RunState:
    QUEUED = "queued"
    PLANNING = "planning"
    DELEGATING = "delegating"
    DEVELOPING = "developing"
    VERIFYING = "verifying"
    RETRYING = "retrying"
    LEADER_REVIEW = "leader-review"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _msg_id() -> str:
    return f"msg_{uuid4().hex[:8]}"


def _cmd_id() -> str:
    return f"cmd_{uuid4().hex[:8]}"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _lang_for_file(path: str) -> str:
    ext_map = {
        ".py": "python", ".ts": "typescript", ".tsx": "typescriptreact",
        ".js": "javascript", ".jsx": "javascriptreact", ".json": "json",
        ".md": "markdown", ".html": "html", ".css": "css",
    }
    return ext_map.get(Path(path).suffix, "plaintext")


# ─── TaskDelegator (SDK-native Dev→QA Delegation Unit) ────────────────────────


class TaskDelegator:
    """
    Encapsulates a single Dev→QA delegation as a structured unit.

    PHASE 4 REFACTOR: Replaces the manual `_execute_task` while loop.
    Each delegator instance manages one task's complete Dev→QA lifecycle
    including retry iterations, DB state updates, and event emissions.

    The delegator does NOT manage cross-task coordination or Leader
    re-planning — that responsibility stays with the RunManager's
    async task dispatch.
    """

    def __init__(
        self,
        run_manager: "RunManager",
        dev_agent: "DevAgent",
        qa_agent: "QaAgent",
        run_id: str,
        task: AgentTask,
        task_idx: int,
        total_tasks: int,
        goal: str,
        base_progress: int,
        llm_configs: dict[str, dict[str, Any]] | None = None,
        max_retries: int = MAX_QA_RETRIES,
    ) -> None:
        self._mgr = run_manager
        self._dev = dev_agent
        self._qa = qa_agent
        self._run_id = run_id
        self._task = task
        self._task_idx = task_idx
        self._total = total_tasks
        self._goal = goal
        self._base_progress = base_progress
        self._llm_configs = llm_configs or {}
        self._max_retries = max_retries

    async def execute(self) -> tuple[str, list[str], bool]:
        """
        Execute the Dev→QA delegation for this task.

        Loop structure (with MAX_QA_RETRIES=2):
          Attempt 1: Standard Dev → QA
          Attempt 2: Retry Dev (with critique) → QA
          --- mentorship intercept ---
          Attempt 3: Mentored Dev (with leader_guidance.md) → QA

        Returns:
            ("completed" | "failed", files_changed, is_internal_error)
        """
        dev_input = self._goal
        last_files: list[str] = []

        for attempt in range(1, self._max_retries + 3):
            # ── DEVELOPING phase ─────────────────────────────────────
            dev_result, last_files = await self._delegate_to_dev(
                dev_input, attempt,
            )
            if dev_result is None:
                return "failed", [], False

            # ── VERIFYING phase ──────────────────────────────────────
            qa_outcome = await self._delegate_to_qa(
                dev_result, attempt,
            )

            if qa_outcome == "passed":
                return "completed", last_files, False

            if isinstance(qa_outcome, tuple):
                # (failed_reason, is_internal_error, retryable, failing_dims)
                reason, is_internal, retryable, failing_dims = qa_outcome
                if is_internal or not retryable:
                    return "failed", last_files, is_internal

                if attempt == self._max_retries:
                    # ── MENTORSHIP INTERCEPT ──────────────────────────
                    # Standard retries exhausted. Escalate to the Leader
                    # for targeted architectural guidance before the
                    # final Dev attempt.
                    mentor_guidance = await self._delegate_to_leader_mentor(
                        failing_dims,
                    )
                    dev_input = (
                        f"URGENT: Tech Lead intervention. Your previous "
                        f"{attempt} attempts FAILED QA verification.\n\n"
                        f"The Tech Lead has analyzed the failures and "
                        f"provided an architectural fix. Read "
                        f"/workspace/leader_guidance.md and apply the "
                        f"EXACT steps described.\n\n"
                        f"--- LEADER GUIDANCE ---\n"
                        f"{mentor_guidance}\n"
                        f"--- END GUIDANCE ---\n\n"
                        f"Original task:\n{self._goal}"
                    )

                elif attempt > self._max_retries:
                    # ── POST-MENTORSHIP FAILURE ───────────────────────
                    # The mentored attempt also failed. Task is
                    # completely exhausted — escalate to Leader replan.
                    break

                else:
                    # ── STANDARD RETRY — critique handoff to Dev ──────
                    await self._prepare_retry(attempt, failing_dims)
                    retry_reason = (
                        f"QA scored below thresholds: {', '.join(failing_dims)}"
                        if failing_dims else "QA checks failed"
                    )
                    dev_input = (
                        f"IMPORTANT: A previous implementation attempt was "
                        f"evaluated and FAILED.\n"
                        f"Reason: {retry_reason}\n\n"
                        f"Please review the detailed critique at: "
                        f"/workspace/critique_report.md\n"
                        f"Address ALL issues mentioned in the critique to "
                        f"improve the code quality.\n\n"
                        f"Original task:\n{self._goal}"
                    )

        return "failed", last_files, False

    # ─── Dev Delegation ───────────────────────────────────────────────────

    async def _delegate_to_dev(
        self, dev_input: str, attempt: int,
    ) -> tuple["DevAgentResult | None", list[str]]:
        """Delegate to the Dev agent and return (result, files_changed)."""
        dev_progress = self._base_progress + int((1 / self._total) * 30)
        await self._mgr._update_run_status(
            self._run_id, RunState.DEVELOPING, "developing", dev_progress)
        await self._mgr._emit_run_state(self._run_id, "running", "developing",
            attempt=attempt, progress=dev_progress)

        await self._mgr._emit_agent_status(self._run_id, "dev", "thinking",
            activity="Analyzing task..." if attempt == 1 else "Fixing QA issues...",
            task_id=self._task.id, attempt=attempt)

        await self._mgr._emit_agent_message(self._run_id, "dev", "Dev",
            f"{'Implementing' if attempt == 1 else f'Retry #{attempt-1}'}: "
            f"{dev_input[:200]}")

        await self._mgr._emit_agent_status(self._run_id, "dev", "working",
            activity="Writing code via MCP tools",
            task_id=self._task.id, attempt=attempt)

        dev_result = await self._dev.run(
            run_id=self._run_id, goal=dev_input,
            context={"attempt": attempt, "task_id": self._task.id},
            llm_config=self._llm_configs.get("dev"),
        )

        if dev_result.status == "error":
            await self._mgr._emit_agent_message(self._run_id, "dev", "Dev",
                f"Error: {dev_result.error}")
            return None, []

        await self._mgr._emit_agent_message(self._run_id, "dev", "Dev",
            f"Done. Changed: {', '.join(dev_result.files_changed)}. "
            f"{dev_result.summary}")

        # Emit fs events
        for path in dev_result.files_changed:
            await self._mgr._emit(self._run_id, "dev:start-edit",
                {"fileName": path, "taskId": self._task.id})
            await self._mgr._emit_fs_update(
                self._run_id, path, dev_result.raw_output, "dev")
            await self._mgr._emit(self._run_id, "dev:stop-edit",
                {"fileName": path})

        await self._mgr._emit_agent_status(self._run_id, "dev", "idle",
            task_id=self._task.id, attempt=attempt)

        return dev_result, dev_result.files_changed

    # ─── QA Delegation ────────────────────────────────────────────────────

    async def _delegate_to_qa(
        self, dev_result: "DevAgentResult", attempt: int,
    ) -> "str | tuple[str, bool, bool, list[str]]":
        """
        Delegate to the QA agent and evaluate results.

        Returns:
            "passed" if QA passed all thresholds, or
            (summary, is_internal_error, retryable, failing_dimensions) tuple.
        """
        qa_progress = self._base_progress + int((1 / self._total) * 60)
        await self._mgr._update_run_status(
            self._run_id, RunState.VERIFYING, "verifying", qa_progress)
        await self._mgr._emit_run_state(self._run_id, "running", "verifying",
            attempt=attempt, progress=qa_progress)

        await self._mgr._emit_agent_status(self._run_id, "qa", "thinking",
            activity="Preparing verification checks",
            task_id=self._task.id, attempt=attempt)

        await self._mgr._emit_agent_message(self._run_id, "qa", "QA",
            f"Verifying: {', '.join(dev_result.files_changed)}")

        await self._mgr._emit_agent_status(self._run_id, "qa", "working",
            activity="Running checks", task_id=self._task.id, attempt=attempt)

        qa_result = await self._qa.run(
            run_id=self._run_id, task_id=self._task.id,
            attempt=attempt, changed_files=dev_result.files_changed,
            llm_config=self._llm_configs.get("qa"),
        )

        # Emit terminal events
        for check in qa_result.commands:
            await self._mgr._emit_terminal(
                run_id=self._run_id, agent="qa", command=check.command,
                stdout=check.stdout, stderr=check.stderr,
                exit_code=check.exit_code, duration_ms=check.duration_ms,
                attempt=attempt,
            )

        # Evaluate dimensional scores
        scores = qa_result.scores
        scores_dict = scores.to_dict()

        if qa_result.status == "passed" and scores.passes_thresholds():
            await self._mgr._emit(self._run_id, "qa:passed",
                qa_result.to_passed_dict())
            await self._mgr._emit_agent_message(self._run_id, "qa", "QA",
                f"✓ Passed (scores: CQ={scores_dict['code_quality']}, "
                f"REQ={scores_dict['requirements']}, "
                f"ROB={scores_dict['robustness']}, "
                f"SEC={scores_dict['security']}): {qa_result.summary}")
            await self._mgr._emit_agent_status(self._run_id, "qa", "idle",
                task_id=self._task.id, attempt=attempt)

            # Surface critique_report.md in the frontend FileExplorer
            await self._emit_critique_artifact()

            return "passed"

        # QA failed — determine reason
        failing_dims = scores.failing_dimensions()
        if failing_dims:
            qa_result.summary += (
                f" | SCORE THRESHOLD FAILURES: {', '.join(failing_dims)}"
            )
            qa_result.status = "failed"

        await self._mgr._emit(self._run_id, "qa:report",
            qa_result.to_report_dict())
        await self._mgr._emit_agent_message(self._run_id, "qa", "QA",
            f"✗ Failed (scores: CQ={scores_dict['code_quality']}, "
            f"REQ={scores_dict['requirements']}, "
            f"ROB={scores_dict['robustness']}, "
            f"SEC={scores_dict['security']}): {qa_result.summary}")
        await self._mgr._emit_agent_status(self._run_id, "qa", "idle",
            task_id=self._task.id, attempt=attempt)

        # Surface critique_report.md in the frontend FileExplorer
        await self._emit_critique_artifact()

        has_internal_error = any(
            e.kind == "internal" for e in qa_result.errors
        )
        return (
            qa_result.summary,
            has_internal_error,
            qa_result.retryable,
            failing_dims,
        )

    # ─── Critique Artifact Surfacing ────────────────────────────────────

    async def _emit_critique_artifact(self) -> None:
        """
        Read critique_report.md from the workspace via the OpenHands SDK
        and emit fs:update so it instantly appears in the frontend
        FileExplorer.

        AUDIT REMEDIATION: Uses OpenHandsClient.get_runtime().read_file()
        instead of host-side Path.exists() / Path.read_text().
        """
        try:
            from ..services.openhands_client import get_openhands_client
            client = get_openhands_client()
            runtime = client.get_runtime("repo-main")
            content = runtime.read_file("/workspace/critique_report.md")

            await self._mgr._emit_fs_update(
                self._run_id,
                "critique_report.md",
                content,
                source_agent="qa",
            )
            logger.info(
                "Emitted fs:update for critique_report.md (%d bytes) on run %s",
                len(content), self._run_id,
            )
        except FileNotFoundError:
            logger.debug(
                "critique_report.md not found in sandbox — skipping fs:update",
            )
        except Exception:
            logger.warning(
                "Failed to emit critique artifact for run %s", self._run_id,
                exc_info=True,
            )

    # ─── Leader Mentorship Delegation ──────────────────────────────────────

    async def _delegate_to_leader_mentor(
        self, failing_dims: list[str],
    ) -> str:
        """
        Escalate to the Leader agent in Mentorship Mode.

        The Leader reads critique_report.md and the broken code, then
        outputs targeted architectural guidance for the Dev agent.
        The guidance is persisted to /workspace/leader_guidance.md and
        emitted as an fs:update so the frontend can display it.

        Returns:
            The raw mentorship guidance text from the Leader.
        """
        review_progress = self._base_progress + int((1 / self._total) * 65)

        # ── Transition to LEADER_REVIEW ──────────────────────────────
        await self._mgr._update_run_status(
            self._run_id, RunState.LEADER_REVIEW, "leader-review", review_progress)
        await self._mgr._emit_run_state(self._run_id, "running", "leader-review",
            progress=review_progress)

        await self._mgr._emit_agent_status(self._run_id, "tech-lead", "thinking",
            activity="Reviewing QA failure for mentorship",
            task_id=self._task.id)

        dim_summary = ', '.join(failing_dims) if failing_dims else 'QA checks'
        await self._mgr._emit_agent_message(self._run_id, "tech-lead", "Tech Lead",
            f"Dev failed 2 attempts (failing: {dim_summary}). "
            f"Reviewing critique_report.md to provide guidance...")

        await self._mgr._emit_agent_status(self._run_id, "tech-lead", "working",
            activity="Diagnosing root cause from QA critique",
            task_id=self._task.id)

        # ── Execute Leader in Mentorship Mode ────────────────────────
        mentor_result = await self._mgr._leader_agent.run(
            run_id=self._run_id,
            goal=(
                f"The Dev agent FAILED the following task after 2 attempts:\n"
                f"  Task: {self._task.label}\n"
                f"  Acceptance Criteria: {self._task.acceptance_criteria}\n\n"
                f"Failing QA dimensions: {dim_summary}\n\n"
                f"Read /workspace/critique_report.md and the relevant source "
                f"files, then provide step-by-step fix instructions."
            ),
            llm_config=self._llm_configs.get("leader"),
            mentorship_mode=True,
        )

        guidance = mentor_result.raw_output or mentor_result.summary or ""

        # ── Persist guidance to workspace via OpenHands SDK ─────────
        # AUDIT REMEDIATION: Uses OpenHandsClient.get_runtime().write_file()
        # instead of host-side Path.write_text().
        try:
            from ..services.openhands_client import get_openhands_client
            client = get_openhands_client()
            runtime = client.get_runtime("repo-main")
            runtime.write_file("/workspace/leader_guidance.md", guidance)
            logger.info(
                "Wrote leader_guidance.md (%d bytes) via SDK for run %s",
                len(guidance), self._run_id,
            )
        except Exception:
            logger.warning(
                "Failed to write leader_guidance.md for run %s",
                self._run_id, exc_info=True,
            )

        # ── Emit fs:update so frontend displays the artifact ─────────
        await self._mgr._emit_fs_update(
            self._run_id, "leader_guidance.md", guidance, source_agent="tech-lead",
        )

        await self._mgr._emit_agent_message(self._run_id, "tech-lead", "Tech Lead",
            f"Mentorship guidance ready. See leader_guidance.md.")
        await self._mgr._emit_agent_status(self._run_id, "tech-lead", "idle",
            task_id=self._task.id)

        return guidance

    # ─── Retry Preparation ────────────────────────────────────────────────

    async def _prepare_retry(
        self, attempt: int, failing_dims: list[str],
    ) -> None:
        """Transition state to RETRYING and notify the Dev agent."""
        qa_progress = self._base_progress + int((1 / self._total) * 60)
        await self._mgr._update_run_status(
            self._run_id, RunState.RETRYING, "retrying", qa_progress)
        await self._mgr._emit_run_state(self._run_id, "running", "retrying",
            attempt=attempt, progress=qa_progress)

        retry_reason = (
            f"QA scored below thresholds: {', '.join(failing_dims)}"
            if failing_dims else "QA checks failed"
        )
        await self._mgr._emit_agent_message(self._run_id, "dev", "Dev",
            f"{retry_reason} — retrying (attempt "
            f"{attempt}/{self._max_retries + 1})...")


# ─── Run Manager ──────────────────────────────────────────────────────────────


class RunManager:
    """
    SDK-native task delegation orchestrator.

    Uses `TaskDelegator` to manage the Dev→QA handoff as a structured
    delegation unit, replacing the previous manual `while` loops.

    ALL state is persisted to the DATABASE. No in-memory dict.
    """

    def __init__(self, broker: EventBroker) -> None:
        self._broker = broker
        self._leader_agent = LeaderAgent()
        self._dev_agent = DevAgent()
        self._qa_agent = QaAgent()

    # ─── CRUD (DB-backed) ─────────────────────────────────────────────────

    async def create_run(
        self,
        goal: str,
        workspace_id: str = "repo-main",
        agent_config: dict | None = None,
    ) -> dict[str, Any]:
        run_id = f"run_{uuid4().hex[:12]}"

        async with async_session() as session:
            await RunStore.create_run(session, run_id, goal, workspace_id)

        return {
            "run_id": run_id,
            "goal": goal,
            "workspace_id": workspace_id,
            "status": RunState.QUEUED,
        }

    async def get_run_snapshot(self, run_id: str) -> dict[str, Any] | None:
        """Fetch the current run state from the DATABASE."""
        async with async_session() as session:
            return await RunStore.get_run_snapshot(session, run_id)

    async def cancel_run(self, run_id: str, reason: str = "user_cancelled") -> dict[str, Any] | None:
        async with async_session() as session:
            run = await RunStore.get_run(session, run_id)
            if run is None:
                return None
            await RunStore.update_run(
                session, run_id,
                status=RunState.CANCELLED, phase="cancelled", progress=run.progress,
            )
        return {"status": "cancelled", "message": f"Run {run_id} cancelled: {reason}"}

    async def _update_run_status(
        self, run_id: str, status: str, phase: str | None = None, progress: int = 0,
    ) -> None:
        async with async_session() as session:
            await RunStore.update_run(
                session, run_id, status=status, phase=phase, progress=progress,
            )

    async def _persist_tasks(
        self, run_id: str, tasks: list[dict[str, Any]],
    ) -> None:
        async with async_session() as session:
            await RunStore.create_tasks(session, run_id, tasks)

    async def _persist_task_status(self, task_id: str, status: str) -> None:
        async with async_session() as session:
            await RunStore.update_task_status(session, task_id, status)

    # ─── Event Emission Helpers ───────────────────────────────────────────

    async def _emit(self, run_id: str, event_type: str, data: dict[str, Any]) -> None:
        await self._broker.publish(run_id, event_type, data)

    async def _load_llm_configs(self) -> dict[str, dict[str, Any]]:
        """
        Fetch agent routing + decrypted API keys from the database.

        Returns a dict keyed by role ("leader", "dev", "qa") with sub-keys:
          - model: str (e.g., "gpt-4o")
          - provider: str (e.g., "openai")
          - api_key: str (decrypted, or empty)
          - base_url: str | None
        """
        async with async_session() as session:
            from sqlalchemy import select
            # Fetch routing config
            result = await session.execute(select(LLMRoutingModel))
            routing = result.scalar_one_or_none()

            # Fetch all API keys
            key_result = await session.execute(select(APIKeyModel))
            key_rows = key_result.scalars().all()

        # Build provider -> (decrypted_key, base_url) map
        provider_keys: dict[str, tuple[str, str | None]] = {}
        for row in key_rows:
            try:
                decrypted = decrypt_key(row.encrypted_key)
            except Exception:
                decrypted = ""
            provider_keys[row.provider] = (decrypted, row.base_url)

        # Use routing config or defaults
        if routing is None:
            routing_map = {
                "leader": ("gpt-4o", "openai"),
                "dev": ("gpt-4o", "openai"),
                "qa": ("gpt-4o", "openai"),
            }
        else:
            routing_map = {
                "leader": (routing.leader_model, routing.leader_provider),
                "dev": (routing.dev_model, routing.dev_provider),
                "qa": (routing.qa_model, routing.qa_provider),
            }

        configs: dict[str, dict[str, Any]] = {}
        for role, (model, provider) in routing_map.items():
            api_key, base_url = provider_keys.get(provider, ("", None))
            configs[role] = {
                "model": model,
                "provider": provider,
                "api_key": api_key,
                "base_url": base_url,
            }

        logger.info(
            "Loaded LLM configs: Leader=%s/%s Dev=%s/%s QA=%s/%s",
            configs["leader"]["model"], configs["leader"]["provider"],
            configs["dev"]["model"], configs["dev"]["provider"],
            configs["qa"]["model"], configs["qa"]["provider"],
        )
        return configs

    async def _emit_agent_status(
        self, run_id: str, role: str, state: str,
        activity: str | None = None, task_id: str | None = None, attempt: int = 0,
    ) -> None:
        await self._emit(run_id, "agent:status", {
            "role": role, "state": state, "activity": activity,
            "currentTaskId": task_id, "attempt": attempt,
        })

    async def _emit_agent_message(
        self, run_id: str, role: str, label: str, content: str,
    ) -> None:
        await self._emit(run_id, "agent:message", {
            "id": _msg_id(), "agent": role, "agentLabel": label,
            "content": content, "timestamp": _now_iso(),
        })

    async def _emit_run_state(
        self, run_id: str, status: str, phase: str, attempt: int = 0, progress: int = 0,
    ) -> None:
        await self._emit(run_id, "run:state", {
            "status": status, "phase": phase, "attempt": attempt, "progress": progress,
        })

    async def _emit_fs_update(
        self, run_id: str, path: str, content: str, source_agent: str = "dev",
    ) -> None:
        await self._emit(run_id, "fs:update", {
            "name": Path(path).name, "path": path, "language": _lang_for_file(path),
            "content": content, "sourceAgent": source_agent, "version": 1,
        })

    async def _emit_terminal(
        self, run_id: str, agent: str, command: str, stdout: str, stderr: str,
        exit_code: int, duration_ms: int, attempt: int = 1,
    ) -> None:
        cmd_id = _cmd_id()
        await self._emit(run_id, "terminal:command", {
            "commandId": cmd_id, "agent": agent, "command": command, "cwd": "/workspace",
        })
        if stdout.strip():
            await self._emit(run_id, "terminal:output", {
                "commandId": cmd_id, "stream": "stdout", "text": stdout,
                "logType": "success" if exit_code == 0 else "output", "attempt": attempt,
            })
        if stderr.strip():
            await self._emit(run_id, "terminal:output", {
                "commandId": cmd_id, "stream": "stderr", "text": stderr,
                "logType": "error", "attempt": attempt,
            })
        await self._emit(run_id, "terminal:exit", {
            "commandId": cmd_id, "exitCode": exit_code, "durationMs": duration_ms,
        })

    async def _emit_run_error(
        self, run_id: str, error_code: str, message: str, task_id: str | None,
    ) -> None:
        await self._emit(run_id, "run:error", {
            "status": "failed", "errorCode": error_code,
            "message": message, "lastKnownTaskId": task_id,
        })

    # ─── Orchestration Loop ──────────────────────────────────────────────

    async def execute_run(self, run_id: str) -> None:
        """
        Full SDK-native delegation pipeline:
        QUEUED → PLANNING → DELEGATING → (per-task via TaskDelegator) → DONE

        The TaskDelegator handles the Dev→QA handoff as a single delegation
        unit, with replan escalation managed by the async task dispatch.

        ALL state is read from and written to the DATABASE.
        """
        # Fetch run from DB
        async with async_session() as session:
            run_model = await RunStore.get_run(session, run_id)

        if run_model is None:
            logger.error("Run %s not found in DB — cannot execute", run_id)
            return

        goal = run_model.goal
        workspace_id = run_model.workspace_id
        start_time = time.monotonic()

        # Generate JWT for MCP facade (legacy — retained for backward compat)
        # AUDIT FIX: Extended from 30 min to 12 hours (720 min) to prevent
        # token expiration during long-running multi-agent compile/retry loops.
        mcp_token = generate_mcp_token(run_id, expiry_minutes=720)
        # NOTE: set_run_token removed — native SDK tools no longer use JWT tokens.

        # ── Load dynamic LLM config from DB ────────────────────────
        llm_configs = await self._load_llm_configs()

        # Counters tracked locally during this execution (not cross-process)
        leader_replans = 0
        all_files_changed: list[str] = []

        try:
            # ── run:created ──────────────────────────────────────────
            await self._emit(run_id, "run:created", {
                "status": "queued", "workspaceId": workspace_id,
            })

            # ══════════════════════════════════════════════════════════
            # STATE: PLANNING
            # ══════════════════════════════════════════════════════════
            await self._update_run_status(run_id, RunState.PLANNING, "planning", 5)
            await self._emit_run_state(run_id, "running", "planning", progress=5)
            await self._emit_agent_status(run_id, "tech-lead", "thinking",
                activity="Analyzing goal and workspace")
            await self._emit_agent_message(run_id, "tech-lead", "Tech Lead",
                f"Analyzing goal: {goal[:200]}")

            # Run Leader Agent
            await self._emit_agent_status(run_id, "tech-lead", "working",
                activity="Decomposing goal into tasks")

            leader_result: LeaderAgentResult = await self._leader_agent.run(
                run_id=run_id, goal=goal,
                llm_config=llm_configs.get("leader"),
            )

            if leader_result.status == "error" or not leader_result.tasks:
                await self._emit_agent_message(run_id, "tech-lead", "Tech Lead",
                    f"Planning failed: {leader_result.error or 'No tasks generated'}")
                await self._emit_run_error(run_id, "planning_failed",
                    leader_result.error or "Leader produced no tasks", None)
                await self._update_run_status(run_id, RunState.FAILED, "failed", 5)
                return

            # Store tasks in DB
            tasks: list[AgentTask] = leader_result.tasks
            task_dicts = [
                {"id": t.id, "label": t.label, "acceptanceCriteria": t.acceptance_criteria,
                 "status": "pending", "agent": "dev"}
                for t in tasks
            ]
            await self._persist_tasks(run_id, task_dicts)

            await self._emit_agent_message(run_id, "tech-lead", "Tech Lead",
                f"Plan ready: {len(tasks)} tasks.\n" +
                "\n".join(f"  {i+1}. {t.label}" for i, t in enumerate(tasks)))
            await self._emit_agent_status(run_id, "tech-lead", "idle")

            # ── task:snapshot — send full task list to frontend ───────
            await self._emit(run_id, "task:snapshot", {
                "tasks": [
                    {"id": t.id, "label": t.label, "status": "pending", "agent": "dev"}
                    for t in tasks
                ],
            })

            # ══════════════════════════════════════════════════════════
            # STATE: DELEGATING (SDK-native task dispatch)
            # ══════════════════════════════════════════════════════════
            total_tasks = len(tasks)

            # PHASE 4: Delegate tasks using the TaskDelegator pattern.
            # Each task is dispatched to the delegator which manages the
            # Dev→QA handoff internally, returning a structured result.
            async for task_idx, task in self._dispatch_tasks(tasks):
                total_tasks = len(tasks)  # Refresh after possible replan appends

                await self._update_run_status(
                    run_id, RunState.DELEGATING, "delegating",
                    10 + int((task_idx / total_tasks) * 80),
                )
                base_progress = 10 + int((task_idx / total_tasks) * 80)

                await self._emit_run_state(run_id, "running", "delegating",
                    progress=base_progress)

                await self._persist_task_status(task.id, "in-progress")
                await self._emit(run_id, "task:update", {
                    "taskId": task.id, "status": "in-progress",
                })

                await self._emit_agent_message(run_id, "tech-lead", "Tech Lead",
                    f"Delegating task {task_idx + 1}/{total_tasks}: {task.label}")

                # ── Delegate to Dev → QA via TaskDelegator ──────────────
                task_goal = (
                    f"Task: {task.label}\n"
                    f"Acceptance Criteria: {task.acceptance_criteria}"
                )

                delegator = TaskDelegator(
                    run_manager=self,
                    dev_agent=self._dev_agent,
                    qa_agent=self._qa_agent,
                    run_id=run_id,
                    task=task,
                    task_idx=task_idx,
                    total_tasks=total_tasks,
                    goal=task_goal,
                    base_progress=base_progress,
                    llm_configs=llm_configs,
                    max_retries=MAX_QA_RETRIES,
                )

                task_result, last_files, is_internal_error = await delegator.execute()

                if task_result == "completed":
                    await self._persist_task_status(task.id, "completed")
                    await self._emit(run_id, "task:update", {
                        "taskId": task.id, "status": "completed",
                    })
                    all_files_changed.extend(last_files)
                    continue

                # ── ESCALATION TO LEADER ───
                await self._persist_task_status(task.id, "failed")
                await self._emit(run_id, "task:update", {
                    "taskId": task.id, "status": "failed",
                })

                # Abort on internal infrastructure errors
                if is_internal_error:
                    await self._update_run_status(
                        run_id, RunState.FAILED, "failed", base_progress)
                    await self._emit_run_error(
                        run_id, "INTERNAL_ERROR",
                        f"Task '{task.label}' failed due to an internal "
                        f"infrastructure error (not a code issue). "
                        f"The run has been aborted.",
                        task.id)
                    return

                if leader_replans >= MAX_LEADER_REPLANS:
                    await self._update_run_status(
                        run_id, RunState.FAILED, "failed", base_progress)
                    await self._emit_run_error(
                        run_id, "MAX_REPLANS_EXCEEDED",
                        f"Task '{task.label}' failed and Leader exhausted "
                        f"{MAX_LEADER_REPLANS} re-plan attempts.",
                        task.id)
                    return

                leader_replans += 1

                # ── Re-delegate to Leader for alternative approach ──
                await self._update_run_status(
                    run_id, RunState.PLANNING, "planning", base_progress)
                await self._emit_run_state(run_id, "running", "planning",
                    progress=base_progress)

                await self._emit_agent_message(run_id, "tech-lead", "Tech Lead",
                    f"Task '{task.label}' failed after {MAX_QA_RETRIES + 1} "
                    f"Dev→QA attempts. Re-planning… "
                    f"(replan {leader_replans}/{MAX_LEADER_REPLANS})")

                await self._emit_agent_status(run_id, "tech-lead", "thinking",
                    activity="Re-analyzing failed task for alternative approach")

                replan_result: LeaderAgentResult = await self._leader_agent.run(
                    run_id=run_id,
                    goal=(
                        f"The following task FAILED after {MAX_QA_RETRIES + 1} "
                        f"Dev→QA attempts and needs to be re-planned:\n"
                        f"  Task: {task.label}\n"
                        f"  Acceptance Criteria: {task.acceptance_criteria}\n\n"
                        f"Original goal: {goal}\n\n"
                        f"Please decompose this task differently or provide "
                        f"an alternative approach."
                    ),
                    llm_config=llm_configs.get("leader"),
                )

                if replan_result.status == "error" or not replan_result.tasks:
                    await self._emit_agent_message(run_id, "tech-lead", "Tech Lead",
                        f"Re-plan failed: "
                        f"{replan_result.error or 'No replacement tasks'}")
                    await self._update_run_status(
                        run_id, RunState.FAILED, "failed", base_progress)
                    await self._emit_run_error(
                        run_id, "REPLAN_FAILED",
                        f"Leader could not re-plan failed task '{task.label}'.",
                        task.id)
                    return

                # ── Inject re-planned tasks into the dispatch queue ──
                new_tasks: list[AgentTask] = replan_result.tasks
                new_task_dicts = [
                    {"id": t.id, "label": t.label,
                     "acceptanceCriteria": t.acceptance_criteria,
                     "status": "pending", "agent": "dev"}
                    for t in new_tasks
                ]
                await self._persist_tasks(run_id, new_task_dicts)

                tasks.extend(new_tasks)  # Extend the dispatch queue

                await self._emit_agent_message(run_id, "tech-lead", "Tech Lead",
                    f"Re-plan ready: {len(new_tasks)} replacement tasks.\n"
                    + "\n".join(f"  • {t.label}" for t in new_tasks))
                await self._emit_agent_status(run_id, "tech-lead", "idle")

                # Emit updated task snapshot (reload from DB for accuracy)
                async with async_session() as session:
                    db_tasks = await RunStore.get_tasks_for_run(session, run_id)
                await self._emit(run_id, "task:snapshot", {
                    "tasks": [
                        {"id": t.id, "label": t.label,
                         "status": t.status, "agent": t.agent}
                        for t in db_tasks
                    ],
                })

            # ══════════════════════════════════════════════════════════
            # STATE: DONE — all tasks completed
            # ══════════════════════════════════════════════════════════
            duration_ms = int((time.monotonic() - start_time) * 1000)
            await self._update_run_status(run_id, RunState.COMPLETED, "done", 100)

            await self._emit(run_id, "run:complete", {
                "status": "completed",
                "summary": f"All {total_tasks} tasks completed successfully.",
                "changedFiles": list(set(all_files_changed)),
                "qaRetries": 0,
                "durationMs": duration_ms,
            })

            # ── SDK Metrics Persistence ─────────────────────────────
            await self._persist_sdk_metrics(run_id, duration_ms)

        except Exception as exc:
            logger.exception("Unhandled error in execute_run for %s", run_id)
            await self._update_run_status(
                run_id, RunState.FAILED, "failed", 0)
            await self._emit_run_error(run_id, "internal_error", str(exc), None)

        finally:
            revoke_run_token(run_id)

    # ─── Async Task Dispatch Generator ──────────────────────────────────

    @staticmethod
    async def _dispatch_tasks(
        tasks: list[AgentTask],
    ):
        """
        Async generator that yields (index, task) pairs from a mutable
        task list. Supports dynamic extension (replan appends) during iteration.

        PHASE 4: Replaces the manual `while task_idx < len(tasks):` loop
        with a clean generator-based dispatch pattern.
        """
        idx = 0
        while idx < len(tasks):
            yield idx, tasks[idx]
            idx += 1

    # ─── SDK Metrics Persistence ──────────────────────────────────────────

    async def _persist_sdk_metrics(
        self, run_id: str, duration_ms: int,
    ) -> None:
        """
        Extract SDK-native metrics from the agents' LLM instances
        and persist them as a structured 'sdk:metrics' event.

        Reads `agent._last_llm.metrics` for each agent role to capture
        real accumulated_cost and token usage from the OpenHands SDK.
        """
        try:
            sdk_metrics: dict[str, Any] = {
                "durationMs": duration_ms,
                "agents": {},
            }

            total_cost = 0.0
            total_prompt = 0
            total_completion = 0

            for role, agent in [
                ("leader", self._leader_agent),
                ("dev", self._dev_agent),
                ("qa", self._qa_agent),
            ]:
                agent_cost = 0.0
                agent_prompt = 0
                agent_completion = 0

                # Extract real metrics from the agent's last-used LLM
                llm_handle = getattr(agent, "_last_llm", None)
                if llm_handle is not None:
                    metrics = getattr(llm_handle, "metrics", None)
                    if metrics is not None:
                        agent_cost = getattr(metrics, "accumulated_cost", 0.0) or 0.0
                        token_usage = getattr(metrics, "accumulated_token_usage", None)
                        if token_usage is not None:
                            agent_prompt = getattr(token_usage, "prompt_tokens", 0) or 0
                            agent_completion = getattr(token_usage, "completion_tokens", 0) or 0

                total_cost += agent_cost
                total_prompt += agent_prompt
                total_completion += agent_completion

                sdk_metrics["agents"][role] = {
                    "cost": agent_cost,
                    "promptTokens": agent_prompt,
                    "completionTokens": agent_completion,
                }

            sdk_metrics["totalCost"] = total_cost
            sdk_metrics["totalPromptTokens"] = total_prompt
            sdk_metrics["totalCompletionTokens"] = total_completion

            # Persist as structured event
            await self._emit(run_id, "sdk:metrics", sdk_metrics)

            logger.info(
                "SDK metrics for run %s: cost=$%.6f, prompt=%d, completion=%d",
                run_id, total_cost, total_prompt, total_completion,
            )
        except Exception:
            logger.exception("Failed to persist SDK metrics for run %s", run_id)


# ─── Singleton ────────────────────────────────────────────────────────────────

_manager: RunManager | None = None


def get_run_manager() -> RunManager:
    global _manager
    if _manager is None:
        _manager = RunManager(broker=get_event_broker())
    return _manager
