/**
 * ==========================================
 * Author: Hieu Nguyen - Codev Team
 * Email: hieuit095@gmail.com
 * Project: ZeroCode - Autonomous Multi-Agent IDE
 * ==========================================
 */
// @ai-module: Right Workspace
// @ai-role: Layout shell for the main content area. Composes CodeEditorPanel (top) and TerminalTaskPanel (bottom)
//           in a vertically resizable split. No state or data fetching — pure layout component.
// @ai-dependencies: None (no direct store or hook imports — layout only)

// [AI-STRICT] RightWorkspace is a layout-only component. Do NOT add state or data fetching here.
// [AI-STRICT] Panel sizes are persisted via autoSaveId="workspace-vertical". Do not remove this prop.


import { Panel, PanelGroup, PanelResizeHandle } from 'react-resizable-panels';
import { CodeEditorPanel } from './CodeEditorPanel';
import { TerminalTaskPanel } from './TerminalTaskPanel';

export function RightWorkspace() {
  return (
    <div className="flex flex-col flex-1 min-w-0 min-h-0 h-full">
      <PanelGroup direction="vertical" autoSaveId="workspace-vertical">
        <Panel defaultSize={68} minSize={30}>
          <div className="h-full flex flex-col">
            <CodeEditorPanel />
          </div>
        </Panel>
        <PanelResizeHandle className="h-[3px] bg-slate-800 hover:bg-sky-500/40 transition-colors cursor-row-resize flex items-center justify-center group">
          <div className="w-12 h-0.5 rounded-full bg-slate-700 group-hover:bg-sky-500/60 transition-colors" />
        </PanelResizeHandle>
        <Panel defaultSize={32} minSize={15}>
          <div className="h-full flex flex-col">
            <TerminalTaskPanel />
          </div>
        </Panel>
      </PanelGroup>
    </div>
  );
}
