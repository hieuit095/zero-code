// @ai-module: Terminal Panel (xterm.js)
// @ai-role: Pure dumb rendering component for the xterm.js terminal emulator.
//           Receives logLines[] as props and renders ANSI-formatted output incrementally.
//           Uses a ref (renderedCountRef) to append only new lines on each render — never re-renders all lines.
//           The xterm instance is owned by this component and must not be accessed from outside.
// @ai-dependencies: Props only (LogLine[], isStreaming — no direct store access)
//                   types/index.ts (LogLine — for ANSI formatting dispatch)

// [AI-STRICT] DO NOT add local state for log lines here. logLines must always come in as a prop from TerminalTaskPanel.
// [AI-STRICT] The xterm Terminal instance is created once in a useEffect with no dependencies.
//             DO NOT move the xterm initialization into useMemo or any other lifecycle — it will break the FitAddon.
// [AI-STRICT] The incremental rendering logic (renderedCountRef) is critical for performance.
//             DO NOT replace it with a full re-render approach (e.g., re-writing all lines on every change).
//             When logLines.length < renderedCountRef.current, TerminalPanel detects a clear and calls term.clear().
// [AI-STRICT] TerminalPanel does NOT handle user keyboard input. It is display-only.
//             DO NOT add term.onData() or any input handler — this terminal is output-only.
// @ai-integration-point: When real WebSocket output arrives, it will be passed through
//   terminalStore.appendLine() -> useTerminalStream() -> TerminalTaskPanel -> TerminalPanel as props.
//   No changes to TerminalPanel itself are needed for the backend integration.


import { useEffect, useRef } from 'react';
import { Terminal as XTerm } from '@xterm/xterm';
import { FitAddon } from '@xterm/addon-fit';
import '@xterm/xterm/css/xterm.css';
import type { LogLine } from '../types';

const ANSI = {
  reset: '\x1b[0m',
  bold: '\x1b[1m',
  brightGreen: '\x1b[92m',
  yellow: '\x1b[33m',
  brightRed: '\x1b[91m',
  cyan: '\x1b[36m',
  brightCyan: '\x1b[96m',
  white: '\x1b[37m',
  gray: '\x1b[90m',
};

function formatLine(text: string, type: LogLine['type']): string {
  switch (type) {
    case 'command': return `${ANSI.brightCyan}${ANSI.bold}${text}${ANSI.reset}`;
    case 'success': return `${ANSI.brightGreen}${text}${ANSI.reset}`;
    case 'warn': return `${ANSI.yellow}${text}${ANSI.reset}`;
    case 'error': return `${ANSI.brightRed}${text}${ANSI.reset}`;
    case 'info': return `${ANSI.cyan}${text}${ANSI.reset}`;
    case 'output': return `${ANSI.gray}${text}${ANSI.reset}`;
    case 'cursor': return `${ANSI.brightCyan}${ANSI.bold}${text}${ANSI.reset}`;
    case 'blank': return '';
    default: return `${ANSI.white}${text}${ANSI.reset}`;
  }
}

interface TerminalPanelProps {
  logLines: LogLine[];
  isStreaming?: boolean;
}

export function TerminalPanel({ logLines, isStreaming = false }: TerminalPanelProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const termRef = useRef<XTerm | null>(null);
  const fitRef = useRef<FitAddon | null>(null);
  const renderedCountRef = useRef(0);

  useEffect(() => {
    if (!containerRef.current || termRef.current) return;

    const term = new XTerm({
      theme: {
        background: '#020817',
        foreground: '#cbd5e1',
        cursor: '#38bdf8',
        cursorAccent: '#020817',
        selectionBackground: '#1e3a5f',
        black: '#1e293b',
        brightBlack: '#475569',
        red: '#f87171',
        brightRed: '#fca5a5',
        green: '#4ade80',
        brightGreen: '#86efac',
        yellow: '#facc15',
        brightYellow: '#fde047',
        blue: '#60a5fa',
        brightBlue: '#93c5fd',
        magenta: '#c084fc',
        brightMagenta: '#d8b4fe',
        cyan: '#22d3ee',
        brightCyan: '#67e8f9',
        white: '#cbd5e1',
        brightWhite: '#f1f5f9',
      },
      fontFamily: '"JetBrains Mono", "Fira Code", "Cascadia Code", monospace',
      fontSize: 12,
      lineHeight: 1.5,
      cursorBlink: true,
      cursorStyle: 'block',
      scrollback: 2000,
      convertEol: true,
    });

    const fitAddon = new FitAddon();
    term.loadAddon(fitAddon);
    term.open(containerRef.current);
    termRef.current = term;
    fitRef.current = fitAddon;

    setTimeout(() => fitAddon.fit(), 50);

    const observer = new ResizeObserver(() => fitAddon.fit());
    observer.observe(containerRef.current);

    return () => {
      observer.disconnect();
      term.dispose();
      termRef.current = null;
      renderedCountRef.current = 0;
    };
  }, []);

  useEffect(() => {
    const term = termRef.current;
    if (!term) return;

    if (logLines.length < renderedCountRef.current) {
      term.clear();
      renderedCountRef.current = 0;
    }

    const newLines = logLines.slice(renderedCountRef.current);
    for (const l of newLines) {
      if (l.type === 'blank') {
        term.writeln('');
      } else {
        term.writeln(formatLine(l.text, l.type));
      }
    }
    renderedCountRef.current = logLines.length;
  }, [logLines]);

  return (
    <div className="relative flex flex-col h-full">
      {isStreaming && (
        <div className="absolute top-1 right-2 flex items-center gap-1.5 z-10 pointer-events-none">
          <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
          <span className="text-[10px] text-emerald-400 font-medium">streaming</span>
        </div>
      )}
      <div
        ref={containerRef}
        className="flex-1 min-h-0 overflow-hidden"
        style={{ padding: '4px 0' }}
      />
    </div>
  );
}
