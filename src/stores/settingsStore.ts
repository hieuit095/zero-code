/**
 * ==========================================
 * Author: Hieu Nguyen - Codev Team
 * Email: hieuit095@gmail.com
 * Project: ZeroCode - Autonomous Multi-Agent IDE
 * ==========================================
 */
// @ai-module: Settings Store
// @ai-role: Persistent Zustand store for agent configuration, model selection, and API keys.
//           Uses Zustand `persist` middleware to save to localStorage.
//           The `getAgentConfig()` selector returns the shape expected by RunStartData.agentConfig.
// @ai-dependencies: types/index.ts (AgentRole)

// [AI-STRICT] API keys stored here are for local development only.
//             In production, keys must be handled server-side. This store structure is ready
//             to be sent to the backend via REST/WS but keys should never be sent over WS.

import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import type { AgentRole } from '../types';

export interface AgentModelConfig {
  provider: string;
  model: string;
  systemPrompt: string | null;
}

interface SettingsState {
  workspaceId: string;
  agentModels: Record<AgentRole, AgentModelConfig>;
  apiKeys: {
    openaiApiKey: string;
    openrouterApiKey: string;
  };

  setWorkspaceId: (id: string) => void;
  setAgentModel: (role: AgentRole, provider: string, model: string) => void;
  setAgentSystemPrompt: (role: AgentRole, prompt: string | null) => void;
  setApiKey: (provider: keyof SettingsState['apiKeys'], key: string) => void;
  getAgentConfig: () => Partial<Record<AgentRole, Record<string, unknown>>>;
  resetSettings: () => void;
}

const defaultAgentModels: Record<AgentRole, AgentModelConfig> = {
  'tech-lead': { provider: 'OpenAI', model: 'gpt-4o', systemPrompt: null },
  dev: { provider: 'OpenAI', model: 'gpt-4o', systemPrompt: null },
  qa: { provider: 'OpenAI', model: 'gpt-4o-mini', systemPrompt: null },
};

const defaultApiKeys = {
  openaiApiKey: '',
  openrouterApiKey: '',
};

export const useSettingsStore = create<SettingsState>()(
  persist(
    (set, get) => ({
      workspaceId: 'repo-main',
      agentModels: { ...defaultAgentModels },
      apiKeys: { ...defaultApiKeys },

      setWorkspaceId: (id) => set({ workspaceId: id }),

      setAgentModel: (role, provider, model) => {
        set((state) => ({
          agentModels: {
            ...state.agentModels,
            [role]: { ...state.agentModels[role], provider, model },
          },
        }));
      },

      setAgentSystemPrompt: (role, prompt) => {
        set((state) => ({
          agentModels: {
            ...state.agentModels,
            [role]: { ...state.agentModels[role], systemPrompt: prompt },
          },
        }));
      },

      setApiKey: (provider, key) => {
        set((state) => ({
          apiKeys: { ...state.apiKeys, [provider]: key },
        }));
      },

      // @ai-integration-point: Pass this return value as `agentConfig` in RunStartData
      //   when calling startRun({ goal, workspaceId, agentConfig: getAgentConfig() }).
      getAgentConfig: () => {
        const { agentModels } = get();
        const config: Partial<Record<AgentRole, Record<string, unknown>>> = {};

        for (const role of Object.keys(agentModels) as AgentRole[]) {
          const entry = agentModels[role];
          config[role] = {
            provider: entry.provider,
            model: entry.model,
            ...(entry.systemPrompt ? { systemPrompt: entry.systemPrompt } : {}),
          };
        }

        return config;
      },

      resetSettings: () =>
        set({
          workspaceId: 'repo-main',
          agentModels: { ...defaultAgentModels },
          apiKeys: { ...defaultApiKeys },
        }),
    }),
    {
      name: 'zero-code-settings',
      partialize: (state) => ({
        workspaceId: state.workspaceId,
        agentModels: state.agentModels,
        apiKeys: state.apiKeys,
      }),
    }
  )
);
