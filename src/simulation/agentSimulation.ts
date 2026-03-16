// @ts-nocheck — DEPRECATED: This file is dead code left for reference only.
// It was the mock simulation engine for the prototype. It is not imported anywhere.
// Remove this file entirely when cleaning up deprecated code.
// @ai-module: Agent Simulation Engine
// @ai-role: Scripted, time-delayed simulation of a multi-agent run. Directly calls Zustand store
//           actions (agentStore, terminalStore, fileStore) on a timer to fake real agent behavior.
//           This module is MOCK-ONLY scaffolding — it has no connection to the real OpenHands SDK.
// @ai-dependencies: stores/agentStore.ts (useAgentStore — getState for direct store access)
//                   stores/terminalStore.ts (useTerminalStore — getState)
//                   stores/fileStore.ts (useFileStore — getState, setState)
//                   data/mockData.ts (mockEditorFiles — mutated directly to simulate a file write)

// [AI-STRICT] THIS ENTIRE FILE IS DISPOSABLE MOCK SCAFFOLDING.
//             When the real backend is connected, DELETE this file entirely.
//             Do NOT add real business logic here. Do NOT extend the simulation with new phases.
//             The simulation exists only to demonstrate the UI data flow end-to-end.
// [AI-STRICT] This file is the ONLY place where Zustand stores are accessed via getState() (outside the hook layer).
//             This pattern is acceptable here because runSimulation() is a standalone async function,
//             not a React component or hook. Do NOT replicate this getState() pattern in components or hooks.
// [AI-STRICT] mockEditorFiles is mutated directly in runSimulation() to simulate a file write.
//             This is intentional mock behavior. When replacing with the real backend, file content
//             must be streamed into fileStore via updateFileContent() from a WebSocket event handler.

// @ai-integration-point: Replace the entire runSimulation() function with a WebSocket event dispatcher:
//   function dispatchWebSocketEvent(event: WSEvent) {
//     switch (event.type) {
//       case "agent:status":   agentStore.updateAgentStatus(event.role, event.status, event.activity); break;
//       case "agent:message":  agentStore.addMessage(event.message); break;
//       case "task:update":    agentStore.updateTask(event.taskId, event.status); break;
//       case "terminal:output": terminalStore.appendLine(event.text, event.logType); break;
//       case "fs:update":      fileStore.updateFileContent(event.name, event.content); break;
//       case "dev:start-edit": fileStore.setAIControlMode(true, event.fileName); break;
//       case "dev:stop-edit":  fileStore.setAIControlMode(false); break;
//       case "run:complete":   agentStore.setSimulationRunning(false); break;
//     }
//   }


import { useAgentStore } from '../stores/agentStore';
import { useTerminalStore } from '../stores/terminalStore';
import { useFileStore } from '../stores/fileStore';
import { mockEditorFiles } from '../data/mockData';

const MODAL_V2_CONTENT = `import { useEffect, useRef, useCallback } from 'react';
import { X } from 'lucide-react';

interface ModalProps {
  open: boolean;
  onClose: () => void;
  title: string;
  children: React.ReactNode;
}

export function Modal({ open, onClose, title, children }: ModalProps) {
  const overlayRef = useRef<HTMLDivElement>(null);

  const handleOverlayClick = useCallback(
    (e: React.MouseEvent<HTMLDivElement>) => {
      if (e.target === overlayRef.current) onClose();
    },
    [onClose]
  );

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    if (open) {
      document.addEventListener('keydown', handleKeyDown);
      document.body.style.overflow = 'hidden';
    }
    return () => {
      document.removeEventListener('keydown', handleKeyDown);
      document.body.style.overflow = '';
    };
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div
      ref={overlayRef}
      role="dialog"
      aria-modal="true"
      aria-labelledby="modal-title"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
      onClick={handleOverlayClick}
    >
      <div className="bg-slate-900 border border-slate-700 rounded-xl shadow-2xl w-full max-w-md mx-4 animate-in fade-in zoom-in-95 duration-200">
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-800">
          <h2 id="modal-title" className="text-base font-semibold text-slate-100">
            {title}
          </h2>
          <button
            onClick={onClose}
            aria-label="Close modal"
            className="p-1 rounded-md text-slate-400 hover:text-slate-200 hover:bg-slate-800 transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
        <div className="px-6 py-5">{children}</div>
      </div>
    </div>
  );
}
`;

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function t(ms: number) {
  return delay(ms);
}

export async function runSimulation(): Promise<void> {
  const agent = useAgentStore.getState();
  const terminal = useTerminalStore.getState();
  const file = useFileStore.getState();

  agent.setSimulationRunning(true);
  agent.setSimulationProgress(0);

  terminal.clearTerminal();
  terminal.appendLine('', 'blank');
  terminal.appendLine('$ nanobot run --goal "Fix Modal backdrop click bug"', 'command');
  terminal.appendLine('Nanobot v0.4.1 — initializing agent swarm...', 'info');
  terminal.appendLine('', 'blank');

  await t(800);
  agent.setSimulationProgress(5);

  // === PHASE 1: Tech Lead analyzes ===
  agent.updateAgentStatus('tech-lead', 'thinking', 'Analyzing bug report...');
  agent.addMessage({
    agent: 'tech-lead',
    agentLabel: 'Tech Lead',
    content: 'New simulation run started. Goal: Fix Modal backdrop click bug reported by QA in previous session.',
  });

  terminal.appendLine('[Tech Lead] Analyzing codebase context...', 'info');
  await t(1200);
  agent.setSimulationProgress(12);

  agent.updateAgentStatus('tech-lead', 'working', 'Creating task plan...');
  agent.addMessage({
    agent: 'tech-lead',
    agentLabel: 'Tech Lead',
    content: 'Root cause identified: Modal.tsx backdrop click handler compares e.target to overlayRef.current, but the ref is attached after conditional render. Delegating fix to Dev.',
  });

  terminal.appendLine('[Tech Lead] Root cause identified: ref timing bug in Modal.tsx', 'info');
  terminal.appendLine('[Tech Lead] Task dispatched to Dev agent', 'info');

  agent.updateTask('t5', 'in-progress');
  await t(1000);
  agent.setSimulationProgress(22);

  // === PHASE 2: Dev opens file and begins editing ===
  agent.updateAgentStatus('tech-lead', 'idle', null);
  agent.updateAgentStatus('dev', 'thinking', 'Reading Modal.tsx...');

  agent.addMessage({
    agent: 'dev',
    agentLabel: 'Dev',
    content: 'Acknowledged. Opening Modal.tsx. Reading current implementation before making changes.',
  });

  terminal.appendLine('[Dev] Opening Modal.tsx for analysis...', 'info');
  await t(800);

  file.openFile('Modal.tsx', true);
  file.setAIControlMode(true, 'Modal.tsx');
  agent.updateAgentStatus('dev', 'working', 'Rewriting Modal.tsx...');
  agent.setSimulationProgress(35);

  agent.addMessage({
    agent: 'dev',
    agentLabel: 'Dev',
    content: 'Found the issue. The onClick handler uses e.target === overlayRef.current but the ref is set during render, not before. Fixing with useCallback and proper ref guard. Also adding aria-modal and keyboard scroll lock.',
  });

  terminal.appendLine('[Dev] Patching backdrop click handler in Modal.tsx...', 'info');
  terminal.appendLine('[Dev] Adding ARIA attributes for accessibility...', 'info');

  await t(1500);
  agent.setSimulationProgress(50);

  mockEditorFiles['Modal.tsx'] = {
    language: 'typescript',
    content: MODAL_V2_CONTENT,
  };

  useFileStore.setState((s) => ({
    openTabs: s.openTabs.map((tab) =>
      tab.id === 'Modal.tsx' ? { ...tab, modified: true } : tab
    ),
  }));

  terminal.appendLine('[Dev] Modal.tsx updated — backdrop click handler refactored', 'success');
  terminal.appendLine('[Dev] Handing off to QA for test run', 'info');

  agent.addMessage({
    agent: 'dev',
    agentLabel: 'Dev',
    content: 'Modal.tsx rewritten. Used useCallback for click handler, added aria-modal, aria-labelledby, scroll lock on body. Exiting AI control mode. QA — run the test suite.',
  });

  await t(600);
  file.setAIControlMode(false);
  agent.updateAgentStatus('dev', 'idle', null);
  agent.updateTask('t5', 'completed');
  agent.setSimulationProgress(60);

  // === PHASE 3: QA runs tests ===
  agent.updateAgentStatus('qa', 'thinking', 'Preparing test suite...');
  agent.addMessage({
    agent: 'qa',
    agentLabel: 'QA',
    content: 'Received updated Modal.tsx. Running full test suite including the previously failing backdrop click test.',
  });

  terminal.appendLine('', 'blank');
  terminal.appendLine('$ vitest run src/components/Modal.test.tsx', 'command');

  await t(800);
  agent.updateAgentStatus('qa', 'working', 'Running Modal.test.tsx...');
  agent.setSimulationProgress(70);

  const testLines = [
    { text: 'RUN  v1.3.1', type: 'info' as const },
    { text: '', type: 'blank' as const },
    { text: ' ✓ Modal renders correctly (4ms)', type: 'success' as const },
    { text: ' ✓ Modal closes on Escape key (2ms)', type: 'success' as const },
    { text: ' ✓ Modal closes on backdrop click (3ms)', type: 'success' as const },
    { text: ' ✓ Modal does not close on inner content click (2ms)', type: 'success' as const },
    { text: ' ✓ Modal traps focus inside (8ms)', type: 'success' as const },
    { text: '', type: 'blank' as const },
    { text: 'Test Files  1 passed (1)', type: 'success' as const },
    { text: 'Tests       5 passed (5)', type: 'success' as const },
    { text: 'Duration    98ms', type: 'info' as const },
  ];

  for (const l of testLines) {
    terminal.appendLine(l.text, l.type);
    await t(180);
  }

  agent.setSimulationProgress(83);
  await t(400);

  agent.addMessage({
    agent: 'qa',
    agentLabel: 'QA',
    content: 'All 5 Modal tests passing, including the previously failing backdrop click case. Also verified ARIA attributes present. Accessibility check: PASS.',
  });

  terminal.appendLine('', 'blank');
  terminal.appendLine('[QA] All tests passing. Accessibility check complete.', 'success');

  agent.updateTask('t6', 'completed');
  agent.updateAgentStatus('qa', 'idle', null);
  agent.setSimulationProgress(92);

  await t(800);

  // === PHASE 4: Tech Lead wraps up ===
  agent.updateAgentStatus('tech-lead', 'thinking', 'Reviewing results...');
  await t(600);

  agent.addMessage({
    agent: 'tech-lead',
    agentLabel: 'Tech Lead',
    content: 'Excellent work. Modal bug resolved, all tests green, accessibility improved. Marking t5 and t6 complete. Next goal: Accessibility audit (t8).',
  });

  agent.updateTask('t8', 'in-progress');

  terminal.appendLine('[Tech Lead] Sprint complete. Queuing next task: Accessibility audit.', 'info');
  terminal.appendLine('', 'blank');
  terminal.appendLine('✓ Simulation complete — 2 tasks resolved, 0 regressions', 'success');
  terminal.appendLine('$ _', 'cursor');

  await t(500);
  agent.updateAgentStatus('tech-lead', 'idle', null);
  agent.setSimulationProgress(100);

  await t(300);
  agent.setSimulationRunning(false);
}
