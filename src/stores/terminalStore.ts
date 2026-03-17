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

// ─── Buffered flush config ────────────────────────────────────────────────────
// When `npm install` or large builds blast thousands of lines per second,
// unbuffered React state updates cause severe render congestion. This buffer
// collects incoming lines and flushes them to state on a fixed interval.
const FLUSH_INTERVAL_MS = 50; // 20 Hz — smooth while avoiding render storms
const MAX_BUFFER_SIZE = 500; // Force-flush if buffer hits this size
const MAX_LOG_LINES = 1_000; // Strict ring-buffer: keep only the last 1K lines

interface TerminalState {
  logLines: LogLine[];
  isStreaming: boolean;

  appendLine: (text: string, type?: LogLineType) => void;
  appendLines: (lines: Array<{ text: string; type: LogLineType }>) => void;
  clearTerminal: () => void;
  setStreaming: (streaming: boolean) => void;

  // AUDIT FIX: Lifecycle actions for the flush timer.
  // - initialize(): (re)starts the flush timer. Safe to call multiple times.
  // - destroy(): pauses the timer and clears the buffer. Does NOT
  //   permanently kill the store — call initialize() to restart.
  initialize: () => void;
  destroy: () => void;
}

// ─── Buffer state (outside Zustand to avoid re-render on buffer writes) ──────

let _buffer: LogLine[] = [];
let _flushTimer: ReturnType<typeof setInterval> | null = null;
// AUDIT FIX: Hold a reference to the Zustand `set` function so that
// initialize() can restart the timer without needing it passed in.
let _setRef: ((fn: (state: TerminalState) => Partial<TerminalState>) => void) | null = null;

function _startFlushTimer(set: (fn: (state: TerminalState) => Partial<TerminalState>) => void) {
  if (_flushTimer !== null) return;
  _setRef = set;

  _flushTimer = setInterval(() => {
    if (_buffer.length === 0) return;

    const batch = _buffer;
    _buffer = [];

    set((state) => {
      const merged = [...state.logLines, ...batch];
      // Trim from the front if we exceed max
      const trimmed = merged.length > MAX_LOG_LINES
        ? merged.slice(merged.length - MAX_LOG_LINES)
        : merged;
      return { logLines: trimmed };
    });
  }, FLUSH_INTERVAL_MS);
}

function _stopFlushTimer() {
  if (_flushTimer !== null) {
    clearInterval(_flushTimer);
    _flushTimer = null;
  }
}

function _enqueue(
  lines: LogLine[],
  set: (fn: (state: TerminalState) => Partial<TerminalState>) => void
) {
  _buffer.push(...lines);

  // Force-flush if buffer reaches capacity
  if (_buffer.length >= MAX_BUFFER_SIZE) {
    const batch = _buffer;
    _buffer = [];

    set((state) => {
      const merged = [...state.logLines, ...batch];
      const trimmed = merged.length > MAX_LOG_LINES
        ? merged.slice(merged.length - MAX_LOG_LINES)
        : merged;
      return { logLines: trimmed };
    });
  }
}

// ─── Store ────────────────────────────────────────────────────────────────────

export const useTerminalStore = create<TerminalState>((set) => {
  // Start the flush timer on store creation
  _startFlushTimer(set);

  return {
    logLines: [],
    isStreaming: false,

    appendLine: (text: string, type: LogLineType = 'info') => {
      _enqueue(
        [{ id: `log-${idCounter++}`, text, type }],
        set
      );
    },

    appendLines: (lines) => {
      const newLines: LogLine[] = lines.map(({ text, type }) => ({
        id: `log-${idCounter++}`,
        text,
        type,
      }));
      _enqueue(newLines, set);
    },

    clearTerminal: () => {
      _buffer = [];
      set({ logLines: [] });
    },

    setStreaming: (streaming: boolean) => {
      set({ isStreaming: streaming });

      // When streaming stops, do one final flush
      if (!streaming && _buffer.length > 0) {
        const batch = _buffer;
        _buffer = [];
        set((state) => {
          const merged = [...state.logLines, ...batch];
          const trimmed = merged.length > MAX_LOG_LINES
            ? merged.slice(merged.length - MAX_LOG_LINES)
            : merged;
          return { logLines: trimmed };
        });
      }
    },

    // AUDIT FIX: (Re)start the flush timer. Safe to call multiple times —
    // _startFlushTimer guards against duplicate intervals. Components that
    // render the terminal should call this on mount via useEffect.
    initialize: () => {
      _startFlushTimer(_setRef ?? set);
    },

    // AUDIT FIX: Pause the timer and clear the buffer. Does NOT
    // permanently kill the store — call initialize() to restart.
    destroy: () => {
      _stopFlushTimer();
      _buffer = [];
    },
  };
});
