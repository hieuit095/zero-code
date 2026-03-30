/**
 * ==========================================
 * Author: Hieu Nguyen - Codev Team
 * Email: hieuit095@gmail.com
 * Project: ZeroCode - Autonomous Multi-Agent IDE
 * ==========================================
 */
// @ai-module: Admin Dashboard
// @ai-role: System metrics dashboard fetching data from /api/admin/metrics and /api/admin/recent-runs.
//           Polls every 10 seconds for live updates.

import { useCallback, useEffect, useState } from 'react';
import { ArrowLeft, Activity, CheckCircle2, XCircle, Clock, RefreshCw, AlertTriangle } from 'lucide-react';

interface Metrics {
    totalRuns: number;
    activeRuns: number;
    completedRuns: number;
    failedRuns: number;
    avgDurationMs: number;
    qaRetryRate: number;
    totalQaFailures: number;
    failureRate: number;
    totalTasks: number;
    completedTasks: number;
}

interface RecentRun {
    id: string;
    goal: string;
    status: string;
    phase: string | null;
    progress: number;
    createdAt: string | null;
    updatedAt: string | null;
}

const _envVal = import.meta.env.VITE_API_BASE_URL?.trim();
const API_BASE = _envVal
  ? _envVal
  : (console.warn('[AdminDashboard] VITE_API_BASE_URL is not set — falling back to window.location.origin + \'/api\''), window.location.origin + '/api');

function formatDuration(ms: number): string {
    if (ms < 1000) return `${ms}ms`;
    const seconds = Math.round(ms / 1000);
    if (seconds < 60) return `${seconds}s`;
    const minutes = Math.floor(seconds / 60);
    const remaining = seconds % 60;
    return `${minutes}m ${remaining}s`;
}

function statusColor(status: string): string {
    switch (status) {
        case 'completed': return 'text-emerald-400';
        case 'failed': return 'text-red-400';
        case 'running': case 'developing': case 'verifying': case 'planning': return 'text-amber-400';
        case 'queued': return 'text-sky-400';
        default: return 'text-slate-400';
    }
}

function StatusDot({ status }: { status: string }) {
    const colors: Record<string, string> = {
        completed: 'bg-emerald-400',
        failed: 'bg-red-400',
        running: 'bg-amber-400 animate-pulse',
        developing: 'bg-amber-400 animate-pulse',
        verifying: 'bg-amber-400 animate-pulse',
        planning: 'bg-amber-400 animate-pulse',
        queued: 'bg-sky-400',
    };
    return <span className={`inline-block w-2 h-2 rounded-full ${colors[status] ?? 'bg-slate-600'}`} />;
}

export default function AdminDashboard() {
    const [metrics, setMetrics] = useState<Metrics | null>(null);
    const [recentRuns, setRecentRuns] = useState<RecentRun[]>([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [lastRefresh, setLastRefresh] = useState<Date>(new Date());

    const fetchData = useCallback(async () => {
        try {
            const [metricsRes, runsRes] = await Promise.all([
                fetch(`${API_BASE}/api/admin/metrics`),
                fetch(`${API_BASE}/api/admin/recent-runs?limit=10`),
            ]);

            if (!metricsRes.ok || !runsRes.ok) {
                throw new Error(`API error: metrics=${metricsRes.status}, runs=${runsRes.status}`);
            }

            const [metricsData, runsData] = await Promise.all([
                metricsRes.json(),
                runsRes.json(),
            ]);

            setMetrics(metricsData);
            setRecentRuns(runsData);
            setError(null);
            setLastRefresh(new Date());
        } catch (err) {
            setError(err instanceof Error ? err.message : 'Failed to fetch metrics');
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => {
        fetchData();
        const interval = setInterval(fetchData, 10_000);
        return () => clearInterval(interval);
    }, [fetchData]);

    return (
        <div className="min-h-screen bg-slate-950 text-slate-100">
            {/* Header */}
            <header className="h-14 flex items-center px-6 border-b border-slate-800 bg-slate-950 gap-4">
                <a href="/" className="flex items-center gap-2 text-slate-400 hover:text-slate-200 transition-colors">
                    <ArrowLeft className="w-4 h-4" />
                    <span className="text-sm">Back to IDE</span>
                </a>
                <div className="flex-1" />
                <h1 className="text-sm font-semibold text-slate-200">Admin Dashboard</h1>
                <div className="flex-1" />
                <div className="flex items-center gap-2 text-xs text-slate-500">
                    <RefreshCw className={`w-3 h-3 ${loading ? 'animate-spin' : ''}`} />
                    Last refresh: {lastRefresh.toLocaleTimeString()}
                </div>
            </header>

            <div className="max-w-6xl mx-auto px-6 py-8 space-y-8">
                {/* Error Banner */}
                {error && (
                    <div className="flex items-center gap-2 px-4 py-3 rounded-lg bg-red-500/10 border border-red-500/30 text-red-300 text-sm">
                        <AlertTriangle className="w-4 h-4 shrink-0" />
                        {error}
                    </div>
                )}

                {/* Metrics Cards */}
                {metrics && (
                    <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                        <MetricCard
                            icon={<Activity className="w-4 h-4 text-sky-400" />}
                            label="Active Runs"
                            value={metrics.activeRuns}
                            accent="border-sky-500/30 bg-sky-500/5"
                        />
                        <MetricCard
                            icon={<CheckCircle2 className="w-4 h-4 text-emerald-400" />}
                            label="Completed"
                            value={metrics.completedRuns}
                            accent="border-emerald-500/30 bg-emerald-500/5"
                        />
                        <MetricCard
                            icon={<XCircle className="w-4 h-4 text-red-400" />}
                            label="Failed"
                            value={metrics.failedRuns}
                            subtext={`${(metrics.failureRate * 100).toFixed(0)}% failure rate`}
                            accent="border-red-500/30 bg-red-500/5"
                        />
                        <MetricCard
                            icon={<Clock className="w-4 h-4 text-amber-400" />}
                            label="Avg Duration"
                            value={formatDuration(metrics.avgDurationMs)}
                            accent="border-amber-500/30 bg-amber-500/5"
                        />
                    </div>
                )}

                {/* QA Stats Row */}
                {metrics && (
                    <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                        <MetricCard label="Total Runs" value={metrics.totalRuns} />
                        <MetricCard label="Total Tasks" value={metrics.totalTasks} subtext={`${metrics.completedTasks} completed`} />
                        <MetricCard label="QA Retry Rate" value={`${(metrics.qaRetryRate * 100).toFixed(0)}%`} subtext={`${metrics.totalQaFailures} failures`} />
                        <MetricCard label="Task Completion" value={metrics.totalTasks > 0 ? `${((metrics.completedTasks / metrics.totalTasks) * 100).toFixed(0)}%` : 'N/A'} />
                    </div>
                )}

                {/* Recent Runs Table */}
                <div>
                    <h2 className="text-sm font-semibold text-slate-300 mb-3">Recent Runs</h2>
                    <div className="rounded-lg border border-slate-800 overflow-hidden">
                        <table className="w-full text-sm">
                            <thead>
                                <tr className="bg-slate-900/50 border-b border-slate-800">
                                    <th className="text-left px-4 py-2.5 text-xs font-medium text-slate-500 uppercase tracking-wider">Status</th>
                                    <th className="text-left px-4 py-2.5 text-xs font-medium text-slate-500 uppercase tracking-wider">Run ID</th>
                                    <th className="text-left px-4 py-2.5 text-xs font-medium text-slate-500 uppercase tracking-wider">Goal</th>
                                    <th className="text-left px-4 py-2.5 text-xs font-medium text-slate-500 uppercase tracking-wider">Progress</th>
                                    <th className="text-left px-4 py-2.5 text-xs font-medium text-slate-500 uppercase tracking-wider">Created</th>
                                </tr>
                            </thead>
                            <tbody>
                                {recentRuns.length === 0 && (
                                    <tr>
                                        <td colSpan={5} className="px-4 py-8 text-center text-slate-600 text-sm">
                                            No runs found
                                        </td>
                                    </tr>
                                )}
                                {recentRuns.map((run) => (
                                    <tr key={run.id} className="border-b border-slate-800/50 hover:bg-slate-900/30 transition-colors">
                                        <td className="px-4 py-3">
                                            <div className="flex items-center gap-2">
                                                <StatusDot status={run.status} />
                                                <span className={`text-xs font-medium capitalize ${statusColor(run.status)}`}>
                                                    {run.status}
                                                </span>
                                            </div>
                                        </td>
                                        <td className="px-4 py-3">
                                            <span className="text-xs font-mono text-slate-400">{run.id.slice(0, 12)}…</span>
                                        </td>
                                        <td className="px-4 py-3">
                                            <span className="text-xs text-slate-300 line-clamp-1">{run.goal || '—'}</span>
                                        </td>
                                        <td className="px-4 py-3">
                                            <div className="flex items-center gap-2">
                                                <div className="w-16 h-1.5 rounded-full bg-slate-800 overflow-hidden">
                                                    <div
                                                        className={`h-full rounded-full transition-all ${run.status === 'completed' ? 'bg-emerald-400' :
                                                                run.status === 'failed' ? 'bg-red-400' : 'bg-amber-400'
                                                            }`}
                                                        style={{ width: `${run.progress}%` }}
                                                    />
                                                </div>
                                                <span className="text-[10px] text-slate-500 font-mono w-7 text-right">{run.progress}%</span>
                                            </div>
                                        </td>
                                        <td className="px-4 py-3">
                                            <span className="text-xs text-slate-500">
                                                {run.createdAt ? new Date(run.createdAt).toLocaleString() : '—'}
                                            </span>
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>
        </div>
    );
}

function MetricCard({
    icon,
    label,
    value,
    subtext,
    accent = 'border-slate-800 bg-slate-900/50',
}: {
    icon?: React.ReactNode;
    label: string;
    value: string | number;
    subtext?: string;
    accent?: string;
}) {
    return (
        <div className={`rounded-lg border p-4 ${accent}`}>
            <div className="flex items-center gap-2 mb-2">
                {icon}
                <span className="text-[11px] text-slate-500 uppercase tracking-wider font-medium">{label}</span>
            </div>
            <div className="text-2xl font-bold text-slate-100">{value}</div>
            {subtext && <div className="text-[11px] text-slate-500 mt-1">{subtext}</div>}
        </div>
    );
}
