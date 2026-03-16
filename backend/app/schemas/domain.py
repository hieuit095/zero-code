"""
Shared domain models mirroring `src/types/index.ts`.

These models are used across event schemas, the run manager, and the OpenHands client.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Optional

from pydantic import BaseModel


class AgentRole(StrEnum):
    TECH_LEAD = "tech-lead"
    DEV = "dev"
    QA = "qa"


class AgentStatus(StrEnum):
    IDLE = "idle"
    THINKING = "thinking"
    WORKING = "working"


class TaskStatus(StrEnum):
    COMPLETED = "completed"
    IN_PROGRESS = "in-progress"
    PENDING = "pending"


class LogLineType(StrEnum):
    COMMAND = "command"
    SUCCESS = "success"
    WARN = "warn"
    ERROR = "error"
    INFO = "info"
    OUTPUT = "output"
    CURSOR = "cursor"
    BLANK = "blank"


class Task(BaseModel):
    id: str
    label: str
    status: TaskStatus
    agent: AgentRole
    subtasks: list[str] | None = None


class FileNode(BaseModel):
    id: str
    name: str
    type: str  # "file" | "folder"
    language: str | None = None
    children: list[FileNode] | None = None


class QaReportIssue(BaseModel):
    kind: str
    file: str
    line: int
    message: str
