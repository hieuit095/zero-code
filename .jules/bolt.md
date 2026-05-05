## 2024-04-03 - Agent Chat Re-render Bottleneck
**Learning:** In `AgentChatter.tsx`, high-frequency WebSocket streaming events (e.g., token-by-token LLM output) caused the entire message history to re-render. Because the `messages` array was mapped inline, every incoming token triggered a full DOM reconciliation for all historical chat bubbles, resulting in an O(N) render cost that degraded performance linearly as the chat lengthened.
**Action:** Always extract items mapped in high-frequency update loops (like streaming logs or chat tokens) into separate components wrapped in `React.memo()`. This creates an O(1) rendering cost where only the actively changing item re-renders, preventing UI stuttering and wasted CPU cycles.

## 2024-05-24 - Recursive Component Memoization
**Learning:** When passing globally active IDs (like `selectedId`) down a recursive tree like `FileExplorer`, standard `React.memo()` fails to yield O(1) re-renders, and naive memoization breaks state propagation.
**Action:** Provide a custom `arePropsEqual` that forces branch nodes (folders) to always re-render (return false) to propagate state, and only memoizes leaf nodes based on derived state changes. Use distinct internal names when memoizing recursive components to prevent the inner name from shadowing the memoized wrapper. Wrap callbacks in `useCallback` when passing to memoized children.
