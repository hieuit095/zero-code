// @ai-module: Tasks Panel
// @ai-role: Pure presentational component rendering the task list with status icons, agent badges,
//           and subtask expansion. Receives tasks[] as a prop — no direct store access.
//           Local state tracks which task rows are expanded (Set<string>).
// @ai-dependencies: Props only (Task[] — sourced from useAgentConnection in TerminalTaskPanel)
//                   types/index.ts (Task, AgentRole)

// [AI-STRICT] TasksPanel is a PURE presentational component. DO NOT add store selectors here.
// [AI-STRICT] Task status transitions (pending -> in-progress -> completed) are managed exclusively
//             by agentStore.updateTask(). This component only displays — it does not mutate task state.
// @ai-integration-point: When the real backend is connected, no changes to TasksPanel are needed.
//   The task data will flow in via useAgentConnection (driven by WebSocket task:update events -> agentStore).


import { CheckCircle2, Circle, Loader2, ChevronDown, ChevronRight } from 'lucide-react';
import { useState } from 'react';
import type { Task, AgentRole } from '../types';

const agentBadge: Record<AgentRole, string> = {
  'tech-lead': 'text-amber-300 bg-amber-500/10 border-amber-500/20',
  dev: 'text-sky-300 bg-sky-500/10 border-sky-500/20',
  qa: 'text-emerald-300 bg-emerald-500/10 border-emerald-500/20',
};

const agentLabel: Record<AgentRole, string> = {
  'tech-lead': 'Lead',
  dev: 'Dev',
  qa: 'QA',
};

interface TasksPanelProps {
  tasks: Task[];
}

export function TasksPanel({ tasks }: TasksPanelProps) {
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  const toggle = (id: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const statusCounts = {
    completed: tasks.filter((t) => t.status === 'completed').length,
    'in-progress': tasks.filter((t) => t.status === 'in-progress').length,
    pending: tasks.filter((t) => t.status === 'pending').length,
  };

  return (
    <div className="flex flex-col h-full overflow-hidden">
      <div className="flex items-center gap-3 px-3 py-2 border-b border-slate-800 shrink-0">
        <span className="flex items-center gap-1.5 text-[11px] text-slate-400">
          <CheckCircle2 className="w-3 h-3 text-emerald-400" />
          {statusCounts.completed} done
        </span>
        <span className="flex items-center gap-1.5 text-[11px] text-slate-400">
          <Loader2 className="w-3 h-3 text-sky-400 animate-spin" />
          {statusCounts['in-progress']} active
        </span>
        <span className="flex items-center gap-1.5 text-[11px] text-slate-400">
          <Circle className="w-3 h-3 text-slate-600" />
          {statusCounts.pending} pending
        </span>
        <div className="flex-1" />
        <div className="flex items-center gap-1 text-[10px] text-slate-500">
          <div className="w-24 h-1.5 rounded-full bg-slate-800 overflow-hidden">
            <div
              className="h-full rounded-full bg-gradient-to-r from-sky-500 to-emerald-500 transition-all duration-500"
              style={{ width: `${tasks.length > 0 ? (statusCounts.completed / tasks.length) * 100 : 0}%` }}
            />
          </div>
          <span className="text-slate-400 font-medium">
            {tasks.length > 0 ? Math.round((statusCounts.completed / tasks.length) * 100) : 0}%
          </span>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto px-2 py-1">
        {tasks.map((task) => {
          const isExpanded = expanded.has(task.id);
          return (
            <div key={task.id} className="mb-0.5">
              <div
                className={`flex items-start gap-2 px-2 py-1.5 rounded-md cursor-pointer transition-colors ${
                  task.status === 'in-progress'
                    ? 'bg-sky-500/5 hover:bg-sky-500/10'
                    : 'hover:bg-slate-800'
                }`}
                onClick={() => task.subtasks && toggle(task.id)}
              >
                <div className="mt-0.5 shrink-0">
                  {task.status === 'completed' && <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />}
                  {task.status === 'in-progress' && <Loader2 className="w-3.5 h-3.5 text-sky-400 animate-spin" />}
                  {task.status === 'pending' && <Circle className="w-3.5 h-3.5 text-slate-600" />}
                </div>
                <span className={`flex-1 text-xs leading-relaxed ${
                  task.status === 'completed'
                    ? 'text-slate-500 line-through'
                    : task.status === 'in-progress'
                    ? 'text-slate-200'
                    : 'text-slate-400'
                }`}>
                  {task.label}
                </span>
                <span className={`text-[10px] font-medium px-1.5 py-0.5 rounded border ${agentBadge[task.agent]} shrink-0`}>
                  {agentLabel[task.agent]}
                </span>
                {task.subtasks && (
                  <span className="text-slate-600 shrink-0">
                    {isExpanded ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
                  </span>
                )}
              </div>
              {isExpanded && task.subtasks && (
                <div className="ml-7 mt-0.5 space-y-0.5 pb-1">
                  {task.subtasks.map((sub, i) => (
                    <div key={i} className="flex items-center gap-1.5 px-2 py-1 rounded text-[11px] text-slate-500">
                      <span className="w-1 h-1 rounded-full bg-slate-700 shrink-0" />
                      {sub}
                    </div>
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
