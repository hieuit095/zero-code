// @ai-module: Terminal Stream Hook
// @ai-role: Data transport abstraction for terminal output consumed by TerminalTaskPanel and TerminalPanel.
//           Derives isStreaming from agent working status so the streaming indicator is always accurate
//           without the simulation needing to manually toggle the flag.
// @ai-dependencies: stores/terminalStore.ts (useTerminalStore)
//                   stores/agentStore.ts (useAgentStore — dev and qa status for isStreaming derivation)
//                   types/index.ts (LogLine, LogLineType)

// [AI-STRICT] TerminalPanel (xterm.js) MUST consume logLines only through this hook.
//             Do NOT pass logLines directly from a store selector to TerminalPanel.
// [AI-STRICT] isStreaming is derived here — do not manage it as local component state in TerminalPanel or TerminalTaskPanel.
//             The derivation logic (dev or qa working => streaming) must remain in this hook.
// [AI-STRICT] When the real backend is connected, the isStreaming derivation should be replaced with
//             a store flag driven by WebSocket 'run:start' / 'run:complete' events (terminalStore.setStreaming).
//             The agent status derivation below can be removed at that point.

import { useEffect } from 'react';
import { useTerminalStore } from '../stores/terminalStore';
import { useAgentStore } from '../stores/agentStore';
import type { LogLine, LogLineType } from '../types';

export interface TerminalStreamReturn {
  logLines: LogLine[];
  isStreaming: boolean;
  appendLine: (text: string, type?: LogLineType) => void;
  clearTerminal: () => void;
}

/**
 * useTerminalStream
 *
 * Data transport abstraction for terminal output.
 * Currently backed by the Zustand terminalStore.
 *
 * WebSocket integration path:
 *   On receiving `terminal:output` WS events from the OpenHands sandbox,
 *   call appendLine(text, type) to push each line into the store.
 *   The isStreaming flag can be driven by the WS connection state or
 *   by the Dev agent's active status (shown below as a derived value).
 */
export function useTerminalStream(): TerminalStreamReturn {
  const logLines = useTerminalStore((s) => s.logLines);
  const storeStreaming = useTerminalStore((s) => s.isStreaming);
  const appendLine = useTerminalStore((s) => s.appendLine);
  const clearTerminal = useTerminalStore((s) => s.clearTerminal);
  const initialize = useTerminalStore((s) => s.initialize);
  const destroy = useTerminalStore((s) => s.destroy);

  // AUDIT FIX: Ensure the flush timer is alive while a terminal-consuming
  // component is mounted. On unmount, pause it safely. initialize() is
  // idempotent — calling it multiple times is harmless.
  useEffect(() => {
    initialize();
    return () => destroy();
  }, [initialize, destroy]);

  // @ai-integration-point: Replace this derived isStreaming with terminalStore.isStreaming alone
  //   once terminalStore.setStreaming is wired to real WebSocket 'run:start' / 'run:complete' events.
  const devStatus = useAgentStore((s) => s.agentStatuses.dev);
  const qaStatus = useAgentStore((s) => s.agentStatuses.qa);

  const isStreaming = storeStreaming || devStatus === 'working' || qaStatus === 'working';

  return {
    logLines,
    isStreaming,
    appendLine,
    clearTerminal,
  };
}
