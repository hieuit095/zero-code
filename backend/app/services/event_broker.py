"""
Redis-backed event broker with DB persistence.

Replaces the in-memory pub-sub with Redis Pub/Sub so events can flow
between the FastAPI API process and the background Worker process.

Publish flow:  Worker → Redis channel → FastAPI WS → React client
Subscribe flow: FastAPI ws.py → Redis subscribe → WebSocket send_json

Rule 1: JSON payloads are identical to the in-memory broker version.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import UTC, datetime
from itertools import count
from typing import Any, AsyncGenerator

import redis.asyncio as aioredis

from ..db.database import async_session
from ..services.run_store import RunStore

logger = logging.getLogger(__name__)

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")


class EventBroker:
    """Redis Pub/Sub event broker with DB persistence."""

    def __init__(self) -> None:
        self._redis: aioredis.Redis | None = None
        self._sequences: dict[str, count] = {}

    # ─── Lifecycle ────────────────────────────────────────────────────────

    async def connect(self) -> None:
        """Connect to Redis. Call during app/worker startup (Rule 3)."""
        if self._redis is None:
            self._redis = aioredis.from_url(REDIS_URL, decode_responses=True)
            logger.info("EventBroker connected to Redis at %s", REDIS_URL)

    async def close(self) -> None:
        """Close Redis connection. Call during app/worker shutdown (Rule 3)."""
        if self._redis:
            await self._redis.close()
            self._redis = None
            logger.info("EventBroker Redis connection closed")

    @property
    def redis(self) -> aioredis.Redis:
        if self._redis is None:
            raise RuntimeError("EventBroker not connected — call connect() first")
        return self._redis

    # ─── Channel naming ──────────────────────────────────────────────────

    @staticmethod
    def _channel(run_id: str) -> str:
        return f"run_events:{run_id}"

    # ─── Sequencing ──────────────────────────────────────────────────────

    def _get_seq(self, run_id: str) -> int:
        if run_id not in self._sequences:
            self._sequences[run_id] = count(start=1)
        return next(self._sequences[run_id])

    # ─── Build event envelope ────────────────────────────────────────────

    def build_event(self, run_id: str | None, event_type: str, data: dict[str, Any]) -> dict[str, Any]:
        """Build a server event envelope with auto-incrementing seq."""
        seq = self._get_seq(run_id or "__global__")
        return {
            "type": event_type,
            "runId": run_id,
            "seq": seq,
            "timestamp": datetime.now(UTC).isoformat(),
            "data": data,
        }

    # ─── Publish ─────────────────────────────────────────────────────────

    async def publish(self, run_id: str, event_type: str, data: dict[str, Any]) -> dict[str, Any]:
        """Publish event to Redis channel AND persist to DB."""
        event = self.build_event(run_id, event_type, data)

        # 1. Publish to Redis channel
        try:
            await self.redis.publish(self._channel(run_id), json.dumps(event))
        except Exception:
            logger.exception("Failed to publish event to Redis for run %s", run_id)

        # 2. Persist to DB (fire-and-forget)
        try:
            async with async_session() as session:
                await RunStore.append_event(
                    session,
                    run_id=run_id,
                    seq=event["seq"],
                    event_type=event["type"],
                    timestamp=event["timestamp"],
                    data=event["data"],
                )
        except Exception:
            logger.exception("Failed to persist event seq=%s for run %s", event["seq"], run_id)

        return event

    # ─── Subscribe (used by ws.py) ───────────────────────────────────────

    async def subscribe(self, run_id: str) -> AsyncGenerator[dict[str, Any], None]:
        """Subscribe to Redis channel for a run. Yields events as published."""
        pubsub = self.redis.pubsub()
        channel = self._channel(run_id)

        await pubsub.subscribe(channel)
        logger.info("Subscribed to Redis channel %s", channel)

        try:
            async for message in pubsub.listen():
                if message["type"] != "message":
                    continue
                try:
                    event = json.loads(message["data"])
                    yield event

                    # Auto-close after terminal events
                    if event.get("type") in ("run:complete", "run:error"):
                        break
                except json.JSONDecodeError:
                    logger.warning("Invalid JSON from Redis channel %s", channel)
        finally:
            await pubsub.unsubscribe(channel)
            await pubsub.close()
            logger.info("Unsubscribed from Redis channel %s", channel)

    # ─── Queue operations (for worker dispatch) ──────────────────────────

    async def enqueue_run(self, run_id: str) -> None:
        """Push a run_id to the pending_runs queue for the worker."""
        await self.redis.lpush("pending_runs", run_id)
        logger.info("Enqueued run %s to pending_runs", run_id)

    async def dequeue_run(self, timeout: int = 0) -> str | None:
        """Pop a run_id from the pending_runs queue (blocking)."""
        result = await self.redis.brpop("pending_runs", timeout=timeout)
        if result:
            return result[1]  # (key, value) tuple
        return None

    # ─── Cleanup ─────────────────────────────────────────────────────────

    def cleanup_run(self, run_id: str) -> None:
        self._sequences.pop(run_id, None)


# ─── Singleton ────────────────────────────────────────────────────────────────

_broker: EventBroker | None = None


def get_event_broker() -> EventBroker:
    global _broker
    if _broker is None:
        _broker = EventBroker()
    return _broker
