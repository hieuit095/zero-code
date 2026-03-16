"""
WebSocket transport for the run lifecycle.

Every websocket frame follows the server envelope:
{
  "type": "agent:status",
  "runId": "run_...",
  "seq": 42,
  "timestamp": "2026-03-16T05:20:14.221Z",
  "data": { ...event-specific payload... }
}

Events are consumed from the EventBroker which is fed by the RunManager
orchestration loop. This is a pure transport layer — no business logic.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..services.event_broker import get_event_broker

router = APIRouter()
logger = logging.getLogger(__name__)


@router.websocket("/ws/runs/{run_id}", name="run_websocket")
async def run_websocket(websocket: WebSocket, run_id: str) -> None:
    """
    WebSocket endpoint for streaming run events to the frontend.

    1. Accept the connection
    2. Send connection:ready
    3. Subscribe to the EventBroker for this run_id
    4. Forward all events as JSON frames
    5. Listen for client control messages in parallel
    """
    await websocket.accept()
    broker = get_event_broker()

    # Send connection:ready immediately
    ready_event = broker.build_event(run_id, "connection:ready", {
        "serverTime": datetime.now(UTC).isoformat(),
        "supportsReconnect": True,
    })
    await websocket.send_json(ready_event)

    # Track tasks for cleanup
    tasks: list[asyncio.Task] = []

    try:
        # ── Task 1: Forward broker events to WebSocket ────────────
        async def forward_events() -> None:
            async for event in broker.subscribe(run_id):
                try:
                    await websocket.send_json(event)
                except Exception:
                    break

                # Auto-close after terminal events
                if event.get("type") in ("run:complete", "run:error"):
                    await asyncio.sleep(0.5)  # Let the client process
                    break

        # ── Task 2: Listen for client control messages ────────────
        async def listen_client() -> None:
            try:
                while True:
                    raw = await websocket.receive_text()
                    try:
                        msg = json.loads(raw)
                        msg_type = msg.get("type")
                        logger.info("WS client message: %s for run %s", msg_type, run_id)

                        if msg_type == "run:cancel":
                            from ..orchestrator.run_manager import get_run_manager
                            manager = get_run_manager()
                            reason = msg.get("data", {}).get("reason", "user_cancelled")
                            manager.cancel_run(run_id, reason)

                    except json.JSONDecodeError:
                        logger.warning("Invalid JSON from WS client: %s", raw[:100])
            except WebSocketDisconnect:
                pass
            except Exception:
                pass

        # Run both tasks concurrently
        forward_task = asyncio.create_task(forward_events())
        listen_task = asyncio.create_task(listen_client())
        tasks = [forward_task, listen_task]

        # Wait for either to complete
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)

        # Cancel the other
        for task in pending:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass

    except WebSocketDisconnect:
        logger.info("WS disconnected for run %s", run_id)
    except Exception as e:
        logger.error("WS error for run %s: %s", run_id, e)
    finally:
        # Clean up
        for task in tasks:
            if not task.done():
                task.cancel()
        try:
            await websocket.close()
        except Exception:
            pass
