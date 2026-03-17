# E2E Integration & Synchronization Audit

**Date:** 2026-03-17  
**Scope:** React UI (Zustand) ↔ FastAPI (WebSockets/REST) ↔ Redis Pub/Sub ↔ Async Worker (TaskDelegator) ↔ Nanobot Agents ↔ OpenHands SDK  
**Mode:** READ-ONLY — zero source modifications  

---

## 1. Executive Summary

> **VERDICT: NOT READY for user dogfooding.**  
> The backend orchestration is architecturally sound — the `TaskDelegator`, `EventBroker`, DB-backed state machine, and `worker.py` crash recovery are all correctly wired. However, **the React frontend is significantly behind the backend**, leaving several major features invisible to the user. The most critical gap is that the **QA Dimensional Scoring system** (4 scores: code_quality, requirements, robustness, security) exists only in the backend Python layer — the frontend TypeScript types, Zustand stores, and UI components have ZERO awareness of these scores. Additionally, the Settings flow has a split-brain between two UIs, and the `Header.tsx` "Generate" button does not pass the user's model routing preferences to the backend.

| Area | Backend | Frontend | Sync Status |
|------|---------|----------|-------------|
| Run Lifecycle (start/state/complete/error) | ✅ | ✅ | ✅ Synced |
| Agent Status & Messages | ✅ | ✅ | ✅ Synced |
| Task Snapshot & Updates | ✅ | ✅ | ✅ Synced |
| File Tree & Editor Sync | ✅ | ✅ | ✅ Synced |
| Terminal Streaming | ✅ | ✅ | ✅ Synced |
| QA Retry Banner | ✅ | ✅ | ⚠️ Partial (no scores) |
| **QA Dimensional Scores** | ✅ | ❌ | 🔴 **BROKEN** |
| **Settings → Agent Config** | ✅ | ❌ | 🔴 **BROKEN** |
| **Error Boundary for Fatal Runs** | ✅ | ❌ | 🔴 **BROKEN** |
| Reconnect Hydration | ✅ | ✅ | ✅ Synced |
| Worker Crash → UI Error | ✅ | ⚠️ | ⚠️ Partial |

---

## 2. UI/UX Disconnects (Critical Integration Gaps)

### GAP-01: QA Dimensional Scores — Completely Invisible in UI

**Severity: 🔴 CRITICAL**

The backend `qa_agent.py` computes 4 dimensional scores (`code_quality`, `requirements`, `robustness`, `security`) and the `TaskDelegator` emits them in `qa:report` and `qa:passed` events. **The React frontend has ZERO awareness of these scores.**

| Layer | File | Evidence |
|-------|------|----------|
| **Type Contract** | `src/types/runEvents.ts:366-376` | `QaReportData` interface has NO score fields — only `taskId`, `attempt`, `status`, `failingCommand`, `exitCode`, `summary`, `rawLogTail`, `errors`, `retryable` |
| **Type Contract** | `src/types/runEvents.ts:389-397` | `QaPassedData` interface also has NO score fields |
| **Zustand Store** | `src/stores/agentStore.ts:16-23` | `QaRetryState` interface has NO score fields — only `failingCommand` and `defectSummary` |
| **WS Dispatch** | `src/hooks/useRunConnection.ts:366-388` | `qa:report` handler consumes only `taskId`, `attempt`, `retryable`, `failingCommand`, `summary`, `rawLogTail` — score data is silently dropped |
| **UI Component** | `src/components/TasksPanel.tsx:88-115` | QA retry banner shows only attempt count and `defectSummary` text — no score bars, no threshold indicators |
| **grep verification** | All `src/**/*.ts` and `src/**/*.tsx` | `grep -r "scores" src/` → **0 results** |

**Impact:** Users see a generic "QA Failed" banner with no visibility into which dimensions failed (e.g., security at 75/90) or what the threshold targets are. The entire scoring system is wasted backend compute.

### GAP-02: Agent Model Configuration — Never Reaches Backend

**Severity: 🔴 CRITICAL**

The `settingsStore.ts` defines a `getAgentConfig()` selector that returns the correct `RunStartData.agentConfig` shape. But `Header.tsx` (the component that calls `startRun()`) **never imports or uses `settingsStore`**.

| Layer | File | Line(s) | Evidence |
|-------|------|---------|----------|
| Settings Store | `src/stores/settingsStore.ts:77-89` | `getAgentConfig()` correctly maps models → `{ "tech-lead": { model: "gpt-4o" }, ... }` |
| Header (Generate) | `src/components/Header.tsx:40-56` | `startRun({ goal: goal.trim(), workspaceId: 'repo-main' })` — **no `agentConfig` field** |
| Header (WS path) | `src/components/Header.tsx:46-48` | `sendMessage({ type: 'run:start', data: { goal, workspaceId } })` — **no `agentConfig`** |

**Impact:** No matter what model/provider the user selects in Settings, the backend always receives the default config. The entire `AgentRoutingSection` UI and the `AgentSetupPage` model dropdowns are non-functional.

### GAP-03: AgentSetupPage — Fully Ephemeral, Not Persisted

**Severity: ⚠️ HIGH**

The `AgentSetupPage.tsx` component manages model selection and system prompts entirely in local `useState`. Changes are lost on page refresh. It does NOT:
- Read from `settingsStore.ts` (which exists and has `setAgentModel`, `setAgentSystemPrompt`)
- Call any backend REST endpoint
- Connect to the `APIFeedSetupPage`'s `AgentRoutingSection` in any way

| Layer | File | Line(s) | Evidence |
|-------|------|---------|----------|
| Component | `src/components/settings/AgentSetupPage.tsx:269-281` | `useState` for models and prompts — no store import |
| Store | `src/stores/settingsStore.ts:51-67` | `setAgentModel()` and `setAgentSystemPrompt()` exist but are NEVER called from ANY component |

**Impact:** Users configure agents in `AgentSetupPage`, then visit `APIFeedSetupPage` which has its OWN `AgentRoutingSection` with a completely separate `useState` for the same data. Two UIs, zero persistence, zero synchronization.

### GAP-04: `critique_report.md` Artifact — Not Surfaced in UI

**Severity: ⚠️ MEDIUM**

The `TaskDelegator` uses a file-based critique handoff pattern — QA writes critique to `/workspace/critique_report.md`, and on retry the Dev agent reads it. The UI has no visibility into this artifact:
- The `FileExplorer` would show it IF a `fs:update` event was emitted for it, but the current QA agent writes it via MCP tools and no `fs:update` event is emitted for `critique_report.md`
- Users cannot manually inspect why QA failed at the file level

---

## 3. Data Flow Broken Links (Backend → Frontend)

### LINK-01: `qa:report` Event Payload Mismatch

**Backend emits** (from `run_manager.py` via `qa_result.to_report_dict()`):
```python
{
  "taskId": "...", "attempt": 1, "status": "failed",
  "failingCommand": "...", "exitCode": 2,
  "summary": "...", "rawLogTail": [...], "errors": [...],
  "retryable": true,
  "scores": {  # ← PRESENT in backend payload
    "code_quality": 85, "requirements": 70,
    "robustness": 60, "security": 95
  },
  "failingDimensions": ["requirements", "robustness"]  # ← PRESENT
}
```

**Frontend expects** (from `src/types/runEvents.ts:366-376`):
```typescript
interface QaReportData {
  taskId: string; attempt: number; status: 'failed';
  failingCommand: string; exitCode: number;
  summary: string; rawLogTail: string[];
  errors: QaReportIssue[]; retryable: boolean;
  // ← scores: MISSING
  // ← failingDimensions: MISSING
}
```

**Result:** The `scores` and `failingDimensions` fields arrive over the WebSocket but are silently ignored because TypeScript destructuring only reads known fields. The data is LOST.

### LINK-02: `qa:passed` Event Payload Mismatch

Same pattern — backend emits `scores` in the passed event, frontend `QaPassedData` type doesn't include it.

### LINK-03: `run:error` Event — No Dedicated UI Error State

The `worker.py` (line 93) correctly emits `run:error` with `WORKER_CRASH` error code on sandbox crash. The `useRunConnection.ts` (line 226, 270-286) does:
- Set `state.error` to the message string
- Set `runStatus` to `"failed"` and disable terminal streaming

**BUT** — the `Header.tsx` (line 38) checks `runStatus !== 'failed'` to determine `isRunning`, which correctly stops the spinner. However, there is **NO error toast, error banner, or error modal** anywhere in the UI to display the `state.error` message. The user sees the "Running..." indicator disappear, but has no visible explanation of what went wrong.

The only hint is the small `error` field in `RunConnectionState` (line 71), which is read by **nobody** in the component tree.

---

## 4. Edge Case Unhandled UI States

### EDGE-01: No Error Boundary Component

There is no React Error Boundary wrapping the main App. A JSON parse failure in `useRunConnection.ts:528-534` sets `state.error` but the component tree has no way to display it globally. The user sees nothing.

### EDGE-02: Infinite "Reconnecting…" Banner

The `Header.tsx` (line 160-171) renders a disconnect banner when `connectionStatus === 'reconnecting'`. However, there is no maximum reconnection limit — the exponential backoff in `useRunConnection.ts:564` caps at 10 seconds but retries forever. After extended network loss, the banner pulses indefinitely with no "Give Up" button.

### EDGE-03: `run:start` via WebSocket — Server Ignores It

`Header.tsx` (line 44-48) has a "preferred path" that sends `run:start` over WebSocket if `isConnected`. However, the `ws_router.py` backend handler likely requires REST-based run creation (POST `/api/runs`). If the WS handler doesn't recognize `run:start`, the message is silently dropped. The `startRun` REST fallback (line 51) only fires when `!isConnected`, meaning cold starts work but runs initiated while already connected to a previous run's socket may fail silently.

### EDGE-04: Settings Store vs. API Settings — Split Brain

Three separate settings systems exist with no synchronization:

| System | Persistence | Scope |
|--------|-------------|-------|
| `settingsStore.ts` | localStorage | Model selection (never sent to backend) |
| `AgentSetupPage.tsx` | None (useState) | Model + prompts (lost on refresh) |
| `APIFeedSetupPage.tsx` → `AgentRoutingSection` | Backend DB via REST | Provider + model routing |

Only the `AgentRoutingSection` actually persists to the backend. But the `Header.tsx` Generate button doesn't read from ANY of these when calling `startRun()`.

---

## 5. The Final Polish Checklist

Strictly prioritized by impact on dogfooding readiness:

| # | Priority | Task | Files to Modify |
|---|----------|------|----------------|
| 1 | 🔴 P0 | **Add `scores` and `failingDimensions` to `QaReportData` and `QaPassedData` types** | `src/types/runEvents.ts` |
| 2 | 🔴 P0 | **Add score fields to `QaRetryState` in `agentStore.ts`** and update `setQaRetryState` consumer | `src/stores/agentStore.ts` |
| 3 | 🔴 P0 | **Update `qa:report` handler in `useRunConnection.ts`** to parse and store scores | `src/hooks/useRunConnection.ts:366-388` |
| 4 | 🔴 P0 | **Create QA Score Display UI** — add score bars/chips to the QA retry banner in `TasksPanel.tsx` showing all 4 dimensional scores with threshold indicators | `src/components/TasksPanel.tsx` |
| 5 | 🔴 P0 | **Wire `agentConfig` from `settingsStore.getAgentConfig()` into `Header.tsx` `startRun()`** so the user's model selections actually reach the backend | `src/components/Header.tsx` |
| 6 | ⚠️ P1 | **Unify settings**: Make `AgentSetupPage.tsx` read/write `settingsStore` instead of local `useState`. Remove the duplicate `AgentRoutingSection` from `APIFeedSetupPage.tsx` or merge them. | `AgentSetupPage.tsx`, `APIFeedSetupPage.tsx`, `settingsStore.ts` |
| 7 | ⚠️ P1 | **Add a global error toast/banner** that reads `useRunConnection().error` and displays fatal run errors to the user | `src/App.tsx` or `src/components/Header.tsx` |
| 8 | ⚠️ P1 | **Add reconnect limit** (e.g., 10 attempts) and a "Connection Failed — Retry?" fallback UI | `src/hooks/useRunConnection.ts`, `src/components/Header.tsx` |
| 9 | ⚠️ P1 | **Validate `run:start` WS path** — confirm the backend WS handler processes `run:start` events, or remove the WS path from `Header.tsx` and always use REST | `Header.tsx`, `backend/app/api/ws_router.py` |
| 10 | 💡 P2 | **Surface `critique_report.md`** — emit `fs:update` for the critique artifact so it appears in `FileExplorer` and can be opened in Monaco | `qa_agent.py` or `run_manager.py` |
| 11 | 💡 P2 | **Remove `AgentSetupPage` system prompt `useState`** — wire to `settingsStore.setAgentSystemPrompt()` and persist to backend | `AgentSetupPage.tsx`, `settingsStore.ts` |
| 12 | 💡 P2 | **Add score history to `run:complete` event** — include aggregate scores across all tasks for the run summary | `run_manager.py` emit, `runEvents.ts` type |

---

## Appendix: Vector-by-Vector Trace Results

### Vector 1: Settings & Multi-Provider Flow ⚠️ PARTIAL

- ✅ `APIFeedSetupPage.tsx` correctly calls `POST /api/settings/keys` and `POST /api/settings/llm`
- ✅ Backend `settings.py` encrypts keys with Fernet and returns masked previews
- ❌ `AgentSetupPage.tsx` is entirely local — changes are lost on refresh
- ❌ `Header.tsx` does not pass `agentConfig` from any settings source
- ❌ `settingsStore.ts` exists but is imported by ZERO components (dead code)

### Vector 2: WebSocket State & UI Hydration ✅ SOLID

- ✅ `useRunConnection.ts` correctly dispatches all 19 server event types
- ✅ Reconnect hydration via `hydrateFromSnapshot()` with event queueing
- ✅ Mutable refs prevent stale closure traps in reconnect logic
- ✅ `task:snapshot` correctly replaces the full task list during replans

### Vector 3: Terminal Streaming & Workspace File Sync ✅ SOLID

- ✅ `terminal:command` → `appendLine` with `$` prefix
- ✅ `terminal:output` → `appendLine` with correct `logType`
- ✅ `terminal:exit` → formatted exit code and duration
- ✅ `fs:update` → `setFileFromServer()` opens tab + sets content
- ✅ `dev:start-edit` / `dev:stop-edit` → `setAIControlMode()` locks/unlocks Monaco

### Vector 4: QA Dimensional Scoring Visibility 🔴 BROKEN

- ✅ Backend computes and emits 4 dimensional scores
- ❌ Frontend type contracts do not include score fields
- ❌ Zustand store `QaRetryState` has no score fields
- ❌ `useRunConnection.ts` handler drops score data silently
- ❌ `TasksPanel.tsx` shows generic pass/fail — no score visualization

### Vector 5: Resilience & Worker Death Handling ⚠️ PARTIAL

- ✅ `worker.py` catches unhandled exceptions and emits `run:error`
- ✅ `useRunConnection.ts` sets `runStatus` to `"failed"` and disables spinner
- ❌ No visible error toast/banner — user sees spinner stop with no explanation
- ❌ No reconnect limit — infinite retry loop possible
