/**
 * ==========================================
 * Author: Hieu Nguyen - Codev Team
 * Email: hieuit095@gmail.com
 * Project: ZeroCode - Autonomous Multi-Agent IDE
 * ==========================================
 */
// @ai-module: QA Dashboard
// @ai-role: Pure presentational component rendering the full QA score history from the
//           qaScoreHistory Zustand slice. Each evaluation entry shows 4 dimensional bars
//           (code_quality, requirements, robustness, security) with values jumping directly
//           to the backend-provided scores — no artificial animation from 0.
// @ai-dependencies: Props only (QaScoreEntry[] — sourced from useAgentConnection in TerminalTaskPanel)

// [AI-STRICT] QADashboard is a PURE presentational component. DO NOT add store selectors here.
// [AI-STRICT] All score data arrives from real WebSocket `qa:report` and `qa:passed` events.
//             ZERO mocks, ZERO hardcoded fallback data.


import { CheckCircle2, XCircle, Shield, Code2, FileCheck, Bug } from 'lucide-react';
import type { QaScoreEntry } from '../stores/agentStore';

const DIMENSION_CONFIG: Record<string, {
  label: string;
  threshold: number;
  icon: typeof Code2;
}> = {
  code_quality: { label: 'Code Quality', threshold: 80, icon: Code2 },
  requirements: { label: 'Requirements', threshold: 80, icon: FileCheck },
  robustness: { label: 'Robustness', threshold: 70, icon: Bug },
  security: { label: 'Security', threshold: 90, icon: Shield },
};

const DIMENSION_ORDER = ['code_quality', 'requirements', 'robustness', 'security'];

function DimensionBar({ dim, value, isFailing }: { dim: string; value: number; isFailing: boolean }) {
  const config = DIMENSION_CONFIG[dim] ?? { label: dim, threshold: 70, icon: Code2 };
  const pct = Math.max(0, Math.min(100, value));
  const Icon = config.icon;

  const barColor = isFailing
    ? 'bg-red-400'
    : pct >= config.threshold
      ? 'bg-emerald-400'
      : 'bg-amber-400';

  const textColor = isFailing
    ? 'text-red-300'
    : pct >= config.threshold
      ? 'text-emerald-300'
      : 'text-amber-300';

  const bgGlow = isFailing
    ? 'shadow-red-500/10'
    : pct >= config.threshold
      ? 'shadow-emerald-500/10'
      : 'shadow-amber-500/10';

  return (
    <div className="flex items-center gap-2.5">
      <Icon className={`w-3 h-3 ${textColor} shrink-0`} />
      <span className="text-[10px] text-slate-400 w-[72px] truncate shrink-0">{config.label}</span>
      <div className={`flex-1 h-2 rounded-full bg-slate-800/80 overflow-hidden relative shadow-inner ${bgGlow}`}>
        {/* Threshold marker */}
        <div
          className="absolute top-0 bottom-0 w-px bg-slate-600/80 z-10"
          style={{ left: `${config.threshold}%` }}
        />
        {/* Score bar — jumps directly to value, no artificial animation */}
        <div
          className={`h-full rounded-full ${barColor}`}
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className={`text-[11px] font-mono font-semibold w-8 text-right ${textColor}`}>
        {pct}
      </span>
    </div>
  );
}

interface QADashboardProps {
  qaScoreHistory: QaScoreEntry[];
}

export function QADashboard({ qaScoreHistory }: QADashboardProps) {
  if (qaScoreHistory.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-full text-slate-500 gap-2">
        <Shield className="w-8 h-8 text-slate-700" />
        <span className="text-xs">No QA evaluations yet</span>
        <span className="text-[10px] text-slate-600">Scores will appear when the QA agent runs</span>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Header summary */}
      <div className="flex items-center gap-3 px-3 py-2 border-b border-slate-800 shrink-0">
        <span className="flex items-center gap-1.5 text-[11px] text-slate-400">
          <Shield className="w-3 h-3 text-emerald-400" />
          {qaScoreHistory.length} evaluation{qaScoreHistory.length !== 1 ? 's' : ''}
        </span>
        <span className="flex items-center gap-1.5 text-[11px] text-slate-400">
          <CheckCircle2 className="w-3 h-3 text-emerald-400" />
          {qaScoreHistory.filter((e) => e.status === 'passed').length} passed
        </span>
        <span className="flex items-center gap-1.5 text-[11px] text-slate-400">
          <XCircle className="w-3 h-3 text-red-400" />
          {qaScoreHistory.filter((e) => e.status === 'failed').length} failed
        </span>
      </div>

      {/* Score history list */}
      <div className="flex-1 overflow-y-auto px-2 py-2 space-y-2">
        {qaScoreHistory.map((entry, idx) => {
          const failingSet = new Set(entry.failingDimensions);
          const isPassed = entry.status === 'passed';

          return (
            <div
              key={`qa-${idx}-${entry.taskId}-${entry.attempt}`}
              className={`rounded-lg border p-3 transition-all ${
                isPassed
                  ? 'bg-emerald-500/5 border-emerald-500/15'
                  : 'bg-red-500/5 border-red-500/15'
              }`}
            >
              {/* Entry header */}
              <div className="flex items-center gap-2 mb-2.5">
                {isPassed ? (
                  <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400 shrink-0" />
                ) : (
                  <XCircle className="w-3.5 h-3.5 text-red-400 shrink-0" />
                )}
                <span className={`text-[11px] font-semibold ${isPassed ? 'text-emerald-300' : 'text-red-300'}`}>
                  {isPassed ? 'Passed' : 'Failed'}
                </span>
                <span className="text-[10px] text-slate-500">
                  Attempt {entry.attempt}
                </span>
                <div className="flex-1" />
                <span className="text-[9px] font-mono text-slate-600 truncate max-w-[120px]">
                  {entry.taskId}
                </span>
              </div>

              {/* Dimensional score bars */}
              <div className="space-y-1.5 mb-2">
                {DIMENSION_ORDER.map((dim) => {
                  const value = entry.scores[dim];
                  if (value === undefined) return null;
                  return (
                    <DimensionBar
                      key={dim}
                      dim={dim}
                      value={value}
                      isFailing={failingSet.has(dim)}
                    />
                  );
                })}
                {/* Render any extra dimensions not in the standard 4 */}
                {Object.entries(entry.scores)
                  .filter(([dim]) => !DIMENSION_ORDER.includes(dim))
                  .map(([dim, value]) => (
                    <DimensionBar
                      key={dim}
                      dim={dim}
                      value={value}
                      isFailing={failingSet.has(dim)}
                    />
                  ))}
              </div>

              {/* Summary text */}
              {entry.summary && (
                <p className="text-[10px] text-slate-500 leading-relaxed line-clamp-2">
                  {entry.summary}
                </p>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
