# Multi-Agent IDE Implementation Plan

## 1. Current State Analysis

### What is already implemented in the React codebase

- The frontend is a Vite + React + TypeScript app with Tailwind, Monaco Editor, xterm.js, and Zustand.
- The main layout is already close to the target IDE shell:
  - `Header` for goal input, run controls, and settings
  - `LeftSidebar` for file explorer and agent chatter
  - `RightWorkspace` for editor + terminal/tasks split view
- State is already separated into clean domains:
  - `agentStore.ts` for agent messages, statuses, tasks, and mock run progress
  - `fileStore.ts` for file tree, open tabs, active editor file, and AI control mode
  - `terminalStore.ts` for terminal output and streaming state
- The UI is intentionally wrapped behind transport hooks:
  - `useAgentConnection.ts`
  - `useFileSystem.ts`
  - `useTerminalStream.ts`
  - `useSimulation.ts`
- Many files already contain `@ai-integration-point` comments with placeholder event names such as:
  - `agent:status`
  - `agent:message`
  - `task:update`
  - `terminal:output`
  - `fs:update`
  - `dev:start-edit`
  - `dev:stop-edit`
  - `run:complete`
- The component structure is solid enough that we do not need a UI rewrite before backend work starts.

### What is still mock / simulated

- The app is frontend-only today. There is no FastAPI backend, no Nanobot integration, and no OpenHands integration.
- `useSimulation.ts` and `simulation/agentSimulation.ts` drive a scripted fake run.
- `mockData.ts` provides the file tree, chat feed, tasks, terminal logs, and editor file contents.
- The code editor is display-only for streamed AI changes; user edits are not persisted anywhere.
- Agent settings and API key settings are local component state only.
- The Generate flow in `Header.tsx` is still a local timeout, not a real run start.
- The file explorer is a virtual tree, not a real project filesystem.
- The terminal is output-only and only renders pre-seeded or simulated log lines.
- The skills panel is UI-only and not connected to any actual runtime capability map.

### Technical gaps that must be closed for the AI backend

- There is no transport layer for a real run lifecycle.
- File contents are not reactive Zustand state; they are read from a mutable in-memory map.
- There is no run/session model, reconnect flow, or snapshot replay strategy.
- There is no backend-owned source of truth for:
  - tasks
  - agent status
  - terminal streams
  - workspace files
  - run history
- There is no secure sandbox boundary yet. If we used Nanobot exactly as-is, it would default to local shell/file tools, which is not acceptable for the target architecture.
- There is no QA failure contract to feed structured defects back to the Dev agent.

### Current repo health

- The production build succeeds after installing dependencies.
- Typecheck and lint do not currently pass because the prototype has drift:
  - unused variables in mock settings/simulation files
  - `AgentMessage` typing mismatch in `agentSimulation.ts`
- The current frontend bundle is large because Monaco/xterm ship in the main chunk.
- None of the above blocks planning, but they should be cleaned up while Phase 1 is underway.

### Architectural conclusion

- The frontend is best treated as a strong UI prototype with deliberate backend seams already marked.
- Nanobot should be used as the per-agent reasoning/tool loop, not as the entire multi-agent workflow engine.
- The non-linear Leader -> Dev -> QA -> Dev -> QA loop should be implemented explicitly in backend orchestration code.
- OpenHands should be used only as the sandbox and execution substrate. The frontend must never call OpenHands directly.

## 2. System Architecture Diagram (Text-based)

```text
User
  |
  v
React + Vite Frontend
  - Header goal input
  - Monaco editor
  - xterm terminal
  - Tasks panel
  - Agent chatter
  |
  | WebSocket: live run events
  | REST: snapshots, settings, reconnect bootstrap
  v
FastAPI Backend
  - Run API
  - WebSocket gateway
  - Event broker
  - Run/session store
  - Config store
  |
  v
Custom Orchestrator State Machine
  - Leader agent wrapper
  - Developer agent wrapper
  - QA agent wrapper
  - Retry/termination policy
  - Structured defect reports
  |
  v
Nanobot Runtime
  - One Nanobot-backed agent profile per role
  - MCP-compatible tool layer
  - Progress callbacks / message bus
  |
  v
Custom Sandbox Tools
  - sandbox_list_files
  - sandbox_read_file
  - sandbox_write_file / apply_patch
  - sandbox_exec
  - sandbox_run_tests
  - sandbox_capture_logs
  |
  v
OpenHands SDK / Remote Workspace / Remote Agent Server
  - secure isolated workspace
  - file operations
  - terminal command execution
  - test execution
  - logs / artifacts
  |
  v
Sandbox Filesystem + Processes


Primary control loop
--------------------
1. Frontend sends goal
2. FastAPI creates run + sandbox session
3. Leader decomposes goal into tasks
4. Dev edits files through OpenHands-backed tools
5. QA executes commands/tests inside same sandbox
6. If QA fails:
     QA emits structured defect report
     -> Dev receives report directly
     -> Dev patches code
     -> QA retests
     -> repeat until pass / max retries / escalation
7. Leader receives pass/fail summary and decides next task
8. Backend streams every status, file change, and terminal event back to React
```

### Recommended boundary decisions

- FastAPI owns the run lifecycle and event schema.
- Nanobot owns agent prompting, tool calling, skills, and optional MCP tool access.
- OpenHands owns isolation and command/file execution.
- React owns rendering only; it should not invent run state locally.

## 3. API & WebSocket Contracts

### 3.1 Event envelope

Use a single envelope for every WebSocket frame:

```json
{
  "type": "agent:status",
  "runId": "run_01JXYZ...",
  "seq": 42,
  "timestamp": "2026-03-16T05:20:14.221Z",
  "data": {}
}
```

### 3.2 Recommended REST endpoints

#### `POST /api/runs`

Starts a new run and returns the stream URL.

Request:

```json
{
  "goal": "Build the first version of a multi-agent IDE backend",
  "workspaceId": "repo-main",
  "agentConfig": {
    "tech-lead": { "model": "gpt-4o", "systemPrompt": "..." },
    "dev": { "model": "gpt-4o", "systemPrompt": "..." },
    "qa": { "model": "gpt-4o-mini", "systemPrompt": "..." }
  },
  "limits": {
    "maxQaRetriesPerTask": 4,
    "maxRunMinutes": 30
  }
}
```

Response:

```json
{
  "runId": "run_01JXYZ...",
  "workspaceId": "repo-main",
  "status": "queued",
  "wsUrl": "/ws/runs/run_01JXYZ..."
}
```

#### `GET /api/runs/{runId}/snapshot`

Used on refresh/reconnect to recover the latest known state.

#### `POST /api/runs/{runId}/cancel`

Cancels the active run and all child QA/Dev retries.

#### `GET /api/workspaces/{workspaceId}/tree`

Returns the current filesystem tree.

#### `GET /api/workspaces/{workspaceId}/file?path=...`

Returns the latest full file content for editor rehydration.

#### `POST /api/config/agents`

Persists per-agent model/prompt settings.

### 3.3 Frontend -> backend WebSocket control messages

#### `run:start`

Use if you want to keep run start on the same socket instead of REST.

```json
{
  "type": "run:start",
  "data": {
    "goal": "Add user interrupts and live file sync",
    "workspaceId": "repo-main",
    "agentConfig": {
      "tech-lead": { "model": "gpt-4o" },
      "dev": { "model": "gpt-4o" },
      "qa": { "model": "gpt-4o-mini" }
    }
  }
}
```

#### `run:cancel`

```json
{
  "type": "run:cancel",
  "runId": "run_01JXYZ...",
  "data": {
    "reason": "user_cancelled"
  }
}
```

#### `user:interrupt`

For future "pause and steer" support.

```json
{
  "type": "user:interrupt",
  "runId": "run_01JXYZ...",
  "data": {
    "message": "Stop touching auth flows and focus only on the editor transport layer."
  }
}
```

#### `workspace:refresh`

```json
{
  "type": "workspace:refresh",
  "runId": "run_01JXYZ...",
  "data": {
    "reason": "manual_refresh"
  }
}
```

### 3.4 Backend -> frontend run lifecycle events

#### `connection:ready`

```json
{
  "type": "connection:ready",
  "runId": null,
  "seq": 1,
  "timestamp": "2026-03-16T05:20:00.000Z",
  "data": {
    "serverTime": "2026-03-16T05:20:00.000Z",
    "supportsReconnect": true
  }
}
```

#### `run:created`

```json
{
  "type": "run:created",
  "runId": "run_01JXYZ...",
  "seq": 2,
  "timestamp": "2026-03-16T05:20:01.000Z",
  "data": {
    "status": "queued",
    "workspaceId": "repo-main"
  }
}
```

#### `run:state`

```json
{
  "type": "run:state",
  "runId": "run_01JXYZ...",
  "seq": 3,
  "timestamp": "2026-03-16T05:20:03.000Z",
  "data": {
    "status": "planning",
    "phase": "leader",
    "attempt": 0,
    "progress": 8
  }
}
```

#### `run:complete`

```json
{
  "type": "run:complete",
  "runId": "run_01JXYZ...",
  "seq": 200,
  "timestamp": "2026-03-16T05:25:33.000Z",
  "data": {
    "status": "completed",
    "summary": "All QA checks passed after 2 dev iterations.",
    "changedFiles": ["src/hooks/useRunConnection.ts", "backend/app/ws.py"],
    "qaRetries": 1,
    "durationMs": 332000
  }
}
```

#### `run:error`

```json
{
  "type": "run:error",
  "runId": "run_01JXYZ...",
  "seq": 201,
  "timestamp": "2026-03-16T05:25:34.000Z",
  "data": {
    "status": "failed",
    "errorCode": "MAX_RETRIES_EXCEEDED",
    "message": "QA still failed after 4 retry attempts.",
    "lastKnownTaskId": "task_qa_terminal_sync"
  }
}
```

### 3.5 Backend -> frontend agent events

#### `agent:status`

```json
{
  "type": "agent:status",
  "runId": "run_01JXYZ...",
  "seq": 17,
  "timestamp": "2026-03-16T05:20:10.000Z",
  "data": {
    "role": "dev",
    "state": "working",
    "activity": "Patching websocket reducer",
    "currentTaskId": "task_ws_transport",
    "attempt": 1
  }
}
```

#### `agent:message:start`

```json
{
  "type": "agent:message:start",
  "runId": "run_01JXYZ...",
  "seq": 18,
  "timestamp": "2026-03-16T05:20:11.000Z",
  "data": {
    "messageId": "msg_dev_001",
    "role": "dev",
    "kind": "analysis"
  }
}
```

#### `agent:message:delta`

```json
{
  "type": "agent:message:delta",
  "runId": "run_01JXYZ...",
  "seq": 19,
  "timestamp": "2026-03-16T05:20:11.200Z",
  "data": {
    "messageId": "msg_dev_001",
    "delta": "The current file store is reading from mockEditorFiles..."
  }
}
```

#### `agent:message`

Emit the finalized message for the current UI feed.

```json
{
  "type": "agent:message",
  "runId": "run_01JXYZ...",
  "seq": 20,
  "timestamp": "2026-03-16T05:20:12.000Z",
  "data": {
    "id": "msg_dev_001",
    "agent": "dev",
    "agentLabel": "Dev",
    "content": "Replacing the mock editor map with reactive store-backed file content.",
    "timestamp": "05:20:12"
  }
}
```

### 3.6 Backend -> frontend task events

#### `task:snapshot`

```json
{
  "type": "task:snapshot",
  "runId": "run_01JXYZ...",
  "seq": 10,
  "timestamp": "2026-03-16T05:20:05.000Z",
  "data": {
    "tasks": [
      {
        "id": "task_ws_transport",
        "label": "Create frontend websocket transport layer",
        "status": "in-progress",
        "agent": "dev",
        "subtasks": [
          "Add typed event schema",
          "Replace simulation hook",
          "Wire stores to stream dispatcher"
        ]
      }
    ]
  }
}
```

#### `task:update`

```json
{
  "type": "task:update",
  "runId": "run_01JXYZ...",
  "seq": 44,
  "timestamp": "2026-03-16T05:20:22.000Z",
  "data": {
    "taskId": "task_ws_transport",
    "status": "completed"
  }
}
```

### 3.7 Backend -> frontend filesystem events

#### `fs:tree`

```json
{
  "type": "fs:tree",
  "runId": "run_01JXYZ...",
  "seq": 7,
  "timestamp": "2026-03-16T05:20:04.000Z",
  "data": {
    "workspaceId": "repo-main",
    "tree": [
      { "id": "src", "name": "src", "type": "folder", "children": [] }
    ]
  }
}
```

#### `dev:start-edit`

```json
{
  "type": "dev:start-edit",
  "runId": "run_01JXYZ...",
  "seq": 30,
  "timestamp": "2026-03-16T05:20:16.000Z",
  "data": {
    "fileName": "src/hooks/useRunConnection.ts",
    "taskId": "task_ws_transport"
  }
}
```

#### `fs:update`

For Phase 1, send full content snapshots. Later, optionally add patch events.

```json
{
  "type": "fs:update",
  "runId": "run_01JXYZ...",
  "seq": 31,
  "timestamp": "2026-03-16T05:20:16.200Z",
  "data": {
    "name": "src/hooks/useRunConnection.ts",
    "path": "src/hooks/useRunConnection.ts",
    "language": "typescript",
    "content": "import { useEffect } from 'react';",
    "sourceAgent": "dev",
    "version": 3
  }
}
```

#### `dev:stop-edit`

```json
{
  "type": "dev:stop-edit",
  "runId": "run_01JXYZ...",
  "seq": 36,
  "timestamp": "2026-03-16T05:20:20.000Z",
  "data": {
    "fileName": "src/hooks/useRunConnection.ts"
  }
}
```

### 3.8 Backend -> frontend terminal events

#### `terminal:command`

```json
{
  "type": "terminal:command",
  "runId": "run_01JXYZ...",
  "seq": 50,
  "timestamp": "2026-03-16T05:20:25.000Z",
  "data": {
    "commandId": "cmd_001",
    "agent": "qa",
    "command": "npm run typecheck",
    "cwd": "/workspace"
  }
}
```

#### `terminal:output`

```json
{
  "type": "terminal:output",
  "runId": "run_01JXYZ...",
  "seq": 51,
  "timestamp": "2026-03-16T05:20:25.100Z",
  "data": {
    "commandId": "cmd_001",
    "stream": "stderr",
    "text": "src/hooks/useSimulation.ts(25,10): error TS6133...",
    "logType": "error",
    "attempt": 1
  }
}
```

#### `terminal:exit`

```json
{
  "type": "terminal:exit",
  "runId": "run_01JXYZ...",
  "seq": 60,
  "timestamp": "2026-03-16T05:20:30.000Z",
  "data": {
    "commandId": "cmd_001",
    "exitCode": 2,
    "durationMs": 4320
  }
}
```

### 3.9 Backend -> frontend QA loop events

#### `qa:report`

This is the most important contract for the non-linear loop.

```json
{
  "type": "qa:report",
  "runId": "run_01JXYZ...",
  "seq": 61,
  "timestamp": "2026-03-16T05:20:30.200Z",
  "data": {
    "taskId": "task_ws_transport",
    "attempt": 1,
    "status": "failed",
    "failingCommand": "npm run typecheck",
    "exitCode": 2,
    "summary": "TypeScript errors remain in the mock simulation layer.",
    "rawLogTail": [
      "src/hooks/useSimulation.ts(25,10): error TS6133...",
      "src/simulation/agentSimulation.ts(133,20): error TS2345..."
    ],
    "errors": [
      {
        "kind": "typescript",
        "file": "src/hooks/useSimulation.ts",
        "line": 25,
        "message": "initialAgentMessages is declared but never read"
      }
    ],
    "retryable": true
  }
}
```

#### `qa:passed`

```json
{
  "type": "qa:passed",
  "runId": "run_01JXYZ...",
  "seq": 95,
  "timestamp": "2026-03-16T05:21:10.000Z",
  "data": {
    "taskId": "task_ws_transport",
    "attempt": 2,
    "commands": [
      { "command": "npm run typecheck", "exitCode": 0 },
      { "command": "npm run lint", "exitCode": 0 }
    ],
    "summary": "Transport layer changes are passing lint and typecheck."
  }
}
```

### 3.10 Internal backend contracts

The backend should model these explicitly even if they never leave the server:

#### `AgentTask`

```json
{
  "id": "task_ws_transport",
  "owner": "dev",
  "goal": "Create the frontend websocket transport layer",
  "acceptanceCriteria": [
    "Simulation is removable",
    "Stores are driven by websocket events",
    "Reconnect snapshot works"
  ],
  "status": "in-progress"
}
```

#### `DefectReport`

```json
{
  "taskId": "task_ws_transport",
  "attempt": 1,
  "summary": "Typecheck failed after patching.",
  "failingCommand": "npm run typecheck",
  "exitCode": 2,
  "errors": [],
  "rawLogTail": [],
  "retryable": true
}
```

The QA agent should emit `DefectReport` objects, and the Dev agent should consume them directly without going back through the Leader unless:

- retries exceed policy
- the defect implies architectural redesign
- the sandbox is broken
- the test signal is ambiguous

## 4. Implementation Phases

## Phase 1: Frontend Refactoring — ✅ DELIVERED

### Goal

Replace simulation-centric state with transport-centric state while preserving the current UI.

### Tasks

1. Introduce a typed event schema on the frontend.
   - Add `src/types/runEvents.ts`
   - Model every websocket frame as a discriminated union
2. Replace `useSimulation.ts` with a real transport hook.
   - Suggested file: `src/hooks/useRunConnection.ts`
   - Manage socket lifecycle, reconnect, heartbeat, and dispatch
3. Refactor stores so they accept server-owned data.
   - `agentStore`: remove mock-only run progress fields
   - `fileStore`: move file contents into reactive Zustand state
   - `terminalStore`: rely on backend-driven streaming flags
4. Preserve current UI component boundaries.
   - Keep `useAgentConnection`, `useFileSystem`, and `useTerminalStream` as abstraction layers
5. Make settings persist locally first.
   - Use a dedicated `settingsStore` with localStorage middleware
   - This lets the backend receive clean agent configs later
6. Keep the simulation only behind a dev-only adapter if needed.
   - Do not keep it as the main code path

### Acceptance criteria

- Clicking Generate starts a real connection path, not a timeout.
- Agent chatter, terminal output, task list, and editor contents can all be driven from websocket events.
- Reloading the page can recover a run snapshot from the backend.

### Notes

- This phase is mostly plumbing and data shape work, not visual redesign.
- The existing hook abstraction is the biggest frontend asset in this repo.

## Phase 2: Backend Setup — ✅ DELIVERED

### Goal

Stand up the minimal FastAPI service that can create a sandbox session, stream events, and expose workspace state.

### Recommended backend structure

```text
backend/
  app/
    main.py
    api/
      runs.py
      workspaces.py
      ws.py
    schemas/
      events.py
      runs.py
      workspace.py
    services/
      event_broker.py
      openhands_client.py
      run_store.py
    orchestrator/
      run_manager.py
```

### Tasks

1. Scaffold FastAPI with:
   - `/health`
   - `POST /api/runs`
   - `GET /api/runs/{runId}/snapshot`
   - `GET /api/workspaces/{workspaceId}/tree`
   - `GET /api/workspaces/{workspaceId}/file`
   - `/ws/runs/{runId}`
2. Create an event broker.
   - In-memory queue first
   - Later replaceable with Redis or Postgres-backed event log
3. Wrap OpenHands behind a service boundary.
   - `create_workspace()`
   - `list_tree()`
   - `read_file()`
   - `write_file()`
   - `exec_command()`
   - `stream_command_output()`
4. Keep backend credentials server-side only.
   - Agent model keys
   - OpenHands credentials
   - any future provider keys
5. Prove the sandbox integration before adding multi-agent logic.
   - Create a run
   - list files
   - read a file
   - execute `pwd` or `npm run typecheck`
   - stream logs to the frontend

### Acceptance criteria

- A frontend websocket can subscribe to a run and receive real backend events.
- A sandboxed workspace can be created and inspected through OpenHands.
- Terminal output can stream from the sandbox into the existing xterm panel.

### Important design rule

- Do not let the frontend call OpenHands directly.
- Do not let Nanobot tools operate on the host machine in production mode.

## Phase 3: The Brain

### Goal

Build the actual multi-agent orchestration loop using Nanobot-backed agents plus explicit backend state transitions.

### Core design choice

Use Nanobot as the execution runtime for each agent role, but build the Leader/Dev/QA workflow as custom orchestration code.

### Why this matters

- Nanobot gives us:
  - tool calling
  - MCP compatibility
  - progress callbacks
  - background subagent support
  - message bus patterns
- Nanobot does not, by itself, define this product's specific state machine:
  - task decomposition
  - retry policy
  - QA defect routing
  - escalation rules
  - IDE event streaming contracts

### Tasks

1. Define three agent profiles.
   - `leader_agent.py`
   - `dev_agent.py`
   - `qa_agent.py`
2. Replace Nanobot's default local shell/file behavior with custom sandbox tools.
   - `sandbox_list_files`
   - `sandbox_read_file`
   - `sandbox_apply_patch`
   - `sandbox_exec`
   - `sandbox_run_tests`
   - `sandbox_collect_artifacts`
3. Implement the run state machine.
   - `PLANNING`
   - `DELEGATING`
   - `DEVELOPING`
   - `VERIFYING`
   - `RETRYING`
   - `DONE`
   - `FAILED`
4. Implement the QA defect package.
   - QA must return structured defects, not just raw logs
5. Add retry and escalation policy.
   - Example:
     - retry same task up to 4 times
     - escalate to Leader on ambiguous failures or repeated regressions
6. Keep the same OpenHands workspace across Dev/QA iterations for a run.
   - This preserves edits and avoids rehydration cost

### Initial orchestration flow

```text
Leader receives user goal
  -> creates tasks + acceptance criteria
  -> assigns one task to Dev
Dev inspects files and edits through sandbox tools
  -> emits file updates
  -> hands task to QA
QA runs lint/typecheck/tests in sandbox
  -> if pass: emits qa:passed to Leader
  -> if fail: emits qa:report directly to Dev
Dev reads defect report and patches
QA retests
  -> repeat until pass or retry limit
Leader marks task complete and schedules next task
```

### Acceptance criteria

- The backend can complete one task end-to-end with at least one automated QA retry.
- Dev never executes directly on the host.
- QA can send defects back to Dev without restarting the entire run.

## Phase 4: Integration and Real-time Streaming

### Goal

Connect the live backend loop to the existing IDE panels and make the experience feel autonomous instead of request/response.

### Tasks

1. Wire backend events into the frontend stores.
   - `agent:status` -> agent status pills and activity bar
   - `agent:message` -> agent chatter feed
   - `task:update` -> tasks panel
   - `terminal:output` -> xterm
   - `fs:update` -> Monaco
2. Support reconnect and snapshot replay.
   - Browser refresh should not destroy the run view
3. Add user controls.
   - cancel run
   - refresh workspace tree
   - future interrupt message
4. Add backend-side event sequencing and frontend-side dedupe.
   - required for reliable real-time UX
5. Surface non-linear loop state clearly.
   - show attempt count
   - show "QA failed -> Dev retrying"
   - show active command and current file
6. Add artifact capture.
   - terminal logs
   - changed files
   - final summary
   - QA failure reports

### Acceptance criteria

- The editor updates while the Dev agent writes.
- The terminal streams live stdout/stderr from sandbox commands.
- The QA retry loop is visible in the UI without manual refresh.
- The run can be refreshed or re-opened from a snapshot.

### Nice-to-have after Phase 4

- persist runs and event logs in Postgres
- diff/patch visualization instead of full file snapshots
- per-command expandable terminal sessions
- user approvals for dangerous actions
- artifact download and replay

## 5. Immediate Next Steps

1. Create the frontend transport layer now.
   - Add `src/types/runEvents.ts`
   - Add `src/hooks/useRunConnection.ts`
   - Refactor `useSimulation.ts` callers to use typed socket events
   - Move file contents into Zustand state instead of `mockEditorFiles`

2. Scaffold the FastAPI backend now.
   - Create `backend/app/main.py`
   - Add `backend/app/api/ws.py`
   - Add `backend/app/schemas/events.py`
   - Add `backend/app/services/openhands_client.py`
   - Implement a stub run that streams `run:created`, `fs:tree`, and `terminal:output`

3. Implement the smallest real Leader -> Dev -> QA loop now.
   - One task only
   - One OpenHands workspace
   - Dev can inspect/read/write files through sandbox tools
   - QA can run `npm run typecheck`
   - If QA fails, send a structured `qa:report` back to Dev and retry once

## References

- OpenHands SDK docs: https://docs.openhands.dev/sdk
- OpenHands getting started: https://docs.openhands.dev/sdk/getting-started
- OpenHands agent delegation: https://docs.openhands.dev/sdk/guides/agent-delegation
- OpenHands task tool set: https://docs.openhands.dev/sdk/guides/task-tool-set
- OpenHands build your own agent server: https://docs.openhands.dev/sdk/agent-server/build-your-own-agent-server
- OpenHands remote workspace backends: https://docs.openhands.dev/sdk/workspace/backends
- Nanobot repository: https://github.com/HKUDS/nanobot
