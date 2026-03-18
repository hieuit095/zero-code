// @ai-module: Header
// @ai-role: Top application bar containing the goal input, Generate button, run controls,
//           agent status indicator, and the Settings gear icon that opens SettingsModal.
//           Also hosts the SettingsModal component itself (rendered at the header level so it portals correctly).
// @ai-dependencies: hooks/useRunConnection.ts (startRun, disconnect, runStatus, runProgress)
//                   stores/settingsStore.ts (getAgentConfig — injected into run payload)
//                   components/settings/SettingsModal.tsx (modal shell)

// [AI-STRICT] The "Generate" / goal input workflow is mock-only scaffolding (setIsGenerating with a 2-second timeout).
//             When the real backend is connected:
//             1. Remove the isGenerating local state and timeout.
//             2. Wire the Generate button to useSimulation().startSimulation() with the goal text as a parameter.
//             3. Pass the goal to the backend via ws.send({ type: "run:start", goal }).
// @ai-integration-point: Replace the Generate button handler with:
//   const handleGenerate = () => {
//     if (\!goal.trim() || isRunning) return;
//     sendMessage({ type: "run:start", goal });
//   };
//   This requires threading sendMessage from useAgentConnection through to Header.


import { useState } from 'react';
import { Bot, Sparkles, Settings, ChevronDown, Zap, RotateCcw, AlertTriangle, X } from 'lucide-react';
import { useRunConnection } from '../hooks/useRunConnection';
import { useAgentStore } from '../stores/agentStore';
import { useSettingsStore } from '../stores/settingsStore';
import { SettingsModal } from './settings/SettingsModal';
import type { SettingsTab } from './settings/SettingsModal';

export function Header() {
  const [goal, setGoal] = useState('');
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [settingsTab, setSettingsTab] = useState<SettingsTab>('agent-setup');
  const [errorDismissed, setErrorDismissed] = useState(false);
  const { startRun, disconnect, sendMessage, isConnected, error: runError } = useRunConnection();
  const runStatus = useAgentStore((s) => s.runStatus);
  const progress = useAgentStore((s) => s.runProgress);
  const resetAgent = useAgentStore((s) => s.resetToInitial);
  const connectionStatus = useAgentStore((s) => s.connectionStatus);
  const getAgentConfig = useSettingsStore((s) => s.getAgentConfig);
  // PHASE 3 FIX (Task 3): Dynamic workspace ID from settings store.
  const workspaceId = useSettingsStore((s) => s.workspaceId);

  const isRunning = runStatus !== null && runStatus !== 'completed' && runStatus !== 'failed';

  const handleGenerate = async () => {
    if (!goal.trim() || isRunning) return;
    try {
      const agentConfig = getAgentConfig();

      // Preferred path: dispatch run:start over WebSocket
      if (isConnected) {
        sendMessage({
          type: 'run:start',
          data: { goal: goal.trim(), workspaceId, agentConfig },
        });
      } else {
        // Fallback: REST → WS handshake for cold start
        await startRun({ goal: goal.trim(), workspaceId, agentConfig });
      }
    } catch {
      // Connection error is shown via runConnection state
    }
  };

  const handleReset = () => {
    disconnect();
    resetAgent();
    setErrorDismissed(false);
  };

  // PHASE 3 FIX: Surface fatal run:error messages visibly.
  const showErrorBanner = !!runError && !errorDismissed;

  const showDisconnectBanner = connectionStatus === 'disconnected' || connectionStatus === 'reconnecting';

  return (
    <>
      <header className="h-14 flex items-center px-4 border-b border-slate-800 bg-slate-950 shrink-0 gap-4">
        <div className="flex items-center gap-2 w-44 shrink-0">
          <div className="flex items-center justify-center w-7 h-7 rounded-md bg-sky-500/15 border border-sky-500/30">
            <Bot className="w-4 h-4 text-sky-400" />
          </div>
          <span className="font-semibold text-slate-100 text-sm tracking-tight">Nanobot IDE</span>
          <span className="text-[10px] font-medium px-1.5 py-0.5 rounded bg-sky-500/15 text-sky-400 border border-sky-500/20 ml-0.5">
            ALPHA
          </span>
        </div>

        <div className="flex-1 flex items-center gap-2 max-w-2xl mx-auto">
          <div className="flex-1 flex items-center bg-slate-900 border border-slate-700 rounded-md px-3 gap-2 focus-within:border-sky-500/60 transition-colors">
            <Sparkles className="w-3.5 h-3.5 text-slate-500 shrink-0" />
            <input
              type="text"
              value={goal}
              onChange={(e) => setGoal(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleGenerate()}
              placeholder="Describe your goal (e.g., Build a login form)..."
              className="flex-1 bg-transparent text-sm text-slate-200 placeholder:text-slate-500 py-2 focus:outline-none"
            />
            {goal && (
              <button onClick={() => setGoal('')} className="text-slate-500 hover:text-slate-300 text-xs transition-colors">
                ✕
              </button>
            )}
          </div>
          <button
            onClick={handleGenerate}
            disabled={!goal.trim() || isRunning}
            className="flex items-center gap-1.5 px-4 py-2 rounded-md bg-sky-600 hover:bg-sky-500 disabled:opacity-50 disabled:cursor-not-allowed text-white text-sm font-medium transition-colors shrink-0"
          >
            <Zap className={`w-3.5 h-3.5 ${isRunning ? 'animate-pulse' : ''}`} />
            {isRunning ? 'Running...' : 'Generate'}
          </button>
        </div>

        <div className="flex items-center gap-2 shrink-0">
          <div className="flex items-center gap-1.5 relative">
            {isRunning ? (
              <div className="flex items-center gap-2 bg-amber-500/10 border border-amber-500/30 rounded-md px-3 py-1.5">
                <div className="flex items-center gap-1.5">
                  <span className="w-1.5 h-1.5 rounded-full bg-amber-400 animate-pulse" />
                  <span className="text-xs text-amber-300 font-medium">Running...</span>
                </div>
                <div className="w-20 h-1 rounded-full bg-slate-800 overflow-hidden">
                  <div
                    className="h-full rounded-full bg-amber-400 transition-all duration-300"
                    style={{ width: `${progress}%` }}
                  />
                </div>
                <span className="text-[10px] text-amber-400 font-mono w-7 text-right">{progress}%</span>
              </div>
            ) : (
              <button
                onClick={handleReset}
                title="Reset run state"
                className="p-1.5 rounded-md hover:bg-slate-800 border border-transparent hover:border-slate-700 text-slate-500 hover:text-slate-300 transition-colors"
              >
                <RotateCcw className="w-3.5 h-3.5" />
              </button>
            )}
          </div>

          <div className="w-px h-5 bg-slate-800" />

          <button className="flex items-center gap-1.5 px-2 py-1.5 rounded-md hover:bg-slate-800 text-slate-400 hover:text-slate-200 transition-colors text-xs">
            <div className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
            3 agents
          </button>
          <button
            onClick={() => setSettingsOpen(true)}
            className={`p-1.5 rounded-md hover:bg-slate-800 transition-colors ${settingsOpen ? 'text-sky-400 bg-sky-500/10' : 'text-slate-400 hover:text-slate-200'}`}
            title="Settings"
          >
            <Settings className="w-4 h-4" />
          </button>
          <button className="flex items-center gap-1 pl-1 pr-2 py-1 rounded-md hover:bg-slate-800 transition-colors group">
            <div className="w-7 h-7 rounded-full bg-gradient-to-br from-amber-400 to-orange-500 flex items-center justify-center text-[11px] font-bold text-white">
              U
            </div>
            <ChevronDown className="w-3 h-3 text-slate-500 group-hover:text-slate-300 transition-colors" />
          </button>
        </div>

        <SettingsModal
          open={settingsOpen}
          activeTab={settingsTab}
          onTabChange={setSettingsTab}
          onClose={() => setSettingsOpen(false)}
        />
      </header>
      {showDisconnectBanner && (
        <div className={`flex items-center justify-center gap-2 px-4 py-1.5 text-xs font-medium ${connectionStatus === 'reconnecting'
          ? 'bg-amber-500/15 border-b border-amber-500/30 text-amber-300'
          : 'bg-red-500/15 border-b border-red-500/30 text-red-300'
          }`}>
          <span className={`w-1.5 h-1.5 rounded-full ${connectionStatus === 'reconnecting' ? 'bg-amber-400 animate-pulse' : 'bg-red-400'
            }`} />
          {connectionStatus === 'reconnecting'
            ? 'Connection lost. Reconnecting…'
            : 'Disconnected from server.'}
        </div>
      )}
      {/* PHASE 3 FIX: Global error banner for fatal run:error events */}
      {showErrorBanner && (
        <div className="flex items-center gap-3 px-4 py-2 text-sm font-medium bg-red-500/15 border-b border-red-500/30 text-red-200 animate-in slide-in-from-top-1">
          <AlertTriangle className="w-4 h-4 text-red-400 shrink-0" />
          <span className="flex-1 truncate">
            <span className="font-semibold text-red-300">Run Failed: </span>
            {runError}
          </span>
          <button
            onClick={() => setErrorDismissed(true)}
            className="p-0.5 rounded hover:bg-red-500/20 text-red-400 hover:text-red-200 transition-colors shrink-0"
            title="Dismiss error"
          >
            <X className="w-3.5 h-3.5" />
          </button>
        </div>
      )}
    </>
  );
}
