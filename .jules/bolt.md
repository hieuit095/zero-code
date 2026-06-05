## 2024-04-03 - Agent Chat Re-render Bottleneck
**Learning:** In `AgentChatter.tsx`, high-frequency WebSocket streaming events (e.g., token-by-token LLM output) caused the entire message history to re-render. Because the `messages` array was mapped inline, every incoming token triggered a full DOM reconciliation for all historical chat bubbles, resulting in an O(N) render cost that degraded performance linearly as the chat lengthened.
**Action:** Always extract items mapped in high-frequency update loops (like streaming logs or chat tokens) into separate components wrapped in `React.memo()`. This creates an O(1) rendering cost where only the actively changing item re-renders, preventing UI stuttering and wasted CPU cycles.

## 2024-06-05 - React Recursive Tree Re-render Bottleneck
**Learning:** Standard React.memo() shallow comparison fails to optimize recursive tree components (like File Explorer) when passing a globally active ID (e.g. selectedId). This causes O(N) re-renders across the whole tree on any selection change.
**Action:** To achieve O(1) re-renders, provide a custom arePropsEqual function to React.memo(). Crucially, branch nodes (folders) must always return false to propagate new props, while leaf nodes (files) only re-render if their specific selection state changes. Always pair this with useCallback for child handlers.
