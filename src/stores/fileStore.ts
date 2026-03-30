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

// ── Monaco debounce: coalesce rapid fs:update content bursts ──────────────────
// AUDIT FIX: Rapid DevAgent writes (multiple fs:update events within milliseconds)
// would cause Zustand to fire a store update per event, triggering a Monaco re-render
// per keystroke — overwhelming the editor and risking desync or infinite render loops.
// This Map debounces per-file: subsequent setFileFromServer calls for the same file
// cancel the previous pending timer and schedule a new one. Only after the burst
// stops (≥150ms gap) does a single state update fire, causing one re-render.
const _pendingServerEdits = new Map<string, ReturnType<typeof setTimeout>>();

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL?.trim() || '';

/** Map file extensions to Monaco language IDs */
function langForPath(filePath: string): string {
  const ext = filePath.slice(filePath.lastIndexOf('.'));
  const map: Record<string, string> = {
    '.py': 'python', '.ts': 'typescript', '.tsx': 'typescriptreact',
    '.js': 'javascript', '.jsx': 'javascriptreact', '.json': 'json',
    '.md': 'markdown', '.html': 'html', '.css': 'css',
    '.yml': 'yaml', '.yaml': 'yaml', '.sh': 'shell',
    '.toml': 'toml', '.rs': 'rust', '.go': 'go',
  };
  return map[ext] ?? 'plaintext';
}

interface FileState {
  fileTree: FileNode[];
  fileContents: Record<string, { content: string; language: string }>;
  openTabs: EditorTab[];
  activeTabId: string;
  isAIControlMode: boolean;
  aiControlledFile: string | null;
  isLoadingFile: boolean;

  getActiveContent: () => string;
  getActiveLanguage: () => string;

  openFile: (name: string, modified?: boolean) => void;
  closeTab: (id: string) => void;
  setActiveTab: (id: string) => void;
  updateFileContent: (name: string, content: string) => void;
  setFileTree: (tree: FileNode[]) => void;
  setFileFromServer: (name: string, path: string, language: string, content: string) => void;
  setAIControlMode: (active: boolean, fileName?: string) => void;
  fetchAndOpenFile: (filePath: string, workspaceId: string) => Promise<void>;
}

export const useFileStore = create<FileState>((set, get) => ({
  fileTree: [],
  fileContents: {},
  openTabs: [],
  activeTabId: '',
  isAIControlMode: false,
  aiControlledFile: null,
  isLoadingFile: false,

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

  // Hydrate a single file from fs:update events — opens the tab if not already open.
  // AUDIT FIX (Monaco Race Condition): Debounce the CONTENT update so that rapid
  // DevAgent writes (multiple fs:update events in milliseconds) do NOT cause a
  // Zustand store update per event. Only ONE update fires after the burst stops
  // (≥150ms gap), preventing Monaco from being overwhelmed by rapid re-renders.
  // The tab open/modified state is still updated immediately so the file explorer
  // stays in sync; only the content field is debounced.
  setFileFromServer: (name: string, _path: string, language: string, content: string) => {
    // Immediately open/modify the tab so the file explorer reflects the update at once
    set((state) => {
      const existingTab = state.openTabs.find((t) => t.id === name);
      const newTabs = existingTab
        ? state.openTabs.map((t) => (t.id === name ? { ...t, modified: true } : t))
        : [...state.openTabs, { id: name, name, modified: true }];
      return { openTabs: newTabs, activeTabId: name };
    });

    // Cancel any pending debounce for this file — the latest write wins
    const existingTimer = _pendingServerEdits.get(name);
    if (existingTimer !== undefined) {
      clearTimeout(existingTimer);
    }

    // Schedule the content update; subsequent writes within 150ms cancel the previous timer
    const timer = setTimeout(() => {
      _pendingServerEdits.delete(name);
      set((state) => {
        // Only apply if no user has since closed the tab
        if (!(name in state.fileContents) && !state.openTabs.find((t) => t.id === name)) {
          return state;  // tab was closed — discard stale update
        }
        return {
          fileContents: {
            ...state.fileContents,
            [name]: { content, language },
          },
        };
      });
    }, 150);

    _pendingServerEdits.set(name, timer);
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

  // Fetch file content from the backend REST API and open it in the editor
  fetchAndOpenFile: async (filePath: string, workspaceId: string) => {
    const state = get();

    // If content is already cached, just switch to the tab
    if (state.fileContents[filePath]) {
      get().openFile(filePath);
      return;
    }

    // Show loading state
    set({ isLoadingFile: true });

    try {
      const url = `${API_BASE_URL}/api/workspaces/${encodeURIComponent(workspaceId)}/file?path=${encodeURIComponent(filePath)}`;
      const res = await fetch(url);

      if (!res.ok) {
        console.warn(`[fileStore] Failed to fetch file: ${res.status} ${res.statusText} (${filePath})`);
        // Still open the tab with a fallback message so the UI doesn't silently fail
        get().setFileFromServer(
          filePath,
          filePath,
          langForPath(filePath),
          `// Failed to load file: ${filePath}\n// Server returned ${res.status} ${res.statusText}`,
        );
        return;
      }

      const data = await res.json();
      const content = data.content ?? '';
      const language = langForPath(filePath);

      get().setFileFromServer(filePath, filePath, language, content);
    } catch (err) {
      console.error('[fileStore] Error fetching file content:', err);
      get().setFileFromServer(
        filePath,
        filePath,
        langForPath(filePath),
        `// Error loading file: ${filePath}\n// ${err instanceof Error ? err.message : 'Unknown error'}`,
      );
    } finally {
      set({ isLoadingFile: false });
    }
  },
}));
