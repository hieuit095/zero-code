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

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text
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
    total_cost: Mapped[float] = mapped_column(Float, default=0.0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
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


# ─── Encrypted API Key Vault ──────────────────────────────────────────────────

import os
from cryptography.fernet import Fernet
import base64
import hashlib

# Derive a Fernet key from an env-var secret (or generate per-process)
_API_KEY_SECRET = os.environ.get("API_KEY_SECRET", "")
if _API_KEY_SECRET:
    # Derive a 32-byte key from the secret via SHA-256 → base64
    _derived = hashlib.sha256(_API_KEY_SECRET.encode()).digest()
    _FERNET_KEY = base64.urlsafe_b64encode(_derived)
else:
    _FERNET_KEY = Fernet.generate_key()

_fernet = Fernet(_FERNET_KEY)


def encrypt_key(plaintext: str) -> str:
    """Encrypt an API key for safe DB storage."""
    return _fernet.encrypt(plaintext.encode()).decode()


def decrypt_key(ciphertext: str) -> str:
    """Decrypt an API key from DB storage."""
    return _fernet.decrypt(ciphertext.encode()).decode()


class APIKeyModel(Base):
    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    provider: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    encrypted_key: Mapped[str] = mapped_column(Text, nullable=False)
    label: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    base_url: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )


class LLMRoutingModel(Base):
    """
    Singleton table storing which model+provider each agent role uses.

    Only ONE row should exist (id=1). The API upserts this row.
    """
    __tablename__ = "llm_routing"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    leader_model: Mapped[str] = mapped_column(String(128), default="gpt-4o")
    leader_provider: Mapped[str] = mapped_column(String(64), default="openai")
    dev_model: Mapped[str] = mapped_column(String(128), default="gpt-4o")
    dev_provider: Mapped[str] = mapped_column(String(64), default="openai")
    qa_model: Mapped[str] = mapped_column(String(128), default="gpt-4o")
    qa_provider: Mapped[str] = mapped_column(String(64), default="openai")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

