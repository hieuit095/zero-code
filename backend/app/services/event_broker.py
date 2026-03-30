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
import threading
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
        self._reconnect_attempts: int = 0
        self._sub_last_seq: dict[str, int] = {}
        self._authorized_runs: set[str] = set()

    async def connect(self) -> None:
        """Connect to Redis and verify the connection."""
        if self._redis is None:
            redis_url = get_settings().redis_url
            client = aioredis.from_url(
                redis_url,
                decode_responses=True,
                socket_connect_timeout=5.0,
                socket_timeout=10.0,
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

    async def reconnect(self) -> bool:
        """Reconnect to Redis with exponential backoff (up to 5 retries)."""
        redis_url = get_settings().redis_url
        for attempt in range(1, 6):
            try:
                client = aioredis.from_url(
                    redis_url,
                    decode_responses=True,
                    socket_connect_timeout=5.0,
                    socket_timeout=10.0,
                )
                await client.ping()
                self._redis = client
                self._reconnect_attempts = 0
                logger.info("EventBroker reconnected to Redis at %s", redis_url)
                return True
            except (ConnectionError, Exception) as exc:
                logger.warning(
                    "Redis reconnect attempt %s/5 failed: %s",
                    attempt,
                    exc,
                )
                if attempt < 5:
                    await asyncio.sleep(2 ** (attempt - 1))
        self._redis = None
        self._reconnect_attempts = 5
        logger.error("EventBroker could not reconnect to Redis after 5 attempts")
        return False

    async def authorize_run(self, run_id: str) -> None:
        """Authorize a run_id to subscribe to events."""
        self._authorized_runs.add(run_id)

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
                    # session.begin() exits here → transaction COMMITS
                    # Redis publish STRICTLY AFTER confirmed DB commit
                    # P1-B FIX: redis_published declared OUTSIDE the try at the same 22-space
                    # indent as the `if not redis_published:` check so it is always in scope.
                    if self.has_redis:
                        redis_published = False  # noqa: F841  # set inside try below
                        try:
                            await asyncio.wait_for(
                                self.redis.publish(
                                    self._channel(run_id), json.dumps(event)
                                ),
                                timeout=5.0,
                            )
                            redis_published = True
                        except asyncio.TimeoutError:
                            logger.error(
                                "Redis publish TIMEOUT (5s) for event seq=%s run=%s "
                                "— DB committed, flagging for DB polling recovery",
                                event["seq"], run_id,
                            )
                        except Exception as redis_exc:
                            # P1-B FIX: Log at CRITICAL level so it's immediately visible,
                            # but do NOT re-raise — DB is SSOT, orchestrator must not crash.
                            logger.critical(
                                "Redis publish failed, but event is safe in Postgres SSOT: %s",
                                redis_exc,
                            )
                if not redis_published:
                    # P1-D FIX: Recovery marker moved OUTSIDE session.begin() block so it
                    # fires regardless of exceptions inside the transaction.
                    try:
                        recovery_key = f"zero:events:{run_id}:{event['seq']}:redis_failed"
                        await asyncio.wait_for(
                            self.redis.setex(recovery_key, 300, "1"),
                            timeout=5.0,
                        )
                    except Exception as e:
                        logger.warning(
                            "Recovery marker setex failed for seq=%s run=%s: %s",
                            event["seq"],
                            run_id,
                            e,
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

        return event

    async def subscribe(self, run_id: str) -> AsyncGenerator[dict[str, Any], None]:
        """Subscribe to Redis channel for a run and yield JSON-decoded events."""
        if run_id not in self._authorized_runs:
            raise PermissionError(f"Unauthorized run_id: {run_id}")
        if not self.has_redis:
            async for event in self._subscribe_via_db(run_id):
                yield event
            return

        pubsub = self.redis.pubsub()
        channel = self._channel(run_id)

        await pubsub.subscribe(channel)
        logger.info("Sent SUBSCRIBE for Redis channel %s", channel)

        # AUDIT FIX: Drain the subscription confirmation from Redis before
        # starting to listen. Redis sends a "* 1\r\n$9\r\nsubscribe\r\n..." confirmation
        # on the socket. Without draining it, the first get_message() call in the
        # listen loop would return this confirmation as the first "event", causing
        # the frontend to receive a malformed frame. Drain with a small timeout
        # to avoid blocking indefinitely if the server doesn't confirm.
        try:
            confirm_msg = await asyncio.wait_for(
                pubsub.get_message(), timeout=5.0
            )
            logger.debug(
                "Redis subscription confirmed for channel %s: %s",
                channel,
                confirm_msg,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "Redis did not confirm subscription to %s within 5s — "
                "proceeding anyway; early events may be missed",
                channel,
            )

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

                if (event.get("seq", 0) > self._sub_last_seq.get(run_id, 0)):
                    self._sub_last_seq[run_id] = event["seq"]
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
        last_seq = self._sub_last_seq.get(run_id, 0)
        terminal_types = {"run:complete", "run:error"}
        terminal_statuses = {"completed", "failed", "cancelled"}

        while True:
            async with async_session() as session:
                rows = await RunStore.get_events_for_run(session, run_id, after_seq=last_seq)
                run = await RunStore.get_run(session, run_id)

            for row in rows:
                last_seq = row.seq
                self._sub_last_seq[run_id] = row.seq
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
_broker_lock = threading.Lock()


def get_event_broker() -> EventBroker:
    """Return the singleton EventBroker (created lazily). Thread-safe."""
    global _broker
    if _broker is None:
        with _broker_lock:
            if _broker is None:
                _broker = EventBroker()
    return _broker
