# ULTIMATE_QA_AUDIT_REPORT — ZeroCode Multi-Agent IDE
**Auditor:** Principal QA Engineer & Lead Security Auditor
**Date:** 2026-03-29
**Scope:** `backend/app/` + `src/`
**Severity:** 🔴 P0-Critical · 🟠 P1-High · 🟡 P2-Medium

---

## 1. THE QA VERDICT

**The codebase has 4 active P0 silent-failure paths that will cause data corruption or unbounded retry loops without any observable error in production logs.** The Ralph retry mechanism and the `decrypted = ""` fallback are particularly dangerous because they give the appearance of graceful degradation while silently propagating corrupted state. This is not a resilient system — it is a system that hides its own failures.

---

## 2. CRITICAL BUGS & SILENT FAILURES

### 🔴 P0-A: Ralph Retry Swallows LLM Server Crashes — Silent Fallthrough to Empty Output
**File:** `backend/app/agents/dev_agent.py:535`

```python
except Exception as Ralph_conv_exc:
    logger.warning(
        "Ralph retry conversation interrupted for run=%s task=%s attempt=%s",
        run_id, task_id, Ralph_attempt + 1, exc_info=True,
    )
    # ← NO re-raise. NO state cleanup. Code falls through to parse_result()
```

**What happens:** If the LLM server returns an error (503, network timeout, rate limit) during a Ralph retry conversation, the exception is caught, logged at WARNING level, and execution **falls through** to `raw_output = extract_last_assistant_text(llm_messages)`. Since the conversation crashed, `llm_messages` contains only what was accumulated before the crash — potentially empty or partial. This empty/partial output is then passed to `_parse_result()` and returned as if it were valid Dev output.

**Exploit scenario:** LLM server goes down mid-Dev-run. Ralph retry triggers → LLM call fails → exception swallowed → Ralph returns empty `files_changed: []` → QA gets a Dev result with no code changes → QA scores it 0.0 → Run marked as failed, but the actual failure is buried in a WARNING log.

**Fix required:** `except` block must either re-raise after logging, or set a `Ralph_conv_exc` flag and return an explicit error result.

---

### 🔴 P0-B: Ralph Syntax Check Silently Skips ALL Errors — Not Just Syntax Errors
**File:** `backend/app/agents/dev_agent.py:518`

```python
except Exception as Ralph_check_err:
    logger.debug(
        "Ralph py_compile check failed for %s: %s",
        py_file, Ralph_check_err,
    )
```

**What happens:** The bare `except Exception` catches **everything**: `PermissionError` (can't read the file), `FileNotFoundError` (path is wrong), `asyncio.TimeoutError` (sandbox is hung), `SyntaxError` (actual syntax error). All are treated identically — only a DEBUG log fires, and the function returns `None` (meaning "no errors found"). A file with `chmod 000` or a sandbox timeout will silently pass Ralph as if it were syntactically correct.

**Specific failure modes:**
- `PermissionError: [Errno 13] Permission denied: '/workspace/foo.py'` → Ralph returns `None` → QA receives invalid code
- `asyncio.TimeoutError` on sandbox execution → Ralph returns `None` → QA receives stale code
- File doesn't exist in workspace but Dev claims it does → Ralph returns `None` → QA receives nothing

**Fix required:** Narrow the exception to `SyntaxError` only. For all other exception types, log at WARNING level and return a distinct error that forces Ralph to fail explicitly.

---

### 🔴 P0-C: Ralph Retry Fails Silently If First Conversation Has No `llm_messages`
**File:** `backend/app/agents/dev_agent.py:492`

```python
if Ralph_attempt < Ralph_MAX_RETRIES:
    ...
    await asyncio.to_thread(conversation.run)
    # ← If this SUCCEEDS but returns 0 new messages (LLM returned empty), the
    # code continues with the ORIGINAL llm_messages (before the retry), meaning
    # the retry had zero effect but the loop still decrements Ralph_attempt.
    raw_output = extract_last_assistant_text(llm_messages)
    after_snapshot = self._snapshot_workspace(workspace_root)
    continue  # ← Ralph_attempt increments regardless
```

**What happens:** If `conversation.run()` completes without raising an exception but the LLM returned no new messages (e.g., LLM hit a content filter and output nothing), the retry loop still counts this as a successful attempt. After 2 such failed retries, Ralph exits the loop and returns `_parse_result()` with the original messages — which may contain the SAME syntax errors that Ralph was supposed to catch. The Dev agent has now wasted 2 retry slots without fixing anything.

**Fix required:** Check that `llm_messages` actually grew after `conversation.run()`. If no new messages, treat as a Ralph failure and exit explicitly.

---

### 🔴 P0-D: Encryption Failure Returns Empty String — Silent Data Corruption
**File:** `backend/app/orchestrator/run_manager.py:825`

```python
try:
    decrypted = self._crypto.decrypt(event_data["encrypted"])
except Exception:
    decrypted = ""  # ← SILENT FALLBACK — no log, no re-raise
```

**What happens:** If `decrypt()` raises ANY exception (wrong key, tampered ciphertext, encoding error, library bug), the code sets `decrypted = ""` and continues. The `event_data` dict is then populated with `decrypted = ""` as the `data` field, and the event is returned to all subscribers. Downstream components receive an event with `data = {}` or empty fields and have no way to know the original payload was corrupted. This is indistinguishable from a legitimately empty event.

**What should happen:** Log at CRITICAL level and either re-raise or set an explicit `is_decryption_error = True` flag so consumers can distinguish a missing payload from a corrupted one.

---

### 🔴 P0-E: Leadership Guidance Write Failure Is Logged But Run Continues
**File:** `backend/app/orchestrator/run_manager.py:680`

```python
except asyncio.TimeoutError:
    logger.error(
        "Timeout writing leader_guidance.md for run %s — sandbox may be unresponsive",
        self._run_id,
    )
except Exception:
    logger.warning(
        "Failed to write leader_guidance.md for run %s",
        self._run_id, exc_info=True,
    )
# ← NO re-raise. NO early return.
# Dev agent is told "read /workspace/leader_guidance.md" but the file doesn't exist.
# Dev run will fail with FileNotFoundError but the error is attributed to Dev, not to guidance write.
```

**What happens:** If the sandbox is unresponsive or the write fails, the exception is caught and logged, but the mentorship retry continues. The Dev agent receives the instruction "read /workspace/leader_guidance.md" and tries to read a file that doesn't exist, generating a Dev-level error that masks the real root cause.

**Fix required:** After the write fails, return an explicit error result or write a minimal fallback guidance file so the Dev agent has something to work with.

---

### 🔴 P0-F: QA Silent Self-Test Failure — Empty Test Cases Not Raised
**File:** `backend/app/agents/qa_agent.py` (already flagged in prior audit)

The `_collect_self_test_cases()` method returns `[]` on failure, which is indistinguishable from "LLM chose not to generate tests." The QA verification loop then executes an empty test suite, which produces "0 passed, 0 failed" — this is flagged as `exit_code = 1` (Anti-Silent-Failure), but the exception that caused `_collect_self_test_cases` to return `[]` is never surfaced. If the failure was due to sandbox corruption or LLM crash, not by choice, there is no way to know.

---

### 🟠 P1-A: AgentStore Infinite Re-render Risk
**File:** `src/stores/agentStore.ts`

```typescript
const streamMessage = (agentId: string, delta: StreamingMessage) => {
    get().streamMessage(agentId, delta);
    // ↑ get() is called INSIDE the useEffect dependency array.
    // This is a known React anti-pattern: the effect's output is a function call
    // whose result is a store action that mutates the store. The store IS the
    // reactive state. The effect reads from get() (non-reactive) and sets via
    // the action (also non-reactive). But if streamMessage is called from a
    // WebSocket handler firing every 50ms, and streamMessage internally calls
    // set() which triggers a re-render, and if a component subscribes to
    // agentStore and uses agentsDashboardRefresh in its deps, the re-render
    // cascade can become infinite if the selector returns a new object reference
    // on every call.
```

The `_mergeStreamingAgents` function constructs a new `agents` object via `Object.fromEntries(...)` on every call. Any component that subscribes to `useAgentStore((s) => s.agents)` will receive a new object reference on every `streamMessage` call — causing an unbounded re-render loop if the component's `useEffect` has `agents` in its dependency array.

---

### 🟠 P1-B: Redis Publish After DB Commit — Failures Logged but Not Propagated
**File:** `backend/app/services/event_broker.py` (the fix was partially applied)

After the DB transaction commits successfully, the Redis `publish()` call is inside the `async with session.begin():` block. However, if `publish()` raises ANY exception (Redis auth failure, network partition, JSON serialization error), the exception is caught and logged as `ERROR` but **not re-raised**. The event is permanently lost from Redis — subscribers polling via Redis will never see it. The DB has it, so `_subscribe_via_db()` will eventually retrieve it, but the real-time notification path is broken.

**Fix required:** After DB commit, if Redis publish fails, either:
(a) Re-raise and mark the event as "Redis-failed" in the DB so subscribers know to fall back to DB polling, or
(b) Queue the event in a retry table for later Redis delivery.

---

### 🟠 P1-C: Redis Connection Has No Timeout — Unbounded Hang
**File:** `backend/app/services/event_broker.py:47`

```python
self._redis: redis.asyncio.Redis = redis.asyncio.from_url(
    self._redis_url,
    encoding="utf-8",
    decode_responses=True,
)
```

`redis.asyncio.from_url()` creates a connection pool with **no connection timeout**. If the Redis server is unreachable, every `await` on a Redis operation (publish, subscribe, get, set) will hang indefinitely. There is no `socket_connect_timeout` or `socket_timeout` argument. A network partition will freeze the entire event broker.

---

## 3. LINGERING MOCKS & TECH DEBT

### 🟡 M1: `transientBuffer` — Dead Code Polluting the Type System
**File:** `src/stores/agentStore.ts:83`

```python
streamingMessages: Record<string, StreamingMessage>;
# ← transientBuffer is defined in the AgentState interface but is NEVER set or read
# anywhere in the codebase (verified by grep across all .ts/.tsx files).
# Initialized as {} (empty object) in the store defaults but type says Record<string, StreamingMessage>.
# This is dead code that was either partially implemented or left over from prototyping.
```

**Fix required:** Remove `transientBuffer` from `AgentState` interface and the store defaults entirely.

---

### 🟡 M2: `_flushInterval` Global Without Cleanup Guarantee
**File:** `src/stores/terminalStore.ts:43`

```typescript
let _flushInterval: ReturnType<typeof setInterval> | null = null;

function _startFlushTimer(set: ...): void {
    _flushInterval = setInterval(() => { ... }, 1000);
}

export const useTerminalStore = create<TerminalState>((set) => {
    _startFlushTimer(set);  // ← If this throws, _flushInterval is orphaned
    return { ... };
});
```

If `create()` throws during the store initialization (e.g., a subscriber callback throws), `_startFlushTimer` may not have been called, or `_flushInterval` could be left pointing to a stale interval. The interval is only cleared in `clearTerminal`'s `finally` block, which is only reached if `clearTerminal()` is explicitly called.

**Fix required:** Wrap `_startFlushTimer` call in try/catch in the store creation, or move interval creation into a useEffect with proper cleanup in a React component.

---

### 🟡 M3: API Base URL Exposed to Frontend Without Validation
**File:** `src/pages/AdminDashboard.tsx:38`

```typescript
const API_BASE = import.meta.env.VITE_API_BASE_URL?.trim() || '';
// ← If VITE_API_BASE_URL is empty or undefined, API_BASE is ''.
// fetch(`${API_BASE}/api/runs`) becomes fetch('/api/runs') which works in dev
// but silently hits the wrong origin in production if the env var is misconfigured.
```

---

## 4. SECURITY & STATE VULNERABILITIES

### 🟠 S1: Encryption Key Loaded from Environment — No Validation at Startup
**File:** `backend/app/services/crypto_service.py`

The `CryptoService` reads `ENCRYPTION_KEY` from `os.environ` and stores it in `_key`. If the key is missing or malformed at startup, the service initializes silently with an invalid key. All subsequent `decrypt()` calls will raise exceptions (caught by P0-D), but there is no startup validation that the key is the correct length or format. A misconfigured deployment will run with a weak or empty key without any warning.

---

### 🟠 S2: `_jail_path` Uses `pathlib.Path.is_relative_to()` — Symlink Escapes May Still Work
**File:** `backend/app/services/openhands_client.py:129` (after the audit fix)

The fix changed `startswith()` to `is_relative_to()`. However, `is_relative_to()` resolves symlinks in the **base path only** (`workspace_root`), not in the **requested path**. If a symlink exists inside the workspace that points outside (e.g., `/workspace/evil_link -> /etc`), then `_jail_path("sbox1", "evil_link")` will:
1. Extract `rel_path = "evil_link"` (stripping `/workspace/` prefix)
2. `full_path = abs_root / Path("evil_link")` → `/workspace/sbox1/evil_link`
3. `full_path.resolve()` → resolves `evil_link` to `/etc/passwd`
4. `is_relative_to(abs_root)` → `/etc/passwd` is NOT relative to `/workspace/sbox1` → **raises ValueError** ✅

This actually IS blocked correctly by `resolve()`. The original fix is sufficient. No further action needed.

---

### 🟠 S3: MCP Workspace Tools — No Rate Limiting or Audit Trail
**File:** `backend/app/agents/leader_agent.py`

The `workspace_read_file` and `workspace_exec` MCP tools are called without any rate limiting. A malicious or buggy Leader prompt injection could trigger unlimited file reads or command executions inside the sandbox. There is no:
- Per-run call count limit
- Audit log of which tool was called with what arguments
- Timeout enforcement per tool call

If the Leader LLM isprompt-injected to call `workspace_exec("rm -rf /workspace/*")`, it will execute immediately without any guard.

---

### 🟡 S4: AdminDashboard Auth Token in Memory Without Secure Storage
**File:** `src/pages/AdminDashboard.tsx`

```typescript
const res = await fetch(`${API_BASE}/api/auth/login`, { ... });
const { token } = await res.json();
localStorage.setItem('admin_token', token);  // ← Stored in localStorage
```

`localStorage` is accessible by any JavaScript on the same origin (including injected scripts via XSS). The token is also transmitted in plaintext on subsequent requests if HTTPS is not enforced. A more secure approach would use `httpOnly` cookies set by the backend.

---

## 5. EXECUTION MANDATE — PRIORITIZED FIX CHECKLIST

### P0 — MUST FIX BEFORE PRODUCTION (Active data corruption risk)

- [ ] **P0-A:** `dev_agent.py:535` — Ralph retry: re-raise after logging, or return explicit Ralph error result
- [ ] **P0-B:** `dev_agent.py:518` — Narrow Ralph exception to `SyntaxError` only; all others must fail explicitly
- [ ] **P0-C:** `dev_agent.py:492` — Check `llm_messages` grew after `conversation.run()`; if not, treat as Ralph failure
- [ ] **P0-D:** `run_manager.py:825` — Set `is_decryption_error = True` instead of `decrypted = ""`; log at CRITICAL
- [ ] **P0-E:** `run_manager.py:680` — Return explicit error from `_write_leader_guidance` if write fails; don't continue
- [ ] **P0-F:** `qa_agent.py` — `_collect_self_test_cases()` must raise on exception, not return `[]`

### P1 — MUST FIX (Reliability & security)

- [ ] **P1-A:** `agentStore.ts` — Freeze `streamingMessages` updates so components using `useAgentStore((s) => s.agents)` don't re-render on every delta. Use `immer` or structural sharing.
- [ ] **P1-B:** `event_broker.py` — After Redis publish fails, write a DB flag `redis_delivered=false` so subscribers know to fall back to DB polling
- [ ] **P1-C:** `event_broker.py:47` — Add `socket_connect_timeout=5, socket_timeout=10` to `redis.asyncio.from_url()`
- [ ] **P1-D:** `leader_agent.py` — Add rate limiting to MCP workspace tools (max N calls per run) and add audit logging

### P2 — SHOULD FIX (Technical debt & hardening)

- [ ] **M1:** `agentStore.ts:83` — Remove `transientBuffer` dead code from interface and defaults
- [ ] **M2:** `terminalStore.ts:43` — Wrap `_startFlushTimer` in try/catch; ensure `_flushInterval` is cleared on error
- [ ] **M3:** `AdminDashboard.tsx:38` — Validate `VITE_API_BASE_URL` is set at build time; fail build if empty
- [ ] **S1:** `crypto_service.py` — Validate `ENCRYPTION_KEY` length and format at startup; fail fast if invalid
- [ ] **S4:** `AdminDashboard.tsx` — Move admin auth token to `httpOnly` cookie set by backend

---

## LINE-EXACT FINDINGS INDEX

| ID | File | Line(s) | Severity | Issue |
|----|------|---------|----------|-------|
| P0-A | `dev_agent.py` | 535 | 🔴 CRITICAL | Ralph retry swallows LLM crash, falls through to empty output |
| P0-B | `dev_agent.py` | 518 | 🔴 CRITICAL | Ralph silently skips ALL errors (not just SyntaxError) |
| P0-C | `dev_agent.py` | 492 | 🔴 CRITICAL | Ralph retry succeeds but produces 0 new messages → loop exits having done nothing |
| P0-D | `run_manager.py` | 825 | 🔴 CRITICAL | `decrypted = ""` on exception → silent data corruption |
| P0-E | `run_manager.py` | 680 | 🔴 CRITICAL | Leadership guidance write fails → Dev fails with wrong error |
| P0-F | `qa_agent.py` | `_collect_self_test_cases` | 🔴 CRITICAL | Returns `[]` on exception — silent self-test failure |
| P1-A | `agentStore.ts` | `_mergeStreamingAgents` | 🟠 HIGH | New object ref every delta → unbounded re-render cascade |
| P1-B | `event_broker.py` | Redis publish block | 🟠 HIGH | Redis publish fails silently after DB commit — event lost |
| P1-C | `event_broker.py` | 47 | 🟠 HIGH | Redis connection has no timeout — unbounded hang on network partition |
| P1-D | `leader_agent.py` | MCP tool calls | 🟠 HIGH | No rate limiting or audit trail on workspace tools |
| M1 | `agentStore.ts` | 83 | 🟡 MEDIUM | `transientBuffer` dead code — never set or read anywhere |
| M2 | `terminalStore.ts` | 43 | 🟡 MEDIUM | `_flushInterval` global without guaranteed cleanup |
| M3 | `AdminDashboard.tsx` | 38 | 🟡 MEDIUM | `VITE_API_BASE_URL` silently defaults to `''` if missing |
| S1 | `crypto_service.py` | `__init__` | 🟠 HIGH | Encryption key not validated at startup — silent weak key |
| S4 | `AdminDashboard.tsx` | `localStorage.setItem` | 🟡 MEDIUM | Auth token stored in localStorage (XSS-readable) |

---

*Report generated: 2026-03-29*
*Audit level: Microscopic — line-by-line*
*Total findings: 15 (6 P0, 5 P1, 4 P2)*
