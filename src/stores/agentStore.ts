/**
 * ==========================================
 * Author: Hieu Nguyen - Codev Team
 * Email: hieuit095@gmail.com
 * Project: ZeroCode - Autonomous Multi-Agent IDE
 * ==========================================
 */
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

// ── Streaming message buffer ─────────────────────────────────────────────────
// Holds in-flight LLM token deltas keyed by messageId. Each entry accumulates
// real `agent:message:delta` WebSocket payloads until the final `agent:message`
// event arrives, at which point the entry is removed and the complete message
// is added to the persistent `messages[]` array.

export interface StreamingMessage {
  role: AgentRole;
  content: string;
  lastSeq: number;
}

// ── QA score history entry ───────────────────────────────────────────────────
// Persists each QA evaluation (report or pass) so the QA Dashboard can render
// score trends across retries. Populated exclusively from real `qa:report` and
// `qa:passed` WebSocket events — never from mocks or hardcoded data.

export interface QaScoreEntry {
  taskId: string;
  attempt: number;
  status: 'failed' | 'passed';
  scores: Record<string, number>;
  failingDimensions: string[];
  summary: string;
  timestamp: string;
}

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

type ConnectionStatus = 'idle' | 'connected' | 'disconnected' | 'reconnecting';

interface AgentState {
  messages: AgentMessage[];
  tasks: Task[];
  agentStatuses: AgentStatuses;
  activeActivities: ActiveActivities;
  runStatus: string | null;
  runProgress: number;
  qaRetryState: QaRetryState | null;
  connectionStatus: ConnectionStatus;

  // ── Phase 1: Streaming buffer ──────────────────────────────────────────
  streamingMessages: Record<string, StreamingMessage>;

  // ── Phase 2: QA score history ──────────────────────────────────────────
  qaScoreHistory: QaScoreEntry[];

  addMessage: (message: Omit<AgentMessage, 'id'>) => void;
  addMessageFromServer: (message: AgentMessage) => void;
  updateAgentStatus: (agent: AgentRole, status: AgentStatus, activity?: string | null) => void;
  upsertTask: (id: string, status: Task['status']) => void;
  setTasks: (tasks: Task[]) => void;
  setRunStatus: (status: string | null) => void;
  setRunProgress: (progress: number) => void;
  setQaRetryState: (state: QaRetryState) => void;
  clearQaRetryState: () => void;
  setConnectionStatus: (status: ConnectionStatus) => void;

  // ── Phase 1: Streaming actions ─────────────────────────────────────────
  startStreamingMessage: (messageId: string, role: AgentRole) => void;
  appendStreamingDelta: (messageId: string, delta: string, seq: number) => void;
  finalizeStreamingMessage: (messageId: string) => void;

  // ── Phase 2: QA history actions ────────────────────────────────────────
  pushQaScore: (entry: QaScoreEntry) => void;
  clearQaScoreHistory: () => void;

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
  connectionStatus: 'idle' as ConnectionStatus,
  streamingMessages: {},
  qaScoreHistory: [],

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

  upsertTask: (id, status) => {
    set((state) => {
      const idx = state.tasks.findIndex((t) => t.id === id);
      if (idx !== -1) {
        const updated = [...state.tasks];
        updated[idx] = { ...updated[idx], status };
        return { tasks: updated };
      } else {
        console.warn(`[agentStore] upsertTask: task ${id} not in array — inserted (possible out-of-order event)`);
        return { tasks: [...state.tasks, { id, status, label: '', description: '' }] };
      }
    });
  },

  // Full task list hydration from task:snapshot events
  setTasks: (tasks) => set({ tasks }),

  setRunStatus: (status) => set({ runStatus: status }),

  setRunProgress: (progress) => set({ runProgress: progress }),

  setQaRetryState: (state) => set({ qaRetryState: state }),

  clearQaRetryState: () => set({ qaRetryState: null }),

  setConnectionStatus: (status) => set({ connectionStatus: status }),

  // ── Phase 1: Streaming buffer actions ────────────────────────────────

  startStreamingMessage: (messageId, role) => {
    set((state) => ({
      streamingMessages: {
        ...state.streamingMessages,
        [messageId]: { role, content: '', lastSeq: 0 },
      },
    }));
  },

  appendStreamingDelta: (messageId, delta, seq) => {
    set((state) => {
      const existing = state.streamingMessages[messageId];
      if (!existing) return state;
      if (existing.lastSeq !== undefined && seq <= existing.lastSeq) return state;
      return {
        streamingMessages: {
          ...state.streamingMessages,
          [messageId]: {
            ...existing,
            content: existing.content + delta,
            lastSeq: seq,
          },
        },
      };
    });
  },

  finalizeStreamingMessage: (messageId) => {
    set((state) => {
      const next = { ...state.streamingMessages };
      delete next[messageId];
      return { streamingMessages: next };
    });
  },

  // ── Phase 2: QA history actions ──────────────────────────────────────

  pushQaScore: (entry) => {
    set((state) => ({
      qaScoreHistory: [...state.qaScoreHistory, entry],
    }));
  },

  clearQaScoreHistory: () => set({ qaScoreHistory: [] }),

  resetToInitial: () =>
    set({
      messages: [],
      tasks: [],
      agentStatuses: { ...defaultStatuses },
      activeActivities: { ...defaultActivities },
      runStatus: null,
      runProgress: 0,
      qaRetryState: null,
      connectionStatus: 'idle' as ConnectionStatus,
      streamingMessages: {},
      qaScoreHistory: [],
    }),
}));
