"""
Run manager with async state machine orchestrating the full Leader → Dev → QA loop.

States:
  QUEUED → PLANNING → DELEGATING → DEVELOPING → VERIFYING → (next task or DONE)
                                       ↑            ↓
                                       └── RETRYING ┘  (max 2 retries per task)
                                                       → FAILED (if exhausted)

The Leader decomposes the user goal into tasks. The orchestrator loops through
each task, running the Dev→QA engine for each one. All state transitions emit
events via the EventBroker (Rule 4: events match Pydantic schemas).
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
from ..agents.mcp_tools import clear_run_token, set_run_token
from ..agents.qa_agent import QaAgent, QaAgentResult
from ..core.security import generate_mcp_token, revoke_run_token
from ..db.database import async_session
from ..services.event_broker import EventBroker, get_event_broker
from ..services.run_store import RunStore

logger = logging.getLogger(__name__)

MAX_QA_RETRIES = 2


# ─── Run States ───────────────────────────────────────────────────────────────


class RunState:
    QUEUED = "queued"
    PLANNING = "planning"
    DELEGATING = "delegating"
    DEVELOPING = "developing"
    VERIFYING = "verifying"
    RETRYING = "retrying"
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


# ─── Run Manager ──────────────────────────────────────────────────────────────


class RunManager:
    """Async state machine: Leader (plan) → per-task Dev → QA loop."""

    def __init__(self, broker: EventBroker) -> None:
        self._broker = broker
        self._runs: dict[str, dict[str, Any]] = {}
        self._leader_agent = LeaderAgent()
        self._dev_agent = DevAgent()
        self._qa_agent = QaAgent()

    # ─── CRUD ─────────────────────────────────────────────────────────────

    async def create_run(
        self,
        goal: str,
        workspace_id: str = "repo-main",
        agent_config: dict | None = None,
    ) -> dict[str, Any]:
        run_id = f"run_{uuid4().hex[:12]}"
        run = {
            "run_id": run_id,
            "goal": goal,
            "workspace_id": workspace_id,
            "agent_config": agent_config,
            "status": RunState.QUEUED,
            "phase": None,
            "progress": 0,
            "tasks": [],
            "current_task_idx": -1,
            "files_changed": [],
            "created_at": _now_iso(),
            "started_at": None,
            "finished_at": None,
        }
        self._runs[run_id] = run

        # Persist to DB
        try:
            async with async_session() as session:
                await RunStore.create_run(session, run_id, goal, workspace_id)
        except Exception:
            logger.exception("Failed to persist run %s", run_id)

        return run

    def get_run_snapshot(self, run_id: str) -> dict[str, Any] | None:
        return self._runs.get(run_id)

    def cancel_run(self, run_id: str, reason: str = "user_cancelled") -> dict[str, Any] | None:
        run = self._runs.get(run_id)
        if run is None:
            return None
        run["status"] = RunState.CANCELLED
        run["finished_at"] = _now_iso()
        return {"status": "cancelled", "message": f"Run {run_id} cancelled: {reason}"}

    async def update_run_status(
        self, run_id: str, status: str, phase: str | None = None, progress: int = 0
    ) -> None:
        run = self._runs.get(run_id)
        if run:
            run["status"] = status
            run["phase"] = phase
            run["progress"] = progress

        # Persist to DB
        try:
            async with async_session() as session:
                await RunStore.update_run(
                    session, run_id, status=status, phase=phase, progress=progress
                )
        except Exception:
            logger.exception("Failed to persist status for run %s", run_id)

    async def _persist_tasks(
        self, run_id: str, tasks: list[dict[str, Any]]
    ) -> None:
        """Persist planned tasks to DB after Leader finishes."""
        try:
            async with async_session() as session:
                await RunStore.create_tasks(session, run_id, tasks)
        except Exception:
            logger.exception("Failed to persist tasks for run %s", run_id)

    async def _persist_task_status(
        self, task_id: str, status: str
    ) -> None:
        """Persist a single task status change."""
        try:
            async with async_session() as session:
                await RunStore.update_task_status(session, task_id, status)
        except Exception:
            logger.exception("Failed to persist task status for %s", task_id)

    # ─── Event Emission Helpers ───────────────────────────────────────────

    async def _emit(self, run_id: str, event_type: str, data: dict[str, Any]) -> None:
        await self._broker.publish(run_id, event_type, data)

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
        Full async state machine:
        QUEUED → PLANNING → DELEGATING → (per-task DEVELOPING → VERIFYING) → DONE
        """
        run = self._runs.get(run_id)
        if run is None:
            return

        run["started_at"] = _now_iso()
        start_time = time.monotonic()
        goal = run["goal"]

        # Generate JWT for MCP facade and inject into mcp_tools
        mcp_token = generate_mcp_token(run_id, expiry_minutes=30)
        set_run_token(run_id, mcp_token)

        try:
            # ── run:created ──────────────────────────────────────────
            await self._emit(run_id, "run:created", {
                "status": "queued", "workspaceId": run["workspace_id"],
            })

            # ══════════════════════════════════════════════════════════
            # STATE: PLANNING
            # ══════════════════════════════════════════════════════════
            run["status"] = RunState.PLANNING
            run["phase"] = "planning"
            run["progress"] = 5

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
            )

            if leader_result.status == "error" or not leader_result.tasks:
                await self._emit_agent_message(run_id, "tech-lead", "Tech Lead",
                    f"Planning failed: {leader_result.error or 'No tasks generated'}")
                await self._emit_run_error(run_id, "planning_failed",
                    leader_result.error or "Leader produced no tasks", None)
                return

            # Store tasks in run state
            tasks: list[AgentTask] = leader_result.tasks
            run["tasks"] = [
                {"id": t.id, "label": t.label, "acceptanceCriteria": t.acceptance_criteria,
                 "status": "pending", "agent": "dev"}
                for t in tasks
            ]

            # Persist tasks to DB
            await self._persist_tasks(run_id, run["tasks"])

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
            # STATE: DELEGATING (task loop)
            # ══════════════════════════════════════════════════════════
            all_files_changed: list[str] = []
            total_tasks = len(tasks)

            for task_idx, task in enumerate(tasks):
                run["current_task_idx"] = task_idx
                run["status"] = RunState.DELEGATING
                run["phase"] = "delegating"

                # Progress: 10% (planning done) + proportional per task
                base_progress = 10 + int((task_idx / total_tasks) * 80)
                run["progress"] = base_progress

                await self._emit_run_state(run_id, "running", "delegating",
                    progress=base_progress)

                # Mark task as in-progress
                run["tasks"][task_idx]["status"] = "in-progress"
                await self._emit(run_id, "task:update", {
                    "taskId": task.id, "status": "in-progress",
                })

                await self._emit_agent_message(run_id, "tech-lead", "Tech Lead",
                    f"Delegating task {task_idx + 1}/{total_tasks}: {task.label}")

                # ── Run Dev → QA loop for this task ──────────────────
                task_goal = (
                    f"Task: {task.label}\n"
                    f"Acceptance Criteria: {task.acceptance_criteria}"
                )
                task_result = await self._execute_task(
                    run_id=run_id,
                    task=task,
                    task_idx=task_idx,
                    total_tasks=total_tasks,
                    goal=task_goal,
                    base_progress=base_progress,
                )

                if task_result == "completed":
                    run["tasks"][task_idx]["status"] = "completed"
                    await self._persist_task_status(task.id, "completed")
                    await self._emit(run_id, "task:update", {
                        "taskId": task.id, "status": "completed",
                    })
                    all_files_changed.extend(run.get("_last_files", []))
                else:
                    # Task failed — mark it and abort
                    run["tasks"][task_idx]["status"] = "failed"
                    await self._persist_task_status(task.id, "failed")
                    await self._emit(run_id, "task:update", {
                        "taskId": task.id, "status": "failed",
                    })

                    run["status"] = RunState.FAILED
                    run["phase"] = "failed"
                    run["finished_at"] = _now_iso()
                    await self.update_run_status(run_id, RunState.FAILED, "failed", run["progress"])

                    await self._emit_run_error(run_id, "task_failed",
                        f"Task '{task.label}' failed after {MAX_QA_RETRIES + 1} attempts.",
                        task.id)
                    return

            # ══════════════════════════════════════════════════════════
            # STATE: DONE — all tasks completed
            # ══════════════════════════════════════════════════════════
            duration_ms = int((time.monotonic() - start_time) * 1000)
            run["status"] = RunState.COMPLETED
            run["phase"] = "done"
            run["progress"] = 100
            run["files_changed"] = list(set(all_files_changed))
            run["finished_at"] = _now_iso()
            await self.update_run_status(run_id, RunState.COMPLETED, "done", 100)

            await self._emit(run_id, "run:complete", {
                "status": "completed",
                "summary": f"All {total_tasks} tasks completed successfully.",
                "changedFiles": run["files_changed"],
                "qaRetries": 0,
                "durationMs": duration_ms,
            })

        except Exception as exc:
            logger.exception("Unhandled error in execute_run for %s", run_id)
            run["status"] = RunState.FAILED
            run["finished_at"] = _now_iso()
            await self.update_run_status(run_id, RunState.FAILED, "failed", run.get("progress", 0))
            await self._emit_run_error(run_id, "internal_error", str(exc), None)

        finally:
            # Clean up JWT token and revoke run from active set
            clear_run_token(run_id)
            revoke_run_token(run_id)

    # ─── Per-Task Dev → QA Engine ─────────────────────────────────────────

    async def _execute_task(
        self,
        run_id: str,
        task: AgentTask,
        task_idx: int,
        total_tasks: int,
        goal: str,
        base_progress: int,
    ) -> str:
        """
        Run the Dev → QA loop for a single task.
        Returns "completed" or "failed".
        """
        run = self._runs[run_id]
        dev_input = goal
        attempt = 0

        while attempt <= MAX_QA_RETRIES:
            attempt += 1

            # ── DEVELOPING ───────────────────────────────────────────
            run["status"] = RunState.DEVELOPING
            run["phase"] = "developing"
            dev_progress = base_progress + int((1 / total_tasks) * 30)
            run["progress"] = dev_progress

            await self._emit_run_state(run_id, "running", "developing",
                attempt=attempt, progress=dev_progress)

            await self._emit_agent_status(run_id, "dev", "thinking",
                activity="Analyzing task..." if attempt == 1 else "Fixing QA issues...",
                task_id=task.id, attempt=attempt)

            await self._emit_agent_message(run_id, "dev", "Dev",
                f"{'Implementing' if attempt == 1 else f'Retry #{attempt-1}'}: {dev_input[:200]}")

            await self._emit_agent_status(run_id, "dev", "working",
                activity="Writing code via MCP tools",
                task_id=task.id, attempt=attempt)

            dev_result: DevAgentResult = await self._dev_agent.run(
                run_id=run_id, goal=dev_input,
                context={"attempt": attempt, "task_id": task.id},
            )

            if dev_result.status == "error":
                await self._emit_agent_message(run_id, "dev", "Dev",
                    f"Error: {dev_result.error}")
                return "failed"

            run["_last_files"] = dev_result.files_changed

            await self._emit_agent_message(run_id, "dev", "Dev",
                f"Done. Changed: {', '.join(dev_result.files_changed)}. {dev_result.summary}")

            # Emit fs events
            for path in dev_result.files_changed:
                await self._emit(run_id, "dev:start-edit", {"fileName": path, "taskId": task.id})
                await self._emit_fs_update(run_id, path, dev_result.raw_output, "dev")
                await self._emit(run_id, "dev:stop-edit", {"fileName": path})

            await self._emit_agent_status(run_id, "dev", "idle",
                task_id=task.id, attempt=attempt)

            # ── VERIFYING ────────────────────────────────────────────
            run["status"] = RunState.VERIFYING
            run["phase"] = "verifying"
            qa_progress = base_progress + int((1 / total_tasks) * 60)
            run["progress"] = qa_progress

            await self._emit_run_state(run_id, "running", "verifying",
                attempt=attempt, progress=qa_progress)

            await self._emit_agent_status(run_id, "qa", "thinking",
                activity="Preparing verification checks",
                task_id=task.id, attempt=attempt)

            await self._emit_agent_message(run_id, "qa", "QA",
                f"Verifying: {', '.join(dev_result.files_changed)}")

            await self._emit_agent_status(run_id, "qa", "working",
                activity="Running checks", task_id=task.id, attempt=attempt)

            qa_result: QaAgentResult = await self._qa_agent.run(
                run_id=run_id, task_id=task.id,
                attempt=attempt, changed_files=dev_result.files_changed,
            )

            # Emit terminal events
            for check in qa_result.commands:
                await self._emit_terminal(
                    run_id=run_id, agent="qa", command=check.command,
                    stdout=check.stdout, stderr=check.stderr,
                    exit_code=check.exit_code, duration_ms=check.duration_ms,
                    attempt=attempt,
                )

            # ── QA PASSED ────────────────────────────────────────────
            if qa_result.status == "passed":
                await self._emit(run_id, "qa:passed", qa_result.to_passed_dict())
                await self._emit_agent_message(run_id, "qa", "QA",
                    f"✓ Passed: {qa_result.summary}")
                await self._emit_agent_status(run_id, "qa", "idle",
                    task_id=task.id, attempt=attempt)
                return "completed"

            # ── QA FAILED ────────────────────────────────────────────
            await self._emit(run_id, "qa:report", qa_result.to_report_dict())
            await self._emit_agent_message(run_id, "qa", "QA",
                f"✗ Failed: {qa_result.summary}")
            await self._emit_agent_status(run_id, "qa", "idle",
                task_id=task.id, attempt=attempt)

            if not qa_result.retryable or attempt > MAX_QA_RETRIES:
                break

            # ── RETRYING — pass defect report back to Dev (Rule 3) ───
            run["status"] = RunState.RETRYING
            run["phase"] = "retrying"

            await self._emit_run_state(run_id, "running", "retrying",
                attempt=attempt, progress=run["progress"])
            await self._emit_agent_message(run_id, "dev", "Dev",
                f"QA failed — retrying (attempt {attempt}/{MAX_QA_RETRIES + 1})...")

            dev_input = json.dumps(qa_result.to_report_dict(), indent=2)

        return "failed"


# ─── Singleton ────────────────────────────────────────────────────────────────

_manager: RunManager | None = None


def get_run_manager() -> RunManager:
    global _manager
    if _manager is None:
        _manager = RunManager(broker=get_event_broker())
    return _manager
