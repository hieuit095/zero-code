"""
Pydantic event schemas mirroring `src/types/runEvents.ts`.

Every server event follows the envelope:
    { "type": str, "runId": str | None, "seq": int, "timestamp": str, "data": dict }

Every client control message follows:
    { "type": str, "runId": str | None, "data": dict }
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, Field

from .domain import (
    AgentRole,
    AgentStatus,
    FileNode,
    LogLineType,
    QaReportIssue,
    Task,
    TaskStatus,
)

T = TypeVar("T", bound=BaseModel)


# ─── Envelopes ────────────────────────────────────────────────────────────────


class ServerEventEnvelope(BaseModel, Generic[T]):
    """Server → Client event wrapper. Matches RunEventEnvelope<TType, TData>."""

    type: str
    run_id: str | None = Field(default=None, alias="runId")
    seq: int
    timestamp: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    data: Any  # Typed via concrete subclasses

    model_config = {"populate_by_name": True}


class ClientEventEnvelope(BaseModel, Generic[T]):
    """Client → Server control message wrapper. Matches RunClientEventEnvelope<TType, TData>."""

    type: str
    run_id: str | None = Field(default=None, alias="runId")
    data: Any

    model_config = {"populate_by_name": True}


# ─── Server Event Payloads ────────────────────────────────────────────────────


class ConnectionReadyData(BaseModel):
    server_time: str = Field(alias="serverTime")
    supports_reconnect: bool = Field(default=True, alias="supportsReconnect")

    model_config = {"populate_by_name": True}


class RunCreatedData(BaseModel):
    status: Literal["queued"] = "queued"
    workspace_id: str = Field(alias="workspaceId")

    model_config = {"populate_by_name": True}


class RunStateData(BaseModel):
    status: str
    phase: str
    attempt: int = 0
    progress: int = 0


class RunCompleteData(BaseModel):
    status: Literal["completed"] = "completed"
    summary: str
    changed_files: list[str] = Field(default_factory=list, alias="changedFiles")
    qa_retries: int = Field(default=0, alias="qaRetries")
    duration_ms: int = Field(default=0, alias="durationMs")

    model_config = {"populate_by_name": True}


class RunErrorData(BaseModel):
    status: Literal["failed"] = "failed"
    error_code: str = Field(alias="errorCode")
    message: str
    last_known_task_id: str | None = Field(default=None, alias="lastKnownTaskId")

    model_config = {"populate_by_name": True}


class AgentStatusData(BaseModel):
    role: AgentRole
    state: AgentStatus
    activity: str | None = None
    current_task_id: str | None = Field(default=None, alias="currentTaskId")
    attempt: int = 0

    model_config = {"populate_by_name": True}


class AgentMessageStartData(BaseModel):
    message_id: str = Field(alias="messageId")
    role: AgentRole
    kind: str = "analysis"

    model_config = {"populate_by_name": True}


class AgentMessageDeltaData(BaseModel):
    message_id: str = Field(alias="messageId")
    delta: str

    model_config = {"populate_by_name": True}


class AgentMessageData(BaseModel):
    id: str
    agent: AgentRole
    agent_label: str = Field(alias="agentLabel")
    content: str
    timestamp: str

    model_config = {"populate_by_name": True}


class TaskSnapshotData(BaseModel):
    tasks: list[Task]


class TaskUpdateData(BaseModel):
    task_id: str = Field(alias="taskId")
    status: TaskStatus

    model_config = {"populate_by_name": True}


class FileTreeData(BaseModel):
    workspace_id: str = Field(alias="workspaceId")
    tree: list[FileNode]

    model_config = {"populate_by_name": True}


class DevStartEditData(BaseModel):
    file_name: str = Field(alias="fileName")
    task_id: str | None = Field(default=None, alias="taskId")

    model_config = {"populate_by_name": True}


class FileUpdateData(BaseModel):
    name: str
    path: str
    language: str
    content: str
    source_agent: AgentRole = Field(alias="sourceAgent")
    version: int = 1

    model_config = {"populate_by_name": True}


class DevStopEditData(BaseModel):
    file_name: str = Field(alias="fileName")

    model_config = {"populate_by_name": True}


class TerminalCommandData(BaseModel):
    command_id: str = Field(alias="commandId")
    agent: AgentRole
    command: str
    cwd: str = "/workspace"

    model_config = {"populate_by_name": True}


class TerminalOutputData(BaseModel):
    command_id: str = Field(alias="commandId")
    stream: Literal["stdout", "stderr"]
    text: str
    log_type: LogLineType = Field(alias="logType")
    attempt: int = 1

    model_config = {"populate_by_name": True}


class TerminalExitData(BaseModel):
    command_id: str = Field(alias="commandId")
    exit_code: int = Field(alias="exitCode")
    duration_ms: int = Field(alias="durationMs")

    model_config = {"populate_by_name": True}


class QaReportData(BaseModel):
    task_id: str = Field(alias="taskId")
    attempt: int
    status: Literal["failed"] = "failed"
    failing_command: str = Field(alias="failingCommand")
    exit_code: int = Field(alias="exitCode")
    summary: str
    raw_log_tail: list[str] = Field(default_factory=list, alias="rawLogTail")
    errors: list[QaReportIssue] = Field(default_factory=list)
    retryable: bool = True

    model_config = {"populate_by_name": True}


class QaPassedData(BaseModel):
    task_id: str = Field(alias="taskId")
    attempt: int
    commands: list[dict[str, Any]] = Field(default_factory=list)
    summary: str

    model_config = {"populate_by_name": True}


# ─── Client Event Payloads ────────────────────────────────────────────────────


class RunStartData(BaseModel):
    goal: str
    workspace_id: str = Field(default="repo-main", alias="workspaceId")
    agent_config: dict[str, dict[str, Any]] | None = Field(default=None, alias="agentConfig")

    model_config = {"populate_by_name": True}


class RunCancelData(BaseModel):
    reason: str = "user_cancelled"


class UserInterruptData(BaseModel):
    message: str


class WorkspaceRefreshData(BaseModel):
    reason: str = "manual_refresh"


# ─── Event Type Registry ─────────────────────────────────────────────────────

SERVER_EVENT_TYPES: set[str] = {
    "connection:ready",
    "run:created",
    "run:state",
    "run:complete",
    "run:error",
    "agent:status",
    "agent:message:start",
    "agent:message:delta",
    "agent:message",
    "task:snapshot",
    "task:update",
    "fs:tree",
    "dev:start-edit",
    "fs:update",
    "dev:stop-edit",
    "terminal:command",
    "terminal:output",
    "terminal:exit",
    "qa:report",
    "qa:passed",
}

CLIENT_EVENT_TYPES: set[str] = {
    "run:start",
    "run:cancel",
    "user:interrupt",
    "workspace:refresh",
}
