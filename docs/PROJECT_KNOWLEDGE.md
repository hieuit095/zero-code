# PROJECT_KNOWLEDGE.md

Treat this file as the operational source of truth for AI-assisted work in this repository. Synthesize changes through this architecture first. If a convenient implementation conflicts with this document, follow this document.

This file is derived from `plan.md` and `deployment-plan.md`. Keep those documents aligned if this file changes.

## 1. Project Vision & Core Loop

- Build a **Multi-Agent IDE that eliminates verification fatigue**.
- Optimize for an **autonomous, self-correcting loop**, not a one-shot code generator.
- Reduce the user's manual burden of: write code -> run checks -> inspect logs -> retry -> re-verify.
- Preserve the product's defining behavior: the system must verify its own work inside a sandbox and fix itself when verification fails.
- Implement the workflow as a **non-linear execution loop**, not a linear chain.

**Canonical execution loop**

1. **Leader (Planner)** receives the user goal.
2. **Leader** decomposes the goal into explicit tasks with acceptance criteria.
3. **Dev (Coder)** inspects the repository and edits code inside the sandbox.
4. **QA (Tester in Sandbox)** runs lint, typecheck, tests, and targeted verification inside the same sandbox.
5. If QA passes, return the result to **Leader** for task completion and next-task planning.
6. If QA fails, QA must emit a structured **`qa:report`** directly to **Dev**.
7. **Dev (Fixer)** must patch the code using the QA defect report.
8. **QA (Retest)** must re-run verification inside the same sandbox.
9. Repeat **Dev -> QA -> Dev -> QA** until the task passes, retry limits are exceeded, or escalation is required.

**Escalate back to Leader only when**

- retries exceed policy
- the defect implies architectural redesign
- the sandbox is broken or inconsistent
- the QA signal is ambiguous

**Preserve these loop invariants**

- Keep **Dev and QA in the same run-scoped workspace** so edits and test context persist across retries.
- Make the retry loop visible in the UI with attempt counts, current task, active file, and active command.
- Require QA to produce structured failure data, not only raw logs.
- Treat the Leader as the planner and escalation point, not the relay for every QA failure.

## 2. Technology Stack & System Boundaries

**Frontend**

- Use **React + Vite** for the UI shell.
- Use **Zustand** for client-side view state.
- Use **Monaco Editor** for code editing and file visualization.
- Use **Xterm.js** for streamed terminal output.
- Treat the frontend as a **rendering client** for backend-owned run state.

**Backend / Orchestrator**

- Use **Python + FastAPI** for REST APIs, WebSockets, run lifecycle management, snapshots, and settings persistence.
- Let FastAPI own:
  - run creation and cancellation
  - websocket event streaming
  - snapshot recovery
  - event sequencing
  - retry and escalation policy
  - canonical run state

**Agent Framework**

- Use **Nanobot** for per-agent reasoning, prompting, skill usage, and MCP tool consumption.
- Create one Nanobot-backed role profile per agent:
  - Leader
  - Dev
  - QA

**Execution Sandbox**

- Use **OpenHands SDK** as the execution substrate.
- Expose OpenHands to agents **only through a run-scoped HTTP MCP service**.
- Treat the sandbox MCP facade as the native tool surface for file operations, patching, command execution, tests, logs, and artifacts.

**Canonical control path**

`React UI -> FastAPI Orchestrator -> Run State Machine -> Nanobot Role Agents -> Sandbox MCP Facade -> OpenHands Workspace`

**Boundary ownership**

- **React** owns rendering and user interaction only.
- **FastAPI** owns run orchestration and event contracts.
- **Nanobot** owns agent cognition and tool invocation.
- **Sandbox MCP** owns the safe tool interface exposed to agents.
- **OpenHands** owns isolated filesystem and process execution.

## 3. Strict Anti-Patterns & Hard Rules (CRITICAL)

- **Rule 1:** The React frontend **MUST NEVER** interact directly with OpenHands or the MCP layer.
- **Rule 2:** Nanobot agents **MUST NEVER** use local host shell or local filesystem tools in production. They must use only the sandbox tools exposed through the OpenHands MCP facade.
- **Rule 3:** Do **not** use Nanobot as the multi-agent workflow engine. The non-linear **Leader -> Dev -> QA -> Dev -> QA** loop must be implemented explicitly in FastAPI backend orchestration code.

**Additional hard rules**

- Do **not** let the frontend invent canonical run state locally. The backend is the source of truth.
- Do **not** bypass FastAPI when introducing new run lifecycle behavior.
- Do **not** expose sandbox MCP endpoints publicly. Keep them private, internal, authenticated, and run-scoped.
- Do **not** let QA failures collapse into raw terminal text only. Always emit a structured defect package.
- Do **not** create a fresh sandbox for each Dev/QA retry unless the orchestrator is explicitly recovering from sandbox failure.
- Do **not** couple the frontend directly to OpenHands SDK semantics, raw workspace APIs, or ad hoc agent prompt behavior.
- Do **not** let production agent configs include permissive host tools "for convenience."
- Do **not** change websocket event names or payload shapes casually. Event contracts are product contracts.
- Do **not** remove append-only sequencing from event streams. Reconnect, replay, and dedupe depend on it.
- Do **not** move credentials, provider keys, or OpenHands secrets into the frontend.

## 4. AI Coding Guidelines & Formatting

- Use **`// @ai-integration-point`** in JavaScript or TypeScript when writing stub code, transport seams, websocket dispatchers, store reducers, or frontend/backend connection points.
- Use **`# @ai-integration-point`** in Python when writing orchestrator seams, API stubs, sandbox adapters, event publishers, or state-machine transitions.
- Prefer extending existing integration markers over inventing new comment conventions.
- Write code so the architectural seam is obvious to future agents.

**When modifying event-driven code**

- Follow the defined JSON websocket envelope exactly:
  - `type`
  - `runId`
  - `seq`
  - `timestamp`
  - `data`
- Preserve strict adherence to the existing frontend-to-backend control messages too, especially:
  - `run:start`
  - `run:cancel`
  - `user:interrupt`
  - `workspace:refresh`
- Preserve strict adherence to the existing event names, especially:
  - `connection:ready`
  - `agent:status`
  - `agent:message:start`
  - `agent:message:delta`
  - `agent:message`
  - `task:snapshot`
  - `task:update`
  - `fs:tree`
  - `fs:update`
  - `dev:start-edit`
  - `dev:stop-edit`
  - `terminal:command`
  - `terminal:output`
  - `terminal:exit`
  - `qa:report`
  - `qa:passed`
  - `run:created`
  - `run:state`
  - `run:complete`
  - `run:error`
- Update backend schemas, frontend TypeScript event unions, websocket handlers, Zustand reducers, and snapshot replay logic together.
- Keep websocket events append-only and sequence-numbered for replay and dedupe safety.
- Prefer full file snapshots in `fs:update` during early implementation. Do not prematurely optimize to diffs if it adds instability.

**When modifying QA contracts**

- Treat **`qa:report`** as the key contract for the self-correcting loop.
- Require structured QA data such as:
  - `taskId`
  - `attempt`
  - `status`
  - `failingCommand`
  - `exitCode`
  - `summary`
  - `rawLogTail`
  - `errors`
  - `retryable`
- Route retryable QA failures directly to Dev without forcing the Leader to re-plan the entire task.

**When modifying backend orchestration**

- Model explicit run states such as:
  - `PLANNING`
  - `DELEGATING`
  - `DEVELOPING`
  - `VERIFYING`
  - `RETRYING`
  - `DONE`
  - `FAILED`
- Keep retry policy, escalation policy, and cancellation behavior inside backend orchestration code.
- Preserve snapshot recovery and reconnect semantics whenever run state changes.

## 5. Backend and Sandbox Implementation Directives

- Keep FastAPI as the owner of run lifecycle APIs and websocket entrypoints.
- Wrap OpenHands behind service interfaces such as:
  - `create_workspace()`
  - `destroy_workspace()`
  - `list_tree()`
  - `read_file()`
  - `write_file()`
  - `execute_command()`
  - `stream_command_output()`
- Prefer a dedicated internal `sandbox-mcp` service instead of embedding ad hoc sandbox calls in agent prompts.
- Expose only the safe MCP tool subset agents need, such as:
  - `workspace_get_tree`
  - `workspace_read_file`
  - `workspace_write_file`
  - `workspace_apply_patch`
  - `workspace_exec`
  - `workspace_run_test`
  - `workspace_get_log_tail`
- Enforce tool allowlists per role with run-scoped authentication.
- Keep all service-to-service traffic private and authenticated.

## 6. Frontend Integration Directives

- Preserve the existing React shell and component boundaries unless a change is required by the architecture.
- Replace simulation-driven flows with transport-driven flows.
- Keep abstraction layers such as frontend hooks and stores, but make them consume backend-owned state.
- Drive editor contents, task updates, agent chatter, and terminal output from backend events instead of mock data.
- Support refresh and reconnect by rehydrating from backend snapshots.
- Surface the non-linear QA retry loop clearly in the UI instead of flattening it into a generic "loading" state.

## 7. Delivery Priorities

- First, stabilize the frontend shell and replace simulation with typed transport.
- Second, scaffold the FastAPI backend and websocket contracts.
- Third, prove OpenHands workspace creation, file IO, and command execution behind a backend service.
- Fourth, expose the sandbox through MCP and connect Nanobot to it.
- Fifth, ship the smallest real Dev -> QA vertical slice.
- Sixth, add the full Leader -> Dev -> QA loop with structured retries and escalation.

## 8. Decision Filter for Future AI Sessions

- If a proposed change weakens the sandbox boundary, reject it.
- If a proposed change moves orchestration logic into the frontend, reject it.
- If a proposed change relies on host shell or host filesystem access for production agents, reject it.
- If a proposed change bypasses typed event contracts, reject it.
- If a proposed change makes QA less structured or less autonomous, reject it.
- If a proposed change strengthens the self-correcting loop, backend-owned state, sandbox safety, and event contract clarity, prefer it.
