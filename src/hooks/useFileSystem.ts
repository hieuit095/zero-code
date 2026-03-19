/**
 * ==========================================
 * Author: Hieu Nguyen - Codev Team
 * Email: hieuit095@gmail.com
 * Project: ZeroCode - Autonomous Multi-Agent IDE
 * ==========================================
 */
// @ai-module: File System Hook
// @ai-role: Data transport abstraction for file state consumed by UI components (FileExplorer, CodeEditorPanel).
//           Provides a clean interface over fileStore so components are decoupled from the store implementation.
// @ai-dependencies: stores/fileStore.ts (useFileStore)
//                   types/index.ts (FileNode, EditorTab)

// [AI-STRICT] UI components (FileExplorer, CodeEditorPanel) MUST import from this hook, never from fileStore directly.

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
  isLoadingFile: boolean;
  openFile: (name: string, modified?: boolean) => void;
  closeTab: (id: string) => void;
  setActiveTab: (id: string) => void;
  fetchAndOpenFile: (filePath: string, workspaceId: string) => Promise<void>;
}

export function useFileSystem(): FileSystemReturn {
  const fileTree = useFileStore((s) => s.fileTree);
  const openTabs = useFileStore((s) => s.openTabs);
  const activeTabId = useFileStore((s) => s.activeTabId);
  const isAIControlMode = useFileStore((s) => s.isAIControlMode);
  const aiControlledFile = useFileStore((s) => s.aiControlledFile);
  const isLoadingFile = useFileStore((s) => s.isLoadingFile);
  const getActiveContent = useFileStore((s) => s.getActiveContent);
  const getActiveLanguage = useFileStore((s) => s.getActiveLanguage);
  const openFile = useFileStore((s) => s.openFile);
  const closeTab = useFileStore((s) => s.closeTab);
  const setActiveTab = useFileStore((s) => s.setActiveTab);
  const fetchAndOpenFile = useFileStore((s) => s.fetchAndOpenFile);

  return {
    fileTree,
    openTabs,
    activeTabId,
    activeFileContent: getActiveContent(),
    activeFileLanguage: getActiveLanguage(),
    isAIControlMode,
    aiControlledFile,
    isLoadingFile,
    openFile,
    closeTab,
    setActiveTab,
    fetchAndOpenFile,
  };
}
