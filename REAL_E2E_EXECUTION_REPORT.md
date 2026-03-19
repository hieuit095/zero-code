# REAL E2E Execution Report

Date: 2026-03-19

## Scope

This was a real end-to-end execution of the ZeroCode multi-agent flow with no mocks, no simulated tool output, and no bypass of the OpenHands sandbox path.

Runtime used:

- Redis on `127.0.0.1:6379` via Docker
- Backend API on `http://127.0.0.1:8000`
- Background worker via `python -m worker`
- React/Vite frontend on `http://127.0.0.1:5173`
- SQLite dev database at `backend/e2e.db`

LLM provider and routing were configured to Together and verified live through the API:

```json
{
  "leaderModel": "zai-org/GLM-5",
  "leaderProvider": "together",
  "devModel": "openai/gpt-oss-120b",
  "devProvider": "together",
  "qaModel": "MiniMaxAI/MiniMax-M2.5",
  "qaProvider": "together"
}
```

Connection test result:

```json
{
  "success": true,
  "message": "API key valid - connection successful.",
  "provider": "together"
}
```

## Final Successful Run

Final green run used:

- Run ID: `run_901ca0182324`
- Workspace: `repo-e2e-live-20260319-g`
- Goal: create `calculator.py`, create `test_calculator.py`, and verify with `pytest`
- Final status: `completed`

Final snapshot:

```json
{
  "runId": "run_901ca0182324",
  "status": "completed",
  "phase": "done",
  "progress": 100,
  "workspaceId": "repo-e2e-live-20260319-g"
}
```

Final metrics:

```json
{
  "runId": "run_901ca0182324",
  "totalDurationMs": 295472,
  "qaFailureCount": 0,
  "totalCommandsExecuted": 4,
  "tasksCompleted": 2,
  "totalTasks": 2,
  "status": "completed"
}
```

Actual model-routing evidence from worker logs:

```text
-> together_ai/zai-org/GLM-5
together_ai/openai/gpt-oss-120b
together_ai/MiniMaxAI/MiniMax-M2.5
```

Actual planning/output evidence from the persisted event log:

```json
{"seq": 9, "type": "agent:message:delta", "data": {"delta": "Plan ready: 2 tasks.\n  1. Create calculator.py with pytest coverage\n  2. Create test_calculator.py with pytest coverage"}}
{"seq": 45, "type": "terminal:command", "data": {"agent": "qa", "command": "python -m pytest -q", "cwd": "/workspace"}}
{"seq": 46, "type": "terminal:output", "data": {"stream": "stdout", "text": ".....                                                                    [100%]\n5 passed in 0.03s\n"}}
{"seq": 97, "type": "run:complete", "data": {"status": "completed", "summary": "All 2 tasks completed successfully.", "qaRetries": 0, "durationMs": 295240}}
```

Actual sandbox result on disk after completion:

- `backend/workspaces/repo-e2e-live-20260319-g/calculator.py`
- `backend/workspaces/repo-e2e-live-20260319-g/test_calculator.py`
- `backend/workspaces/repo-e2e-live-20260319-g/critique_report.md`

## Retry Path Validation

I also validated the non-linear self-healing path on a separate real run:

- Run ID: `run_1af2d475912f`
- Workspace: `repo-e2e-live-20260319-f`

This run hit a real QA failure, transitioned into retry mode, then completed:

```json
{"seq": 40, "type": "qa:report", "data": {"status": "failed", "retryable": true}}
{"seq": 46, "type": "run:state", "data": {"status": "running", "phase": "retrying", "attempt": 1}}
{"seq": 48, "type": "agent:message:delta", "data": {"delta": "QA scored below thresholds: ... - retrying (attempt 1/3)..."}}
{"seq": 132, "type": "run:complete", "data": {"status": "completed"}}
```

That proves the real Dev -> QA -> retry loop executed in the OpenHands-backed path. The Tech Lead mentorship path was not needed in the final validated runs because the retry loop recovered before a second QA exhaustion.

## Bugs Found And Fixed

### 1. MCP facade was hardwired to `repo-main`

Symptom:

- Real runs created fresh workspaces, but Dev and QA MCP tools still operated on `backend/workspaces/repo-main`.

Root cause:

- MCP servers were mounted once at startup with a fixed workspace root and had no run-scoped workspace claim.

Fix:

- Added `workspace_id` to generated MCP JWTs in `backend/app/core/security.py`
- Passed `workspace_id` when minting the MCP token in `backend/app/orchestrator/run_manager.py`
- Reworked `backend/app/agents/mcp_tools.py` so each request resolves the workspace from the authenticated token instead of a startup constant
- Updated the mount log in `backend/app/api/mcp.py` to reflect fallback behavior

### 2. Leader planned redundant verification-only Dev tasks

Symptom:

- The planner emitted extra tasks such as "Run pytest to verify all tests pass", which caused redundant Dev cycles and stalls.

Fix:

- Tightened the planner prompt in `backend/app/agents/leader_agent.py`
- Added verification-task collapse logic in `backend/app/orchestrator/run_manager.py`

### 3. QA heuristics hallucinated expected files on Python tasks

Symptom:

- QA treated dotted identifiers like `pytest.raises` as file names and in one run pushed the flow toward an unintended `test_calc.py`.

Fix:

- Forced deterministic assisted review for Python-file tasks in `backend/app/agents/qa_agent.py`
- Restricted expected-file extraction to real file suffixes in `backend/app/agents/qa_agent.py`

### 4. Dev summaries leaked raw SDK/tool-call repr text

Symptom:

- Some Dev `agent:message` events included raw `tool_calls=[...]` or other unstructured SDK text instead of a clean summary.

Fix:

- Updated `backend/app/agents/llm_utils.py` to extract the structured `finish(...)` payload before falling back to `str(message)`

### 5. Leader planning failed hard on malformed/empty model output

Symptom:

- Run `run_d1660837e837` failed in planning with `JSON_PARSE_ERROR: Expecting value: line 1 column 1 (char 0)`.

Root cause:

- `LeaderAgent` treated any non-JSON planner response as a terminal failure.

Fix:

- Hardened `backend/app/agents/leader_agent.py` so malformed planner output falls back to a deterministic minimal task list derived from the goal instead of killing the run immediately

### 6. `run:complete` hardcoded `qaRetries: 0`

Symptom:

- In retrying run `run_1af2d475912f`, the metrics endpoint correctly reported `qaFailureCount: 1`, but the terminal `run:complete` event still emitted `qaRetries: 0`.

Fix:

- Updated `backend/app/orchestrator/run_manager.py` so the completion event reads the real QA failure count from `RunStore` before emitting `run:complete`

## Changed Source Files

- `backend/app/agents/leader_agent.py`
- `backend/app/agents/llm_utils.py`
- `backend/app/agents/mcp_tools.py`
- `backend/app/agents/qa_agent.py`
- `backend/app/api/mcp.py`
- `backend/app/core/security.py`
- `backend/app/orchestrator/run_manager.py`

## Evidence Artifacts

Primary green-run artifacts:

- `output/e2e/run_901ca0182324.meta.json`
- `output/e2e/run_901ca0182324.snapshot.json`
- `output/e2e/run_901ca0182324.eventlog.jsonl`

Retry-path validation artifacts:

- `output/e2e/run_1af2d475912f.meta.json`
- `output/e2e/run_1af2d475912f.snapshot.json`
- `output/e2e/run_1af2d475912f.eventlog.jsonl`

Earlier remediation artifacts:

- `output/e2e/run_1c2b23b7ac27.meta.json`
- `output/e2e/run_1c2b23b7ac27.snapshot.json`
- `output/e2e/run_1c2b23b7ac27.eventlog.jsonl`
- `output/e2e/run_d1660837e837.meta.json`
- `output/e2e/run_d1660837e837.snapshot.json`
- `output/e2e/run_d1660837e837.eventlog.jsonl`

## Conclusion

The repository now completes a real Together-backed multi-agent workflow end to end through the actual OpenHands sandboxed path. Planning, Dev execution, QA sandbox verification, persisted event logging, and retry behavior were all exercised with live services and real model calls.
