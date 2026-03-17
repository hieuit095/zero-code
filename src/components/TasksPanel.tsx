// @ai-module: Tasks Panel
// @ai-role: Pure presentational component rendering the task list with status icons, agent badges,
//           QA retry indicators, and subtask expansion. Receives tasks[] and qaRetryState as props.
// @ai-dependencies: Props only (Task[] — sourced from useAgentConnection in TerminalTaskPanel)

// [AI-STRICT] TasksPanel is a PURE presentational component. DO NOT add store selectors here.
// [AI-STRICT] Task status transitions are managed by agentStore.updateTask(). This component only displays.


import { AlertTriangle, CheckCircle2, Circle, Loader2, ChevronDown, ChevronRight, RotateCw } from 'lucide-react';
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

interface QaRetryState {
  taskId: string;
  attempt: number;
  maxAttempts: number;
  status: 'failed' | 'retrying' | 'passed';
  failingCommand: string | null;
  defectSummary: string | null;
  scores: Record<string, number> | null;
  failingDimensions: string[];
}

const SCORE_LABELS: Record<string, { label: string; threshold: number }> = {
  code_quality: { label: 'Code Quality', threshold: 80 },
  requirements: { label: 'Requirements', threshold: 80 },
  robustness: { label: 'Robustness', threshold: 70 },
  security: { label: 'Security', threshold: 90 },
};

function ScoreBar({ dim, value, isFailing }: { dim: string; value: number; isFailing: boolean }) {
  const info = SCORE_LABELS[dim] ?? { label: dim, threshold: 70 };
  const pct = Math.max(0, Math.min(100, value));
  const barColor = isFailing
    ? 'bg-red-400'
    : pct >= info.threshold
      ? 'bg-emerald-400'
      : 'bg-amber-400';
  const textColor = isFailing ? 'text-red-300' : pct >= info.threshold ? 'text-emerald-300' : 'text-amber-300';

  return (
    <div className="flex items-center gap-2">
      <span className="text-[10px] text-slate-400 w-20 truncate shrink-0">{info.label}</span>
      <div className="flex-1 h-1.5 rounded-full bg-slate-800 overflow-hidden relative">
        {/* Threshold marker */}
        <div
          className="absolute top-0 bottom-0 w-px bg-slate-600 z-10"
          style={{ left: `${info.threshold}%` }}
        />
        <div
          className={`h-full rounded-full transition-all duration-500 ${barColor}`}
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className={`text-[10px] font-mono font-medium w-7 text-right ${textColor}`}>
        {pct}
      </span>
    </div>
  );
}

interface TasksPanelProps {
  tasks: Task[];
  qaRetryState?: QaRetryState | null;
}

export function TasksPanel({ tasks, qaRetryState }: TasksPanelProps) {
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

  const failingSet = new Set(qaRetryState?.failingDimensions ?? []);

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

      {/* ── QA Retry Banner with Scoreboard ──────────────────────── */}
      {qaRetryState && (qaRetryState.status === 'retrying' || qaRetryState.status === 'failed' || qaRetryState.status === 'passed') && (
        <div className={`mx-2 mt-2 rounded-lg border text-xs transition-all duration-300 ${qaRetryState.status === 'passed'
            ? 'bg-emerald-500/5 border-emerald-500/20 text-emerald-300'
            : qaRetryState.status === 'retrying'
              ? 'bg-amber-500/5 border-amber-500/20 text-amber-300'
              : 'bg-red-500/5 border-red-500/20 text-red-300'
          }`}>
          {/* Header */}
          <div className="flex items-center gap-2 font-medium px-3 pt-2 pb-1.5">
            {qaRetryState.status === 'passed' ? (
              <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />
            ) : qaRetryState.status === 'retrying' ? (
              <RotateCw className="w-3.5 h-3.5 animate-spin" />
            ) : (
              <AlertTriangle className="w-3.5 h-3.5" />
            )}
            <span>
              {qaRetryState.status === 'passed'
                ? `QA Passed — All Checks Clear`
                : `QA Failed — Attempt ${qaRetryState.attempt}/${qaRetryState.maxAttempts}`}
              {qaRetryState.status === 'retrying' && ' — Dev Retrying'}
            </span>
          </div>

          {/* Dimensional Scoreboard */}
          {qaRetryState.scores && (
            <div className="mx-3 mb-2 px-2.5 py-2 rounded-md bg-slate-950/60 border border-slate-800/50 space-y-1.5">
              <div className="flex items-center gap-1.5 mb-1">
                <span className="text-[9px] font-semibold text-slate-500 uppercase tracking-widest">QA Scores</span>
                {qaRetryState.status === 'passed' ? (
                  <span className="text-[9px] font-medium px-1.5 py-0.5 rounded bg-emerald-500/10 border border-emerald-500/20 text-emerald-400">
                    all passing
                  </span>
                ) : failingSet.size > 0 && (
                  <span className="text-[9px] font-medium px-1.5 py-0.5 rounded bg-red-500/10 border border-red-500/20 text-red-400">
                    {failingSet.size} below threshold
                  </span>
                )}
              </div>
              {Object.entries(qaRetryState.scores).map(([dim, value]) => (
                <ScoreBar
                  key={dim}
                  dim={dim}
                  value={value}
                  isFailing={failingSet.has(dim)}
                />
              ))}
            </div>
          )}

          {qaRetryState.failingCommand && (
            <div className="mt-1 px-3 pb-1 font-mono text-[10px] text-slate-400 truncate">
              $ {qaRetryState.failingCommand}
            </div>
          )}
          {qaRetryState.defectSummary && (
            <div className="px-3 pb-2 text-[10px] text-slate-500 line-clamp-2">
              {qaRetryState.defectSummary}
            </div>
          )}
        </div>
      )}

      <div className="flex-1 overflow-y-auto px-2 py-1">
        {tasks.map((task) => {
          const isExpanded = expanded.has(task.id);
          const isRetrying = qaRetryState?.taskId === task.id && qaRetryState.status === 'retrying';
          return (
            <div key={task.id} className="mb-0.5">
              <div
                className={`flex items-start gap-2 px-2 py-1.5 rounded-md cursor-pointer transition-colors ${isRetrying
                  ? 'bg-amber-500/5 hover:bg-amber-500/10 ring-1 ring-amber-500/20'
                  : task.status === 'in-progress'
                    ? 'bg-sky-500/5 hover:bg-sky-500/10'
                    : 'hover:bg-slate-800'
                  }`}
                onClick={() => task.subtasks && toggle(task.id)}
              >
                <div className="mt-0.5 shrink-0">
                  {isRetrying && <RotateCw className="w-3.5 h-3.5 text-amber-400 animate-spin" />}
                  {!isRetrying && task.status === 'completed' && <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />}
                  {!isRetrying && task.status === 'in-progress' && <Loader2 className="w-3.5 h-3.5 text-sky-400 animate-spin" />}
                  {!isRetrying && task.status === 'pending' && <Circle className="w-3.5 h-3.5 text-slate-600" />}
                </div>
                <span className={`flex-1 text-xs leading-relaxed ${isRetrying
                  ? 'text-amber-200'
                  : task.status === 'completed'
                    ? 'text-slate-500 line-through'
                    : task.status === 'in-progress'
                      ? 'text-slate-200'
                      : 'text-slate-400'
                  }`}>
                  {task.label}
                </span>
                {isRetrying && (
                  <span className="text-[10px] font-medium px-1.5 py-0.5 rounded border text-amber-300 bg-amber-500/10 border-amber-500/20 shrink-0">
                    Retry
                  </span>
                )}
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
