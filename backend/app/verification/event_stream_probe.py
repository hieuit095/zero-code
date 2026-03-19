# ==========================================
# Author: Hieu Nguyen - Codev Team
# Email: hieuit095@gmail.com
# Project: ZeroCode - Autonomous Multi-Agent IDE
# ==========================================
"""
Deterministic Redis/WebSocket event streaming probe.

This probe verifies:
  - run/task state is committed to PostgreSQL before the corresponding Redis/WS event arrives
  - Redis-backed WebSocket forwarding delivers streaming event types
  - event log sequencing remains monotonic and persisted

Usage:
  python -m app.verification.event_stream_probe
  python -m app.verification.event_stream_probe --base-url http://127.0.0.1:8000
"""

from __future__ import annotations

import argparse
import asyncio
import json
import uuid
from typing import Any

import websockets
from sqlalchemy import select

from ..config import get_settings
from ..db.database import async_session
from ..db.models import EventLogModel, TaskModel
from ..orchestrator.run_manager import RunState, get_run_manager
from ..services.event_broker import get_event_broker
from ..services.run_store import RunStore


async def _create_probe_run(run_id: str, task_id: str) -> None:
    async with async_session() as session:
        await RunStore.create_run(
            session,
            run_id=run_id,
            goal="Deterministic event stream probe",
            workspace_id="repo-main",
            status=RunState.QUEUED,
        )
        await RunStore.create_tasks(
            session,
            run_id,
            [
                {
                    "id": task_id,
                    "label": "Probe task",
                    "status": "pending",
                    "agent": "dev",
                    "acceptanceCriteria": "Probe only",
                }
            ],
        )


async def _fetch_event_row(run_id: str, seq: int) -> EventLogModel | None:
    async with async_session() as session:
        result = await session.execute(
            select(EventLogModel)
            .where(EventLogModel.run_id == run_id, EventLogModel.seq == seq)
        )
        return result.scalar_one_or_none()


async def _fetch_task_status(task_id: str) -> str | None:
    async with async_session() as session:
        task = await session.get(TaskModel, task_id)
    return task.status if task else None


async def _fetch_run_snapshot(run_id: str) -> dict[str, Any] | None:
    async with async_session() as session:
        return await RunStore.get_run_snapshot(session, run_id)


def _to_ws_url(base_url: str, run_id: str) -> str:
    base = base_url.rstrip("/")
    if base.startswith("https://"):
        ws_base = "wss://" + base[len("https://"):]
    elif base.startswith("http://"):
        ws_base = "ws://" + base[len("http://"):]
    else:
        ws_base = base
    return f"{ws_base}/ws/runs/{run_id}"


async def run_probe(base_url: str | None = None) -> dict[str, Any]:
    settings = get_settings()
    base_url = (base_url or f"http://127.0.0.1:{settings.port}").rstrip("/")
    run_id = f"stream_probe_{uuid.uuid4().hex[:12]}"
    task_id = f"task_{uuid.uuid4().hex[:8]}"

    await _create_probe_run(run_id, task_id)
    manager = get_run_manager()
    broker = get_event_broker()
    await broker.connect()

    expected_types = [
        "run:state",
        "task:update",
        "run:state",
        "agent:message:start",
        "agent:message:delta",
        "agent:message",
        "fs:update",
        "terminal:command",
        "terminal:output",
        "terminal:exit",
    ]
    received: list[dict[str, Any]] = []
    assertions: dict[str, Any] = {
        "dbBeforeEmitRunState": False,
        "dbBeforeEmitTaskUpdate": False,
        "deltaStreamSeen": False,
        "fsUpdateSeen": False,
        "terminalOutputSeen": False,
        "eventLogRowsPresent": True,
        "seqMonotonic": True,
    }

    async with websockets.connect(_to_ws_url(base_url, run_id), open_timeout=15) as ws:
        ready_event = json.loads(await asyncio.wait_for(ws.recv(), timeout=15))
        if ready_event.get("type") != "connection:ready":
            raise RuntimeError(f"Unexpected first WS event: {ready_event}")

        # Let the WS forwarder finish subscribing to Redis before publishing.
        await asyncio.sleep(0.5)

        await manager._update_run_status(run_id, RunState.PLANNING, "planning", 5)
        await manager._emit_run_state(run_id, "running", "planning", progress=5)
        await manager._persist_task_status(task_id, "in-progress")
        await manager._emit(run_id, "task:update", {"taskId": task_id, "status": "in-progress"})
        await manager._update_run_status(run_id, RunState.DEVELOPING, "developing", 25)
        await manager._emit_run_state(run_id, "running", "developing", progress=25)
        await manager._emit_agent_message(run_id, "dev", "Dev", "Streaming delta over Redis")
        await manager._emit_fs_update(run_id, "stream_probe.txt", "event-stream-probe\n", "dev")
        await manager._emit_terminal(
            run_id=run_id,
            agent="qa",
            command="python -c \"print('ok')\"",
            stdout="ok\n",
            stderr="",
            exit_code=0,
            duration_ms=120,
            attempt=1,
        )

        previous_seq = 0
        for expected_type in expected_types:
            event = json.loads(await asyncio.wait_for(ws.recv(), timeout=15))
            received.append(event)

            if event.get("type") != expected_type:
                raise RuntimeError(
                    f"Expected WS event {expected_type}, received {event.get('type')}"
                )

            seq = int(event["seq"])
            if seq <= previous_seq:
                assertions["seqMonotonic"] = False
            previous_seq = seq

            row = await _fetch_event_row(run_id, seq)
            if row is None or row.type != expected_type:
                assertions["eventLogRowsPresent"] = False

            if expected_type == "run:state" and event["data"]["phase"] == "developing":
                snapshot = await _fetch_run_snapshot(run_id)
                assertions["dbBeforeEmitRunState"] = (
                    snapshot is not None
                    and snapshot.get("status") == RunState.DEVELOPING
                    and snapshot.get("phase") == "developing"
                )

            if expected_type == "task:update":
                assertions["dbBeforeEmitTaskUpdate"] = (
                    await _fetch_task_status(task_id) == "in-progress"
                )

            if expected_type == "agent:message:delta":
                assertions["deltaStreamSeen"] = event["data"]["delta"] == "Streaming delta over Redis"

            if expected_type == "fs:update":
                assertions["fsUpdateSeen"] = event["data"]["path"] == "stream_probe.txt"

            if expected_type == "terminal:output":
                assertions["terminalOutputSeen"] = event["data"]["text"] == "ok\n"

    passed = all(assertions.values())
    return {
        "status": "passed" if passed else "failed",
        "runId": run_id,
        "taskId": task_id,
        "wsBaseUrl": base_url,
        "assertions": assertions,
        "receivedTypes": [event["type"] for event in received],
    }


async def _async_main(base_url: str | None) -> int:
    try:
        result = await run_probe(base_url=base_url)
    except Exception as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}))
        return 1

    print(json.dumps(result))
    return 0 if result.get("status") == "passed" else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the deterministic event stream probe.")
    parser.add_argument(
        "--base-url",
        default=None,
        help="FastAPI base URL hosting /ws/runs/* (default: local backend port).",
    )
    args = parser.parse_args()
    return asyncio.run(_async_main(base_url=args.base_url))


if __name__ == "__main__":
    raise SystemExit(main())
