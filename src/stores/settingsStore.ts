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
//           The `getAvailableProviders()` selector returns only providers with a configured API key.
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

// ─── Provider Registry ──────────────────────────────────────────────────────
// Display names and metadata for known providers. The `id` is the key used in
// apiKeys, agentConfigs, and the backend routing table.

export interface ProviderInfo {
  id: string;
  name: string;
}

export const PROVIDER_REGISTRY: ProviderInfo[] = [
  { id: 'openai', name: 'OpenAI' },
  { id: 'anthropic', name: 'Anthropic' },
  { id: 'google', name: 'Google AI' },
  { id: 'together', name: 'Together.ai' },
  { id: 'openrouter', name: 'OpenRouter' },
  { id: 'mistral', name: 'Mistral' },
  { id: 'groq', name: 'Groq' },
];

const PROVIDER_NAME_MAP: Record<string, string> = Object.fromEntries(
  PROVIDER_REGISTRY.map((p) => [p.id, p.name]),
);

// ─── State Interface ─────────────────────────────────────────────────────────

interface SettingsState {
  workspaceId: string;
  agentModels: Record<AgentRole, AgentModelConfig>;

  /** Generic multi-provider API key map. Key = provider id, Value = raw API key. */
  apiKeys: Record<string, string>;

  setWorkspaceId: (id: string) => void;
  setAgentModel: (role: AgentRole, provider: string, model: string) => void;
  setAgentSystemPrompt: (role: AgentRole, prompt: string | null) => void;

  /** Set or clear a provider's API key. Pass empty string to remove. */
  setProviderKey: (providerId: string, key: string) => void;

  /** @deprecated Use setProviderKey instead. Kept for backward compat. */
  setApiKey: (provider: string, key: string) => void;

  /**
   * Returns an array of provider IDs that have a non-empty API key configured.
   * Used by AgentSetupPage to conditionally populate the provider dropdown.
   */
  getAvailableProviders: () => ProviderInfo[];

  /**
   * Returns the raw API key for a given provider, or empty string if not set.
   */
  getApiKeyForProvider: (providerId: string) => string;

  /**
   * Returns the shape expected by RunStartData.agentConfig.
   * Now includes `api_key` per role so the backend has everything it needs.
   */
  getAgentConfig: () => Partial<Record<AgentRole, Record<string, unknown>>>;

  resetSettings: () => void;
}

// ─── Defaults ────────────────────────────────────────────────────────────────

const defaultAgentModels: Record<AgentRole, AgentModelConfig> = {
  'tech-lead': { provider: 'openai', model: 'gpt-4o', systemPrompt: null },
  dev: { provider: 'openai', model: 'gpt-4o', systemPrompt: null },
  qa: { provider: 'openai', model: 'gpt-4o-mini', systemPrompt: null },
};

const defaultApiKeys: Record<string, string> = {};

// ─── Store ───────────────────────────────────────────────────────────────────

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

      setProviderKey: (providerId, key) => {
        set((state) => {
          const next = { ...state.apiKeys };
          if (key) {
            next[providerId] = key;
          } else {
            delete next[providerId];
          }
          return { apiKeys: next };
        });
      },

      // Backward compat shim
      setApiKey: (provider, key) => {
        get().setProviderKey(provider, key);
      },

      getAvailableProviders: () => {
        const { apiKeys } = get();
        return PROVIDER_REGISTRY.filter((p) => (apiKeys[p.id] ?? '').length > 0);
      },

      getApiKeyForProvider: (providerId) => {
        return get().apiKeys[providerId] ?? '';
      },

      getAgentConfig: () => {
        const { agentModels, apiKeys } = get();
        const config: Partial<Record<AgentRole, Record<string, unknown>>> = {};

        for (const role of Object.keys(agentModels) as AgentRole[]) {
          const entry = agentModels[role];
          config[role] = {
            provider: entry.provider,
            model: entry.model,
            api_key: apiKeys[entry.provider] ?? '',
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
      // Migrate old localStorage shape (openaiApiKey/openrouterApiKey) to new generic map
      migrate: (persisted: unknown) => {
        const state = persisted as Record<string, unknown>;
        if (state && typeof state === 'object' && state.apiKeys) {
          const keys = state.apiKeys as Record<string, string>;
          // Convert old { openaiApiKey: '...', openrouterApiKey: '...' } to { openai: '...', openrouter: '...' }
          if ('openaiApiKey' in keys) {
            const migrated: Record<string, string> = {};
            if (keys.openaiApiKey) migrated.openai = keys.openaiApiKey;
            if (keys.openrouterApiKey) migrated.openrouter = keys.openrouterApiKey;
            state.apiKeys = migrated;
          }
        }
        return state as unknown as SettingsState;
      },
      version: 1,
    }
  )
);

/**
 * Lookup helper: returns the display name for a provider ID.
 * Falls back to the raw ID with first letter capitalized.
 */
export function getProviderDisplayName(providerId: string): string {
  return PROVIDER_NAME_MAP[providerId] ?? providerId.charAt(0).toUpperCase() + providerId.slice(1);
}
