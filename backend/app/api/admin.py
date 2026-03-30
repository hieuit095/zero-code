# ==========================================
# Author: Hieu Nguyen - Codev Team
# Email: hieuit095@gmail.com
# Project: ZeroCode - Autonomous Multi-Agent IDE
# ==========================================
"""
Admin metrics API for the Multi-Agent IDE.

Provides global system metrics for the admin dashboard:
- Total/active/completed/failed runs
- Average run duration
- QA retry rate
- Failure rate
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy import func, select

from ..config import get_settings
from ..db.database import async_session
from ..db.models import EventLogModel, RunModel, TaskModel

router = APIRouter(prefix="/api/admin", tags=["admin"])


async def require_admin_auth(x_admin_key: str = Header(None)) -> str:
    """Validate X-Admin-Key header against the configured api_key_secret."""
    settings = get_settings()
    if not x_admin_key or x_admin_key != settings.api_key_secret:
        raise HTTPException(status_code=401, detail="Unauthorized admin access")
    return x_admin_key


@router.get("/metrics")
async def get_global_metrics(authorize: str = Depends(require_admin_auth)) -> dict:
    """
    Aggregate global metrics from the database.

    Returns:
      - totalRuns, activeRuns, completedRuns, failedRuns
      - avgDurationMs
      - qaRetryRate (qa:report events / total runs with events)
      - failureRate (failed / total completed+failed)
    """
    async with async_session() as session:
        # Total runs by status
        total_result = await session.execute(
            select(func.count(RunModel.id))
        )
        total_runs = total_result.scalar() or 0

        active_result = await session.execute(
            select(func.count(RunModel.id))
            .where(RunModel.status.in_(["queued", "running", "planning", "developing", "verifying"]))
        )
        active_runs = active_result.scalar() or 0

        completed_result = await session.execute(
            select(func.count(RunModel.id))
            .where(RunModel.status == "completed")
        )
        completed_runs = completed_result.scalar() or 0

        failed_result = await session.execute(
            select(func.count(RunModel.id))
            .where(RunModel.status == "failed")
        )
        failed_runs = failed_result.scalar() or 0

        # Average duration (completed runs only)
        avg_duration_ms = 0
        if completed_runs > 0:
            duration_result = await session.execute(
                select(
                    func.avg(
                        func.julianday(RunModel.updated_at) - func.julianday(RunModel.created_at)
                    )
                ).where(RunModel.status == "completed")
            )
            avg_days = duration_result.scalar()
            if avg_days:
                avg_duration_ms = int(avg_days * 86400 * 1000)

        # QA retry rate: total qa:report events
        qa_reports_result = await session.execute(
            select(func.count(EventLogModel.id))
            .where(EventLogModel.type == "qa:report")
        )
        total_qa_failures = qa_reports_result.scalar() or 0

        # QA retry rate = qa failures / total finished runs
        finished_runs = completed_runs + failed_runs
        qa_retry_rate = round(total_qa_failures / finished_runs, 2) if finished_runs > 0 else 0.0

        # Failure rate
        failure_rate = round(failed_runs / finished_runs, 2) if finished_runs > 0 else 0.0

        # Total tasks
        tasks_result = await session.execute(
            select(func.count(TaskModel.id))
        )
        total_tasks = tasks_result.scalar() or 0

        completed_tasks_result = await session.execute(
            select(func.count(TaskModel.id))
            .where(TaskModel.status == "completed")
        )
        completed_tasks = completed_tasks_result.scalar() or 0

    return {
        "totalRuns": total_runs,
        "activeRuns": active_runs,
        "completedRuns": completed_runs,
        "failedRuns": failed_runs,
        "avgDurationMs": avg_duration_ms,
        "qaRetryRate": qa_retry_rate,
        "totalQaFailures": total_qa_failures,
        "failureRate": failure_rate,
        "totalTasks": total_tasks,
        "completedTasks": completed_tasks,
    }


@router.get("/recent-runs")
async def get_recent_runs(limit: int = 10, authorize: str = Depends(require_admin_auth)) -> list[dict]:
    """Return the most recent runs for the admin dashboard table."""
    async with async_session() as session:
        result = await session.execute(
            select(
                RunModel.id,
                RunModel.goal,
                RunModel.status,
                RunModel.phase,
                RunModel.progress,
                RunModel.created_at,
                RunModel.updated_at,
            )
            .order_by(RunModel.created_at.desc())
            .limit(min(limit, 50))
        )
        rows = result.all()

    return [
        {
            "id": r.id,
            "goal": r.goal[:120] if r.goal else "",
            "status": r.status,
            "phase": r.phase,
            "progress": r.progress,
            "createdAt": r.created_at.isoformat() if r.created_at else None,
            "updatedAt": r.updated_at.isoformat() if r.updated_at else None,
        }
        for r in rows
    ]
