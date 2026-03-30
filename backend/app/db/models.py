# ==========================================
# Author: Hieu Nguyen - Codev Team
# Email: hieuit095@gmail.com
# Project: ZeroCode - Autonomous Multi-Agent IDE
# ==========================================
"""
SQLAlchemy ORM models for persistent run state.

Tables:
  - runs: Run lifecycle (id, goal, status, workspace_id, timestamps)
  - tasks: Planned tasks per run (id, run_id, label, status, acceptance_criteria)
  - event_log: Append-only event stream per run (id, run_id, seq, type, data)
"""

from datetime import UTC, datetime
from functools import lru_cache
from typing import Any, Optional

from cryptography.fernet import Fernet
from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from ..config import get_settings

import base64
import hashlib


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

    tasks: Mapped[list["TaskModel"]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
    )
    events: Mapped[list["EventLogModel"]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
    )


class TaskModel(Base):
    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("runs.id"),
        nullable=False,
    )
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
    __table_args__ = (
        UniqueConstraint("run_id", "seq", name="uq_event_log_run_seq"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("runs.id"),
        nullable=False,
        index=True,
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    type: Mapped[str] = mapped_column(String(64), nullable=False)
    timestamp: Mapped[str] = mapped_column(String(64), nullable=False)
    data: Mapped[Any] = mapped_column(JSON, nullable=False)

    run: Mapped["RunModel"] = relationship(back_populates="events")


class AuditLogModel(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("runs.id"),
        nullable=False,
        index=True,
    )
    agent_role: Mapped[str] = mapped_column(String(32), nullable=False)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    target: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )

    run: Mapped["RunModel"] = relationship()


@lru_cache(maxsize=1)
def _get_fernet() -> Fernet:
    secret = get_settings().api_key_secret
    if not secret:
        raise RuntimeError(
            "API_KEY_SECRET is required to encrypt and decrypt provider keys."
        )

    # Reject known placeholder values that would compromise key confidentiality
    _PLACEHOLDER_PATTERNS = (
        "your-", "change-me", "placeholder", "secret", "example",
    )
    secret_lower = secret.lower()
    if any(secret_lower.startswith(p) or p in secret_lower for p in _PLACEHOLDER_PATTERNS):
        raise ValueError(
            f"API_KEY_SECRET appears to be a placeholder value ('{secret}'). "
            "Set a strong, random value in backend/.env."
        )

    derived = hashlib.sha256(secret.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(derived))


def encrypt_key(plaintext: str) -> str:
    """Encrypt an API key for safe DB storage."""
    return _get_fernet().encrypt(plaintext.encode()).decode()


def decrypt_key(ciphertext: str) -> str:
    """Decrypt an API key from DB storage."""
    return _get_fernet().decrypt(ciphertext.encode()).decode()


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
    """Singleton table storing which model+provider each agent role uses."""

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
