## 2024-04-03 - Agent Chat Re-render Bottleneck
**Learning:** In `AgentChatter.tsx`, high-frequency WebSocket streaming events (e.g., token-by-token LLM output) caused the entire message history to re-render. Because the `messages` array was mapped inline, every incoming token triggered a full DOM reconciliation for all historical chat bubbles, resulting in an O(N) render cost that degraded performance linearly as the chat lengthened.
**Action:** Always extract items mapped in high-frequency update loops (like streaming logs or chat tokens) into separate components wrapped in `React.memo()`. This creates an O(1) rendering cost where only the actively changing item re-renders, preventing UI stuttering and wasted CPU cycles.

## 2024-04-04 - React Recursive Tree Re-render Bottleneck
**Learning:** In `FileExplorer.tsx`, rendering a deeply nested file tree recursively triggered an O(N) re-render of every single file node whenever the global `selectedId` changed, because normal `React.memo` shallow comparison fails to capture derived state logic.
**Action:** When memoizing recursive branch/leaf tree components based on a global ID (like `selectedId`), implement a custom `arePropsEqual` function. Crucially, always ensure branch nodes (folders) return `false` to propagate the changes down the tree, while leaf nodes (files) only re-render if their specific selection status toggled.
