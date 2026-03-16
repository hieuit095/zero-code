// @ai-module: Agent Connection Hook
// @ai-role: Data transport abstraction layer for agent state consumed by UI components.
//           Decouples components from the Zustand store implementation so the store can be
//           swapped for a real WebSocket connection without touching any UI component.
//           Exports three hooks: useAgentConnection (read), useAgentActions (write), useAgentStatus (per-agent).
// @ai-dependencies: stores/agentStore.ts (useAgentStore)
//                   types/index.ts (AgentMessage, Task, AgentRole, AgentStatuses, ActiveActivities)

// [AI-STRICT] UI components MUST import from this hook, never from agentStore directly.
//             This boundary is intentional — it keeps WebSocket integration changes isolated to this file.
// [AI-STRICT] The isConnected / isConnecting fields currently return static mock values (true / false).
//             When the real backend is connected, drive these from WebSocket readyState.
// [AI-STRICT] sendMessage is a no-op stub. When the real backend is connected, implement it as:
//             ws.send(JSON.stringify(payload)) — do NOT add optimistic state updates here.

import { useAgentStore } from '../stores/agentStore';
import type { AgentMessage, Task, AgentRole, AgentStatuses, ActiveActivities } from '../types';

export interface AgentConnectionReturn {
  messages: AgentMessage[];
  tasks: Task[];
  agentStatuses: AgentStatuses;
  activeActivities: ActiveActivities;
  // @ai-integration-point: isConnected should reflect WebSocket.readyState === WebSocket.OPEN.
  isConnected: boolean;
  // @ai-integration-point: isConnecting should reflect WebSocket.readyState === WebSocket.CONNECTING.
  isConnecting: boolean;
  // @ai-integration-point: Replace this stub with ws.send(JSON.stringify(payload)).
  //   Expected payload shape: { type: 'user:message', content: string } — confirm with backend API spec.
  sendMessage: (payload: unknown) => void;
}

/**
 * useAgentConnection
 *
 * Data transport abstraction for agent state.
 * Currently backed by Zustand mock store.
 *
 * WebSocket integration path:
 *   Replace the store selectors below with a useEffect that opens
 *   a WebSocket to the Python backend. On each `onmessage` event,
 *   dispatch to the store via addMessage / updateAgentStatus / updateTask.
 *   Set isConnected/isConnecting from the WS readyState.
 *   Wire sendMessage to ws.send(JSON.stringify(payload)).
 */
export function useAgentConnection(): AgentConnectionReturn {
  const messages = useAgentStore((s) => s.messages);
  const tasks = useAgentStore((s) => s.tasks);
  const agentStatuses = useAgentStore((s) => s.agentStatuses);
  const activeActivities = useAgentStore((s) => s.activeActivities);

  return {
    messages,
    tasks,
    agentStatuses,
    activeActivities,
    isConnected: true,
    isConnecting: false,
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
  const updateAgentStatus = useAgentStore((s) => s.updateAgentStatus);
  const updateTask = useAgentStore((s) => s.updateTask);
  const isSimulationRunning = useAgentStore((s) => s.isSimulationRunning);
  const simulationProgress = useAgentStore((s) => s.simulationProgress);

  return { addMessage, updateAgentStatus, updateTask, isSimulationRunning, simulationProgress };
}

export function useAgentStatus(agent: AgentRole) {
  const status = useAgentStore((s) => s.agentStatuses[agent]);
  const activity = useAgentStore((s) => s.activeActivities[agent]);
  return { status, activity };
}
