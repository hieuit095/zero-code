# Codebase Alignment Audit Report

## Executive Summary
A comprehensive read-only audit of the Multi-Agent IDE codebase was conducted to evaluate alignment against internal architectural blueprints (`PROJECT_KNOWLEDGE.md`, `plan.md`, `deployment-plan.md`) and the official OpenHands SDK documentation. 

The backend orchestration, security posture, and OpenHands SDK integrations are largely **highly compliant** and sophisticated, correctly isolating execution boundaries and utilizing SDK-native features like the `LLMSummarizingCondenser` and MCP routing. However, critical gaps remain primarily in **Frontend state wiring**, specifically regarding agent configurations, QA metrics hydration, and error visibility. Further, SDK-native LLM metrics tracking remains unimplemented on the backend.

---

## 1. Architectural Invariants & State Flow
*   **Database as Source of Truth (Compliant):** Implementation in `run_manager.py` fetches LLM configs (`_load_llm_configs`) and manages run states exclusively through the `RunStore` instead of in-memory dictionaries.
*   **Orchestration Engine (Compliant):** The FastAPI background worker (`worker.py`) successfully polls Redis and manages the demanding orchestration (Leader -> Dev -> QA) via a structured `TaskDelegator`, fulfilling Rule 2 (FastAPI must not block).
*   **Frontend as Dumb Client (Partial Compliance):** The `useRunConnection.ts` hook acts as a pure event consumer bridging REST and WebSocket. However, settings management remains fragmented:
    *   **Split-Brain Settings:** `AgentSetupPage.tsx` relies on ephemeral local state (`useState`) instead of syncing with `settingsStore.ts` or the backend API mounted at `/api/settings.py`.
    *   **Missing Agent Config Payload:** `Header.tsx` does not read from `settingsStore` to pass selected agent models/prompts during `startRun()`. Consequently, the backend silently falls back to default routing (`gpt-4o` / OpenAI).

## 2. OpenHands SDK Native Compliance
*   **Iterative Refinement (Compliant):** Elegantly encapsulated within the `TaskDelegator` class in `run_manager.py`. Structured JSON endpoints natively drive retry loops, providing Dev Agents with specifically extracted QA failures and the path to `critique_report.md`.
*   **Context Condenser (Compliant):** Correctly implemented via `LLMSummarizingCondenser`. Both `DevAgent` and `QaAgent` inject the condenser during `Agent` initialization, securing token efficiency during long retry cycles.
*   **MCP Tool Surface (Compliant):** Exceptionally aligned. `app/api/mcp.py` mounts role-scoped FastMCP servers `/internal/mcp/{role}/sse`. The `DevAgent` properly connects to this endpoint in its `mcp_config`.
*   **Metrics & Cost Tracking (Non-Compliant):** The SDK documentation emphasizes tracking token limits and costs. While `self._last_llm` exposes metrics inside agent classes, the `RunManager` / `TaskDelegator` does not extract `llm.metrics` or `conversation.conversation_stats` post-execution, preventing persistence to the relational database.

## 3. Agent Cognition & Nanobot Integration
*   **Skill Injection (Compliant):** Successfully deployed in `qa_agent.py` through `_build_qa_skills()`. It accurately evaluates modified files' extensions and dynamically injects `PYTHON_SECURITY_SKILL` or `TYPESCRIPT_SECURITY_SKILL` as native SDK `Skill` objects right into the `AgentContext`.
*   **QA Dimensional Scoring (Compliant Backend / Non-Compliant Frontend):** The `QA_SYSTEM_PROMPT` enforces JSON extraction of 4 dimensional scores (Code Quality, Requirements, Robustness, Security). While the backend perfectly evaluates these through `QaScores.passes_thresholds()`, the frontend interfaces in `useRunConnection.ts` discard this data because `runEvents.ts` typings omit these critical metrics (GAP-01 from E2E integration).
*   **Dynamic LLM Configuration (Compliant):** Backend API (`/api/settings.py`) supports multi-provider settings. They are securely decrypted by `RunManager._load_llm_configs()` and routed immediately into the OpenHands `LLM` objects mapping out role-based routing correctly.

## 4. Security & Hardening
*   **Fernet Encryption (Compliant):** Correctly used in `settings.py` for API key at-rest storage. Keys are masked during API transmission preventing frontend exposure.
*   **Path Jailing (Compliant):** `openhands_client.py` implements a robust `_jail_path` utilizing `os.path.realpath` to prohibit any transversal directory attacks (e.g., stopping escapes via symlinks or `../../` patterns outside the workspace).
*   **Worker Death Resilience (Compliant):** Unhandled worker crashes in `worker.py` catch base `Exception`, gracefully fail the database state preventing phantom hanging runs, and broadcast a `run:error` via Redis.
*   **Frontend Error Visibility (Non-Compliant):** Although the backend cleanly transmits `run:error` on critical faults, the frontend masks these catastrophic failures. `useRunConnection.ts` stores `error: event.data.message`, but `Header.tsx` and UI components lack a dedicated visual toast or modal to surface this to the user.

---

## Actionable Realignment Roadmap

1.  **[🔴 P0] Frontend Settings Synchronization:** 
    *   Plumb `settingsStore.ts` into `AgentSetupPage.tsx` to ensure system prompts and models are persistent. 
    *   Ensure `Header.tsx` dispatches the active `agentConfig` in its `run:start` payload.
2.  **[🔴 P0] QA Metrics Visualization:** 
    *   Align `runEvents.ts` with the backend `QaReportData` and `QaPassedData` shapes so dimensional scores avoid being silently dropped by the WebSocket consumer.
3.  **[⚠️ P1] Telemetry & Cost Tracking Persistence:** 
    *   Extract OpenHands SDK metrics (`llm.metrics` & `conversation_stats`) post-execution inside `run_manager.py` and write to the PostgreSQL database for admin auditing.
4.  **[⚠️ P1] Global Error Handling:** 
    *   Implement a global error toast or standard notification modal explicitly bound to `useRunConnection().error` to visibly display worker crash payloads (`run:error`).
