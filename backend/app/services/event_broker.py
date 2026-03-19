# ==========================================
# Author: Hieu Nguyen - Codev Team
# Email: hieuit095@gmail.com
# Project: ZeroCode - Autonomous Multi-Agent IDE
# ==========================================
"""
Redis-backed event broker with DB persistence.

Publish flow: Worker -> PostgreSQL event_log -> Redis channel -> FastAPI WS -> React
Subscribe flow: FastAPI ws.py -> Redis subscribe -> WebSocket send_json
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import UTC, datetime
from typing import Any, AsyncGenerator

import redis.asyncio as aioredis
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from ..config import get_settings
from ..db.database import async_session
from ..db.models import RunModel
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
            client = aioredis.from_url(
                redis_url,
                decode_responses=True,
                socket_connect_timeout=1,
                socket_timeout=10,
            )
            try:
                await client.ping()
            except Exception as exc:
                await client.aclose()
                logger.warning(
                    "Redis unavailable at %s; falling back to DB-backed queue/events: %s",
                    redis_url,
                    exc,
                )
                self._redis = None
                return

            self._redis = client
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

    @property
    def has_redis(self) -> bool:
        return self._redis is not None

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
        max_attempts = 5
        event: dict[str, Any] | None = None

        for attempt in range(1, max_attempts + 1):
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
                break
            except IntegrityError as exc:
                detail = str(getattr(exc, "orig", exc))
                is_seq_collision = (
                    "event_log.run_id, event_log.seq" in detail
                    or "uq_event_log_run_seq" in detail
                )
                if not is_seq_collision or attempt >= max_attempts:
                    logger.exception("Failed to persist event for run %s", run_id)
                    raise

                logger.warning(
                    "Event seq collision for run %s while publishing %s; retrying (%s/%s)",
                    run_id,
                    event_type,
                    attempt,
                    max_attempts,
                )
                await asyncio.sleep(0.05 * attempt)
            except Exception:
                logger.exception("Failed to persist event for run %s", run_id)
                raise

        if event is None:
            raise RuntimeError(f"Failed to build event for run {run_id}")

        if not self.has_redis:
            return event

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
        if not self.has_redis:
            async for event in self._subscribe_via_db(run_id):
                yield event
            return

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
        if not self.has_redis:
            logger.info(
                "Redis unavailable; leaving run %s in DB queued state for worker polling",
                run_id,
            )
            return

        try:
            await self.redis.lpush("pending_runs", run_id)
            logger.info("Enqueued run %s to pending_runs", run_id)
        except Exception as exc:
            logger.warning(
                "Redis enqueue failed for run %s; worker can recover via DB polling: %s",
                run_id,
                exc,
            )

    async def dequeue_run(self, timeout: int = 0) -> str | None:
        """Pop a run_id from the pending_runs queue."""
        if self.has_redis:
            try:
                result = await self.redis.brpop("pending_runs", timeout=timeout)
                if result:
                    return result[1]
                db_run_id = await self._dequeue_run_via_db(timeout=0)
                if db_run_id:
                    logger.info(
                        "Redis queue empty; recovered queued run %s from DB polling",
                        db_run_id,
                    )
                return db_run_id
            except Exception as exc:
                logger.warning(
                    "Redis dequeue failed; falling back to DB queued-run polling: %s",
                    exc,
                )
                try:
                    await self._redis.aclose()
                except Exception:
                    logger.debug("Failed to close Redis after dequeue error", exc_info=True)
                self._redis = None

        return await self._dequeue_run_via_db(timeout)

    async def _dequeue_run_via_db(self, timeout: int) -> str | None:
        """Fallback queued-run polling when Redis is unavailable."""
        deadline = time.monotonic() + timeout if timeout > 0 else None
        while True:
            async with async_session() as session:
                result = await session.execute(
                    select(RunModel.id)
                    .where(RunModel.status == "queued")
                    .order_by(RunModel.created_at.asc())
                    .limit(1)
                )
                run_id = result.scalar_one_or_none()

            if run_id:
                return run_id

            if deadline is not None and time.monotonic() >= deadline:
                return None

            await asyncio.sleep(0.5)

    def cleanup_run(self, run_id: str) -> None:
        logger.debug("EventBroker cleanup requested for run %s", run_id)

    async def _subscribe_via_db(self, run_id: str) -> AsyncGenerator[dict[str, Any], None]:
        """Fallback event stream when Redis is unavailable."""
        last_seq = 0
        terminal_types = {"run:complete", "run:error"}
        terminal_statuses = {"completed", "failed", "cancelled"}

        while True:
            async with async_session() as session:
                rows = await RunStore.get_events_for_run(session, run_id, after_seq=last_seq)
                run = await RunStore.get_run(session, run_id)

            for row in rows:
                last_seq = row.seq
                event = {
                    "type": row.type,
                    "runId": run_id,
                    "seq": row.seq,
                    "timestamp": row.timestamp,
                    "data": row.data,
                }
                yield event
                if row.type in terminal_types:
                    return

            if run is None:
                return

            if run.status in terminal_statuses and not rows:
                return

            await asyncio.sleep(0.25)


_broker: EventBroker | None = None


def get_event_broker() -> EventBroker:
    global _broker
    if _broker is None:
        _broker = EventBroker()
    return _broker
