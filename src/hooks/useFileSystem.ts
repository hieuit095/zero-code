// @ai-module: File System Hook
// @ai-role: Data transport abstraction for file state consumed by UI components (FileExplorer, CodeEditorPanel).
//           Provides a clean interface over fileStore so components are decoupled from the store implementation.
//           When the real backend is connected, this hook is where WebSocket 'fs:*' events will be wired in.
// @ai-dependencies: stores/fileStore.ts (useFileStore)
//                   types/index.ts (FileNode, EditorTab)

// [AI-STRICT] UI components (FileExplorer, CodeEditorPanel) MUST import from this hook, never from fileStore directly.
// [AI-STRICT] activeFileContent and activeFileLanguage are synchronously derived from the mutable mockEditorFiles map.
//             They are NOT Zustand reactive state — they update when activeTabId changes (via key prop on Monaco).
//             When replacing with the real backend, store content in Zustand state and make these reactive selectors.

import { useFileStore } from '../stores/fileStore';
import type { FileNode, EditorTab } from '../types';

export interface FileSystemReturn {
  fileTree: FileNode[];
  openTabs: EditorTab[];
  activeTabId: string;
  activeFileContent: string;
  activeFileLanguage: string;
  isAIControlMode: boolean;
  aiControlledFile: string | null;
  openFile: (name: string, modified?: boolean) => void;
  closeTab: (id: string) => void;
  setActiveTab: (id: string) => void;
}

/**
 * useFileSystem
 *
 * Data transport abstraction for file state.
 * Currently backed by the Zustand fileStore.
 *
 * WebSocket integration path:
 *   On receiving a `file:update` WS event from OpenHands sandbox,
 *   call updateFileContent(name, content) to stream content into the editor.
 *   Call setAIControlMode(true, fileName) when the Dev agent begins writing.
 *   Call setAIControlMode(false) when the agent yields control.
 */
export function useFileSystem(): FileSystemReturn {
  const fileTree = useFileStore((s) => s.fileTree);
  const openTabs = useFileStore((s) => s.openTabs);
  const activeTabId = useFileStore((s) => s.activeTabId);
  const isAIControlMode = useFileStore((s) => s.isAIControlMode);
  const aiControlledFile = useFileStore((s) => s.aiControlledFile);
  const getActiveContent = useFileStore((s) => s.getActiveContent);
  const getActiveLanguage = useFileStore((s) => s.getActiveLanguage);
  const openFile = useFileStore((s) => s.openFile);
  const closeTab = useFileStore((s) => s.closeTab);
  const setActiveTab = useFileStore((s) => s.setActiveTab);

  return {
    fileTree,
    openTabs,
    activeTabId,
    activeFileContent: getActiveContent(),
    activeFileLanguage: getActiveLanguage(),
    isAIControlMode,
    aiControlledFile,
    openFile,
    closeTab,
    setActiveTab,
  };
}
