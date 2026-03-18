"""
Async SQLAlchemy engine and session for PostgreSQL.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ..config import get_settings

DATABASE_URL = get_settings().database_url
if not DATABASE_URL.startswith("postgresql+asyncpg://"):
    raise RuntimeError(
        "ZeroCode requires PostgreSQL via an asyncpg DATABASE_URL. "
        "Example: postgresql+asyncpg://zerocode:zerocode@localhost:5432/zerocode"
    )

engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    pool_pre_ping=True,
)

async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def init_db() -> None:
    """Create all tables (idempotent)."""
    from .models import Base

    async with engine.begin() as conn:
        await conn.execute(text("SELECT 1"))
        await conn.run_sync(Base.metadata.create_all)


async def get_session() -> AsyncSession:  # type: ignore[misc]
    """Dependency-injectable session factory."""
    async with async_session() as session:
        yield session  # type: ignore[misc]
