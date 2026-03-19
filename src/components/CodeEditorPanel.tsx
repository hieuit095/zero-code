/**
 * ==========================================
 * Author: Hieu Nguyen - Codev Team
 * Email: hieuit095@gmail.com
 * Project: ZeroCode - Autonomous Multi-Agent IDE
 * ==========================================
 */
// @ai-module: Code Editor Panel
// @ai-role: Monaco Editor integration wrapped in the file tab system. Renders the active file content
//           from useFileSystem() and sets readOnly mode when the Dev agent has AI control of the file.
//           The Monaco instance is keyed by activeTabId so it re-mounts cleanly on tab switch.
// @ai-dependencies: hooks/useFileSystem.ts (file content, tabs, AI control mode)
//                   hooks/useAgentConnection.ts (useAgentStatus — Dev agent activity label)
//                   components/EditorTabBar.tsx

// [AI-STRICT] Monaco Editor options are wrapped in useMemo with [isAIControlMode] as the dependency.
//             DO NOT change this structure. Removing useMemo will cause Monaco to re-instantiate on every
//             render, breaking the editor state. The only allowed dependency is isAIControlMode because
//             that is the only option that changes at runtime.
// [AI-STRICT] The Monaco <Editor> component uses key={activeTabId} to force re-mount on tab switch.
//             This is intentional — it ensures Monaco picks up the new content for the newly active file.
//             DO NOT remove the key prop or content will not update when switching tabs.
// [AI-STRICT] Monaco Editor is a controlled display component for the AI IDE.
//             DO NOT add onChange handlers to Monaco unless implementing a real user editing feature.
//             User edits are not currently persisted — this editor is primarily for AI agent output display.
// @ai-integration-point: To stream AI-written content into the editor in real time, wire WebSocket
//   fs:update events to fileStore.updateFileContent(name, content). Monaco will re-render
//   because activeFileContent is derived from the active tab in fileStore.


import { useMemo } from 'react';
import Editor from '@monaco-editor/react';
import { Lock, CreditCard as Edit3 } from 'lucide-react';
import { EditorTabBar } from './EditorTabBar';
import { useFileSystem } from '../hooks/useFileSystem';
import { useAgentStatus } from '../hooks/useAgentConnection';

export function CodeEditorPanel() {
  const {
    openTabs,
    activeTabId,
    activeFileContent,
    activeFileLanguage,
    isAIControlMode,
    aiControlledFile,
    closeTab,
    setActiveTab,
  } = useFileSystem();

  const { activity: devActivity } = useAgentStatus('dev');

  const editorOptions = useMemo(
    () => ({
      fontSize: 13,
      fontFamily: '"JetBrains Mono", "Fira Code", "Cascadia Code", monospace',
      fontLigatures: true,
      minimap: { enabled: false },
      scrollBeyondLastLine: false,
      lineNumbers: 'on' as const,
      renderLineHighlight: 'line' as const,
      scrollbar: { verticalScrollbarSize: 5, horizontalScrollbarSize: 5 },
      padding: { top: 12 },
      tabSize: 2,
      wordWrap: 'off' as const,
      smoothScrolling: true,
      cursorBlinking: 'smooth' as const,
      cursorSmoothCaretAnimation: 'on' as const,
      bracketPairColorization: { enabled: true },
      guides: { bracketPairs: true, indentation: true },
      readOnly: isAIControlMode,
      renderValidationDecorations: 'on' as const,
    }),
    [isAIControlMode]
  );

  return (
    <div className="flex flex-col flex-1 min-h-0">
      {openTabs.length > 0 ? (
        <>
          <EditorTabBar
            tabs={openTabs}
            activeTabId={activeTabId}
            onSelectTab={setActiveTab}
            onCloseTab={closeTab}
          />

          {isAIControlMode && (
            <div className="flex items-center gap-2 px-3 py-1.5 bg-amber-500/10 border-b border-amber-500/30 shrink-0">
              <Lock className="w-3 h-3 text-amber-400 shrink-0" />
              <span className="text-[11px] text-amber-300 font-medium">AI Control Mode</span>
              <span className="text-[11px] text-amber-400/70">—</span>
              <span className="text-[11px] text-amber-400/70">
                {devActivity ?? `Dev agent is editing ${aiControlledFile ?? 'this file'}...`}
              </span>
              <span className="ml-1 flex items-center gap-0.5">
                <span className="w-1 h-1 rounded-full bg-amber-400 animate-bounce" style={{ animationDelay: '0ms' }} />
                <span className="w-1 h-1 rounded-full bg-amber-400 animate-bounce" style={{ animationDelay: '150ms' }} />
                <span className="w-1 h-1 rounded-full bg-amber-400 animate-bounce" style={{ animationDelay: '300ms' }} />
              </span>
            </div>
          )}

          {!isAIControlMode && (
            <div className="flex items-center gap-1.5 px-3 py-1 bg-slate-900/50 border-b border-slate-800/50 shrink-0">
              <Edit3 className="w-2.5 h-2.5 text-slate-600" />
              <span className="text-[10px] text-slate-600">Editable</span>
            </div>
          )}

          <div className="flex-1 min-h-0">
            <Editor
              height="100%"
              language={activeFileLanguage}
              value={activeFileContent}
              theme="vs-dark"
              options={editorOptions}
              key={activeTabId}
            />
          </div>
        </>
      ) : (
        <div className="flex-1 flex flex-col items-center justify-center text-slate-600 gap-2">
          <Edit3 className="w-8 h-8 text-slate-700" />
          <span className="text-sm">No files open — select a file from the explorer</span>
        </div>
      )}
    </div>
  );
}
