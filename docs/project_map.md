# ZeroCode — Project Map

> **Purpose**: AI-friendly reference for navigating the codebase.
> **Rule**: If a file's role is unclear, check `docs/PROJECT_KNOWLEDGE.md` for architectural context.

---

## Root (`/`)

```
├── index.html                 # Vite HTML entry point
├── vite.config.ts             # Vite bundler config
├── package.json               # Frontend dependencies (React, Zustand, Monaco, Xterm.js)
├── tsconfig.json              # TypeScript project references
├── tsconfig.app.json          # TS config for app code
├── tsconfig.node.json         # TS config for Node/Vite tooling
├── tailwind.config.js         # Tailwind CSS theme
├── postcss.config.js          # PostCSS → Tailwind pipeline
├── eslint.config.js           # ESLint flat config
├── Dockerfile                 # Production frontend build (Nginx)
├── setup.sh                   # One-click dev setup (macOS/Linux)
├── setup.bat                  # One-click dev setup (Windows)
├── .env.example               # Root env template (Redis, LLM keys, JWT secret, CORS)
├── .env                       # Local env overrides (git-ignored)
├── README.md                  # Getting Started + Architecture overview
└── OPENSANDBOX_AUDIT_AND_BLUEPRINT.md  # Audit findings & scaling roadmap
```

---

## `src/` — Frontend (React + Vite + TypeScript)

The frontend is a **rendering client**. It owns zero canonical state — all run/task/agent state is backend-owned and streamed via WebSockets.

```
src/
├── main.tsx                   # ReactDOM.createRoot entry
├── App.tsx                    # Root layout: resizable panels (sidebar, editor, terminal, agents)
├── index.css                  # Global styles
├── vite-env.d.ts              # Vite type shims
│
├── components/                # ── UI Components ──────────────────────────
│   ├── Header.tsx             # Top bar: run controls, goal input, status indicator
│   ├── LeftSidebar.tsx        # Icon rail: file explorer / tasks / agents toggle
│   ├── RightWorkspace.tsx     # Right column container (editor + terminal)
│   ├── FileExplorer.tsx       # Tree view of /workspace files (driven by fs:tree events)
│   ├── CodeEditorPanel.tsx    # Monaco editor panel (content from fs:update events)
│   ├── EditorTabBar.tsx       # Open-file tab management
│   ├── TasksPanel.tsx         # Task list with status badges (task:snapshot / task:update)
│   ├── TerminalPanel.tsx      # Xterm.js terminal (terminal:output streaming)
│   ├── TerminalTaskPanel.tsx  # Per-task terminal grouping
│   ├── AgentChatter.tsx       # Agent message timeline (agent:message events)
│   ├── AgentSkills.tsx        # Agent skills / capabilities display
│   └── settings/              # ── Settings UI ────────────────────────────
│       ├── SettingsModal.tsx   # Modal shell with tab navigation
│       ├── APIFeedSetupPage.tsx# Multi-provider LLM key management UI
│       └── AgentSetupPage.tsx # Per-role model assignment (Leader/Dev/QA)
│
├── hooks/                     # ── Custom React Hooks ─────────────────────
│   ├── useRunConnection.ts    # WebSocket lifecycle: connect, dispatch events, reconnect
│   ├── useAgentConnection.ts  # Agent status subscription
│   ├── useFileSystem.ts       # File tree fetch (REST) + ws-driven updates
│   └── useTerminalStream.ts   # Terminal output buffering from ws events
│
├── stores/                    # ── Zustand State Stores ───────────────────
│   ├── agentStore.ts          # Agent statuses, messages, activities
│   ├── fileStore.ts           # File tree, open tabs, active file content
│   ├── terminalStore.ts       # Terminal lines, command history per task
│   └── settingsStore.ts       # LLM provider keys, model routing config
│
├── types/                     # ── TypeScript Type Definitions ────────────
│   ├── index.ts               # Shared types: RunState, AgentTask, FileNode, etc.
│   └── runEvents.ts           # WebSocket event type unions + payload shapes
│
├── pages/                     # ── Page Components ────────────────────────
│   └── AdminDashboard.tsx     # Admin panel: run history, system metrics
│
├── data/                      # (empty — reserved for static data/fixtures)
└── simulation/                # (empty — reserved for dev simulation drivers)
```

---

## `backend/` — Python Backend (FastAPI)

The backend is the **single source of truth**. It owns run orchestration, agent lifecycle, sandbox provisioning, event streaming, and state persistence.

```
backend/
├── requirements.txt           # Python deps: fastapi, opensandbox, redis, sqlalchemy, PyJWT, mcp
├── worker.py                  # Async Worker process: dequeues runs from Redis, drives RunManager
├── Dockerfile                 # Backend container image
├── .env.example               # Backend-specific env template
├── sql_app.db                 # SQLite database (dev default, swap to Postgres for prod)
├── workspaces/                # Host-side workspace mount point (unused with OpenSandbox)
│
└── app/                       # ── FastAPI Application Package ────────────
    ├── __init__.py
    ├── main.py                # FastAPI app factory: CORS, lifespan, router mounts
    ├── config.py              # Pydantic Settings: reads env vars into typed config
    │
    ├── agents/                # ── LLM Agent Implementations ─────────────
    │   ├── __init__.py
    │   ├── leader_agent.py    # Leader (Planner): decomposes goals → AgentTask[], mentorship mode
    │   ├── dev_agent.py       # Dev (Coder): implements code via sandbox MCP tools
    │   ├── qa_agent.py        # QA (Tester): 4-dimensional scoring, critique_report.md generation
    │   └── mcp_tools.py       # MCP Facade: role-scoped FastMCP servers exposing sandbox tools
    │
    ├── api/                   # ── HTTP & WebSocket Endpoints ─────────────
    │   ├── __init__.py
    │   ├── runs.py            # REST: POST /runs, GET /runs/:id, POST /runs/:id/cancel
    │   ├── ws.py              # WebSocket: /ws/:runId — bidirectional event streaming
    │   ├── workspaces.py      # REST: GET /workspaces/:id/tree, GET /workspaces/:id/files
    │   ├── settings.py        # REST: CRUD for API keys + LLM routing config
    │   ├── admin.py           # REST: admin dashboard data, run metrics
    │   └── mcp.py             # Internal MCP SSE mounts with JWT auth middleware
    │
    ├── core/                  # ── Security & Cross-cutting ───────────────
    │   ├── __init__.py
    │   └── security.py        # JWT generation/validation for run-scoped MCP auth
    │
    ├── db/                    # ── Database Layer ─────────────────────────
    │   ├── __init__.py
    │   ├── database.py        # AsyncSession factory (SQLAlchemy async engine)
    │   └── models.py          # ORM models: RunModel, TaskModel, EventLogModel,
    │                          #   AuditLogModel, APIKeyModel, LLMRoutingModel
    │                          #   + Fernet encrypt/decrypt helpers
    │
    ├── orchestrator/          # ── Run Lifecycle Engine ────────────────────
    │   ├── __init__.py
    │   └── run_manager.py     # RunManager: state machine (PLANNING→DEVELOPING→VERIFYING→…)
    │                          #   TaskDelegator: Dev→QA loop with retry, mentorship, snapshot rollback
    │                          #   _persist_agent_metrics: LLM cost/token accumulation
    │                          #   _persist_sdk_metrics: end-of-run telemetry event
    │
    ├── schemas/               # ── Pydantic Schemas & Domain Types ────────
    │   ├── __init__.py
    │   ├── domain.py          # AgentTask, RunState enum, shared domain objects
    │   └── events.py          # WebSocket event envelope schemas + event type registry
    │
    └── services/              # ── Infrastructure Services ────────────────
        ├── __init__.py
        ├── openhands_client.py# OpenSandboxClient: container provisioning, file I/O, command exec
        │                      #   Resource throttling (CPU/RAM), network isolation,
        │                      #   snapshot/restore, zombie cleanup, setup_dependencies()
        ├── event_broker.py    # Redis Pub/Sub event broker (publish + subscribe per run)
        ├── run_store.py       # Async CRUD: runs, tasks, events, metrics (SQLAlchemy)
        └── command_policy.py  # Role-based command allowlist/blocklist enforcement
```

---

## `docs/` — Architecture Documentation

```
docs/
├── PROJECT_KNOWLEDGE.md       # Source of truth: vision, tech stack, hard rules, anti-patterns
├── SYSTEM_ARCHITECTURE.md     # Detailed system architecture and component interactions
├── plan.md                    # Implementation plan and milestone tracking
└── deployment-plan.md         # Deployment strategy, staging, and production config
```

---

## `infra/` — Infrastructure

```
infra/
└── staging/
    └── docker-compose.yml     # Staging stack: frontend-web, orchestrator-api, redis
                               #   (Postgres commented out — using SQLite for dev)
```

---

## Data Flow Cheat Sheet

```
User Goal (UI)
  │
  ▼
POST /runs ──► Redis Queue ──► Worker (worker.py)
                                  │
                                  ▼
                            RunManager.execute_run()
                                  │
                    ┌─────────────┼─────────────┐
                    ▼             ▼             ▼
              LeaderAgent    DevAgent       QaAgent
              (planning)    (coding)      (testing)
                    │             │             │
                    └──── MCP Tools (mcp_tools.py) ────┐
                                                       ▼
                                              OpenSandboxClient
                                            (Docker container)
                                                       │
                                                       ▼
                                              sandbox.files.*
                                              sandbox.commands.*
```

Events flow back via **Redis Pub/Sub → WebSocket → React stores**.
