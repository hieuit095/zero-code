"""
Redis-backed event broker with DB persistence.

Publish flow: Worker -> PostgreSQL event_log -> Redis channel -> FastAPI WS -> React
Subscribe flow: FastAPI ws.py -> Redis subscribe -> WebSocket send_json
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any, AsyncGenerator

import redis.asyncio as aioredis

from ..config import get_settings
from ..db.database import async_session
from ..services.run_store import RunStore

logger = logging.getLogger(__name__)


class EventBroker:
    """Redis Pub/Sub event broker with DB-backed event sequencing."""

    def __init__(self) -> None:
        self._redis: aioredis.Redis | None = None

    async def connect(self) -> None:
        """Connect to Redis and verify the connection."""
        if self._redis is None:
            redis_url = get_settings().redis_url
            self._redis = aioredis.from_url(redis_url, decode_responses=True)
            await self._redis.ping()
            logger.info("EventBroker connected to Redis at %s", redis_url)

    async def close(self) -> None:
        """Close the Redis connection."""
        if self._redis is not None:
            await self._redis.aclose()
            self._redis = None
            logger.info("EventBroker Redis connection closed")

    @property
    def redis(self) -> aioredis.Redis:
        if self._redis is None:
            raise RuntimeError("EventBroker not connected; call connect() first")
        return self._redis

    @staticmethod
    def _channel(run_id: str) -> str:
        return f"run_events:{run_id}"

    def build_event(
        self,
        run_id: str | None,
        event_type: str,
        data: dict[str, Any],
        *,
        seq: int = 0,
    ) -> dict[str, Any]:
        """Build a server event envelope."""
        return {
            "type": event_type,
            "runId": run_id,
            "seq": seq,
            "timestamp": datetime.now(UTC).isoformat(),
            "data": data,
        }

    async def publish(self, run_id: str, event_type: str, data: dict[str, Any]) -> dict[str, Any]:
        """
        Persist the event before publishing it to Redis.

        This preserves DB-before-emit ordering and keeps event sequence state in
        PostgreSQL instead of process memory.
        """
        try:
            async with async_session() as session:
                async with session.begin():
                    seq = await RunStore.reserve_next_event_seq(session, run_id)
                    event = self.build_event(run_id, event_type, data, seq=seq)
                    await RunStore.append_event(
                        session,
                        run_id=run_id,
                        seq=event["seq"],
                        event_type=event["type"],
                        timestamp=event["timestamp"],
                        data=event["data"],
                        commit=False,
                    )
        except Exception:
            logger.exception("Failed to persist event for run %s", run_id)
            raise

        try:
            await self.redis.publish(self._channel(run_id), json.dumps(event))
        except Exception:
            logger.exception(
                "Failed to publish persisted event seq=%s to Redis for run %s",
                event["seq"],
                run_id,
            )

        return event

    async def subscribe(self, run_id: str) -> AsyncGenerator[dict[str, Any], None]:
        """Subscribe to Redis channel for a run and yield JSON-decoded events."""
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
                except json.JSONDecodeError:
                    logger.warning("Invalid JSON from Redis channel %s", channel)
                    continue

                yield event

                if event.get("type") in ("run:complete", "run:error"):
                    break
        finally:
            await pubsub.unsubscribe(channel)
            await pubsub.aclose()
            logger.info("Unsubscribed from Redis channel %s", channel)

    async def enqueue_run(self, run_id: str) -> None:
        """Push a run_id to the pending_runs queue for the worker."""
        await self.redis.lpush("pending_runs", run_id)
        logger.info("Enqueued run %s to pending_runs", run_id)

    async def dequeue_run(self, timeout: int = 0) -> str | None:
        """Pop a run_id from the pending_runs queue."""
        result = await self.redis.brpop("pending_runs", timeout=timeout)
        if result:
            return result[1]
        return None

    def cleanup_run(self, run_id: str) -> None:
        logger.debug("EventBroker cleanup requested for run %s", run_id)


_broker: EventBroker | None = None


def get_event_broker() -> EventBroker:
    global _broker
    if _broker is None:
        _broker = EventBroker()
    return _broker
