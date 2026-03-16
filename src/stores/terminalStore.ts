// @ai-module: Terminal Store
// @ai-role: Zustand store for terminal output log lines and streaming state.
//           Feeds data to TerminalPanel (xterm.js renderer) via the useTerminalStream hook.
//           The store is the sole writer; TerminalPanel is a pure read consumer.
// @ai-dependencies: types/index.ts (LogLine, LogLineType)

// [AI-STRICT] DO NOT write to this store directly from UI components.
//             Use the appendLine / appendLines / clearTerminal / setStreaming actions only.
// [AI-STRICT] The logLines array is append-only during a run. TerminalPanel detects a clear
//             by checking if logLines.length < renderedCountRef — do not splice or reorder lines.

import { create } from 'zustand';
import type { LogLine, LogLineType } from '../types';

let idCounter = 1000;

interface TerminalState {
  logLines: LogLine[];
  isStreaming: boolean;

  appendLine: (text: string, type?: LogLineType) => void;
  appendLines: (lines: Array<{ text: string; type: LogLineType }>) => void;
  clearTerminal: () => void;
  setStreaming: (streaming: boolean) => void;
}

export const useTerminalStore = create<TerminalState>((set) => ({
  logLines: [],
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
