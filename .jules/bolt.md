## 2024-04-03 - Agent Chat Re-render Bottleneck
**Learning:** In `AgentChatter.tsx`, high-frequency WebSocket streaming events (e.g., token-by-token LLM output) caused the entire message history to re-render. Because the `messages` array was mapped inline, every incoming token triggered a full DOM reconciliation for all historical chat bubbles, resulting in an O(N) render cost that degraded performance linearly as the chat lengthened.
**Action:** Always extract items mapped in high-frequency update loops (like streaming logs or chat tokens) into separate components wrapped in `React.memo()`. This creates an O(1) rendering cost where only the actively changing item re-renders, preventing UI stuttering and wasted CPU cycles.

## 2026-04-11 - Task List Re-render Bottleneck
**Learning:** In `TasksPanel.tsx`, high-frequency status updates and QA score streaming caused the entire task list to re-render. Because the `tasks` array was mapped inline, every status change triggered a full DOM reconciliation for all tasks.
**Action:** Extracted the mapped items into `TaskItem` and `ScoreBar` components wrapped in `React.memo()`. Wrapped the `toggle` handler in `useCallback()` and derived state in `useMemo()`. This converts an O(N) re-render bottleneck into an O(1) operation where only the affected task re-renders.
