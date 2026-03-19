/**
 * ==========================================
 * Author: Hieu Nguyen - Codev Team
 * Email: hieuit095@gmail.com
 * Project: ZeroCode - Autonomous Multi-Agent IDE
 * ==========================================
 */
/**
 * WebSocket and REST contract types for the run lifecycle described in `plan.md` section 3.
 *
 * Expected server envelope JSON shape:
 * {
 *   "type": "agent:status",
 *   "runId": "run_01JXYZ...",
 *   "seq": 42,
 *   "timestamp": "2026-03-16T05:20:14.221Z",
 *   "data": { ...event-specific payload... }
 * }
 *
 * Expected client control message JSON shape:
 * {
 *   "type": "run:cancel",
 *   "runId": "run_01JXYZ...",
 *   "data": { ...event-specific payload... }
 * }
 */

import type { AgentRole, FileNode, LogLineType, Task, TaskStatus } from './index';

// @ai-integration-point: Backend Type Mapping - Mirror these interfaces from future Pydantic schemas in `backend/app/schemas/events.py` so the frontend and backend share one event vocabulary.

export interface RunEventEnvelope<TType extends string, TData> {
  type: TType;
  runId: string | null;
  seq: number;
  timestamp: string;
  data: TData;
}

export interface RunClientEventEnvelope<TType extends string, TData> {
  type: TType;
  runId?: string;
  data: TData;
}

/**
 * `connection:ready` payload from `plan.md` section 3.4.
 *
 * Expected JSON payload:
 * {
 *   "serverTime": "2026-03-16T05:20:00.000Z",
 *   "supportsReconnect": true
 * }
 */
export interface ConnectionReadyData {
  serverTime: string;
  supportsReconnect: boolean;
}

/**
 * `run:created` payload from `plan.md` section 3.4.
 *
 * Expected JSON payload:
 * {
 *   "status": "queued",
 *   "workspaceId": "repo-main"
 * }
 */
export interface RunCreatedData {
  status: 'queued';
  workspaceId: string;
}

/**
 * `run:state` payload from `plan.md` section 3.4.
 *
 * Expected JSON payload:
 * {
 *   "status": "planning",
 *   "phase": "leader",
 *   "attempt": 0,
 *   "progress": 8
 * }
 */
export interface RunStateData {
  status: string;
  phase: string;
  attempt: number;
  progress: number;
}

/**
 * `run:complete` payload from `plan.md` section 3.4.
 *
 * Expected JSON payload:
 * {
 *   "status": "completed",
 *   "summary": "All QA checks passed after 2 dev iterations.",
 *   "changedFiles": ["src/hooks/useRunConnection.ts"],
 *   "qaRetries": 1,
 *   "durationMs": 332000
 * }
 */
export interface RunCompleteData {
  status: 'completed';
  summary: string;
  changedFiles: string[];
  qaRetries: number;
  durationMs: number;
}

/**
 * `run:error` payload from `plan.md` section 3.4.
 *
 * Expected JSON payload:
 * {
 *   "status": "failed",
 *   "errorCode": "MAX_RETRIES_EXCEEDED",
 *   "message": "QA still failed after 4 retry attempts.",
 *   "lastKnownTaskId": "task_qa_terminal_sync"
 * }
 */
export interface RunErrorData {
  status: 'failed';
  errorCode: string;
  message: string;
  lastKnownTaskId: string | null;
}

/**
 * `agent:status` payload from `plan.md` section 3.5.
 *
 * Expected JSON payload:
 * {
 *   "role": "dev",
 *   "state": "working",
 *   "activity": "Patching websocket reducer",
 *   "currentTaskId": "task_ws_transport",
 *   "attempt": 1
 * }
 */
export interface AgentStatusEventData {
  role: AgentRole;
  state: 'idle' | 'thinking' | 'working';
  activity: string | null;
  currentTaskId: string | null;
  attempt: number;
}

/**
 * `agent:message:start` payload from `plan.md` section 3.5.
 *
 * Expected JSON payload:
 * {
 *   "messageId": "msg_dev_001",
 *   "role": "dev",
 *   "kind": "analysis"
 * }
 */
export interface AgentMessageStartData {
  messageId: string;
  role: AgentRole;
  kind: 'analysis' | 'thought' | 'summary' | string;
}

/**
 * `agent:message:delta` payload from `plan.md` section 3.5.
 *
 * Expected JSON payload:
 * {
 *   "messageId": "msg_dev_001",
 *   "delta": "The current file store is reading from mockEditorFiles..."
 * }
 */
export interface AgentMessageDeltaData {
  messageId: string;
  delta: string;
}

/**
 * `agent:message` payload from `plan.md` section 3.5.
 *
 * Expected JSON payload:
 * {
 *   "id": "msg_dev_001",
 *   "agent": "dev",
 *   "agentLabel": "Dev",
 *   "content": "Replacing the mock editor map with reactive store-backed file content.",
 *   "timestamp": "05:20:12"
 * }
 */
export interface AgentMessageData {
  id: string;
  agent: AgentRole;
  agentLabel: string;
  content: string;
  timestamp: string;
}

/**
 * `task:snapshot` payload from `plan.md` section 3.6.
 *
 * Expected JSON payload:
 * {
 *   "tasks": [
 *     {
 *       "id": "task_ws_transport",
 *       "label": "Create frontend websocket transport layer",
 *       "status": "in-progress",
 *       "agent": "dev",
 *       "subtasks": ["Add typed event schema"]
 *     }
 *   ]
 * }
 */
export interface TaskSnapshotData {
  tasks: Task[];
}

/**
 * `task:update` payload from `plan.md` section 3.6.
 *
 * Expected JSON payload:
 * {
 *   "taskId": "task_ws_transport",
 *   "status": "completed"
 * }
 */
export interface TaskUpdateData {
  taskId: string;
  status: TaskStatus;
}

/**
 * `fs:tree` payload from `plan.md` section 3.7.
 *
 * Expected JSON payload:
 * {
 *   "workspaceId": "repo-main",
 *   "tree": [{ "id": "src", "name": "src", "type": "folder", "children": [] }]
 * }
 */
export interface FileTreeData {
  workspaceId: string;
  tree: FileNode[];
}

/**
 * `dev:start-edit` payload from `plan.md` section 3.7.
 *
 * Expected JSON payload:
 * {
 *   "fileName": "src/hooks/useRunConnection.ts",
 *   "taskId": "task_ws_transport"
 * }
 */
export interface DevStartEditData {
  fileName: string;
  taskId: string | null;
}

/**
 * `fs:update` payload from `plan.md` section 3.7.
 *
 * Expected JSON payload:
 * {
 *   "name": "src/hooks/useRunConnection.ts",
 *   "path": "src/hooks/useRunConnection.ts",
 *   "language": "typescript",
 *   "content": "import { useEffect } from 'react';",
 *   "sourceAgent": "dev",
 *   "version": 3
 * }
 */
export interface FileUpdateData {
  name: string;
  path: string;
  language: string;
  content: string;
  sourceAgent: AgentRole;
  version: number;
}

/**
 * `dev:stop-edit` payload from `plan.md` section 3.7.
 *
 * Expected JSON payload:
 * {
 *   "fileName": "src/hooks/useRunConnection.ts"
 * }
 */
export interface DevStopEditData {
  fileName: string;
}

/**
 * `terminal:command` payload from `plan.md` section 3.8.
 *
 * Expected JSON payload:
 * {
 *   "commandId": "cmd_001",
 *   "agent": "qa",
 *   "command": "npm run typecheck",
 *   "cwd": "/workspace"
 * }
 */
export interface TerminalCommandData {
  commandId: string;
  agent: AgentRole;
  command: string;
  cwd: string;
}

/**
 * `terminal:output` payload from `plan.md` section 3.8.
 *
 * Expected JSON payload:
 * {
 *   "commandId": "cmd_001",
 *   "stream": "stderr",
 *   "text": "src/hooks/useSimulation.ts(25,10): error TS6133...",
 *   "logType": "error",
 *   "attempt": 1
 * }
 */
export interface TerminalOutputData {
  commandId: string;
  stream: 'stdout' | 'stderr';
  text: string;
  logType: LogLineType;
  attempt: number;
}

/**
 * `terminal:exit` payload from `plan.md` section 3.8.
 *
 * Expected JSON payload:
 * {
 *   "commandId": "cmd_001",
 *   "exitCode": 2,
 *   "durationMs": 4320
 * }
 */
export interface TerminalExitData {
  commandId: string;
  exitCode: number;
  durationMs: number;
}

export interface QaReportIssue {
  kind: string;
  file: string;
  line: number;
  message: string;
}

/**
 * `qa:report` payload from `plan.md` section 3.9.
 *
 * Expected JSON payload:
 * {
 *   "taskId": "task_ws_transport",
 *   "attempt": 1,
 *   "status": "failed",
 *   "failingCommand": "npm run typecheck",
 *   "exitCode": 2,
 *   "summary": "TypeScript errors remain in the mock simulation layer.",
 *   "rawLogTail": ["src/hooks/useSimulation.ts(25,10): error TS6133..."],
 *   "errors": [{ "kind": "typescript", "file": "src/hooks/useSimulation.ts", "line": 25, "message": "..." }],
 *   "retryable": true
 * }
 */
export interface QaReportData {
  taskId: string;
  attempt: number;
  status: 'failed';
  failingCommand: string;
  exitCode: number;
  summary: string;
  rawLogTail: string[];
  errors: QaReportIssue[];
  retryable: boolean;
  scores?: Record<string, number>;
  failingDimensions?: string[];
}

/**
 * `qa:passed` payload from `plan.md` section 3.9.
 *
 * Expected JSON payload:
 * {
 *   "taskId": "task_ws_transport",
 *   "attempt": 2,
 *   "commands": [{ "command": "npm run typecheck", "exitCode": 0 }],
 *   "summary": "Transport layer changes are passing lint and typecheck."
 * }
 */
export interface QaPassedData {
  taskId: string;
  attempt: number;
  commands: Array<{
    command: string;
    exitCode: number;
  }>;
  summary: string;
  scores?: Record<string, number>;
}

export type ConnectionReadyEvent = RunEventEnvelope<'connection:ready', ConnectionReadyData>;
export type RunCreatedEvent = RunEventEnvelope<'run:created', RunCreatedData>;
export type RunStateEvent = RunEventEnvelope<'run:state', RunStateData>;
export type RunCompleteEvent = RunEventEnvelope<'run:complete', RunCompleteData>;
export type RunErrorEvent = RunEventEnvelope<'run:error', RunErrorData>;
export type AgentStatusEvent = RunEventEnvelope<'agent:status', AgentStatusEventData>;
export type AgentMessageStartEvent = RunEventEnvelope<'agent:message:start', AgentMessageStartData>;
export type AgentMessageDeltaEvent = RunEventEnvelope<'agent:message:delta', AgentMessageDeltaData>;
export type AgentMessageEvent = RunEventEnvelope<'agent:message', AgentMessageData>;
export type TaskSnapshotEvent = RunEventEnvelope<'task:snapshot', TaskSnapshotData>;
export type TaskUpdateEvent = RunEventEnvelope<'task:update', TaskUpdateData>;
export type FileTreeEvent = RunEventEnvelope<'fs:tree', FileTreeData>;
export type DevStartEditEvent = RunEventEnvelope<'dev:start-edit', DevStartEditData>;
export type FileUpdateEvent = RunEventEnvelope<'fs:update', FileUpdateData>;
export type DevStopEditEvent = RunEventEnvelope<'dev:stop-edit', DevStopEditData>;
export type TerminalCommandEvent = RunEventEnvelope<'terminal:command', TerminalCommandData>;
export type TerminalOutputEvent = RunEventEnvelope<'terminal:output', TerminalOutputData>;
export type TerminalExitEvent = RunEventEnvelope<'terminal:exit', TerminalExitData>;
export type QaReportEvent = RunEventEnvelope<'qa:report', QaReportData>;
export type QaPassedEvent = RunEventEnvelope<'qa:passed', QaPassedData>;

export type RunSocketServerEvent =
  | ConnectionReadyEvent
  | RunCreatedEvent
  | RunStateEvent
  | RunCompleteEvent
  | RunErrorEvent
  | AgentStatusEvent
  | AgentMessageStartEvent
  | AgentMessageDeltaEvent
  | AgentMessageEvent
  | TaskSnapshotEvent
  | TaskUpdateEvent
  | FileTreeEvent
  | DevStartEditEvent
  | FileUpdateEvent
  | DevStopEditEvent
  | TerminalCommandEvent
  | TerminalOutputEvent
  | TerminalExitEvent
  | QaReportEvent
  | QaPassedEvent;

/**
 * `run:start` payload from `plan.md` section 3.3.
 *
 * Expected JSON payload:
 * {
 *   "goal": "Add user interrupts and live file sync",
 *   "workspaceId": "repo-main",
 *   "agentConfig": {
 *     "tech-lead": { "model": "gpt-4o" },
 *     "dev": { "model": "gpt-4o" },
 *     "qa": { "model": "gpt-4o-mini" }
 *   }
 * }
 */
export interface RunStartData {
  goal: string;
  workspaceId: string;
  agentConfig?: Partial<Record<AgentRole, Record<string, unknown>>>;
}

/**
 * `run:cancel` payload from `plan.md` section 3.3.
 *
 * Expected JSON payload:
 * {
 *   "reason": "user_cancelled"
 * }
 */
export interface RunCancelData {
  reason: string;
}

/**
 * `user:interrupt` payload from `plan.md` section 3.3.
 *
 * Expected JSON payload:
 * {
 *   "message": "Stop touching auth flows and focus only on the editor transport layer."
 * }
 */
export interface UserInterruptData {
  message: string;
}

/**
 * `workspace:refresh` payload from `plan.md` section 3.3.
 *
 * Expected JSON payload:
 * {
 *   "reason": "manual_refresh"
 * }
 */
export interface WorkspaceRefreshData {
  reason: string;
}

export type RunStartClientEvent = RunClientEventEnvelope<'run:start', RunStartData>;
export type RunCancelClientEvent = RunClientEventEnvelope<'run:cancel', RunCancelData>;
export type UserInterruptClientEvent = RunClientEventEnvelope<'user:interrupt', UserInterruptData>;
export type WorkspaceRefreshClientEvent = RunClientEventEnvelope<'workspace:refresh', WorkspaceRefreshData>;

export type RunSocketClientEvent =
  | RunStartClientEvent
  | RunCancelClientEvent
  | UserInterruptClientEvent
  | WorkspaceRefreshClientEvent;

// @ai-integration-point: Contract Versioning - Add a shared `schemaVersion` field to both client and server envelopes once the backend event broker and Pydantic schemas are introduced.
