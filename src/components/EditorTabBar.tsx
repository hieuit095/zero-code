// @ai-module: Editor Tab Bar
// @ai-role: Pure presentational component rendering the row of open file tabs above Monaco.
//           Receives all tab data as props from CodeEditorPanel — no direct store access.
//           Handles tab selection and close via callback props.
// @ai-dependencies: Props only (EditorTab[], activeTabId, onSelectTab, onCloseTab)

// [AI-STRICT] EditorTabBar is a PURE presentational component. DO NOT add store selectors here.
//             All tab management logic lives in fileStore. This component only renders and forwards events.
// [AI-STRICT] The local EditorTab type definition here duplicates the one in types/index.ts.
//             This is intentional component-level isolation. Do NOT import from types/index.ts here
//             to avoid a circular dependency risk if this component is ever extracted as a library.


import { X, FileCode } from 'lucide-react';

export type EditorTab = {
  id: string;
  name: string;
  modified?: boolean;
};

interface EditorTabBarProps {
  tabs: EditorTab[];
  activeTabId: string;
  onSelectTab: (id: string) => void;
  onCloseTab: (id: string) => void;
}

function TabIcon({ name }: { name: string }) {
  if (name.endsWith('.css')) return <FileCode className="w-3.5 h-3.5 text-sky-400 shrink-0" />;
  return <FileCode className="w-3.5 h-3.5 text-sky-300 shrink-0" />;
}

export function EditorTabBar({ tabs, activeTabId, onSelectTab, onCloseTab }: EditorTabBarProps) {
  return (
    <div className="flex items-end h-9 border-b border-slate-800 bg-slate-950 overflow-x-auto shrink-0">
      {tabs.map((tab) => {
        const isActive = tab.id === activeTabId;
        return (
          <div
            key={tab.id}
            onClick={() => onSelectTab(tab.id)}
            className={`group flex items-center gap-1.5 px-3 h-full cursor-pointer border-r border-slate-800 text-xs transition-colors relative shrink-0 ${
              isActive
                ? 'bg-slate-900 text-slate-100'
                : 'bg-slate-950 text-slate-400 hover:bg-slate-900 hover:text-slate-200'
            }`}
          >
            {isActive && (
              <span className="absolute top-0 inset-x-0 h-[2px] bg-sky-500 rounded-b" />
            )}
            <TabIcon name={tab.name} />
            <span className="max-w-[120px] truncate">{tab.name}</span>
            {tab.modified && (
              <span className="w-1.5 h-1.5 rounded-full bg-amber-400 shrink-0" />
            )}
            <button
              onClick={(e) => {
                e.stopPropagation();
                onCloseTab(tab.id);
              }}
              className={`p-0.5 rounded transition-colors ${
                isActive
                  ? 'text-slate-400 hover:text-slate-200 hover:bg-slate-700'
                  : 'text-transparent group-hover:text-slate-500 hover:!text-slate-300 hover:bg-slate-700'
              }`}
            >
              <X className="w-3 h-3" />
            </button>
          </div>
        );
      })}
      <div className="flex-1 border-b border-slate-800 h-full" />
    </div>
  );
}
