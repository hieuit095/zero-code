# Deployment Plan: From Mock Frontend to Production Multi-Agent IDE

## Goal

Turn the current React mock-up into a production-ready multi-agent IDE by deploying the system in layers:

1. A real backend and event system
2. A secure OpenHands-backed execution substrate
3. A run-scoped MCP bridge that makes the sandbox feel like a native toolset to Nanobot
4. A Leader -> Dev -> QA orchestration loop with automated retry
5. Persistence, metrics, security, and rollout controls for staging and production

This plan assumes the architecture in [plan.md](c:/Users/USER/Documents/GitHub/zero-code/plan.md) remains the source of truth.

## Core Deployment Decision

### Use OpenHands as the sandbox runtime and expose it to Nanobot through MCP

Do not make Nanobot reason about raw sandbox APIs or invent file/terminal semantics in prompts.

Instead:

- Provision an OpenHands workspace per run or per user session.
- Put an MCP facade in front of that workspace.
- Let Nanobot consume the MCP server as a native tool provider.

This is the right direction for this project because:

- OpenHands already supports remote execution and isolated workspaces for production deployments.
- OpenHands agents can be switched from local workspaces to Docker or API-based remote workspaces by changing the workspace argument, while keeping the same conversation model.
- OpenHands MCP support and tool filtering make it easy to expose only the tool surface you want.
- Nanobot can connect to remote MCP servers over HTTP, limit the exposed tool set with `enabledTools`, and auto-register MCP tools on startup.

In practice, the production chain should be:

```text
React UI
  -> FastAPI Orchestrator
  -> Run-scoped OpenHands Workspace
  -> Sandbox MCP Facade
  -> Nanobot Agents
```

Not this:

```text
React UI
  -> Nanobot with local shell/filesystem
```

## How the OpenHands Guides Map to This Rollout

- Getting Started and Hello World
  - Use these to validate the base SDK install, model wiring, and first workspace execution flow before building orchestration.
- Custom Tools
  - Use this only for capability gaps that are not worth exposing through MCP.
  - The preferred path for sandbox operations is MCP, not ad hoc custom tool prompting.
- MCP
  - This is the foundation for the sandbox bridge.
  - The sandbox should be exposed as an MCP server that Nanobot consumes as a native toolset.
- Skill
  - Use skills to package stable role instructions and reusable operating procedures.
  - This is most useful for Dev and QA behavior standards.
- Plugins
  - Treat plugins as optional packaging for OpenHands-native helper agents or hook bundles.
  - They are useful, but not on the critical path if Nanobot remains the main agent framework.
- Conversation Persistence
  - Use this for resumability and recovery wherever OpenHands-native conversations are involved.
- Context Condenser
  - Use this once runs become long enough that context growth starts hurting cost or reliability.
- Agent Delegation
  - Use this for fan-out work such as repo analysis, test planning, or docs lookup.
- Task Tool Set
  - Use this as the conceptual model for the main sequential Leader -> specialist workflow.
- Iterative Refinement
  - Use this as the model for the Dev <-> QA retry loop.
- Security
  - Use confirmation policies and analyzers for high-risk actions and deployment hardening.
- Metrics
  - Use conversation and run metrics for cost tracking, quota management, and rollout dashboards.

## Target Production Topology

### Internet-facing services

- `frontend-web`
  - Static React app
  - Served via CDN / static host
- `orchestrator-api`
  - FastAPI REST + WebSocket gateway
  - Auth, run lifecycle, snapshots, settings

### Internal services

- `run-worker`
  - Executes long-running workflows
  - Owns Leader / Dev / QA orchestration
- `sandbox-mcp`
  - HTTP MCP service
  - Proxies file and terminal operations into a specific OpenHands workspace
- `openhands-runtime`
  - Agent server / workspace runtime
  - Docker or API-based sandbox backend
- `redis`
  - Event fan-out, background queue, cancellation, heartbeats
- `postgres`
  - Run metadata, task state, settings, session pointers, audit trail
- `object-storage`
  - Terminal logs, artifacts, snapshots, exported reports

### Security boundary

- The frontend never talks to OpenHands directly.
- The frontend never talks to MCP directly.
- Nanobot never gets host shell/file tools in production.
- Sandbox MCP endpoints are private and run-scoped.

## Recommended Repository / Service Layout

```text
/
  src/                         # existing React app
  backend/
    app/                       # FastAPI API, websocket, run manager
  sandbox-mcp/
    app/                       # MCP server that wraps OpenHands workspace ops
  infra/
    docker/
    staging/
    production/
  docs/
    plan.md
    deployment-plan.md
```

## Sequential Phases

## Phase 0: Stabilize the Prototype

### Objective

Clean the current codebase enough that it can safely become the shell of a real product.

### Build work

- Fix current frontend lint/typecheck drift.
- Remove or quarantine mock-only assumptions that would block backend integration.
- Create a local `.env.example` for frontend and backend.
- Add Dockerfiles for:
  - frontend
  - backend
- Add a local `docker-compose.yml` for:
  - frontend
  - backend
  - postgres
  - redis

### Deployment work

- Stand up a local stack with one command.
- Confirm the UI still renders exactly as expected after containerization.

### Exit gate

- `vite build`, lint, and typecheck are clean.
- The repo can boot as a repeatable local stack.

### Why this phase matters

You do not want to introduce OpenHands, MCP, workers, and WebSockets while the shell itself is still drifting.

## Phase 1: Deploy the OpenHands Runtime Layer

### Objective

Deploy a real isolated workspace backend before building the agent loop.

### Build work

- Add `backend/app/services/openhands_client.py`.
- Choose one of two runtime modes:
  - `DockerWorkspace` / `DockerDevWorkspace` for local and early staging
  - `APIRemoteWorkspace` or OpenHands Agent Server for shared staging and production
- Standardize workspace operations behind a simple service interface:
  - `create_workspace()`
  - `destroy_workspace()`
  - `list_tree()`
  - `read_file()`
  - `write_file()`
  - `execute_command()`
  - `stream_command_output()`

### Deployment work

- For local and internal dev:
  - Run OpenHands in Docker with a prebuilt agent-server image.
- For shared staging:
  - Deploy OpenHands Agent Server as an internal service.
- For production:
  - Deploy OpenHands runtime on isolated compute with per-workspace resource limits.

### Success checks

- The backend can provision a workspace on demand.
- The backend can list files, read a file, write a file, and run `pwd` or `npm run typecheck` in that workspace.
- Workspace creation and cleanup are reliable.

### OpenHands guidance this phase uses

- The SDK install path includes `openhands-sdk`, `openhands-tools`, `openhands-workspace`, and `openhands-agent-server`.
- OpenHands remote agent servers are explicitly designed for isolated production deployments and support REST + WebSocket streaming.

## Phase 2: Deploy the Sandbox MCP Facade

### Objective

Turn each OpenHands workspace into a clean MCP tool surface for Nanobot.

### Build work

Create a separate `sandbox-mcp` service with tools like:

- `workspace_list_dir`
- `workspace_get_tree`
- `workspace_read_file`
- `workspace_write_file`
- `workspace_edit_file`
- `workspace_apply_patch`
- `workspace_exec`
- `workspace_run_test`
- `workspace_get_log_tail`
- `workspace_download_artifact`

Each tool should:

- accept a `runId` or `workspaceId`
- authenticate with a short-lived internal token
- call the OpenHands workspace service
- return structured results, not raw transport blobs

### Tool surface rules

- Keep the MCP tool names simple and programming-native.
- Expose only the safe subset the agents need.
- Treat dangerous actions separately:
  - destructive deletes
  - long-running install commands
  - network calls from inside the sandbox

### Deployment work

- Deploy `sandbox-mcp` as an internal HTTP MCP service.
- Put it on the same private network as the backend and OpenHands runtime.
- Do not expose it publicly.

### Nanobot integration

Configure Nanobot agents with a run-scoped MCP config:

```json
{
  "tools": {
    "mcpServers": {
      "sandbox": {
        "url": "https://sandbox-mcp.internal/runs/{runId}/mcp",
        "headers": {
          "Authorization": "Bearer <run-scoped-token>"
        },
        "enabledTools": [
          "workspace_list_dir",
          "workspace_get_tree",
          "workspace_read_file",
          "workspace_write_file",
          "workspace_edit_file",
          "workspace_apply_patch",
          "workspace_exec",
          "workspace_run_test",
          "workspace_get_log_tail"
        ]
      }
    }
  }
}
```

### Exit gate

- A Nanobot agent can connect to the sandbox MCP endpoint and use the exposed tools without custom prompt instructions about how the sandbox API works.
- Local host tools are disabled or absent in production-mode agent configs.

### Why this is the most important architectural shift

This is the phase that converts the system from "AI with custom wrappers" into "AI with a native programming environment."

## Phase 3: Deploy the FastAPI Orchestrator

### Objective

Deploy the backend that owns runs, sessions, sockets, and state transitions.

### Build work

- Add:
  - `backend/app/main.py`
  - `backend/app/api/runs.py`
  - `backend/app/api/workspaces.py`
  - `backend/app/api/ws.py`
  - `backend/app/services/run_store.py`
  - `backend/app/services/event_broker.py`
  - `backend/app/orchestrator/run_manager.py`
- Implement the contracts defined in [plan.md](c:/Users/USER/Documents/GitHub/zero-code/plan.md):
  - `POST /api/runs`
  - `GET /api/runs/{runId}/snapshot`
  - `POST /api/runs/{runId}/cancel`
  - `GET /api/workspaces/{workspaceId}/tree`
  - `GET /api/workspaces/{workspaceId}/file`
  - `/ws/runs/{runId}`

### Deployment work

- Deploy FastAPI and worker in one service for MVP.
- Split `run-worker` into a separate process only after websocket/API stability is proven.

### Exit gate

- The UI can open a socket and receive real events.
- The backend can rehydrate run state from the database after restart.
- Cancelling a run stops the worker and associated workspace activity.

### Notes

- Use Postgres for canonical state.
- Use Redis for event fan-out and cancellation signals.
- Keep all websocket events append-only with sequence numbers.

## Phase 4: Cut the Frontend Over to Live Data

### Objective

Deploy the current React UI against the real backend without redesigning it.

### Build work

- Replace `useSimulation.ts` with `useRunConnection.ts`.
- Add `src/types/runEvents.ts`.
- Move file contents into reactive Zustand state.
- Wire:
  - `agent:status`
  - `agent:message`
  - `task:update`
  - `fs:tree`
  - `fs:update`
  - `terminal:output`
  - `qa:report`
  - `qa:passed`

### Deployment work

- Deploy the frontend to a preview environment first.
- Point preview to staging backend only.
- Keep the old simulation path disabled behind a dev flag if still needed for UI work.

### Exit gate

- The UI no longer depends on simulation to demonstrate a run.
- Browser refresh can recover a live run snapshot.
- The editor, task list, chatter feed, and terminal all move from backend events.

## Phase 5: Deploy the First Vertical Slice

### Objective

Ship one real autonomous workflow end-to-end before building the full multi-agent system.

### Recommended first slice

`Goal -> Dev agent -> QA agent -> pass/fail -> streamed UI`

Do not introduce the full Leader agent yet.

### Build work

- Create one Nanobot-backed Dev agent profile.
- Create one Nanobot-backed QA agent profile.
- Both connect to the same sandbox MCP server.
- QA executes:
  - `npm run typecheck`
  - `npm run lint`
  - one targeted test command
- QA emits a structured defect report if a command fails.

### Deployment work

- Deploy this flow only in internal staging first.
- Run it against seeded repos or this repo itself.

### Exit gate

- The system can fix a real frontend issue inside the sandbox.
- QA can fail the run with structured data.
- The terminal and editor reflect the run in real time.

### Why this phase exists

It proves the two hardest product assumptions:

- Nanobot can operate correctly through the MCP facade.
- OpenHands can support the file and command loop reliably enough for automation.

## Phase 6: Deploy the Full Leader / Dev / QA Loop

### Objective

Introduce the full non-linear loop only after the vertical slice is stable.

### Build work

- Add the Leader agent.
- Use a sequential orchestration model for core task flow.
- Use fan-out only where it adds real value.

### Recommended orchestration split

- Use a Task Tool Set style pattern for the main workflow:
  - planning
  - assigning one task
  - resuming a specialist with context
- Use delegation only for parallelizable sub-work:
  - repo analysis
  - docs lookup
  - test matrix generation

### Why

OpenHands documents position Task Tool Set as best for expert delegation and multi-turn workflows, while DelegateTool is best for concurrent fan-out/fan-in work. That maps well to:

- sequential Leader -> Dev -> QA task execution
- optional parallel subanalysis where useful

### Implement the retry loop using iterative refinement semantics

- Dev produces a patch
- QA critiques and scores or validates
- if below threshold, Dev retries with QA feedback
- stop on:
  - pass
  - retry ceiling
  - escalation condition

### Deployment work

- Release this phase behind an internal feature flag.
- Keep retry limits conservative at first.

### Exit gate

- At least one task can move through:
  - Leader planning
  - Dev implementation
  - QA failure
  - Dev retry
  - QA success

## Phase 7: Persistence, Context, and Long-Run Reliability

### Objective

Make long sessions resumable, affordable, and reliable.

### Build work

- Persist run metadata, task states, events, and artifacts in Postgres + object storage.
- Add a run replay endpoint.
- Store:
  - final summaries
  - qa reports
  - terminal logs
  - file versions or snapshots

### OpenHands features to use where applicable

- Conversation persistence auto-saves `ConversationState` changes to `base_state.json`.
- Events and base state are split, which is useful for resumability and audit trails.
- `LLMSummarizingCondenser` can reduce context size by replacing older event ranges with summaries.
- `conversation_stats.get_combined_metrics()` and per-usage metrics let you track cost by agent or subsystem.

### Deployment work

- Add database migrations.
- Add a daily cleanup job for expired runs and orphaned workspaces.
- Add object-storage lifecycle policies for large logs/artifacts.

### Exit gate

- A run survives service restart.
- A long session can be resumed from persisted state.
- Per-run and per-agent cost reports are visible in admin views or logs.

## Phase 8: Security Hardening and Safe Operations

### Objective

Lock down the system before any external beta.

### Build work

- Add strong service-to-service auth between:
  - orchestrator
  - sandbox-mcp
  - openhands runtime
- Add per-run signed tokens for MCP access.
- Separate safe and risky tool classes.
- Add backend-enforced command allow/deny policies.

### OpenHands security controls to apply

- Use confirmation policies for risky actions where appropriate:
  - `AlwaysConfirm()`
  - `NeverConfirm()`
  - `ConfirmRisky()`
- Use `LLMSecurityAnalyzer` or an equivalent safety pass for high-risk actions.
- Keep OpenHands workspaces isolated and resource-bounded.

### Nanobot security controls to apply

- Set `restrictToWorkspace` to true anywhere local tools still exist.
- Use `enabledTools` to expose only the MCP subset each role needs.
- Do not run public instances with permissive defaults.

### Deployment work

- Put all internal services on a private network.
- Add rate limits and user auth at FastAPI.
- Add audit logging for:
  - run creation
  - command execution
  - file writes
  - cancellations
  - failed security checks

### Exit gate

- No path exists from a frontend user directly into OpenHands or MCP.
- Dangerous commands are blocked or require explicit policy approval.
- Audit logs are complete enough for incident review.

## Phase 9: Staging Rollout

### Objective

Deploy a stable shared environment for internal dogfooding.

### Environment shape

- One shared staging frontend
- One staging FastAPI API
- One staging worker
- One staging Postgres
- One staging Redis
- One staging OpenHands runtime pool
- One internal sandbox-mcp service

### Release policy

- Only internal users
- Small repo sizes first
- Short max run times
- One sandbox per run

### Required dashboards

- active runs
- average run duration
- QA retry rate
- workspace creation failures
- MCP tool latency
- OpenHands command failure rate
- token cost per run

### Exit gate

- Internal team can complete repeated end-to-end runs with acceptable reliability.
- Retry loops work without manual intervention in common cases.
- Workspace cleanup is healthy under load.

## Phase 10: Production Rollout

### Objective

Launch safely with a controlled growth model.

### Production rollout order

1. Private alpha
   - invited internal users only
   - one workspace size limit
   - one runtime region
2. Closed beta
   - selected design partners
   - higher run quotas
   - improved artifact retention
3. General availability
   - autoscaling workers
   - multi-region frontend
   - horizontal OpenHands runtime pool

### MVP production topology

- Frontend on CDN/static host
- FastAPI API + WebSocket on container platform
- Background worker on same platform
- Managed Postgres
- Managed Redis
- Managed object storage
- OpenHands Agent Server on isolated container nodes
- Private sandbox-mcp service next to the orchestrator/runtime network

### Scale-out topology after beta

- Separate API and worker pools
- Queue-backed run dispatch
- OpenHands runtime pool autoscaling
- Per-tenant quotas
- Region-aware workspace placement

### Rollback strategy

- Frontend can be rolled back independently.
- Orchestrator deploys must be versioned and reversible.
- MCP server versions must stay backward-compatible with at least one previous agent config.
- If MCP instability appears:
  - freeze new runs
  - let active runs finish
  - route agents back to the last known-good MCP build

## Critical Path

These steps must happen in order:

1. Prototype stabilization
2. OpenHands runtime deployment
3. Sandbox MCP facade
4. FastAPI orchestrator
5. Frontend live transport cutover
6. Single vertical slice
7. Full three-agent loop
8. Persistence and security hardening
9. Shared staging
10. Production

If Phase 2 slips, the rest of the architecture slips with it.

## What to Defer Until After Staging

- fancy diff streaming instead of full file snapshots
- multiple concurrent workspaces per user
- user-defined custom skills marketplace
- broad third-party integrations
- agent-generated deployment of user apps
- advanced cost routing across many models

## Immediate Implementation Sequence

### Sprint 1

- Fix frontend health issues.
- Scaffold backend.
- Deploy OpenHands runtime locally.
- Prove file read/write/exec through a backend service.

### Sprint 2

- Build `sandbox-mcp`.
- Connect one Nanobot agent to it.
- Run real commands in a sandbox through MCP.

### Sprint 3

- Replace frontend simulation with real socket transport.
- Deploy one Dev -> QA vertical slice.

### Sprint 4

- Add Leader orchestration.
- Add retry loop and structured QA defect packets.
- Persist run history and artifacts.

### Sprint 5

- Security hardening.
- Metrics and tracing.
- Internal staging rollout.

## References

- OpenHands Getting Started: https://docs.openhands.dev/sdk/getting-started
- OpenHands Hello World: https://docs.openhands.dev/sdk/guides/hello-world
- OpenHands Custom Tools: https://docs.openhands.dev/sdk/guides/custom-tools
- OpenHands MCP: https://docs.openhands.dev/sdk/guides/mcp
- OpenHands Agent Skills & Context: https://docs.openhands.dev/sdk/guides/skill
- OpenHands Plugins: https://docs.openhands.dev/sdk/guides/plugins
- OpenHands Persistence: https://docs.openhands.dev/sdk/guides/convo-persistence
- OpenHands Context Condenser: https://docs.openhands.dev/sdk/guides/context-condenser
- OpenHands Agent Delegation: https://docs.openhands.dev/sdk/guides/agent-delegation
- OpenHands Task Tool Set: https://docs.openhands.dev/sdk/guides/task-tool-set
- OpenHands Iterative Refinement: https://docs.openhands.dev/sdk/guides/iterative-refinement
- OpenHands Security: https://docs.openhands.dev/sdk/guides/security
- OpenHands Metrics: https://docs.openhands.dev/sdk/guides/metrics
- OpenHands Remote Agent Server Overview: https://docs.openhands.dev/sdk/guides/agent-server/overview
- OpenHands Agent Server Package: https://docs.openhands.dev/sdk/arch/agent-server
- Nanobot README: https://github.com/HKUDS/nanobot
