// @ai-module: Agent Store
// @ai-role: Central Zustand store for all multi-agent state: messages, task list, agent statuses,
//           activity labels, and simulation run/progress flags.
//           This is the single writer for agent-domain state — all mutations go through the actions below.
// @ai-dependencies: types/index.ts (AgentMessage, Task, AgentRole, AgentStatus, AgentStatuses, ActiveActivities)
//                   data/mockData.ts (initialAgentMessages, initialTasks — used as the reset seed)

// [AI-STRICT] DO NOT mutate this Zustand state directly from UI components.
//             Only use the provided actions: addMessage, updateAgentStatus, updateTask,
//             setSimulationRunning, setSimulationProgress, resetToInitial.
// [AI-STRICT] UI components must read this store only through the hook abstractions:
//             useAgentConnection (read-only selectors) and useAgentActions (write actions).
//             Do NOT call useAgentStore() directly from a UI component — always go through the hooks.
// [AI-STRICT] The isSimulationRunning / simulationProgress fields are mock-only.
//             When the real backend is connected, remove these fields and drive progress
//             from WebSocket 'run:progress' events instead.

import { create } from 'zustand';
import type { AgentMessage, Task, AgentRole, AgentStatus, AgentStatuses, ActiveActivities } from '../types';
import { initialAgentMessages, initialTasks } from '../data/mockData';

interface AgentState {
  messages: AgentMessage[];
  tasks: Task[];
  agentStatuses: AgentStatuses;
  activeActivities: ActiveActivities;
  // [AI-STRICT] isSimulationRunning and simulationProgress are mock scaffolding only.
  //             Replace with real connection state (wsConnected, wsError) when integrating the backend.
  isSimulationRunning: boolean;
  simulationProgress: number;

  addMessage: (message: Omit<AgentMessage, 'id'>) => void;
  updateAgentStatus: (agent: AgentRole, status: AgentStatus, activity?: string | null) => void;
  updateTask: (id: string, status: Task['status']) => void;
  setSimulationRunning: (running: boolean) => void;
  setSimulationProgress: (progress: number) => void;
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
  messages: initialAgentMessages,
  tasks: initialTasks,
  agentStatuses: { ...defaultStatuses },
  activeActivities: { ...defaultActivities },
  isSimulationRunning: false,
  simulationProgress: 0,

  // @ai-integration-point: When the real backend is connected, replace the manual id/timestamp
  //   assignment below with the values received from the WebSocket 'agent:message' event payload.
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

  // @ai-integration-point: When the real backend is connected, call this action from the
  //   WebSocket 'agent:status' event handler: updateAgentStatus(event.role, event.status, event.activity).
  updateAgentStatus: (agent, status, activity = null) => {
    set((state) => ({
      agentStatuses: { ...state.agentStatuses, [agent]: status },
      activeActivities: { ...state.activeActivities, [agent]: activity },
    }));
  },

  // @ai-integration-point: When the real backend is connected, call this action from the
  //   WebSocket 'task:update' event handler: updateTask(event.taskId, event.status).
  updateTask: (id, status) => {
    set((state) => ({
      tasks: state.tasks.map((t) => (t.id === id ? { ...t, status } : t)),
    }));
  },

  setSimulationRunning: (running) => set({ isSimulationRunning: running }),

  setSimulationProgress: (progress) => set({ simulationProgress: progress }),

  resetToInitial: () =>
    set({
      messages: initialAgentMessages,
      tasks: initialTasks,
      agentStatuses: { ...defaultStatuses },
      activeActivities: { ...defaultActivities },
      isSimulationRunning: false,
      simulationProgress: 0,
    }),
}));
