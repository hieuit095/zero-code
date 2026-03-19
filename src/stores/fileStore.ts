/**
 * ==========================================
 * Author: Hieu Nguyen - Codev Team
 * Email: hieuit095@gmail.com
 * Project: ZeroCode - Autonomous Multi-Agent IDE
 * ==========================================
 */
// @ai-module: File Store
// @ai-role: Zustand store managing the virtual file system: file tree, open editor tabs,
//           active tab selection, file content (reactive Zustand state), and AI control mode flag.
//           AI control mode is the mechanism by which the Dev agent "locks" a file during editing.
// @ai-dependencies: types/index.ts (FileNode, EditorTab)

// [AI-STRICT] DO NOT call useFileStore.setState() from outside this file.
// [AI-STRICT] File content is stored in Zustand state (fileContents record) for reactive Monaco updates.
//             getActiveContent() and getActiveLanguage() read from this reactive state.

import { create } from 'zustand';
import type { FileNode, EditorTab } from '../types';

interface FileState {
  fileTree: FileNode[];
  fileContents: Record<string, { content: string; language: string }>;
  openTabs: EditorTab[];
  activeTabId: string;
  isAIControlMode: boolean;
  aiControlledFile: string | null;

  getActiveContent: () => string;
  getActiveLanguage: () => string;

  openFile: (name: string, modified?: boolean) => void;
  closeTab: (id: string) => void;
  setActiveTab: (id: string) => void;
  updateFileContent: (name: string, content: string) => void;
  setFileTree: (tree: FileNode[]) => void;
  setFileFromServer: (name: string, path: string, language: string, content: string) => void;
  setAIControlMode: (active: boolean, fileName?: string) => void;
}

export const useFileStore = create<FileState>((set, get) => ({
  fileTree: [],
  fileContents: {},
  openTabs: [],
  activeTabId: '',
  isAIControlMode: false,
  aiControlledFile: null,

  getActiveContent: () => {
    const { activeTabId, fileContents } = get();
    return fileContents[activeTabId]?.content ?? '// No file selected';
  },

  getActiveLanguage: () => {
    const { activeTabId, fileContents } = get();
    return fileContents[activeTabId]?.language ?? 'typescript';
  },

  openFile: (name: string, modified = false) => {
    set((state) => {
      const existing = state.openTabs.find((t) => t.id === name);
      if (existing) {
        return { activeTabId: name };
      }
      return {
        openTabs: [...state.openTabs, { id: name, name, modified }],
        activeTabId: name,
      };
    });
  },

  closeTab: (id: string) => {
    set((state) => {
      const remaining = state.openTabs.filter((t) => t.id !== id);
      let nextActive = state.activeTabId;
      if (state.activeTabId === id && remaining.length > 0) {
        nextActive = remaining[remaining.length - 1].id;
      } else if (remaining.length === 0) {
        nextActive = '';
      }
      return { openTabs: remaining, activeTabId: nextActive };
    });
  },

  setActiveTab: (id: string) => set({ activeTabId: id }),

  updateFileContent: (name: string, content: string) => {
    set((state) => ({
      fileContents: {
        ...state.fileContents,
        [name]: {
          ...(state.fileContents[name] ?? { language: 'typescript' }),
          content,
        },
      },
      openTabs: state.openTabs.map((t) =>
        t.id === name ? { ...t, modified: true } : t
      ),
    }));
  },

  // Full tree hydration from fs:tree events
  setFileTree: (tree: FileNode[]) => set({ fileTree: tree }),

  // Hydrate a single file from fs:update events — opens the tab if not already open
  setFileFromServer: (name: string, _path: string, language: string, content: string) => {
    set((state) => {
      const existingTab = state.openTabs.find((t) => t.id === name);
      const newTabs = existingTab
        ? state.openTabs.map((t) => (t.id === name ? { ...t, modified: true } : t))
        : [...state.openTabs, { id: name, name, modified: true }];

      return {
        fileContents: {
          ...state.fileContents,
          [name]: { content, language },
        },
        openTabs: newTabs,
        activeTabId: name,
      };
    });
  },

  setAIControlMode: (active: boolean, fileName?: string) => {
    set({ isAIControlMode: active, aiControlledFile: fileName ?? null });
    if (active && fileName) {
      set((state) => ({
        openTabs: state.openTabs.map((t) =>
          t.id === fileName ? { ...t, modified: true } : t
        ),
      }));
    }
  },
}));
