/**
 * ==========================================
 * Author: Hieu Nguyen - Codev Team
 * Email: hieuit095@gmail.com
 * Project: ZeroCode - Autonomous Multi-Agent IDE
 * ==========================================
 */
// @ai-module: Agent Connection Hook
// @ai-role: Data transport abstraction layer for agent state consumed by UI components.
//           Decouples components from the Zustand store implementation so the store can be
//           swapped for a real WebSocket connection without touching any UI component.
//           Exports three hooks: useAgentConnection (read), useAgentActions (write), useAgentStatus (per-agent).
// @ai-dependencies: stores/agentStore.ts (useAgentStore)
//                   types/index.ts (AgentMessage, Task, AgentRole, AgentStatuses, ActiveActivities)

// [AI-STRICT] UI components MUST import from this hook, never from agentStore directly.

import { useAgentStore } from '../stores/agentStore';
import type { StreamingMessage, QaScoreEntry } from '../stores/agentStore';
import type { AgentMessage, Task, AgentRole, AgentStatuses, ActiveActivities } from '../types';

export interface AgentConnectionReturn {
  messages: AgentMessage[];
  tasks: Task[];
  agentStatuses: AgentStatuses;
  activeActivities: ActiveActivities;
  runStatus: string | null;
  runProgress: number;
  qaRetryState: ReturnType<typeof useAgentStore.getState>['qaRetryState'];
  streamingMessages: Record<string, StreamingMessage>;
  qaScoreHistory: QaScoreEntry[];
  sendMessage: (payload: unknown) => void;
}

export function useAgentConnection(): AgentConnectionReturn {
  const messages = useAgentStore((s) => s.messages);
  const tasks = useAgentStore((s) => s.tasks);
  const agentStatuses = useAgentStore((s) => s.agentStatuses);
  const activeActivities = useAgentStore((s) => s.activeActivities);
  const runStatus = useAgentStore((s) => s.runStatus);
  const runProgress = useAgentStore((s) => s.runProgress);
  const qaRetryState = useAgentStore((s) => s.qaRetryState);
  const streamingMessages = useAgentStore((s) => s.streamingMessages);
  const qaScoreHistory = useAgentStore((s) => s.qaScoreHistory);

  return {
    messages,
    tasks,
    agentStatuses,
    activeActivities,
    runStatus,
    runProgress,
    qaRetryState,
    streamingMessages,
    qaScoreHistory,
    sendMessage: (_payload: unknown) => {
      // @ai-integration-point: Replace with ws.send(JSON.stringify(_payload))
    },
  };
}

// @ai-integration-point: useAgentActions provides write access to the agent store.
//   When integrating the backend, these actions will be called from the WebSocket event dispatcher,
//   NOT from UI components. UI components should only call sendMessage() for user-initiated events.
export function useAgentActions() {
  const addMessage = useAgentStore((s) => s.addMessage);
  const addMessageFromServer = useAgentStore((s) => s.addMessageFromServer);
  const updateAgentStatus = useAgentStore((s) => s.updateAgentStatus);
  const updateTask = useAgentStore((s) => s.updateTask);
  const setTasks = useAgentStore((s) => s.setTasks);
  const runStatus = useAgentStore((s) => s.runStatus);
  const runProgress = useAgentStore((s) => s.runProgress);

  return { addMessage, addMessageFromServer, updateAgentStatus, updateTask, setTasks, runStatus, runProgress };
}

export function useAgentStatus(agent: AgentRole) {
  const status = useAgentStore((s) => s.agentStatuses[agent]);
  const activity = useAgentStore((s) => s.activeActivities[agent]);
  return { status, activity };
}
