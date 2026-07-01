## 2024-04-03 - Agent Chat Re-render Bottleneck
**Learning:** In `AgentChatter.tsx`, high-frequency WebSocket streaming events (e.g., token-by-token LLM output) caused the entire message history to re-render. Because the `messages` array was mapped inline, every incoming token triggered a full DOM reconciliation for all historical chat bubbles, resulting in an O(N) render cost that degraded performance linearly as the chat lengthened.
**Action:** Always extract items mapped in high-frequency update loops (like streaming logs or chat tokens) into separate components wrapped in `React.memo()`. This creates an O(1) rendering cost where only the actively changing item re-renders, preventing UI stuttering and wasted CPU cycles.

## 2024-05-15 - React Recursive Memoization Bottleneck
**Learning:** When passing a globally active ID down a recursive tree (like File Explorer), standard `React.memo()` shallow comparison fails to provide O(1) re-renders, causing O(N) cascades. Also, inline arrow functions passed as props defeat memoization.
**Action:** Use a custom `arePropsEqual` where branch nodes (folders) always re-render (return `false`) to propagate props, and only memoize leaf nodes based on specific state changes. Wrap callbacks passed to memoized children in `useCallback`.
