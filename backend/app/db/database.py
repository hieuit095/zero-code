# ==========================================
# Author: Hieu Nguyen - Codev Team
# Email: hieuit095@gmail.com
# Project: ZeroCode - Autonomous Multi-Agent IDE
# ==========================================
"""
Async SQLAlchemy engine and session for PostgreSQL.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ..config import get_settings

DATABASE_URL = get_settings().database_url
if not (
    DATABASE_URL.startswith("postgresql+asyncpg://")
    or DATABASE_URL.startswith("sqlite+aiosqlite:///")
):
    raise RuntimeError(
        "ZeroCode requires either PostgreSQL via asyncpg or SQLite via aiosqlite. "
        "Examples: postgresql+asyncpg://zerocode:zerocode@localhost:5432/zerocode "
        "or sqlite+aiosqlite:///./e2e.db"
    )

_ENGINE_KWARGS: dict[str, object] = {
    "echo": False,
    "pool_pre_ping": not DATABASE_URL.startswith("sqlite+aiosqlite:///"),
}

if DATABASE_URL.startswith("sqlite+aiosqlite:///"):
    _ENGINE_KWARGS["connect_args"] = {"timeout": 30}

engine = create_async_engine(
    DATABASE_URL,
    **_ENGINE_KWARGS,
)

async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def init_db() -> None:
    """Create all tables (idempotent)."""
    from .models import Base

    try:
        async with engine.begin() as conn:
            await conn.execute(text("SELECT 1"))
            await conn.run_sync(Base.metadata.create_all)
    except OperationalError as exc:
        if (
            DATABASE_URL.startswith("sqlite+aiosqlite:///")
            and "already exists" in str(exc).lower()
        ):
            return
        raise


async def get_session() -> AsyncSession:  # type: ignore[misc]
    """Dependency-injectable session factory."""
    async with async_session() as session:
        yield session  # type: ignore[misc]
