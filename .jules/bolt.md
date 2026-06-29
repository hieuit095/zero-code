## 2024-04-03 - Agent Chat Re-render Bottleneck
**Learning:** In `AgentChatter.tsx`, high-frequency WebSocket streaming events (e.g., token-by-token LLM output) caused the entire message history to re-render. Because the `messages` array was mapped inline, every incoming token triggered a full DOM reconciliation for all historical chat bubbles, resulting in an O(N) render cost that degraded performance linearly as the chat lengthened.
**Action:** Always extract items mapped in high-frequency update loops (like streaming logs or chat tokens) into separate components wrapped in `React.memo()`. This creates an O(1) rendering cost where only the actively changing item re-renders, preventing UI stuttering and wasted CPU cycles.

## 2024-05-18 - Recursive Component Memoization with Context Props
**Learning:** When passing a globally active ID (e.g., `selectedId`) as a prop down a recursive tree (like a File Tree component), standard `React.memo()` shallow comparison will not yield O(1) re-renders.
**Action:** To achieve O(1) re-renders, provide a custom `arePropsEqual` function that evaluates derived state. Branch nodes (folders) must always re-render (return `false`) to propagate new props to children, while leaf nodes (files) can be memoized based on specific state changes (e.g., selection). Avoid naming the internal function the same as the memoized wrapper.
