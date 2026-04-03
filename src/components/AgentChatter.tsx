/**
 * ==========================================
 * Author: Hieu Nguyen - Codev Team
 * Email: hieuit095@gmail.com
 * Project: ZeroCode - Autonomous Multi-Agent IDE
 * ==========================================
 */
// @ai-module: Agent Chatter
// @ai-role: Controlled component rendering the agent message feed and activity status bar.
//           Receives all data as props from LeftSidebar (which reads from useAgentConnection).
//           Also hosts the tab-switched AgentSkills panel.
// @ai-dependencies: Props only (AgentMessage[], AgentStatuses, ActiveActivities — no direct store access)
//                   components/AgentSkills.tsx (rendered in Skills tab)
//                   types/index.ts (AgentRole, AgentMessage, AgentStatuses, ActiveActivities)

// [AI-STRICT] AgentChatter is a CONTROLLED component. It receives all data as props.
//             DO NOT add useAgentStore() or useAgentConnection() calls inside this component.
//             If additional agent data is needed, add it to the props interface and thread it through LeftSidebar.
// [AI-STRICT] The chat input at the bottom is intentionally disabled (agents are autonomous).
//             When implementing user interrupts in the real backend, wire the Send button to
//             useAgentConnection().sendMessage({ type: "user:message", content }) instead of enabling local state.
// @ai-integration-point: The disabled chat input must be enabled when the real backend supports user messages.
//   Replace the disabled input with a controlled input and wire the Send button to sendMessage().


import { useEffect, useRef, useState, memo } from 'react';
import { Bot, Send, Loader2, Brain, Wrench, MessageSquare, Zap } from 'lucide-react';
import type { AgentRole, AgentMessage, AgentStatuses, ActiveActivities } from '../types';
import type { StreamingMessage } from '../stores/agentStore';
import { AgentSkills } from './AgentSkills';

type BottomTab = 'chat' | 'skills';

const agentConfig: Record<AgentRole, {
  label: string;
  color: string;
  bg: string;
  border: string;
  dot: string;
  dotIdle: string;
}> = {
  'tech-lead': {
    label: 'Tech Lead',
    color: 'text-amber-300',
    bg: 'bg-amber-500/15',
    border: 'border-amber-500/30',
    dot: 'bg-amber-400',
    dotIdle: 'bg-amber-600',
  },
  dev: {
    label: 'Dev',
    color: 'text-sky-300',
    bg: 'bg-sky-500/15',
    border: 'border-sky-500/30',
    dot: 'bg-sky-400',
    dotIdle: 'bg-sky-700',
  },
  qa: {
    label: 'QA',
    color: 'text-emerald-300',
    bg: 'bg-emerald-500/15',
    border: 'border-emerald-500/30',
    dot: 'bg-emerald-400',
    dotIdle: 'bg-emerald-700',
  },
};

interface ActivityBarProps {
  agentStatuses: AgentStatuses;
  activeActivities: ActiveActivities;
}

const ActivityBar = memo(function ActivityBar({ agentStatuses, activeActivities }: ActivityBarProps) {
  const activeAgents = (Object.keys(agentStatuses) as AgentRole[]).filter(
    (r) => agentStatuses[r] !== 'idle'
  );

  if (activeAgents.length === 0) {
    return (
      <div className="flex items-center gap-1.5 px-3 py-1.5 border-b border-slate-800 bg-slate-900/40 shrink-0">
        <span className="w-1.5 h-1.5 rounded-full bg-slate-600" />
        <span className="text-[11px] text-slate-500">All agents idle</span>
      </div>
    );
  }

  return (
    <div className="border-b border-slate-800 bg-slate-900/60 shrink-0">
      {activeAgents.map((role) => {
        const cfg = agentConfig[role];
        const status = agentStatuses[role];
        const activity = activeActivities[role];
        return (
          <div key={role} className={`flex items-center gap-2 px-3 py-1.5 ${cfg.bg} border-b border-slate-800/50 last:border-b-0`}>
            {status === 'thinking' ? (
              <Brain className={`w-3 h-3 ${cfg.color} shrink-0 animate-pulse`} />
            ) : (
              <Wrench className={`w-3 h-3 ${cfg.color} shrink-0`} />
            )}
            <span className={`text-[11px] font-semibold ${cfg.color} shrink-0`}>{cfg.label}</span>
            <span className="text-[11px] text-slate-400 truncate">
              {activity ?? (status === 'thinking' ? 'Thinking...' : 'Working...')}
            </span>
            <Loader2 className={`w-3 h-3 ${cfg.color} ml-auto shrink-0 animate-spin`} />
          </div>
        );
      })}
    </div>
  );
});

const ChatMessageItem = memo(function ChatMessageItem({ msg, cfg }: { msg: AgentMessage, cfg: typeof agentConfig[AgentRole] }) {
  return (
    <div className="group">
      <div className="flex items-start gap-2">
        <div className={`mt-0.5 shrink-0 flex items-center justify-center w-5 h-5 rounded ${cfg.bg} border ${cfg.border}`}>
          <Bot className={`w-3 h-3 ${cfg.color}`} />
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-1.5 mb-0.5">
            <span className={`text-[11px] font-semibold ${cfg.color}`}>{cfg.label}</span>
            <span className="text-[10px] text-slate-600">{msg.timestamp}</span>
          </div>
          <p className="text-[12px] text-slate-300 leading-relaxed break-words">
            {msg.content}
          </p>
        </div>
      </div>
    </div>
  );
});

const StreamingMessageItem = memo(function StreamingMessageItem({ stream, cfg }: { stream: StreamingMessage, cfg: typeof agentConfig[AgentRole] }) {
  return (
    <div className="group">
      <div className="flex items-start gap-2">
        <div className={`mt-0.5 shrink-0 flex items-center justify-center w-5 h-5 rounded ${cfg.bg} border ${cfg.border}`}>
          <Bot className={`w-3 h-3 ${cfg.color} animate-pulse`} />
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-1.5 mb-0.5">
            <span className={`text-[11px] font-semibold ${cfg.color}`}>{cfg.label}</span>
            <span className="text-[10px] text-sky-500/60 flex items-center gap-1">
              <Loader2 className="w-2.5 h-2.5 animate-spin" />
              streaming
            </span>
          </div>
          <p className="text-[12px] text-slate-300 leading-relaxed break-words">
            {stream.content}
            <span className="inline-block w-1.5 h-3.5 ml-0.5 bg-sky-400/70 animate-pulse rounded-sm align-text-bottom" />
          </p>
        </div>
      </div>
    </div>
  );
});

interface AgentChatterProps {
  messages: AgentMessage[];
  agentStatuses: AgentStatuses;
  activeActivities: ActiveActivities;
  streamingMessages: Record<string, StreamingMessage>;
}

export function AgentChatter({ messages, agentStatuses, activeActivities, streamingMessages }: AgentChatterProps) {
  const bottomRef = useRef<HTMLDivElement>(null);
  const [activeTab, setActiveTab] = useState<BottomTab>('chat');

  const streamingEntries = Object.entries(streamingMessages);
  const hasStreamingContent = streamingEntries.length > 0;

  useEffect(() => {
    if (activeTab === 'chat') {
      bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
    }
  }, [messages.length, hasStreamingContent, activeTab]);

  const anyActive = (Object.keys(agentStatuses) as AgentRole[]).some(
    (r) => agentStatuses[r] !== 'idle'
  );

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center border-b border-slate-800 h-9 shrink-0 px-2 gap-0.5">
        <button
          onClick={() => setActiveTab('chat')}
          className={`flex items-center gap-1.5 px-2.5 h-full text-[11px] font-medium border-b-2 transition-colors ${
            activeTab === 'chat'
              ? 'border-sky-500 text-sky-300'
              : 'border-transparent text-slate-500 hover:text-slate-300'
          }`}
        >
          <MessageSquare className="w-3 h-3" />
          Chat
          {anyActive && (
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse ml-0.5" />
          )}
        </button>

        <button
          onClick={() => setActiveTab('skills')}
          className={`flex items-center gap-1.5 px-2.5 h-full text-[11px] font-medium border-b-2 transition-colors ${
            activeTab === 'skills'
              ? 'border-sky-500 text-sky-300'
              : 'border-transparent text-slate-500 hover:text-slate-300'
          }`}
        >
          <Zap className="w-3 h-3" />
          Skills
        </button>

        <div className="flex-1" />

        {activeTab === 'chat' && (
          <div className="flex items-center gap-1.5">
            {(['tech-lead', 'dev', 'qa'] as AgentRole[]).map((role) => {
              const cfg = agentConfig[role];
              const isActive = agentStatuses[role] !== 'idle';
              return (
                <span
                  key={role}
                  title={`${cfg.label}: ${agentStatuses[role]}`}
                  className={`w-2 h-2 rounded-full transition-colors ${
                    isActive
                      ? `${cfg.dot} shadow-[0_0_6px_1px] shadow-current animate-pulse`
                      : cfg.dotIdle
                  }`}
                />
              );
            })}
          </div>
        )}
      </div>

      <div className={activeTab === 'chat' ? 'flex flex-col flex-1 min-h-0' : 'hidden'}>
        <ActivityBar agentStatuses={agentStatuses} activeActivities={activeActivities} />

        <div className="flex-1 overflow-y-auto px-2 py-2 space-y-2">
          {messages.map((msg) => (
            <ChatMessageItem key={msg.id} msg={msg} cfg={agentConfig[msg.agent]} />
          ))}

          {/* ── Streaming Messages (in-flight LLM tokens) ──────────────── */}
          {streamingEntries.map(([msgId, stream]) => (
            <StreamingMessageItem key={`stream-${msgId}`} stream={stream} cfg={agentConfig[stream.role]} />
          ))}

          <div ref={bottomRef} />
        </div>

        <div className="px-2 py-2 border-t border-slate-800 shrink-0">
          <div className="flex items-center gap-2 px-2 py-1.5 rounded-md bg-slate-800 border border-slate-700">
            <input
              disabled
              placeholder="Agents are working..."
              className="flex-1 bg-transparent text-xs text-slate-500 placeholder:text-slate-600 focus:outline-none cursor-not-allowed"
            />
            <button disabled className="text-slate-600 cursor-not-allowed">
              <Send className="w-3 h-3" />
            </button>
          </div>
        </div>
      </div>

      <div className={activeTab === 'skills' ? 'flex flex-col flex-1 min-h-0' : 'hidden'}>
        <AgentSkills />
      </div>
    </div>
  );
}
