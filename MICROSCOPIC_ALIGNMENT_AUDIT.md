# MICROSCOPIC_ALIGNMENT_AUDIT

### 1. The Reality Check (Executive Summary)
The current codebase is a **fake prototype** regarding its execution substrate. Despite the documentation claiming a secure, isolated sandbox powered by the OpenHands SDK, the entire system operates directly on the host machine. The Multi-Agent IDE uses local `subprocess` and built-in Python file I/O instead of instantiating OpenHands `Runtime` or translating commands into `Action`/`Observation` SDK constructs. While the API layer and the `Nanobot` conversational abstractions (`LeaderAgent`, `DevAgent`, `QaAgent`) are mostly faithful, the underlying muscle—the sandbox—is a complete illusion disguised by simple path-string validation (`os.path.realpath`).

### 2. Nanobot Coordination Deviations
While the `TaskDelegator` correctly invokes the Nanobot `LeaderAgent` in `mentorship_mode`, the method of transferring the generated mentorship guidance completely violates the architectural mandates. The orchestrator intercepts the result and writes it directly to the host filesystem, bypassing any agent tools or OpenHands boundaries. The orchestrator also reads the critique directly from the host filesystem.

- **File**: `backend/app/orchestrator/run_manager.py`
- **Lines 447-456**: Destructive Direct File Write
  ```python
          try:
              from ..config import get_settings
              settings = get_settings()
              guidance_path = settings.workspace_path / "repo-main" / "leader_guidance.md"
              guidance_path.write_text(guidance, encoding="utf-8")
              ...
  ```
- **Lines 362-371**: Direct File Access Bypassing SDK
  ```python
      async def _emit_critique_artifact(self) -> None:
          try:
              from ..config import get_settings
              settings = get_settings()
              critique_path = settings.workspace_path / "repo-main" / "critique_report.md"
              if critique_path.exists():
                  content = critique_path.read_text(encoding="utf-8", errors="replace")
                  ...
  ```

### 3. OpenHands Sandbox Violations
The `sandbox-mcp` service and the `WorkspaceFS` are completely faked. Neither spawns an OpenHands runtime nor routes commands to an isolated sandbox. The tools directly map to the backend Python host, creating a critical vulnerability where any agent can run raw system commands and manipulate the host server's local storage.

- **File**: `backend/app/agents/mcp_tools.py`
- **Lines 200-209**: Subprocess execution on the host machine
  ```python
          try:
              result = subprocess.run(
                  command,
                  shell=True,
                  cwd=host_cwd,
                  capture_output=True,
                  text=True,
                  timeout=120,
              )
  ```
- **Lines 100-101 and 126-127**: Standard python disk access
  ```python
              with open(safe_path, "r", encoding="utf-8") as f:
              ...
              with open(safe_path, "w", encoding="utf-8") as f:
  ```

- **File**: `backend/app/services/openhands_client.py`
- **Lines 88-103**: The class `WorkspaceFS` explicitly admits to avoiding OpenHands. "Does NOT spawn any OpenHands Runtime. All operations use the host filesystem anchored to the configured WORKSPACE_ROOT"
- **Lines 190-192**:
  ```python
          return await asyncio.to_thread(host_path.read_text, "utf-8")
  ```

### 4. Missing Features (Doc vs Code)
The following architectural promises are entirely missing or falsified:
- **Missing OpenHands Action Translation**: `SYSTEM_ARCHITECTURE.md` explicitly claims that the MCP facade translates endpoints to native SDK classes (`FileReadAction`, `CmdRunAction`, `CmdOutputObservation`). These do not exist anywhere in the code.
- **Missing Workspace Lifecycle Management**: `PROJECT_KNOWLEDGE.md` and `deployment-plan.md` mandate the `create_workspace()` and `destroy_workspace()` endpoints to isolate runs. There is no remote agent server provisioned; the frontend just mounts a static `repo-main` path.
- **Rule 2 Violated**: `PROJECT_KNOWLEDGE.md` Rule 2 dictates Nanobot agents MUST NEVER use local shell tools. The entire MCP facade explicitly offers `subprocess.run(shell=True)`.

### 5. Architectural Mandates
The following prioritized checklist must be executed to achieve true architectural alignment:
1. **Rip out `subprocess.run()` from `mcp_tools.py`**: Replace the local bash execution with actual OpenHands remote agent server API calls or SDK Runtime bindings.
2. **Remove native `open()` file I/O from MCP Tools**: Connect `read_file` and `write_file` directly to the OpenHands SDK `FileReadAction` and `FileWriteAction`.
3. **Remove Host Interactions from `run_manager.py`**: Stop `TaskDelegator._emit_critique_artifact` and `_delegate_to_leader_mentor` from doing `Path(...).write_text()`. They must use the OpenHands client to read and write files into the sandbox.
4. **Implement Real Sandboxing Lifecycle**: Flesh out `services/openhands_client.py` to actually spin up and destroy isolated Docker containers or Remote Agent Servers for new runs, rather than blindly mapping to a static host directory wrapper.
