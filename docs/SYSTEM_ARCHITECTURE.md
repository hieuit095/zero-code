# System Architecture — Flight Manual

> **Audience:** Future maintainers, on-call engineers, security reviewers.
> **Last Updated:** 2026-03-18 — OpenSandbox migration (replacing OpenHands SDK pseudo-sandbox with true Docker containerization).

---

## 1. System Topology

Zero-Code runs as **two independent OS processes** sharing state exclusively through PostgreSQL and Redis. Neither process holds authoritative in-memory state.

```
┌─────────────────────────────────────────────────────────────────────┐
│  PROCESS 1: FastAPI API Server                                      │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────────────────┐  │
│  │ REST API     │  │ WebSocket    │  │ MCP Facade (/internal/mcp)│  │
│  │ /api/runs/*  │  │ /ws/runs/:id │  │ read_file / write_file    │  │
│  │              │  │              │  │ exec (JWT-protected)      │  │
│  └──────────────┘  └──────┬───────┘  └───────────────────────────┘  │
│                           │ subscribes                               │
└───────────────────────────┼─────────────────────────────────────────┘
                            │
                    ┌───────▼───────┐
                    │  Redis 6+     │
                    │  • Pub/Sub    │  ← events flow Worker → API → WS
                    │  • LPUSH/BRPOP│  ← task queue for run dispatch
                    └───────┬───────┘
                            │
┌───────────────────────────┼─────────────────────────────────────────┐
│  PROCESS 2: Background Worker (python -m worker)                    │
│  ┌──────────────────────────────────────────────────────────────┐    │
│  │ RunManager.execute_run()                                     │    │
│  │ Leader Agent → Dev Agent → QA Agent (retry loop)             │    │
│  │ Publishes events to Redis, persists state to PostgreSQL      │    │
│  └──────────────────────────────────────────────────────────────┘    │
│                                                                     │
│  CRASH SAFETY: On unhandled exception, worker writes FAILED to      │
│  DB AND broadcasts run:error to Redis so the UI is notified.        │
└───────────────────────────┬─────────────────────────────────────────┘
                            │
                    ┌───────▼───────┐
                    │  PostgreSQL   │  ← Single Source of Truth
                    │  (SQLAlchemy) │     runs, tasks, events, audit_log
                    └───────────────┘
```

### Critical Invariant: No In-Memory State
Neither process maintains authoritative state in dictionaries or sets. All reads/writes go through `RunStore` → SQLAlchemy. The `_runs` dict and `_active_runs` set were eliminated during the split-brain remediation.

---

## 2. State Management

| Store | Role | Durability |
|-------|------|------------|
| **PostgreSQL** | Single source of truth for run status, tasks, events, audit logs | Persistent |
| **Redis Pub/Sub** | Ephemeral event bus — Worker publishes, API subscribes and forwards to WS | Volatile |
| **Redis Queue** (`pending_runs`) | FIFO dispatch queue — API enqueues `run_id`, Worker dequeues | Volatile |

### DB-Before-Emit Ordering
All task status transitions follow a strict sequence:
1. `_persist_task_status()` — commit to PostgreSQL
2. `_emit("task:update")` — publish to Redis

This guarantees that if the frontend fetches a REST snapshot during reconnection, the database already reflects the latest state.

### Frontend Hydration Queue
When the WebSocket reconnects after a drop, Redis Pub/Sub events fired during the gap are lost. The frontend recovers via:

1. `socket.onopen` sets `isHydratingRef = true` (gate ON)
2. Fetches `GET /api/runs/:id/snapshot` from REST
3. Applies snapshot to Zustand stores
4. Sets `isHydratingRef = false` (gate OFF)
5. Flushes `pendingEventsRef[]` — replays queued WS events that arrived during the fetch

While the gate is ON, `socket.onmessage` pushes events into the queue instead of dispatching them. After snapshot applies, queued events (which are **newer** than the snapshot) are replayed in order.

---

## 3. The Brains & The Muscle

### The Brains: Nanobot Agents
Nanobot instances (Leader, Dev, QA) drive cognition and workflow. They communicate **exclusively** via the JWT-authenticated MCP HTTP facade at `/internal/mcp/*`. They have **zero** direct access to the host filesystem or shell.

| Agent | Role | MCP Tools Used | Model Tier |
|-------|------|----------------|------------|
| **Leader** | Decomposes goals into tasks; provides Mentorship debugging when Dev fails 2 attempts | `read_file`, `exec` | High-cost, high-reasoning (e.g., Gemini 3.1 Pro, GPT-4o) |
| **Dev** | Writes code to satisfy task acceptance criteria | `read_file`, `write_file`, `exec` | Low-cost, high SWE-Bench (e.g., Minimax m2.5, DeepSeek) |
| **QA** | Runs linters, typecheckers, tests; outputs 4-dimensional scored JSON | `read_file`, `exec` | Mid-cost, high-logic (e.g., GLM 5, Claude 3.5 Sonnet) |

**LLM Economic Routing:** Model selection is configured per-run via the `LLMRoutingModel` database table and the Settings UI. API keys are Fernet-encrypted in `APIKeyModel`. The Leader's expensive model is invoked only twice per task at most: once for planning and once for mentorship (if needed).

### The Muscle: OpenSandbox (Alibaba)
The MCP facade translates Nanobot tool calls into physical OpenSandbox container operations:

| MCP Endpoint | OpenSandbox API | Description |
|-------------|----------------|-------------|
| `POST /internal/mcp/read_file` | `sandbox.files.read_file(path)` | Read file from Docker container |
| `POST /internal/mcp/write_file` | `sandbox.files.write_files([WriteEntry(...)])` | Write file inside Docker container |
| `POST /internal/mcp/exec` | `sandbox.commands.run(command)` | Execute shell command inside Docker container |

**Critical architectural change (2026-03-18):** The previous OpenHands `TerminalExecutor`-based pseudo-sandbox (which relied on host-side `_jail_path()` string jailing) has been completely replaced by Alibaba OpenSandbox. Each workspace now runs inside a **real Docker container** provisioned by `Sandbox.create()`. All file and command operations execute inside the container — there are zero host-side `subprocess`, `open()`, or `os.scandir()` calls.

There is **no subprocess fallback**. If the SDK is unavailable, `SandboxUnavailableError` is raised.

---

## 4. Security Protocols

### 4.1 Container-Based Isolation (OpenSandbox)
- Each workspace runs inside an isolated Docker container managed by Alibaba OpenSandbox.
- The container boundary IS the jail — there is no host-side path resolution needed.
- The previous `_jail_path()` function (which used `os.path.realpath()` to check symlink escapes) has been **removed** since the container boundary provides absolute isolation.
- Agents cannot access, modify, or escape to the host filesystem under any circumstances.

### 4.2 JWT MCP Facade (12-Hour Lifecycle)
- Every MCP endpoint requires a JWT Bearer token.
- Tokens are generated by `RunManager` with a **12-hour TTL** (720 minutes), scoped to a single `run_id`.
- The secret (`MCP_JWT_SECRET`) is loaded from `.env` via `pydantic-settings`. Both processes share the same secret.
- Run-active validation is performed against the **database**, not in-memory.

### 4.3 Command Blocklist (`shlex`-based)
- `CommandPolicy.check()` parses commands using `shlex.split()` to defeat obfuscation.
- Blocks destructive base commands: `rm -rf`, `mkfs`, `dd`, piped destructive chains.
- Role-scoped: QA agents have a narrower allowlist than Dev agents.

### 4.4 QA Internal Error Isolation
- If the QA agent crashes due to infrastructure failure (MCP timeout, SDK crash), it returns `kind="internal"`.
- The orchestrator detects this flag and **aborts the run** with `INTERNAL_ERROR` instead of escalating to the Leader agent for replanning.

---

## 5. Orchestration State Machine (Mentorship-Enabled)

```
QUEUED → PLANNING → DELEGATING → DEVELOPING → VERIFYING
                                      ↑            ↓
                                      └── RETRYING ─┘  (Attempt 2)
                                      ↑            ↓
                                      └── LEADER_REVIEW → DEVELOPING (Attempt 3, mentored)

    Mentored attempt fails → ESCALATION → Leader replans (max 2)
    Replans exhausted      → FAILED
    Internal QA crash      → ABORTED (no replan)
    All tasks pass         → COMPLETED
```

### TaskDelegator Mentorship Interception
After Attempt 2 fails QA, `TaskDelegator.execute()` intercepts the loop and calls `_delegate_to_leader_mentor()`. The Leader agent runs in **Mentorship Mode** (using `LEADER_MENTORSHIP_PROMPT`), reads `critique_report.md` and the broken source files, and outputs architectural guidance into `leader_guidance.md`. The Dev agent then receives a final Attempt 3 with the guidance injected directly into its prompt.

The `LLMSummarizingCondenser` (configured with `max_size=10, keep_first=2`) prevents token explosion during the mentorship phase by squashing older conversation events while preserving the system prompt and the most recent interactions.

### Frontend Hydration & QA Dimensional Scores
Both features are **fully integrated**:
- Frontend hydration uses the `isHydratingRef` gate to queue WS events during REST snapshot fetch.
- QA dimensional scores (Code Quality, Requirements, Robustness, Security) are displayed in `QaRetryIndicator` and included in `qa:report` / `qa:passed` event payloads.

The task loop uses `while task_idx < len(tasks)` with `tasks.extend(new_tasks)` for safe in-place list mutation. The original `for/enumerate` pattern was replaced to prevent the iterator void bug.
