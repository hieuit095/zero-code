"""
Background worker for the Multi-Agent IDE.

Runs as a separate process from the FastAPI API server. Continuously polls
the Redis `pending_runs` queue, loads run details from the DB, and executes
the orchestration loop (Leader → Dev → QA).

Run with:
    python -m worker

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
    """Execute the orchestration loop for a single run."""
    logger.info("Processing run: %s", run_id)
    manager = get_run_manager()

    try:
        await manager.execute_run(run_id)
        logger.info("Run %s completed", run_id)
    except Exception:
        logger.exception("Run %s failed with unhandled error", run_id)


async def main() -> None:
    """Main worker loop: connect, poll Redis queue, execute runs."""

    # ── Startup ──────────────────────────────────────────────
    logger.info("Worker starting up...")

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

                # Load run from in-memory manager or create from DB
                manager = get_run_manager()
                if manager.get_run_snapshot(run_id) is None:
                    # Run was created by the API process — reload from DB
                    from app.db.database import async_session
                    from app.services.run_store import RunStore

                    async with async_session() as session:
                        snapshot = await RunStore.get_run_snapshot(session, run_id)

                    if snapshot is None:
                        logger.error("Run %s not found in DB — skipping", run_id)
                        continue

                    # Hydrate into the manager's in-memory state
                    manager._runs[run_id] = {
                        "run_id": run_id,
                        "goal": snapshot["goal"],
                        "workspace_id": snapshot.get("workspaceId", "repo-main"),
                        "status": snapshot.get("status", "queued"),
                        "phase": snapshot.get("phase"),
                        "progress": snapshot.get("progress", 0),
                        "tasks": [],
                        "files_changed": [],
                        "started_at": None,
                        "finished_at": None,
                    }

                # Execute the run
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
