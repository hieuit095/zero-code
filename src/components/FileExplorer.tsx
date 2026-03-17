// @ai-module: File Explorer
// @ai-role: Tree-view component rendering the virtual file system from fileStore.
//           Clicking a file calls useFileSystem().openFile(name) which updates fileStore to open a new tab.
//           Folder expand/collapse state is local to each FileRow instance.
// @ai-dependencies: hooks/useFileSystem.ts (fileTree, activeTabId, openFile)
//                   types/index.ts (FileNode)

// [AI-STRICT] FileExplorer must only read fileTree and activeTabId from useFileSystem() — do NOT add
//             direct fileStore selectors here.
// [AI-STRICT] File selection calls openFile(node.name). The name (not id) is used as the tab id —
//             this matches the key used in mockEditorFiles. Do NOT change this to use node.id.
// @ai-integration-point: When the real backend is connected, the fileTree should be populated from
//   a WebSocket fs:tree event instead of the static mockData.fileTree seed.
//   Wire the Refresh button to request a fresh tree: ws.send({ type: "fs:list" }).
// @ai-integration-point: The "+" (new file) button is currently a no-op placeholder.
//   Wire it to open a filename prompt and send: ws.send({ type: "fs:create", path: fileName }).


import { useState } from 'react';
import {
  ChevronRight,
  ChevronDown,
  Folder,
  FolderOpen,
  FileCode,
  FileText,
  FileJson,
  GitBranch,
  Plus,
  RefreshCw,
} from 'lucide-react';
import type { FileNode } from '../types';
import { useFileSystem } from '../hooks/useFileSystem';
import { useRunConnection } from '../hooks/useRunConnection';

interface FileRowProps {
  node: FileNode;
  depth: number;
  selectedId: string | null;
  onSelect: (name: string) => void;
}

function getFileIcon(language?: string) {
  if (language === 'css') return <FileCode className="w-3.5 h-3.5 text-sky-400" />;
  if (language === 'json') return <FileJson className="w-3.5 h-3.5 text-yellow-400" />;
  if (language === 'typescript' || language === 'javascript') {
    return <FileCode className="w-3.5 h-3.5 text-sky-300" />;
  }
  return <FileText className="w-3.5 h-3.5 text-slate-400" />;
}

function getFileColor(name: string): string {
  if (name.endsWith('.tsx') || name.endsWith('.jsx')) return 'text-sky-300';
  if (name.endsWith('.ts') || name.endsWith('.js')) return 'text-sky-200';
  if (name.endsWith('.css')) return 'text-sky-400';
  if (name.endsWith('.json')) return 'text-yellow-400';
  return 'text-slate-300';
}

function FileRow({ node, depth, selectedId, onSelect }: FileRowProps) {
  const [expanded, setExpanded] = useState(depth < 1);
  const isSelected = selectedId === node.id || selectedId === node.name;
  const isFolder = node.type === 'folder';

  const handleClick = () => {
    if (isFolder) {
      setExpanded((p) => !p);
    } else {
      onSelect(node.name);
    }
  };

  return (
    <>
      <div
        onClick={handleClick}
        className={`flex items-center gap-1.5 px-2 py-[3px] cursor-pointer text-xs rounded-sm mx-1 select-none group transition-colors ${isSelected
          ? 'bg-sky-500/15 text-sky-300'
          : 'hover:bg-slate-800 text-slate-300 hover:text-slate-100'
          }`}
        style={{ paddingLeft: `${depth * 12 + 8}px` }}
      >
        {isFolder ? (
          <span className="text-slate-500">
            {expanded ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
          </span>
        ) : (
          <span className="w-3" />
        )}
        {isFolder ? (
          expanded ? (
            <FolderOpen className="w-3.5 h-3.5 text-amber-400 shrink-0" />
          ) : (
            <Folder className="w-3.5 h-3.5 text-amber-400 shrink-0" />
          )
        ) : (
          <span className="shrink-0">{getFileIcon(node.language)}</span>
        )}
        <span className={`truncate ${isFolder ? 'text-slate-200' : getFileColor(node.name)}`}>
          {node.name}
        </span>
      </div>
      {isFolder && expanded && node.children?.map((child) => (
        <FileRow
          key={child.id}
          node={child}
          depth={depth + 1}
          selectedId={selectedId}
          onSelect={onSelect}
        />
      ))}
    </>
  );
}

export function FileExplorer() {
  const { fileTree, activeTabId, openFile } = useFileSystem();
  const { sendMessage } = useRunConnection();

  const handleRefresh = () => {
    sendMessage({
      type: 'workspace:refresh',
      data: { reason: 'manual_refresh' },
    });
  };

  const handleAddFile = () => {
    const fileName = window.prompt('Enter file path (e.g. src/utils/helpers.ts):');
    if (!fileName?.trim()) return;

    sendMessage({
      type: 'user:interrupt',
      data: { message: `Create a new file at path: ${fileName.trim()}` },
    });
  };

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center justify-between px-3 py-2 border-b border-slate-800 shrink-0">
        <span className="text-[11px] font-semibold text-slate-400 uppercase tracking-widest">Explorer</span>
        <div className="flex items-center gap-0.5">
          <button
            onClick={handleAddFile}
            title="New file"
            className="p-1 rounded hover:bg-slate-800 text-slate-500 hover:text-slate-300 transition-colors"
          >
            <Plus className="w-3.5 h-3.5" />
          </button>
          <button
            onClick={handleRefresh}
            title="Refresh workspace"
            className="p-1 rounded hover:bg-slate-800 text-slate-500 hover:text-slate-300 transition-colors"
          >
            <RefreshCw className="w-3 h-3" />
          </button>
        </div>
      </div>

      <div className="px-1 py-1 border-b border-slate-800 shrink-0">
        <div className="flex items-center gap-1.5 px-2 py-1 text-[11px]">
          <GitBranch className="w-3 h-3 text-emerald-400" />
          <span className="text-emerald-400 font-medium">main</span>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto py-1">
        {fileTree.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-8 text-slate-600">
            <Folder className="w-6 h-6 mb-2" />
            <span className="text-xs">No files yet</span>
            <span className="text-[10px] text-slate-700 mt-0.5">Start a run to populate</span>
          </div>
        ) : (
          fileTree.map((node) => (
            <FileRow
              key={node.id}
              node={node}
              depth={0}
              selectedId={activeTabId}
              onSelect={openFile}
            />
          ))
        )}
      </div>
    </div>
  );
}
