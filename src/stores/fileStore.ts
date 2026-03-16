// @ai-module: File Store
// @ai-role: Zustand store managing the virtual file system: file tree, open editor tabs,
//           active tab selection, file content (via mockEditorFiles), and AI control mode flag.
//           AI control mode is the mechanism by which the Dev agent "locks" a file during editing.
// @ai-dependencies: types/index.ts (FileNode, EditorTab)
//                   data/mockData.ts (fileTree, mockEditorFiles — mutable in-memory file content map)

// [AI-STRICT] DO NOT mutate mockEditorFiles directly from UI components or hooks.
//             Use updateFileContent(name, content) which handles both the in-memory map and tab modified flag atomically.
// [AI-STRICT] DO NOT call useFileStore.setState() from outside this file EXCEPT from useSimulation.ts (resetSimulation).
//             The only legitimate external setState call is the tab/mode reset in useSimulation.ts.
// [AI-STRICT] The mockEditorFiles object is an in-memory mutable map, NOT Zustand reactive state.
//             getActiveContent() and getActiveLanguage() read from it synchronously.
//             When the real backend is connected, replace these with WebSocket 'fs:read' responses
//             and store file content inside Zustand state so that Monaco re-renders reactively.

import { create } from 'zustand';
import type { FileNode, EditorTab } from '../types';
import { fileTree, mockEditorFiles } from '../data/mockData';

interface FileState {
  fileTree: FileNode[];
  openTabs: EditorTab[];
  activeTabId: string;
  // [AI-STRICT] isAIControlMode set to true puts Monaco into readOnly mode.
  //             Only setAIControlMode() should toggle this flag — do not set it directly.
  isAIControlMode: boolean;
  aiControlledFile: string | null;

  getActiveContent: () => string;
  getActiveLanguage: () => string;

  openFile: (name: string, modified?: boolean) => void;
  closeTab: (id: string) => void;
  setActiveTab: (id: string) => void;
  // @ai-integration-point: When the real backend is connected, call updateFileContent(name, content)
  //   on every 'fs:update' WebSocket event from the OpenHands sandbox to stream real file changes into Monaco.
  updateFileContent: (name: string, content: string) => void;
  // @ai-integration-point: Call setAIControlMode(true, fileName) when a 'dev:start-edit' WS event arrives,
  //   and setAIControlMode(false) when 'dev:stop-edit' is received. This enables/disables Monaco readOnly.
  setAIControlMode: (active: boolean, fileName?: string) => void;
}

export const useFileStore = create<FileState>((set, get) => ({
  fileTree,
  openTabs: [
    { id: 'App.tsx', name: 'App.tsx', modified: false },
    { id: 'AuthForm.tsx', name: 'AuthForm.tsx', modified: true },
    { id: 'index.css', name: 'index.css', modified: false },
  ],
  activeTabId: 'App.tsx',
  isAIControlMode: false,
  aiControlledFile: null,

  // [AI-STRICT] getActiveContent reads from the mutable mockEditorFiles map, not Zustand state.
  //             When replacing with real backend, store content in Zustand state and read from state here.
  getActiveContent: () => {
    const { activeTabId } = get();
    return mockEditorFiles[activeTabId]?.content ?? '// File not found';
  },

  getActiveLanguage: () => {
    const { activeTabId } = get();
    return mockEditorFiles[activeTabId]?.language ?? 'typescript';
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
      }
      return { openTabs: remaining, activeTabId: nextActive };
    });
  },

  setActiveTab: (id: string) => set({ activeTabId: id }),

  updateFileContent: (name: string, content: string) => {
    mockEditorFiles[name] = {
      ...(mockEditorFiles[name] ?? { language: 'typescript' }),
      content,
    };
    set((state) => ({
      openTabs: state.openTabs.map((t) =>
        t.id === name ? { ...t, modified: true } : t
      ),
    }));
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
