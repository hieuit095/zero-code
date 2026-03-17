// @ai-module: Agent Store
// @ai-role: Central Zustand store for all multi-agent state: messages, task list, agent statuses,
//           activity labels, and run lifecycle state (status, progress).
//           This is the single writer for agent-domain state — all mutations go through the actions below.
// @ai-dependencies: types/index.ts (AgentMessage, Task, AgentRole, AgentStatus, AgentStatuses, ActiveActivities)

// [AI-STRICT] DO NOT mutate this Zustand state directly from UI components.
//             Only use the provided actions.
// [AI-STRICT] UI components must read this store only through the hook abstractions:
//             useAgentConnection (read-only selectors) and useAgentActions (write actions).
//             Do NOT call useAgentStore() directly from a UI component — always go through the hooks.

import { create } from 'zustand';
import type { AgentMessage, Task, AgentRole, AgentStatus, AgentStatuses, ActiveActivities } from '../types';

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

type ConnectionStatus = 'connected' | 'disconnected' | 'reconnecting';

interface AgentState {
  messages: AgentMessage[];
  tasks: Task[];
  agentStatuses: AgentStatuses;
  activeActivities: ActiveActivities;
  runStatus: string | null;
  runProgress: number;
  qaRetryState: QaRetryState | null;
  connectionStatus: ConnectionStatus;

  addMessage: (message: Omit<AgentMessage, 'id'>) => void;
  addMessageFromServer: (message: AgentMessage) => void;
  updateAgentStatus: (agent: AgentRole, status: AgentStatus, activity?: string | null) => void;
  updateTask: (id: string, status: Task['status']) => void;
  setTasks: (tasks: Task[]) => void;
  setRunStatus: (status: string | null) => void;
  setRunProgress: (progress: number) => void;
  setQaRetryState: (state: QaRetryState) => void;
  clearQaRetryState: () => void;
  setConnectionStatus: (status: ConnectionStatus) => void;
  resetToInitial: () => void;
}

let msgIdCounter = 100;

const defaultStatuses: AgentStatuses = {
  'tech-lead': 'idle',
  dev: 'idle',
  qa: 'idle',
};

const defaultActivities: ActiveActivities = {
  'tech-lead': null,
  dev: null,
  qa: null,
};

export const useAgentStore = create<AgentState>((set) => ({
  messages: [],
  tasks: [],
  agentStatuses: { ...defaultStatuses },
  activeActivities: { ...defaultActivities },
  runStatus: null,
  runProgress: 0,
  qaRetryState: null,
  connectionStatus: 'disconnected' as ConnectionStatus,

  // Client-side message creation (fallback when server doesn't provide id/timestamp)
  addMessage: (message) => {
    set((state) => ({
      messages: [
        ...state.messages,
        {
          ...message,
          id: `msg-${msgIdCounter++}`,
          timestamp: new Date().toLocaleTimeString('en-US', {
            hour12: false,
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit',
          }),
        },
      ],
    }));
  },

  // Server-authoritative message hydration — preserves backend-provided id and timestamp
  addMessageFromServer: (message) => {
    set((state) => ({
      messages: [...state.messages, message],
    }));
  },

  updateAgentStatus: (agent, status, activity = null) => {
    set((state) => ({
      agentStatuses: { ...state.agentStatuses, [agent]: status },
      activeActivities: { ...state.activeActivities, [agent]: activity },
    }));
  },

  updateTask: (id, status) => {
    set((state) => ({
      tasks: state.tasks.map((t) => (t.id === id ? { ...t, status } : t)),
    }));
  },

  // Full task list hydration from task:snapshot events
  setTasks: (tasks) => set({ tasks }),

  setRunStatus: (status) => set({ runStatus: status }),

  setRunProgress: (progress) => set({ runProgress: progress }),

  setQaRetryState: (state) => set({ qaRetryState: state }),

  clearQaRetryState: () => set({ qaRetryState: null }),

  setConnectionStatus: (status) => set({ connectionStatus: status }),

  resetToInitial: () =>
    set({
      messages: [],
      tasks: [],
      agentStatuses: { ...defaultStatuses },
      activeActivities: { ...defaultActivities },
      runStatus: null,
      runProgress: 0,
      qaRetryState: null,
      connectionStatus: 'disconnected' as ConnectionStatus,
    }),
}));
