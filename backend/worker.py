# ==========================================
# Author: Hieu Nguyen - Codev Team
# Email: hieuit095@gmail.com
# Project: ZeroCode - Autonomous Multi-Agent IDE
# ==========================================
"""
Background worker for the Multi-Agent IDE.

Runs as a separate process from the FastAPI API server. Continuously polls
the Redis `pending_runs` queue, loads run details from the DB, and executes
the orchestration loop (Leader → Dev → QA).

Run with:
    python -m worker

ARCHITECTURE FIX: The worker no longer manually hydrates an in-memory
`_runs` dict. The RunManager is now fully DB-backed, so both this worker
and the FastAPI API server share the same source of truth.

Rule 2: FastAPI MUST NOT block on agent execution. This worker does the heavy lifting.
Rule 3: Redis connection is opened on startup, closed on shutdown.
"""

from __future__ import annotations

import asyncio
import logging
import signal
import sys

# Ensure app package is importable
sys.path.insert(0, ".")

for stream_name in ("stdout", "stderr"):
    stream = getattr(sys, stream_name, None)
    reconfigure = getattr(stream, "reconfigure", None)
    if callable(reconfigure):
        reconfigure(encoding="utf-8", errors="replace")

from app.config import get_settings
from app.db.database import init_db
from app.orchestrator.run_manager import get_run_manager
from app.services.event_broker import get_event_broker

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [WORKER] %(name)s - %(message)s",
)
logger = logging.getLogger("worker")

# Graceful shutdown flag
_shutdown = asyncio.Event()


def _signal_handler(*_: object) -> None:
    """Handle SIGINT/SIGTERM for graceful shutdown."""
    logger.info("Shutdown signal received")
    _shutdown.set()


async def process_run(run_id: str) -> None:
    """
    Execute the orchestration loop for a single run.

    SAFETY: Any unhandled exception is caught and the run is marked as FAILED
    in the database via RunStore, preventing zombie runs.
    """
    logger.info("Processing run: %s", run_id)
    manager = get_run_manager()

    try:
        await manager.execute_run(run_id)
        logger.info("Run %s completed", run_id)
    except Exception as exc:
        logger.exception("Run %s failed with unhandled error", run_id)

        # ── Record FAILED state in DB to prevent zombie runs ─────
        try:
            from app.db.database import async_session
            from app.services.run_store import RunStore

            async with async_session() as session:
                await RunStore.update_run(
                    session,
                    run_id,
                    status="failed",
                    phase="failed",
                    progress=0,
                )
            logger.info(
                "Run %s recorded as FAILED in DB after crash: %s",
                run_id, type(exc).__name__,
            )
        except Exception:
            logger.exception(
                "CRITICAL: Failed to record FAILED status for run %s in DB", run_id
            )

        # ── AUDIT FIX: Broadcast run:error to Redis so the frontend ──
        # breaks out of its loading state. Without this, the React UI
        # would spin indefinitely because no WebSocket event is sent.
        try:
            broker = get_event_broker()
            await broker.publish(run_id, "run:error", {
                "status": "failed",
                "errorCode": "WORKER_CRASH",
                "message": f"Worker process crashed: {type(exc).__name__}: {exc}",
                "lastKnownTaskId": None,
            })
            logger.info("Emitted run:error event for crashed run %s", run_id)
        except Exception:
            logger.exception(
                "CRITICAL: Failed to emit run:error for crashed run %s", run_id
            )


async def main() -> None:
    """Main worker loop: connect, poll Redis queue, execute runs."""

    # ── Startup ──────────────────────────────────────────────
    logger.info("Worker starting up...")

    # Validate required secrets (same check as the API server)
    settings = get_settings()
    settings.validate_required_secrets()

    # Initialize DB (creates tables if needed)
    await init_db()

    # Connect event broker to Redis (Rule 3)
    broker = get_event_broker()
    await broker.connect()

    logger.info("Worker ready — polling pending_runs queue")

    # ── Poll loop ────────────────────────────────────────────
    try:
        while not _shutdown.is_set():
            try:
                # Block for up to 5 seconds waiting for a run
                run_id = await broker.dequeue_run(timeout=5)

                if run_id is None:
                    continue  # Timeout — loop back and check shutdown

                # Verify the run exists in the DB before executing
                manager = get_run_manager()
                snapshot = await manager.get_run_snapshot(run_id)

                if snapshot is None:
                    logger.error("Run %s not found in DB — skipping", run_id)
                    continue
                if snapshot.get("status") != "queued":
                    logger.info(
                        "Run %s dequeued with non-queued status %s — skipping stale queue item",
                        run_id,
                        snapshot.get("status"),
                    )
                    continue

                # Execute the run (RunManager reads all state from DB)
                await process_run(run_id)

            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Error in worker poll loop")
                await asyncio.sleep(1)  # Backoff on errors

    finally:
        # ── Shutdown ─────────────────────────────────────────
        logger.info("Worker shutting down...")
        await broker.close()
        logger.info("Worker stopped")


if __name__ == "__main__":
    # Register signal handlers
    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    asyncio.run(main())
