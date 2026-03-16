// @ai-module: Terminal + Tasks Panel
// @ai-role: Tab-switching container for the bottom panel. Hosts TerminalPanel (xterm) and TasksPanel
//           under a shared tab bar. Fetches logLines/isStreaming from useTerminalStream and
//           tasks from useAgentConnection, then passes them down as props.
// @ai-dependencies: hooks/useTerminalStream.ts (logLines, isStreaming)
//                   hooks/useAgentConnection.ts (tasks)
//                   components/TerminalPanel.tsx
//                   components/TasksPanel.tsx

// [AI-STRICT] Both TerminalPanel and TasksPanel are always mounted (hidden via CSS, not conditional).
//             DO NOT replace the hidden/visible CSS approach with conditional rendering —
//             xterm.js requires a mounted DOM node to remain functional; unmounting it destroys the terminal instance.
// [AI-STRICT] DO NOT add store selectors directly to this component.
//             All data must flow through useTerminalStream and useAgentConnection.
// @ai-integration-point: The Maximize button is a no-op placeholder.
//   Wire it to expand the terminal panel to full height when the real backend is connected.


import { useState } from 'react';
import { Terminal, ListChecks, Maximize2 } from 'lucide-react';
import { TerminalPanel } from './TerminalPanel';
import { TasksPanel } from './TasksPanel';
import { useTerminalStream } from '../hooks/useTerminalStream';
import { useAgentConnection } from '../hooks/useAgentConnection';

type PanelTab = 'terminal' | 'tasks';

export function TerminalTaskPanel() {
  const [activeTab, setActiveTab] = useState<PanelTab>('terminal');
  const { logLines, isStreaming } = useTerminalStream();
  const { tasks } = useAgentConnection();

  const activeTaskCount = tasks.filter((t) => t.status !== 'completed').length;

  return (
    <div className="flex flex-col h-full border-t border-slate-800 bg-slate-950">
      <div className="flex items-center border-b border-slate-800 h-8 shrink-0 px-2 gap-1">
        <button
          onClick={() => setActiveTab('terminal')}
          className={`flex items-center gap-1.5 px-3 h-full text-xs font-medium border-b-2 transition-colors ${
            activeTab === 'terminal'
              ? 'border-sky-500 text-sky-300'
              : 'border-transparent text-slate-400 hover:text-slate-200'
          }`}
        >
          <Terminal className="w-3 h-3" />
          Terminal
          {isStreaming && (
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse ml-0.5" />
          )}
        </button>
        <button
          onClick={() => setActiveTab('tasks')}
          className={`flex items-center gap-1.5 px-3 h-full text-xs font-medium border-b-2 transition-colors ${
            activeTab === 'tasks'
              ? 'border-sky-500 text-sky-300'
              : 'border-transparent text-slate-400 hover:text-slate-200'
          }`}
        >
          <ListChecks className="w-3 h-3" />
          Tasks
          <span className="ml-0.5 text-[10px] bg-sky-500/15 text-sky-400 border border-sky-500/20 rounded px-1">
            {activeTaskCount}
          </span>
        </button>
        <div className="flex-1" />
        <button className="p-1 rounded hover:bg-slate-800 text-slate-500 hover:text-slate-300 transition-colors">
          <Maximize2 className="w-3 h-3" />
        </button>
      </div>

      <div className="flex-1 min-h-0 overflow-hidden">
        <div className={activeTab === 'terminal' ? 'flex flex-col h-full' : 'hidden'}>
          <TerminalPanel logLines={logLines} isStreaming={isStreaming} />
        </div>
        <div className={activeTab === 'tasks' ? 'flex flex-col h-full overflow-hidden' : 'hidden'}>
          <TasksPanel tasks={tasks} />
        </div>
      </div>
    </div>
  );
}
