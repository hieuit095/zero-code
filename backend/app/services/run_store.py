"""
Async repository for Run, Task, and EventLog persistence.

Replaces the in-memory dict in RunManager with real DB operations.
All methods are async and use SQLAlchemy AsyncSession.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import EventLogModel, RunModel, TaskModel


class RunStore:
    """Async CRUD repository for runs, tasks, and events."""

    # ─── Runs ─────────────────────────────────────────────────────────────

    @staticmethod
    async def create_run(
        session: AsyncSession,
        run_id: str,
        goal: str,
        workspace_id: str = "repo-main",
        status: str = "queued",
    ) -> RunModel:
        run = RunModel(
            id=run_id,
            goal=goal,
            workspace_id=workspace_id,
            status=status,
        )
        session.add(run)
        await session.commit()
        await session.refresh(run)
        return run

    @staticmethod
    async def get_run(session: AsyncSession, run_id: str) -> RunModel | None:
        return await session.get(RunModel, run_id)

    @staticmethod
    async def update_run(
        session: AsyncSession,
        run_id: str,
        *,
        status: str | None = None,
        phase: str | None = None,
        progress: int | None = None,
    ) -> None:
        values: dict[str, Any] = {"updated_at": datetime.now(UTC)}
        if status is not None:
            values["status"] = status
        if phase is not None:
            values["phase"] = phase
        if progress is not None:
            values["progress"] = progress

        await session.execute(
            update(RunModel).where(RunModel.id == run_id).values(**values)
        )
        await session.commit()

    @staticmethod
    async def update_run_metrics(
        session: AsyncSession,
        run_id: str,
        *,
        additional_cost: float = 0.0,
        additional_tokens: int = 0,
    ) -> None:
        """Atomically increment cost and token counters on the run row."""
        if additional_cost == 0.0 and additional_tokens == 0:
            return
        await session.execute(
            update(RunModel)
            .where(RunModel.id == run_id)
            .values(
                total_cost=RunModel.total_cost + additional_cost,
                total_tokens=RunModel.total_tokens + additional_tokens,
                updated_at=datetime.now(UTC),
            )
        )
        await session.commit()

    # ─── Tasks ────────────────────────────────────────────────────────────

    @staticmethod
    async def create_tasks(
        session: AsyncSession,
        run_id: str,
        tasks: list[dict[str, Any]],
    ) -> list[TaskModel]:
        models = []
        for t in tasks:
            model = TaskModel(
                id=t["id"],
                run_id=run_id,
                label=t["label"],
                status=t.get("status", "pending"),
                agent=t.get("agent", "dev"),
                acceptance_criteria=t.get("acceptanceCriteria") or t.get("acceptance_criteria"),
            )
            session.add(model)
            models.append(model)
        await session.commit()
        return models

    @staticmethod
    async def update_task_status(
        session: AsyncSession,
        task_id: str,
        status: str,
    ) -> None:
        await session.execute(
            update(TaskModel).where(TaskModel.id == task_id).values(status=status)
        )
        await session.commit()

    @staticmethod
    async def get_tasks_for_run(
        session: AsyncSession, run_id: str
    ) -> list[TaskModel]:
        result = await session.execute(
            select(TaskModel).where(TaskModel.run_id == run_id).order_by(TaskModel.created_at)
        )
        return list(result.scalars().all())

    # ─── Event Log ────────────────────────────────────────────────────────

    @staticmethod
    async def append_event(
        session: AsyncSession,
        run_id: str,
        seq: int,
        event_type: str,
        timestamp: str,
        data: dict[str, Any],
    ) -> EventLogModel:
        event = EventLogModel(
            run_id=run_id,
            seq=seq,
            type=event_type,
            timestamp=timestamp,
            data=data,
        )
        session.add(event)
        await session.commit()
        return event

    @staticmethod
    async def get_events_for_run(
        session: AsyncSession,
        run_id: str,
        after_seq: int = 0,
    ) -> list[EventLogModel]:
        result = await session.execute(
            select(EventLogModel)
            .where(EventLogModel.run_id == run_id, EventLogModel.seq > after_seq)
            .order_by(EventLogModel.seq)
        )
        return list(result.scalars().all())

    # ─── Snapshot (for rehydration) ───────────────────────────────────────

    @staticmethod
    async def get_run_snapshot(
        session: AsyncSession, run_id: str
    ) -> dict[str, Any] | None:
        """Build a full snapshot for frontend rehydration."""
        run = await session.get(RunModel, run_id)
        if run is None:
            return None

        tasks = await RunStore.get_tasks_for_run(session, run_id)

        return {
            "runId": run.id,
            "status": run.status,
            "phase": run.phase,
            "progress": run.progress,
            "goal": run.goal,
            "workspaceId": run.workspace_id,
            "tasks": [
                {
                    "id": t.id,
                    "label": t.label,
                    "status": t.status,
                    "agent": t.agent,
                }
                for t in tasks
            ],
            "createdAt": run.created_at.isoformat() if run.created_at else None,
            "updatedAt": run.updated_at.isoformat() if run.updated_at else None,
        }

    # ─── Metrics ──────────────────────────────────────────────────────────

    @staticmethod
    async def get_run_metrics(
        session: AsyncSession, run_id: str
    ) -> dict[str, Any] | None:
        """
        Compute summary metrics for a run from EventLog and Task tables.

        Returns:
          - total_duration_ms: from run timestamps
          - qa_failure_count: count of qa:report events (QA failures)
          - total_commands_executed: count of exec-related events
          - tasks_completed: count of completed tasks
        """
        from sqlalchemy import func

        run = await session.get(RunModel, run_id)
        if run is None:
            return None

        # QA failure count: events with type containing "qa:report"
        qa_fail_result = await session.execute(
            select(func.count(EventLogModel.id))
            .where(EventLogModel.run_id == run_id, EventLogModel.type == "qa:report")
        )
        qa_failure_count = qa_fail_result.scalar() or 0

        # Total commands executed: events with type "terminal:output"
        exec_result = await session.execute(
            select(func.count(EventLogModel.id))
            .where(EventLogModel.run_id == run_id, EventLogModel.type == "terminal:output")
        )
        total_commands_executed = exec_result.scalar() or 0

        # Tasks completed
        tasks_result = await session.execute(
            select(func.count(TaskModel.id))
            .where(TaskModel.run_id == run_id, TaskModel.status == "completed")
        )
        tasks_completed = tasks_result.scalar() or 0

        # Total tasks
        total_tasks_result = await session.execute(
            select(func.count(TaskModel.id))
            .where(TaskModel.run_id == run_id)
        )
        total_tasks = total_tasks_result.scalar() or 0

        # Duration: difference between created_at and updated_at
        total_duration_ms = 0
        if run.created_at and run.updated_at:
            delta = run.updated_at - run.created_at
            total_duration_ms = int(delta.total_seconds() * 1000)

        return {
            "runId": run_id,
            "totalDurationMs": total_duration_ms,
            "qaFailureCount": qa_failure_count,
            "totalCommandsExecuted": total_commands_executed,
            "tasksCompleted": tasks_completed,
            "totalTasks": total_tasks,
            "status": run.status,
            # ── SDK-native metrics (from sdk:metrics event) ────────────
            **await RunStore._extract_sdk_metrics(session, run_id),
        }

    @staticmethod
    async def _extract_sdk_metrics(
        session: AsyncSession, run_id: str,
    ) -> dict[str, Any]:
        """
        Extract SDK-native LLM metrics from the 'sdk:metrics' event
        emitted by `run_manager._persist_sdk_metrics()`.

        Returns a dict with cost/token fields (or empty defaults if
        no sdk:metrics event exists yet).
        """
        result = await session.execute(
            select(EventLogModel.data)
            .where(
                EventLogModel.run_id == run_id,
                EventLogModel.type == "sdk:metrics",
            )
            .order_by(EventLogModel.seq.desc())
            .limit(1)
        )
        row = result.scalar()

        if row is None:
            return {
                "accumulatedCost": 0.0,
                "promptTokens": 0,
                "completionTokens": 0,
                "agentMetrics": {},
            }

        # row is already a dict (JSON column)
        data = row if isinstance(row, dict) else json.loads(row)
        return {
            "accumulatedCost": data.get("totalCost", 0.0),
            "promptTokens": data.get("totalPromptTokens", 0),
            "completionTokens": data.get("totalCompletionTokens", 0),
            "agentMetrics": data.get("agents", {}),
        }
