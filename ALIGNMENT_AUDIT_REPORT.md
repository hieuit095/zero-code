# Codebase Alignment Audit Report

**Date:** March 19, 2026
**Auditor:** Principal Systems Architect & Lead Integration Engineer
**Mode:** STRICT READ-ONLY

## Executive Summary

A comprehensive architectural and alignment audit was performed against the ZeroCode Multi-Agent IDE codebase. The audit strictly cross-referenced the current implementation against the foundational blueprints: `plan.md`, `deployment-plan.md`, `PROJECT_KNOWLEDGE.md`, `SYSTEM_ARCHITECTURE.md`, and the `OpenhandSDK-docs`.

**Conclusion:** The codebase demonstrates an exceptionally high degree of alignment with the original architectural vision. The rigorous separation of concerns—specifically the boundary between the "Brain" (Nanobot) and the "Muscle" (OpenHands Sandbox)—has been masterfully implemented and secured. 

The audit focused on four critical vectors. Below are the detailed findings.

---

## Vector 1: Technology Boundary & MCP Compliance
**Status: PASSED**

**Objective:** Verify that Nanobot agents never touch the host filesystem directly, but instead operate exclusively through the internal MCP (Model Context Protocol) Facade, which wraps the OpenHands SDK Sandbox execution environment.

**Findings:**
- **MCP Facade Implementation:** The internal MCP facade is correctly implemented using `FastMCP` (`backend/app/agents/mcp_tools.py`). It mounts role-scoped servers (e.g., `zero-code-sandbox-dev`, `zero-code-sandbox-qa`) that provide `workspace_read_file`, `workspace_write_file`, and `workspace_exec` tools.
- **Agent Enforcement:** Nanobot agents (`leader_agent.py`, `dev_agent.py`, `qa_agent.py`) do not use native Python `os` or `subprocess` calls for workspace manipulation. They exclusively interact via the MCP protocol.
- **Path Jailing:** The `_jail_path` function securely uses `os.path.realpath` to resolve requested paths and strictly validates that they remain within the absolute bounds of the `workspace_root`. Null-byte and absolute-path traversal attempts (`/etc/passwd`, `../../`) are successfully trapped and blocked by raising `ValueError`.

## Vector 2: Multi-Agent Orchestration Loop
**Status: PASSED**

**Objective:** Validate that the non-linear execution loop (Leader -> Dev -> QA -> Retry -> Mentorship) is explicitly managed by the backend engine and that Dev/QA handoffs are functioning correctly.

**Findings:**
- **Explicit Orchestration:** The loop is structurally enforced in `backend/app/orchestrator/run_manager.py` via `TaskDelegator.execute()`. State transitions (`QUEUED -> PLANNING -> DELEGATING`) are correctly sequenced.
- **Feedback & Re-planning Loop:** The Dev -> QA handoff correctly implements a retry counter (up to `MAX_QA_RETRIES`). A Dev agent failure routes to the Leader for `mentorship` injection before the final retry, and a structural exhaustion escalates back to `RunManager` for maximum replans (`MAX_LEADER_REPLANS`).
- **Structured QA Responses:** The QA agent outputs structured JSON reports containing `code_quality`, `requirements`, and `performance` dimensional scores (`to_report_dict` / `to_passed_dict`), adhering to the mandate that QA provides intelligent, parseable feedback rather than unstructured text.

## Vector 3: State Management & Invariants 
**Status: PASSED**

**Objective:** Ensure the complete elimination of "Split-Brain" state. The React frontend must act as a dumb rendering client, and the backend must use PostgreSQL as the Single Source of Truth, completely eschewing in-memory dicts representing active runs.

**Findings:**
- **SSOT Enforcement:** There is no usage of `_runs = {}` or `active_runs = set()` in memory across the FastAPI endpoints or background workers. All operations query `RunModel` and `TaskModel` via `RunStore` directly from the database.
- **DB-Before-Emit Sequencing:** `EventBroker` (`backend/app/services/event_broker.py`) enforces strict sequencing. Events are persisted to PostgreSQL (`EventLogModel`) **before** being pushed to the Redis Pub/Sub channels. 
- **Zustand Hydration (Frontend):** The React frontend strictly handles data reception by hydrating its Zustand stores (`agentStore`, `fileStore`, `terminalStore`) from the websocket event streams (`useRunConnection.ts`). Disconnects are flawlessly handled by fetching a REST snapshot (`/api/runs/{runId}/snapshot`), restoring state without racing the websocket events.

## Vector 4: Security & Hardening
**Status: PASSED**

**Objective:** Verify JWT lifespan, Database verification processes, API key encryption at rest, and robust command rejection parsing.

**Findings:**
- **API Key Security:** API keys (`backend/app/db/models.py`) are correctly stored encrypted at rest using the `Fernet` symmetric encryption algorithm (`APIKeyModel.encrypted_key`). The keys are derived from a centralized `API_KEY_SECRET`.
- **JWT Authentication:** The internal Service-to-Service MCP mechanism operates via JWTs. The lifespan has correctly been tuned to 12 hours (`_JWT_EXPIRY_MINUTES = 720`), allowing extended multi-agent compile/retry loops without invalidating credentials.
- **Active State Validation:** Legacy code flaws where tokens were validated against memory arrays have been removed. The JWT validation middleware (`backend/app/core/security.py`) independently queries the PostgreSQL database via `_verify_run_is_active()` to guarantee the run state has not hit a terminal status (`completed`, `failed`).
- **Command Control Policy:** The `CommandPolicy` uses a custom `shlex` quote-aware parsing mechanism that avoids naive `str.split()` failures. It intercepts piped execution flows and reliably stops destructive agents (e.g., blocking `rm -rf /`, `sudo`, `dd`). The QA agent is cleanly sandboxed exclusively to an allowlist of read-only/testing binaries.

---

## Roadmap for Realignment
As the primary alignment audit has **Passed**, no major remediation roadmap is required to address architectural drift or "split-brain" bugs. The implementation is rock solid. 

**Future Recommendations & Hardening Steps:**
1. **Agent Message Streaming Tracking:** In `src/hooks/useRunConnection.ts`, `agent:message:delta` streaming events are currently unhandled comments (`// @ai-integration-point`). Implementing the transient message buffer store for real-time thought projection would drastically increase user observability.
2. **Observability Expansion:** Continue expanding OpenTelemetry hooks mapping the QA structured outputs (`critique_report.md` parsed JSON schemas) directly into a TS-dashboard visualization.
3. **OpenHands SDK Bump:** Continue monitoring OpenHands releases to assure their native `get_runtime` implementation fully maps any newly added `agent-skills` required by the ecosystem before wrapping them behind the MCP sandbox.
