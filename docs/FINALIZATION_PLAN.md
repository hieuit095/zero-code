# FINALIZATION_PLAN.md

### A. Executive Summary
The codebase provides a solid foundation for the Multi-Agent IDE described in `PROJECT_KNOWLEDGE.md`, but it is currently not production-ready. The prototype frontend has been partially ported to transport-driven state, but several mock artifacts remain. The backend orchestra properly utilizes the Dev and QA loop, but fails to adhere to the non-linear Leader escalation policy and exhibits severe security vulnerabilities. Specifically, the "sandbox" execution model defaults to the host machine, escaping isolation completely when the OpenHands SDK is unavailable.

### B. Critical Violations & Bugs
1. **Sandbox Escape (Architecture Violation)**: 
   - `backend/app/services/openhands_client.py` falls back to `asyncio.create_subprocess_shell()` if the OpenHands SDK is not initialized, allowing agents to execute arbitrary commands directly on the host instance.
   - File operations (`list_tree`, `read_file`, `write_file`) in `openhands_client.py` use the native `os` and `pathlib` modules on the backend host filesystem instead of executing through the OpenHands isolation layer.
2. **Authentication Bypass (Security Loophole)**: 
   - `backend/app/core/security.py`'s `require_mcp_auth` dependency allows an unconditional bypass of JWT validation if the legacy `X-Run-Id` header is present. This exposes the MCP tools to unauthenticated actors.
3. **Orchestration Loop Deviation**:
   - `backend/app/orchestrator/run_manager.py` fails to escalate to the Leader when Max QA retries are exhausted. Instead of pausing and asking the Leader to re-plan (as demanded by `PROJECT_KNOWLEDGE.md`), `execute_run` directly sets the run status to `FAILED` and aborts the entire workflow.
4. **Command Policy Weakness (Security Loophole)**: 
   - `backend/app/services/command_policy.py` relies on naive Regex for its blocklist. It blocks `rm -rf /` but fails to block `rm -rf .` or obfuscated commands.

### C. Technical Debt & Mock Data
1. **Frontend Mocks & Scaffolding**:
   - `src/data/mockData.ts`: Retains an in-memory `mockEditorFiles` map that is dangerously mutated instead of relying purely on Zustand state.
   - `src/simulation/agentSimulation.ts`: Exists as pure simulation scaffolding.
   - `src/components/Header.tsx`: The "Generate" action uses a `setTimeout` mock instead of instantly dispatching correctly.
   - `src/components/settings/APIFeedSetupPage.tsx`: The "Test Connection" button uses a mock `setTimeout` delay instead of real REST verification.
2. **Hardcoded Configurations**:
   - `src/hooks/useRunConnection.ts`: Hardcodes `DEFAULT_API_BASE_URL = 'http://localhost:8000'`.
   - `backend/app/services/event_broker.py`: Hardcodes `REDIS_URL = "redis://localhost:6379/0"`.
   - `infra/staging/docker-compose.yml`: Binds `VITE_API_BASE_URL=http://localhost:8000` via env-vars directly.

### D. Missing Edge Case Handling
1. **Worker and Redis Failures**:
   - `backend/worker.py` catches all exceptions during `broker.dequeue_run()` but does not implement a reconnect backoff strategy.
   - Unhandled exceptions in `get_run_manager().execute_run()` inside the `worker.py` are logged but the run is never marked as `FAILED` in the database, resulting in a zombie run state.
2. **Missing Admin Dashboard (UX Disconnect)**:
   - File `AdminDashboard.tsx` is completely missing from the `src/` directory despite being required to wire `GET /api/admin/metrics`.
3. **WebSocket Disconnects (UX Disconnect)**:
   - `src/hooks/useRunConnection.ts` catches socket closures but fails to bubble a visual toast or actionable UI state for the user to understand connection loss.

### E. The Finalization Roadmap

- [ ] **High Priority (Must fix before staging)**
  1. Remove `asyncio.create_subprocess_shell` fallback in `openhands_client.py` and enforce strict OpenHands execution.
  2. Remove `os.walk` and direct host disk I/O in `openhands_client.py` and tunnel file actions strictly through the SDK.
  3. Remove the `X-Run-Id` bypass from `security.py` immediately.
  4. Fix the task failure state transition in `run_manager.py` to route back to `LeaderAgent` instead of aborting the run.

- [ ] **Medium Priority (Stability & UX)**
  1. Delete `mockData.ts` and `agentSimulation.ts`.
  2. Refactor `CommandPolicy.py` from naive Regex matching to a robust command parser (e.g. `shlex.split`) to catch `rm -rf` variations and destructive pipes.
  3. Plumb `worker.py` catch-all exceptions into `RunStore.update_run()` to safely record failed states.
  4. Add visual toast notifications for WebSocket disconnects in the React shell.

- [ ] **Low Priority (Refactoring & Polish)**
  1. Implement `AdminDashboard.tsx` and wire it to the `/api/admin/metrics` endpoint.
  2. Centralize URL resolutions instead of hardcoding `localhost:8000` globally.
  3. Strip `setTimeout` simulations from frontend elements.
