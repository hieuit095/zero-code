/**
 * ==========================================
 * Author: Hieu Nguyen - Codev Team
 * Email: hieuit095@gmail.com
 * Project: ZeroCode - Autonomous Multi-Agent IDE
 * ==========================================
 */
// @ai-module: Settings Modal Shell
// @ai-role: Modal container for the Settings section. Manages tab navigation between Agent Setup and AI API Feed.
//           Renders the correct page component based on activeTab prop. Handles Escape-to-close and backdrop click.
//           The modal is rendered inside the Header component so it sits above all layout panels.
// @ai-dependencies: components/settings/AgentSetupPage.tsx
//                   components/settings/APIFeedSetupPage.tsx

// [AI-STRICT] The modal uses conditional rendering (if (!open) return null) — this is intentional.
//             Settings pages do not need to maintain state across open/close cycles.
//             When persistence is added to AgentSetupPage or APIFeedSetupPage, those pages should
//             read initial state from a store (not local state) to survive modal close/reopen.
// [AI-STRICT] DO NOT move SettingsModal into a React portal. It is positioned fixed and renders correctly
//             inside the Header element due to the z-50 / backdrop-blur classes.


import { useEffect, useRef } from 'react';
import { X, Bot, Key, Zap, Settings2 } from 'lucide-react';
import { AgentSetupPage } from './AgentSetupPage';
import { APIFeedSetupPage } from './APIFeedSetupPage';

export type SettingsTab = 'agent-setup' | 'api-feed';

interface NavItem {
  id: SettingsTab;
  label: string;
  description: string;
  icon: React.ReactNode;
}

const NAV_ITEMS: NavItem[] = [
  {
    id: 'agent-setup',
    label: 'Agent Setup',
    description: 'Models & prompts',
    icon: <Bot className="w-4 h-4" />,
  },
  {
    id: 'api-feed',
    label: 'AI API Feed',
    description: 'Keys & endpoints',
    icon: <Key className="w-4 h-4" />,
  },
];

interface SettingsModalProps {
  open: boolean;
  activeTab: SettingsTab;
  onTabChange: (tab: SettingsTab) => void;
  onClose: () => void;
}

export function SettingsModal({ open, activeTab, onTabChange, onClose }: SettingsModalProps) {
  const backdropRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div
      ref={backdropRef}
      onClick={(e) => { if (e.target === backdropRef.current) onClose(); }}
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/80 backdrop-blur-sm"
    >
      <div className="relative flex h-[680px] w-[900px] max-h-[90vh] max-w-[95vw] rounded-xl border border-slate-700 bg-slate-950 shadow-2xl overflow-hidden">
        <div className="w-52 shrink-0 flex flex-col border-r border-slate-800 bg-slate-900/60">
          <div className="flex items-center gap-2.5 px-4 py-4 border-b border-slate-800">
            <div className="flex items-center justify-center w-7 h-7 rounded-md bg-slate-800 border border-slate-700">
              <Settings2 className="w-4 h-4 text-slate-400" />
            </div>
            <span className="text-sm font-semibold text-slate-200">Settings</span>
          </div>

          <nav className="flex-1 overflow-y-auto p-2 space-y-0.5">
            <div className="px-2 pt-2 pb-1">
              <span className="text-[9px] font-semibold text-slate-600 uppercase tracking-widest">
                Configuration
              </span>
            </div>
            {NAV_ITEMS.map((item) => {
              const active = activeTab === item.id;
              return (
                <button
                  key={item.id}
                  onClick={() => onTabChange(item.id)}
                  className={`flex items-center gap-3 w-full px-3 py-2.5 rounded-lg text-left transition-colors group ${
                    active
                      ? 'bg-sky-500/10 border border-sky-500/20 text-sky-300'
                      : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/60 border border-transparent'
                  }`}
                >
                  <span className={`shrink-0 transition-colors ${active ? 'text-sky-400' : 'text-slate-500 group-hover:text-slate-300'}`}>
                    {item.icon}
                  </span>
                  <div className="min-w-0">
                    <div className="text-xs font-medium truncate">{item.label}</div>
                    <div className={`text-[10px] truncate ${active ? 'text-sky-400/70' : 'text-slate-600'}`}>
                      {item.description}
                    </div>
                  </div>
                </button>
              );
            })}

            <div className="px-2 pt-4 pb-1">
              <span className="text-[9px] font-semibold text-slate-600 uppercase tracking-widest">
                Coming soon
              </span>
            </div>
            {(['Workspace', 'Appearance', 'Shortcuts', 'Integrations'] as const).map((label) => (
              <div
                key={label}
                className="flex items-center gap-3 px-3 py-2.5 rounded-lg text-slate-600 cursor-not-allowed"
              >
                <Zap className="w-4 h-4 shrink-0" />
                <div className="min-w-0">
                  <div className="text-xs font-medium">{label}</div>
                </div>
                <span className="ml-auto text-[9px] text-slate-700 bg-slate-800 border border-slate-700 px-1.5 py-0.5 rounded">
                  Soon
                </span>
              </div>
            ))}
          </nav>

          <div className="px-4 py-3 border-t border-slate-800">
            <p className="text-[10px] text-slate-600 leading-relaxed">Nanobot IDE · Alpha</p>
          </div>
        </div>

        <div className="flex-1 flex flex-col min-w-0">
          <div className="flex items-center justify-between px-6 py-4 border-b border-slate-800 shrink-0">
            <div>
              <h2 className="text-sm font-semibold text-slate-100">
                {NAV_ITEMS.find((n) => n.id === activeTab)?.label}
              </h2>
              <p className="text-[11px] text-slate-500 mt-0.5">
                {NAV_ITEMS.find((n) => n.id === activeTab)?.description}
              </p>
            </div>
            <button
              onClick={onClose}
              className="p-2 rounded-md hover:bg-slate-800 text-slate-500 hover:text-slate-200 transition-colors"
            >
              <X className="w-4 h-4" />
            </button>
          </div>

          <div className="flex-1 min-h-0">
            {activeTab === 'agent-setup' && <AgentSetupPage />}
            {activeTab === 'api-feed' && <APIFeedSetupPage />}
          </div>
        </div>
      </div>
    </div>
  );
}
