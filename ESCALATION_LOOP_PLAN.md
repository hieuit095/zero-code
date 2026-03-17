# ESCALATION_LOOP_PLAN

### 1. Executive Summary
The "Mentorship Loop" introduces a cost-optimized escalation pathway to handle complex tasks where the low-cost `Dev` agent gets stuck in a failure cycle. Instead of failing the entire task and forcing the high-cost `Leader` agent to re-plan everything from scratch (which consumes massive context and compute), the system intercepts the task after **2 failed Dev attempts**. The `Leader` is brought in temporarily in a targeted *Mentorship Mode* to analyze the QA critique and the broken code, and provide explicit guidance. The `Dev` is then given a final attempt armed with this high-level architectural insight. This significantly increases success rates on hard problems while reserving the expensive reasoning model only for targeted interventions.

### 2. State Machine Modifications (`run_manager.py`)
Currently, `TaskDelegator.execute()` runs a loop for `attempt in range(1, self._max_retries + 2)`. If it exceeds `_max_retries` (which is 2), it breaks and fails.

**New State & Flow:**
- Introduce a new state: `RunState.LEADER_REVIEW = "leader-review"`.
- Modify `TaskDelegator.execute()` loop to allow one final attempt post-mentorship.
  - **Attempt 1:** Standard `Dev` -> `QA`.
  - **Attempt 2:** Standard `Dev` retry (with `critique_report.md`) -> `QA`.
  - **Intercept:** If Attempt 2 fails, transition to `RunState.LEADER_REVIEW`.
  - **Mentorship Phase:** Invoke a `_delegate_to_leader_mentor()` method. The Leader reads the workspace and outputs guidance.
  - **Attempt 3:** `Dev` executes again, but the `dev_input` prompt is heavily augmented with the Leader's guidance.

**Context Preservation:**
The `RunManager` already initializes a single `LeaderAgent` instance per run. Because `LeaderAgent.run()` utilizes the `LLMSummarizingCondenser` (which squashes older messages while keeping the system prompt and newest interactions), we can safely reuse the same `Conversation` or instantiate a scoped one for the mentorship phase without exploding the context window.

### 3. Prompt & Context Engineering

**Leader Agent (Mentorship Mode):**
We must add a secondary system prompt to `leader_agent.py`: `LEADER_MENTORSHIP_PROMPT`. 
- **Instructions:** "You are the Tech Lead. The Dev agent has failed to implement the current task after 2 attempts. Your job is to rescue this task. Use your MCP tools (`execute_bash`, `str_replace_editor`) to read `critique_report.md` and inspect the broken code. Do NOT write code. Output a concise, authoritative diagnosis of what went wrong architecturally and step-by-step instructions on how the Dev agent must fix it. Do NOT output JSON tasks. Output plain markdown guidance."
- **Execution:** Modify `LeaderAgent.run()` to accept a `mentorship_mode=True` parameter capable of bypassing the JSON array parsing (`_parse_result`) and instead returning the raw LLM string wrapped in a `LeaderAgentResult`.

**Dev Agent (Receiving Guidance):**
When the `Leader` completes its mentorship review, the `TaskDelegator` will capture the output.
- **Delivery Mechanism:** To ensure the Dev agent firmly anchors on the guidance, the orchestrator will do both:
  1. Generate an artifact via `_emit_fs_update(..., "leader_guidance.md", leader_output, "tech-lead")` so the Dev can see it in the file tree.
  2. Inject a high-priority system message into the subsequent `dev_input` for Attempt 3: 
     *"URGENT: Your previous attempts failed. The Tech Lead has intervened and provided an architectural fix. Read `/workspace/leader_guidance.md` carefully and follow its steps exactly to complete the task."*

### 4. Step-by-Step Implementation Guide

- [ ] **Step 1: Update `leader_agent.py`**
  - Add `LEADER_MENTORSHIP_PROMPT`.
  - Modify `LeaderAgentConfig` or `LeaderAgent.run()` signatures to accept `mentorship_mode: bool = False`.
  - In `LeaderAgent.run()`, if `mentorship_mode` is True, swap the injected system prompt, and bypass JSON parsing, returning the raw text inside `LeaderAgentResult(status="done", raw_output=text, summary="Mentorship complete")`.

- [ ] **Step 2: Update `RunState` in `run_manager.py`**
  - Add `LEADER_REVIEW = "leader-review"` to the `RunState` class.

- [ ] **Step 3: Add `TaskDelegator._delegate_to_leader_mentor()` in `run_manager.py`**
  - Create this async method matching the signature style of `_delegate_to_dev`.
  - It should emit `run:state` (`leader-review`), `agent:status` (`tech-lead`, `thinking`), and `agent:message` indicating the Tech Lead is reviewing the failure.
  - Call `self._mgr._leader_agent.run(..., mentorship_mode=True)`.
  - Emit an `fs:update` for `leader_guidance.md` containing the Leader's raw output.

- [ ] **Step 4: Modify `TaskDelegator.execute()` in `run_manager.py`**
  - Change the loop to handle the mentorship interception:
    ```python
    for attempt in range(1, self._max_retries + 3): # Allow 3 attempts total (2 normal + 1 mentor)
        ...
        if qa_outcome != "passed":
            if attempt == self._max_retries:
                # Trigger Mentorship Phase
                mentor_guidance = await self._delegate_to_leader_mentor(failing_dims)
                dev_input = (
                    f"URGENT: Tech Lead intervention. You failed 2 attempts.\n"
                    f"Read /workspace/leader_guidance.md and apply this exact fix:\n"
                    f"{mentor_guidance}"
                )
            elif attempt > self._max_retries:
                break # Final attempt failed, task fails completely.
            else:
                # Standard _prepare_retry
                await self._prepare_retry(attempt, failing_dims)
                dev_input = f"... standard retry message referencing critique ..."
    ```

- [ ] **Step 5: Frontend Visibility (Optional but recommended)**
  - Ensure the frontend `FileStore` reacts to the `"tech-lead"` author in the `fs:update` event, potentially highlighting `leader_guidance.md` in the UI to show the user the escalation is happening in real-time.
