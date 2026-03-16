// @ai-module: App Root
// @ai-role: Application shell with simple hash-based routing.
//           Renders the IDE layout by default, or the AdminDashboard for #/admin.
// @ai-dependencies: None (no direct store or hook imports — layout + routing only)

// [AI-STRICT] DO NOT add global state, context providers, or data fetching to this file.
//             All state management is Zustand-based and accessed within the relevant leaf components.
// [AI-STRICT] Panel layout configuration (defaultSize, minSize, maxSize) is persisted via autoSaveId in localStorage.
//             Do not remove autoSaveId props or panel resize behavior will not persist across reloads.


import { useEffect, useState, lazy, Suspense } from 'react';
import { Panel, PanelGroup, PanelResizeHandle } from 'react-resizable-panels';
import { Header } from './components/Header';
import { LeftSidebar } from './components/LeftSidebar';
import { RightWorkspace } from './components/RightWorkspace';

const AdminDashboard = lazy(() => import('./pages/AdminDashboard'));

function useHashRoute() {
  const [hash, setHash] = useState(window.location.hash);
  useEffect(() => {
    const handler = () => setHash(window.location.hash);
    window.addEventListener('hashchange', handler);
    return () => window.removeEventListener('hashchange', handler);
  }, []);
  return hash;
}

function IDELayout() {
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

export default function App() {
  const hash = useHashRoute();

  if (hash === '#/admin') {
    return (
      <Suspense fallback={
        <div className="h-screen w-screen flex items-center justify-center bg-slate-950 text-slate-400">
          Loading dashboard…
        </div>
      }>
        <AdminDashboard />
      </Suspense>
    );
  }

  return <IDELayout />;
}

