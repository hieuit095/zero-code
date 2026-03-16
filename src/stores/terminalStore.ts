// @ai-module: Terminal Store
// @ai-role: Zustand store for terminal output log lines and streaming state.
//           Feeds data to TerminalPanel (xterm.js renderer) via the useTerminalStream hook.
//           The store is the sole writer; TerminalPanel is a pure read consumer.
// @ai-dependencies: types/index.ts (LogLine, LogLineType)
//                   data/mockData.ts (initialTerminalLines — used as seed on load and after reset)

// [AI-STRICT] DO NOT write to this store directly from UI components.
//             Use the appendLine / appendLines / clearTerminal / setStreaming actions only.
//             All log output should flow through useTerminalStream.appendLine().
// [AI-STRICT] The logLines array is append-only during a run. TerminalPanel detects a clear
//             by checking if logLines.length < renderedCountRef — do not splice or reorder lines.
//             Clearing must go through clearTerminal() which resets the array to [].
// [AI-STRICT] isStreaming is a derived UI hint. In mock mode it is driven by agent working status
//             (see useTerminalStream). When the real backend is connected, call setStreaming(true/false)
//             based on WebSocket connection state instead.

import { create } from 'zustand';
import type { LogLine, LogLineType } from '../types';
import { initialTerminalLines } from '../data/mockData';

let idCounter = 1000;

interface TerminalState {
  logLines: LogLine[];
  isStreaming: boolean;

  // @ai-integration-point: When the real backend is connected, call appendLine(text, type)
  //   for each line received from the OpenHands sandbox via WebSocket 'terminal:output' events.
  appendLine: (text: string, type?: LogLineType) => void;
  // @ai-integration-point: Use appendLines for batch-flushing buffered stdout from the sandbox.
  appendLines: (lines: Array<{ text: string; type: LogLineType }>) => void;
  clearTerminal: () => void;
  // @ai-integration-point: Call setStreaming(true) when a WebSocket run starts and setStreaming(false)
  //   when the 'run:complete' or 'run:error' event is received.
  setStreaming: (streaming: boolean) => void;
}

export const useTerminalStore = create<TerminalState>((set) => ({
  logLines: initialTerminalLines,
  isStreaming: false,

  appendLine: (text: string, type: LogLineType = 'info') => {
    set((state) => ({
      logLines: [...state.logLines, { id: `log-${idCounter++}`, text, type }],
    }));
  },

  appendLines: (lines) => {
    const newLines: LogLine[] = lines.map(({ text, type }) => ({
      id: `log-${idCounter++}`,
      text,
      type,
    }));
    set((state) => ({ logLines: [...state.logLines, ...newLines] }));
  },

  clearTerminal: () => set({ logLines: [] }),

  setStreaming: (streaming: boolean) => set({ isStreaming: streaming }),
}));
