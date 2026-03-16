"""
SQLAlchemy ORM models for persistent run state.

Tables:
  - runs: Run lifecycle (id, goal, status, workspace_id, timestamps)
  - tasks: Planned tasks per run (id, run_id, label, status, acceptance_criteria)
  - event_log: Append-only event stream per run (id, run_id, seq, type, data)

NOTE: No `from __future__ import annotations` — SQLAlchemy's declarative
mapping requires concrete type objects for Mapped[] resolution.
"""

from datetime import UTC, datetime
from typing import Any, Optional

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class RunModel(Base):
    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    goal: Mapped[str] = mapped_column(Text, nullable=False)
    workspace_id: Mapped[str] = mapped_column(String(128), default="repo-main")
    status: Mapped[str] = mapped_column(String(32), default="queued")
    phase: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    tasks: Mapped[list["TaskModel"]] = relationship(back_populates="run", cascade="all, delete-orphan")
    events: Mapped[list["EventLogModel"]] = relationship(back_populates="run", cascade="all, delete-orphan")


class TaskModel(Base):
    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(64), ForeignKey("runs.id"), nullable=False)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending")
    agent: Mapped[str] = mapped_column(String(32), default="dev")
    acceptance_criteria: Mapped[Optional[Any]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )

    run: Mapped["RunModel"] = relationship(back_populates="tasks")


class EventLogModel(Base):
    __tablename__ = "event_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(64), ForeignKey("runs.id"), nullable=False, index=True)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    type: Mapped[str] = mapped_column(String(64), nullable=False)
    timestamp: Mapped[str] = mapped_column(String(64), nullable=False)
    data: Mapped[Any] = mapped_column(JSON, nullable=False)

    run: Mapped["RunModel"] = relationship(back_populates="events")


class AuditLogModel(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(64), ForeignKey("runs.id"), nullable=False, index=True)
    agent_role: Mapped[str] = mapped_column(String(32), nullable=False)
    action: Mapped[str] = mapped_column(String(32), nullable=False)  # read_file, write_file, exec
    target: Mapped[str] = mapped_column(Text, nullable=False)         # file path or command
    status: Mapped[str] = mapped_column(String(16), nullable=False)   # allowed, blocked
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )

    run: Mapped["RunModel"] = relationship()

