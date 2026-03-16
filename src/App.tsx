// @ai-module: App Root
// @ai-role: Application shell. Composes the resizable panel layout with Header, LeftSidebar, and RightWorkspace.
//           No state lives here — all state is in Zustand stores accessed via hooks inside child components.
// @ai-dependencies: None (no direct store or hook imports — layout only)

// [AI-STRICT] DO NOT add global state, context providers, or data fetching to this file.
//             All state management is Zustand-based and accessed within the relevant leaf components.
// [AI-STRICT] Panel layout configuration (defaultSize, minSize, maxSize) is persisted via autoSaveId in localStorage.
//             Do not remove autoSaveId props or panel resize behavior will not persist across reloads.


import { Panel, PanelGroup, PanelResizeHandle } from 'react-resizable-panels';
import { Header } from './components/Header';
import { LeftSidebar } from './components/LeftSidebar';
import { RightWorkspace } from './components/RightWorkspace';

export default function App() {
  return (
    <div className="h-screen w-screen overflow-hidden flex flex-col bg-slate-950 text-slate-100">
      <Header />
      <main className="flex flex-1 min-h-0">
        <PanelGroup direction="horizontal" autoSaveId="main-horizontal">
          <Panel defaultSize={22} minSize={14} maxSize={40}>
            <div className="h-full">
              <LeftSidebar />
            </div>
          </Panel>
          <PanelResizeHandle className="w-[3px] bg-slate-800 hover:bg-sky-500/40 transition-colors cursor-col-resize flex items-center justify-center group">
            <div className="h-10 w-0.5 rounded-full bg-slate-700 group-hover:bg-sky-500/60 transition-colors" />
          </PanelResizeHandle>
          <Panel defaultSize={78} minSize={40}>
            <div className="h-full">
              <RightWorkspace />
            </div>
          </Panel>
        </PanelGroup>
      </main>
    </div>
  );
}
