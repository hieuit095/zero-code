// @ai-module: Left Sidebar
// @ai-role: Layout shell for the left panel. Composes FileExplorer (top) and AgentChatter (bottom)
//           in a vertically resizable split. Fetches shared agent state from useAgentConnection
//           and passes it down to AgentChatter as props.
// @ai-dependencies: hooks/useAgentConnection.ts (messages, agentStatuses, activeActivities)

// [AI-STRICT] LeftSidebar is a layout-only component. Do NOT add direct store selectors here.
//             All data must come through useAgentConnection to preserve the abstraction boundary.
// [AI-STRICT] Props are passed explicitly to AgentChatter (messages, agentStatuses, activeActivities).
//             Do NOT refactor AgentChatter to read from the store directly — keep it a controlled component.


import { Panel, PanelGroup, PanelResizeHandle } from 'react-resizable-panels';
import { FileExplorer } from './FileExplorer';
import { AgentChatter } from './AgentChatter';
import { useAgentConnection } from '../hooks/useAgentConnection';

export function LeftSidebar() {
  const { messages, agentStatuses, activeActivities } = useAgentConnection();

  return (
    <div className="flex flex-col border-r border-slate-800 bg-slate-950 h-full">
      <PanelGroup direction="vertical" autoSaveId="sidebar-vertical">
        <Panel defaultSize={42} minSize={20}>
          <div className="h-full overflow-hidden">
            <FileExplorer />
          </div>
        </Panel>
        <PanelResizeHandle className="h-[3px] bg-slate-800 hover:bg-sky-500/40 transition-colors cursor-row-resize flex items-center justify-center group">
          <div className="w-8 h-0.5 rounded-full bg-slate-700 group-hover:bg-sky-500/60 transition-colors" />
        </PanelResizeHandle>
        <Panel defaultSize={58} minSize={25}>
          <div className="h-full overflow-hidden relative">
            <AgentChatter
              messages={messages}
              agentStatuses={agentStatuses}
              activeActivities={activeActivities}
            />
          </div>
        </Panel>
      </PanelGroup>
    </div>
  );
}
