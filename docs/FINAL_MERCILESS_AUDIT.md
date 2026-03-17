# FINAL MERCILESS AUDIT
**Date:** 2026-03-16
**Role:** Principal Systems Architect & Lead Security Auditor
**Verdict:** CRITICAL FAIL. SYSTEM IS UNFIT FOR DEPLOYMENT.

This system projects an illusion of stability while being riddled with execution bypasses, fatal race conditions, and catastrophic logic holes that will silently drop state and compromise the host environment. Below is the unvarnished reality of the codebase.

### 1. Integration Seam Failures (Critical)

**1.1 The Hydration Overwrite Race Condition ([useRunConnection.ts](file:///c:/Users/USER/Documents/GitHub/zero-code/src/hooks/useRunConnection.ts))**
- **Location:** `socket.onopen` -> [hydrateFromSnapshot()](file:///c:/Users/USER/Documents/GitHub/zero-code/src/hooks/useRunConnection.ts#401-439)
- **Vulnerability:** When the WebSocket reconnects, [hydrateFromSnapshot](file:///c:/Users/USER/Documents/GitHub/zero-code/src/hooks/useRunConnection.ts#401-439) is triggered asynchronously. During the 100-300ms network roundtrip to fetch the REST snapshot, the newly opened WebSocket is *actively streaming live events*. Those live events mutate the Zustand store. Once the slower REST promise finally resolves, it blindly overwrites the newest real-time state with stale snapshot data fetched *before* those events occurred.
- **Impact:** Permanent desynchronization between Backend and Frontend. Progress updates, tasks, and terminal streams will visually revert.

**1.2 Separated Transactions Race ([run_manager.py](file:///c:/Users/USER/Documents/GitHub/zero-code/backend/app/orchestrator/run_manager.py))**
- **Location:** State Emission logic ([_emit](file:///c:/Users/USER/Documents/GitHub/zero-code/backend/app/orchestrator/run_manager.py#153-155) vs [_persist_task_status](file:///c:/Users/USER/Documents/GitHub/zero-code/backend/app/orchestrator/run_manager.py#147-150))
- **Vulnerability:** Task statuses are emitted to Redis pub/sub ([_emit("task:update")](file:///c:/Users/USER/Documents/GitHub/zero-code/backend/app/orchestrator/run_manager.py#153-155)) before or completely separate from being committed to PostgreSQL ([_persist_task_status(...)](file:///c:/Users/USER/Documents/GitHub/zero-code/backend/app/orchestrator/run_manager.py#147-150)). If the React client drops precisely during this nanosecond gap, the immediate snapshot fetch will pull the older SQL row, completely masking the emitted event and breaking the frontend's progression state.

### 2. Sandbox & Cognition Flaws (Critical)

**2.1 The MCP `cwd` Jailbreak ([mcp.py](file:///c:/Users/USER/Documents/GitHub/zero-code/backend/app/api/mcp.py) / [openhands_client.py](file:///c:/Users/USER/Documents/GitHub/zero-code/backend/app/services/openhands_client.py))**
- **Location:** [mcp.py](file:///c:/Users/USER/Documents/GitHub/zero-code/backend/app/api/mcp.py) ([MCPExecRequest](file:///c:/Users/USER/Documents/GitHub/zero-code/backend/app/api/mcp.py#124-130) and [mcp_exec](file:///c:/Users/USER/Documents/GitHub/zero-code/backend/app/agents/mcp_tools.py#74-96))
- **Vulnerability:** While [mcp_read_file](file:///c:/Users/USER/Documents/GitHub/zero-code/backend/app/agents/mcp_tools.py#50-60) and [mcp_write_file](file:///c:/Users/USER/Documents/GitHub/zero-code/backend/app/agents/mcp_tools.py#62-72) protect against path traversal using the airtight [_jail_path](file:///c:/Users/USER/Documents/GitHub/zero-code/backend/app/api/mcp.py#37-94) helper, [mcp_exec](file:///c:/Users/USER/Documents/GitHub/zero-code/backend/app/agents/mcp_tools.py#74-96) blindly accepts an unvalidated `cwd` (Current Working Directory) from the Nanobot's JSON payload. 
  `result = await client.execute_command(workspace_id, body.command, body.cwd)`
- **Impact:** Total sandbox breach. A rogue agent merely sends `{"command": "cat /etc/shadow", "cwd": "/"}` to bypass the `/workspace` confinement entirely via the shell layer context.

**2.2 Blind Silence in Error Parsing ([openhands_client.py](file:///c:/Users/USER/Documents/GitHub/zero-code/backend/app/services/openhands_client.py) & [qa_agent.py](file:///c:/Users/USER/Documents/GitHub/zero-code/backend/app/agents/qa_agent.py))**
- **Location:** [openhands_client.py](file:///c:/Users/USER/Documents/GitHub/zero-code/backend/app/services/openhands_client.py) (CmdOutputObservation mapping) and [qa_agent.py](file:///c:/Users/USER/Documents/GitHub/zero-code/backend/app/agents/qa_agent.py) (Error extraction)
- **Vulnerability:** In [openhands_client.py](file:///c:/Users/USER/Documents/GitHub/zero-code/backend/app/services/openhands_client.py), the SDK natively merges `stderr` into stdout. The service responds by hardcoding `"stderr": ""` back to the caller. However, `qa_agent.py:324` relies completely on extracting lines from `result["stderr"]` to build structured [QaError](file:///c:/Users/USER/Documents/GitHub/zero-code/backend/app/agents/qa_agent.py#113-121) reports for Python code (e.g., `python -m py_compile`). 
- **Impact:** Critical cognitive failure. Because `stderr` is permanently empty, the QA agent silently eats error messages for all Python files. It registers zero syntax flaws and passes critically broken applications into production.

### 3. Orchestration Edge Cases (High)

**3.1 The Infinite Replanning Void ([run_manager.py](file:///c:/Users/USER/Documents/GitHub/zero-code/backend/app/orchestrator/run_manager.py))**
- **Location:** [execute_run()](file:///c:/Users/USER/Documents/GitHub/zero-code/backend/app/orchestrator/run_manager.py#220-456), under the Escalation to Leader block (line 413)
- **Vulnerability:** Upon task failure, the Leader generates `new_tasks` to inject. The manager executes:
  `tasks = list(tasks) + list(new_tasks)`
  However, the running loop is driven by `for task_idx, task in enumerate(tasks):`. Python iterators lock over the original object reference. Reassigning the local variable [tasks](file:///c:/Users/USER/Documents/GitHub/zero-code/backend/app/services/run_store.py#72-92) does not extend the running loop iteration.
- **Impact:** Fatal workflow corruption. The system abandons newly generated replacement tasks, dropping them into the void, and halts claiming "All tasks completed successfully". 

**3.2 The Blind Pre-Warmer ([qa_agent.py](file:///c:/Users/USER/Documents/GitHub/zero-code/backend/app/agents/qa_agent.py))**
- **Location:** [_ensure_node_env()](file:///c:/Users/USER/Documents/GitHub/zero-code/backend/app/agents/qa_agent.py#183-213)
- **Vulnerability:** The pre-warmer strictly checks for `package.json` at the absolute root of the workspace. If the node.js app is inside a monorepo or standard subdirectory (e.g., `/workspace/frontend/package.json`), the check defaults to "not a node project" and aborts `npm install`. 
- **Impact:** The ensuing `npx tsc` call will panic due to missing node modules. The QA agent classifies this as a non-retryable "ENVIRONMENT ERROR" and instantly fails the entire developer pipeline, resulting in an unrecoverable run.

### 4. Code Quality & Tech Debt (Medium)

**4.1 Silent Death Protocols ([worker.py](file:///c:/Users/USER/Documents/GitHub/zero-code/backend/worker.py))**
- **Location:** [process_run()](file:///c:/Users/USER/Documents/GitHub/zero-code/backend/worker.py#50-87) global exception handler.
- **Vulnerability:** If [get_run_manager().execute_run()](file:///c:/Users/USER/Documents/GitHub/zero-code/backend/app/orchestrator/run_manager.py#589-594) catastrophically crashes (e.g., a fatal DB timeout before the manager's internal `try/catch`), the worker traps the error, writes `failed` to the DB, but NEVER publishes a `run:error` event via the Redis Broker. The frontend client will spin completely unaware of the host crash.

**4.2 Timer Leak ([terminalStore.ts](file:///c:/Users/USER/Documents/GitHub/zero-code/src/stores/terminalStore.ts))**
- **Location:** [_stopFlushTimer()](file:///c:/Users/USER/Documents/GitHub/zero-code/src/stores/terminalStore.ts#60-66)
- **Vulnerability:** Unreachable dead code. The setInterval [_startFlushTimer](file:///c:/Users/USER/Documents/GitHub/zero-code/src/stores/terminalStore.ts#40-59) is invoked but the teardown logic is orphaned. In hot-reload or unmounting scenarios (if the Zustand stores are re-created), this will stack infinite, uncollectable phantom interval loops resulting in massive DOM update collisions.

**4.3 Brittle QA Heuristics**
- **Location:** [_classify_ts_error()](file:///c:/Users/USER/Documents/GitHub/zero-code/backend/app/agents/qa_agent.py#214-234)
- **Vulnerability:** Checking for `error TS2307` via strict string inclusion is fragile. Transpiler upgrades, localization changes, or terminal color ANSI parsing leaks will crack this pattern, triggering bizarre, hallucinated QA decisions.

### 5. Final Verdict & Remediation Mandates
You must halt roadmap progression until the following patches are forced into the system:
1. **[CRITICAL] Jail the `cwd` argument** in `mcp.py:mcp_exec`. It must pass through [_jail_path](file:///c:/Users/USER/Documents/GitHub/zero-code/backend/app/api/mcp.py#37-94).
2. **[CRITICAL] Fix Iterator Expansion** in [run_manager.py](file:///c:/Users/USER/Documents/GitHub/zero-code/backend/app/orchestrator/run_manager.py). Refactor to a `while task_idx < len(tasks)` approach to safely allow dynamic append arrays.
3. **[CRITICAL] Correct the `stderr` logic** in [qa_agent.py](file:///c:/Users/USER/Documents/GitHub/zero-code/backend/app/agents/qa_agent.py). It MUST query from `stdout` due to OpenHands SDK merging outputs.
4. **[HIGH] Invert Reconnect Hydration** in React. You must defer processing of [onmessage](file:///c:/Users/USER/Documents/GitHub/zero-code/src/hooks/useRunConnection.ts#478-495) WebSocket packets inside a queue *until* [hydrateFromSnapshot](file:///c:/Users/USER/Documents/GitHub/zero-code/src/hooks/useRunConnection.ts#401-439) fully resolves and triggers a flush callback.
5. **[MEDIUM] Broaden QA Pre-Warming** to use the `find` command to detect deep `package.json` configurations prior to skipping installs.
6. **[MEDIUM] Add Broker emission** upon raw exceptions in [worker.py](file:///c:/Users/USER/Documents/GitHub/zero-code/backend/worker.py). 
