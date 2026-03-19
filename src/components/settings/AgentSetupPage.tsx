/**
 * ==========================================
 * Author: Hieu Nguyen - Codev Team
 * Email: hieuit095@gmail.com
 * Project: ZeroCode - Autonomous Multi-Agent IDE
 * ==========================================
 */
// @ai-module: Settings — Agent Setup Page
// @ai-role: Settings panel for configuring per-agent AI model selection and system prompt editing.
//           Model and prompt state is persisted via useSettingsStore (Zustand + localStorage).
//           Provides lock/unlock toggle to protect prompts from accidental edits, reset-to-default, and Modified badge.
// @ai-dependencies: types/index.ts (AgentRole), stores/settingsStore.ts (useSettingsStore)


import { useState } from 'react';
import {
  Bot,
  RotateCcw,
  Sparkles,
  Info,
  Lock,
  Unlock,
  Crown,
  Code2,
  TestTube2,
} from 'lucide-react';
import type { AgentRole } from '../../types';
import { useSettingsStore } from '../../stores/settingsStore';

// Removed MODELS and TIER_STYLES constants as we now support arbitrary inputs

interface AgentConfig {
  role: AgentRole;
  label: string;
  icon: React.ReactNode;
  color: string;
  bg: string;
  border: string;
  dot: string;
  defaultPrompt: string;
}

const AGENT_CONFIGS: AgentConfig[] = [
  {
    role: 'tech-lead',
    label: 'Tech Lead',
    icon: <Crown className="w-3.5 h-3.5" />,
    color: 'text-amber-300',
    bg: 'bg-amber-500/10',
    border: 'border-amber-500/30',
    dot: 'bg-amber-400',
    defaultPrompt:
      'You are a senior technical lead responsible for breaking down goals into structured tasks, making architectural decisions, and delegating work to the Dev and QA agents. You think holistically about the project, prioritize correctness and maintainability, and write concise, precise reasoning before assigning tasks.',
  },
  {
    role: 'dev',
    label: 'Developer',
    icon: <Code2 className="w-3.5 h-3.5" />,
    color: 'text-sky-300',
    bg: 'bg-sky-500/10',
    border: 'border-sky-500/30',
    dot: 'bg-sky-400',
    defaultPrompt:
      'You are a skilled software developer focused on writing clean, idiomatic code. You implement tasks assigned by the Tech Lead, follow existing conventions in the codebase, and communicate progress clearly. You ask clarifying questions only when strictly necessary and always prefer making a reasonable decision over stalling.',
  },
  {
    role: 'qa',
    label: 'QA Engineer',
    icon: <TestTube2 className="w-3.5 h-3.5" />,
    color: 'text-emerald-300',
    bg: 'bg-emerald-500/10',
    border: 'border-emerald-500/30',
    dot: 'bg-emerald-400',
    defaultPrompt:
      'You are a quality assurance engineer responsible for writing tests, running static analysis, and verifying that new code does not introduce regressions. You report issues clearly with file paths and line numbers, suggest fixes when possible, and escalate critical failures to the Tech Lead.',
  },
];

interface AgentCardProps {
  config: AgentConfig;
  provider: string;
  model: string;
  prompt: string;
  locked: boolean;
  onProviderChange: (provider: string) => void;
  onModelChange: (model: string) => void;
  onPromptChange: (prompt: string) => void;
  onToggleLock: () => void;
  onResetPrompt: () => void;
}

function ModelDropdown({
  provider,
  model,
  onProviderChange,
  onModelChange,
}: {
  provider: string;
  model: string;
  onProviderChange: (v: string) => void;
  onModelChange: (v: string) => void;
}) {
  return (
    <div className="flex gap-2">
      <input
        type="text"
        value={provider}
        onChange={(e) => onProviderChange(e.target.value)}
        placeholder="Provider (e.g. OpenAI)"
        className="w-1/3 px-3 py-2 rounded-md bg-slate-900 border border-slate-700 hover:border-slate-600 focus:border-sky-500/60 focus:bg-slate-900/80 text-xs text-slate-200 placeholder:text-slate-600 focus:outline-none transition-colors"
      />
      <input
        type="text"
        value={model}
        onChange={(e) => onModelChange(e.target.value)}
        placeholder="Model ID (e.g. gpt-4o)"
        className="flex-1 px-3 py-2 rounded-md bg-slate-900 border border-slate-700 hover:border-slate-600 focus:border-sky-500/60 focus:bg-slate-900/80 text-xs text-slate-200 placeholder:text-slate-600 focus:outline-none transition-colors"
      />
    </div>
  );
}

function AgentCard({
  config,
  provider,
  model,
  prompt,
  locked,
  onProviderChange,
  onModelChange,
  onPromptChange,
  onToggleLock,
  onResetPrompt,
}: AgentCardProps) {
  const isDirty = prompt !== config.defaultPrompt;

  return (
    <div className={`rounded-lg border ${config.border} bg-slate-900/50`}>
      <div className={`flex items-center gap-2.5 px-4 py-3 border-b ${config.border} ${config.bg} rounded-t-lg`}>
        <div className={`flex items-center justify-center w-7 h-7 rounded-md ${config.bg} border ${config.border} ${config.color}`}>
          {config.icon}
        </div>
        <div>
          <span className={`text-sm font-semibold ${config.color}`}>{config.label}</span>
          <p className="text-[10px] text-slate-500 leading-tight">System prompt &amp; model configuration</p>
        </div>
        <div className="ml-auto flex items-center gap-1.5">
          {isDirty && (
            <button
              onClick={onResetPrompt}
              title="Reset to default prompt"
              className="flex items-center gap-1 px-2 py-1 rounded text-[10px] text-slate-400 hover:text-slate-200 hover:bg-slate-700/50 transition-colors"
            >
              <RotateCcw className="w-2.5 h-2.5" />
              Reset
            </button>
          )}
          <button
            onClick={onToggleLock}
            title={locked ? 'Unlock to edit' : 'Lock prompt'}
            className={`p-1.5 rounded transition-colors ${locked
              ? 'text-slate-500 hover:text-slate-300 hover:bg-slate-700/40'
              : 'text-amber-400 hover:text-amber-300 hover:bg-amber-500/10'
              }`}
          >
            {locked ? <Lock className="w-3 h-3" /> : <Unlock className="w-3 h-3" />}
          </button>
        </div>
      </div>

      <div className="px-4 py-3 space-y-3">
        <div>
          <label className="flex items-center gap-1.5 text-[11px] font-semibold text-slate-400 uppercase tracking-widest mb-1.5">
            <Bot className="w-3 h-3" />
            Provider & Model
          </label>
          <ModelDropdown provider={provider} model={model} onProviderChange={onProviderChange} onModelChange={onModelChange} />
        </div>

        <div>
          <label className="flex items-center gap-1.5 text-[11px] font-semibold text-slate-400 uppercase tracking-widest mb-1.5">
            <Sparkles className="w-3 h-3" />
            System Prompt
            {isDirty && (
              <span className="ml-1 text-[9px] font-medium text-amber-400 bg-amber-500/10 border border-amber-500/20 px-1.5 py-0.5 rounded normal-case tracking-normal">
                Modified
              </span>
            )}
          </label>
          <textarea
            value={prompt}
            onChange={(e) => onPromptChange(e.target.value)}
            disabled={locked}
            rows={5}
            className={`w-full bg-slate-950 border rounded-md px-3 py-2 text-xs text-slate-300 leading-relaxed resize-y focus:outline-none transition-colors placeholder:text-slate-600 ${locked
              ? 'border-slate-800 opacity-60 cursor-not-allowed'
              : 'border-slate-700 focus:border-sky-500/60'
              }`}
          />
          {locked && (
            <p className="flex items-center gap-1 mt-1.5 text-[10px] text-slate-600">
              <Lock className="w-2.5 h-2.5" />
              Unlock to edit this agent's system prompt
            </p>
          )}
        </div>
      </div>
    </div>
  );
}

export function AgentSetupPage() {
  const agentModels = useSettingsStore((s) => s.agentModels);
  const setAgentModel = useSettingsStore((s) => s.setAgentModel);
  const setAgentSystemPrompt = useSettingsStore((s) => s.setAgentSystemPrompt);

  const [locked, setLocked] = useState<Record<AgentRole, boolean>>({
    'tech-lead': true,
    dev: true,
    qa: true,
  });

  const setModel = (role: AgentRole, provider: string, model: string) => setAgentModel(role, provider, model);
  const setPrompt = (role: AgentRole, prompt: string) => setAgentSystemPrompt(role, prompt);
  const toggleLock = (role: AgentRole) =>
    setLocked((p) => ({ ...p, [role]: !p[role] }));
  const resetPrompt = (role: AgentRole) => {
    const cfg = AGENT_CONFIGS.find((c) => c.role === role)!;
    setAgentSystemPrompt(role, cfg.defaultPrompt);
  };

  return (
    <div className="h-full overflow-y-auto">
      <div className="max-w-2xl mx-auto px-6 py-6 space-y-4">
        <div className="mb-6">
          <h2 className="text-base font-semibold text-slate-100 mb-1">Agent Setup</h2>
          <p className="text-sm text-slate-500">
            Configure the AI model and system prompt for each agent role. System prompts shape how each agent reasons and communicates.
          </p>
        </div>

        <div className="flex items-start gap-2.5 px-3 py-2.5 rounded-md bg-sky-500/5 border border-sky-500/20">
          <Info className="w-3.5 h-3.5 text-sky-400 shrink-0 mt-0.5" />
          <p className="text-[11px] text-sky-300/80 leading-relaxed">
            Model changes apply to the next agent run. System prompt edits are validated before saving. Unlock an agent's prompt to customize its behavior.
          </p>
        </div>

        {AGENT_CONFIGS.map((cfg) => (
          <AgentCard
            key={cfg.role}
            config={cfg}
            provider={agentModels[cfg.role].provider}
            model={agentModels[cfg.role].model}
            prompt={agentModels[cfg.role].systemPrompt ?? AGENT_CONFIGS.find((c) => c.role === cfg.role)!.defaultPrompt}
            locked={locked[cfg.role]}
            onProviderChange={(p) => setModel(cfg.role, p, agentModels[cfg.role].model)}
            onModelChange={(m) => setModel(cfg.role, agentModels[cfg.role].provider, m)}
            onPromptChange={(p) => setPrompt(cfg.role, p)}
            onToggleLock={() => toggleLock(cfg.role)}
            onResetPrompt={() => resetPrompt(cfg.role)}
          />
        ))}
      </div>
    </div>
  );
}
