// @ai-module: Simulation Hook
// @ai-role: Mock-only hook that orchestrates the local simulation run and provides a full reset.
//           startSimulation() triggers the scripted agent timeline in agentSimulation.ts.
//           resetSimulation() restores all three stores (agent, terminal, file) to their initial seed state.
// @ai-dependencies: stores/agentStore.ts (useAgentStore, resetToInitial)
//                   stores/terminalStore.ts (useTerminalStore, clearTerminal, appendLines)
//                   stores/fileStore.ts (useFileStore, setAIControlMode, setState)
//                   simulation/agentSimulation.ts (runSimulation)
//                   data/mockData.ts (initialTerminalLines, mockEditorFiles)

// [AI-STRICT] This entire file is mock scaffolding. When the real backend is connected:
//             1. Remove runSimulation() and the import of agentSimulation.ts entirely.
//             2. Replace startSimulation() with a real WebSocket initialization:
//                e.g., new WebSocket(WEBSOCKET_URL) — then send the goal payload.
//             3. Replace resetSimulation() with a backend API call to cancel/reset the current run,
//                then clear stores client-side.
// [AI-STRICT] DO NOT add new simulation steps or agent messages to agentSimulation.ts.
//             The simulation is a disposable prototype. All new agent behavior belongs in the real backend.
// [AI-STRICT] useFileStore.setState() is called directly here for the reset path — this is the ONLY
//             legitimate external setState call on fileStore. Do not replicate this pattern elsewhere.

import { useAgentStore } from '../stores/agentStore';
import { useTerminalStore } from '../stores/terminalStore';
import { useFileStore } from '../stores/fileStore';
import { initialAgentMessages, initialTasks, initialTerminalLines, mockEditorFiles } from '../data/mockData';
import { runSimulation } from '../simulation/agentSimulation';

export interface SimulationReturn {
  isRunning: boolean;
  progress: number;
  // @ai-integration-point: Replace startSimulation() body with:
  //   const ws = new WebSocket(import.meta.env.VITE_WS_URL);
  //   ws.onopen = () => ws.send(JSON.stringify({ type: 'run:start', goal }));
  //   ws.onmessage = (e) => dispatchWebSocketEvent(JSON.parse(e.data));
  startSimulation: () => void;
  resetSimulation: () => void;
}

export function useSimulation(): SimulationReturn {
  const isRunning = useAgentStore((s) => s.isSimulationRunning);
  const progress = useAgentStore((s) => s.simulationProgress);
  const resetAgent = useAgentStore((s) => s.resetToInitial);
  const setLogLines = useTerminalStore((s) => s.clearTerminal);
  const appendLines = useTerminalStore((s) => s.appendLines);

  const startSimulation = () => {
    if (isRunning) return;
    runSimulation();
  };

  const resetSimulation = () => {
    resetAgent();
    setLogLines();

    const fileState = useFileStore.getState();
    fileState.setAIControlMode(false);

    const initialMockKeys = ['App.tsx', 'AuthForm.tsx', 'index.css', 'Modal.tsx'];
    initialMockKeys.forEach((key) => {
      if (mockEditorFiles[key]) {
        mockEditorFiles[key] = { ...mockEditorFiles[key] };
      }
    });

    useFileStore.setState({
      openTabs: [
        { id: 'App.tsx', name: 'App.tsx', modified: false },
        { id: 'AuthForm.tsx', name: 'AuthForm.tsx', modified: true },
        { id: 'index.css', name: 'index.css', modified: false },
      ],
      activeTabId: 'App.tsx',
      isAIControlMode: false,
      aiControlledFile: null,
    });

    appendLines(initialTerminalLines.map(({ text, type }) => ({ text, type })));
  };

  return { isRunning, progress, startSimulation, resetSimulation };
}
