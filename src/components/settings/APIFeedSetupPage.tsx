// @ai-module: Settings — AI API Feed Setup Page
// @ai-role: Settings panel for managing AI provider API keys and custom OpenAI-compatible endpoints.
//           All state is local (useState) — keys are NOT persisted anywhere.
//           The "Test connection" button simulates a connectivity check with a random success/failure result.
// @ai-dependencies: None (no store or hook imports — local state only)

// [AI-STRICT] API keys must NEVER be stored in Zustand state or committed to any store that is serialized
//             to localStorage in plaintext. When implementing real persistence, use a secure storage mechanism:
//             - For browser-only: Web Crypto API + IndexedDB encryption.
//             - For server-side: Store keys in Supabase Edge Function secrets, never client-side.
// [AI-STRICT] The test connection simulation (random success/failure) is mock-only.
//             When implementing real connectivity checks, proxy the test through a Supabase Edge Function
//             so the API key is never exposed in browser network traffic.
// @ai-integration-point: Replace the setTimeout simulation in testConnection() with a real Edge Function call:
//   const res = await fetch("/functions/v1/test-api-key", { method: "POST", body: JSON.stringify({ provider, key }) });
//   const { success, message } = await res.json();


import { useState } from 'react';
import {
  Eye,
  EyeOff,
  CheckCircle2,
  AlertCircle,
  Loader2,
  ExternalLink,
  Plus,
  Trash2,
  Info,
  Zap,
  Globe,
  Shield,
} from 'lucide-react';

type TestStatus = 'idle' | 'testing' | 'success' | 'error';

interface Provider {
  id: string;
  name: string;
  description: string;
  docsUrl: string;
  keyPrefix: string;
  keyPlaceholder: string;
  models: string[];
  badge?: string;
  badgeColor?: string;
}

const PROVIDERS: Provider[] = [
  {
    id: 'openai',
    name: 'OpenAI',
    description: 'GPT-4o, GPT-4 Turbo, GPT-3.5 and embeddings.',
    docsUrl: 'https://platform.openai.com/api-keys',
    keyPrefix: 'sk-',
    keyPlaceholder: 'sk-••••••••••••••••••••••••••••••••',
    models: ['gpt-4o', 'gpt-4o-mini', 'gpt-4-turbo', 'gpt-3.5-turbo'],
    badge: 'Recommended',
    badgeColor: 'text-sky-400 bg-sky-500/10 border-sky-500/20',
  },
  {
    id: 'anthropic',
    name: 'Anthropic',
    description: 'Claude 3.5 Sonnet, Claude 3 Opus, Haiku — long context & reasoning.',
    docsUrl: 'https://console.anthropic.com/settings/keys',
    keyPrefix: 'sk-ant-',
    keyPlaceholder: 'sk-ant-••••••••••••••••••••••••••••••',
    models: ['claude-3-5-sonnet', 'claude-3-opus', 'claude-3-haiku'],
  },
  {
    id: 'google',
    name: 'Google AI',
    description: 'Gemini 1.5 Pro and Flash with up to 1M token context window.',
    docsUrl: 'https://aistudio.google.com/app/apikey',
    keyPrefix: 'AIza',
    keyPlaceholder: 'AIza••••••••••••••••••••••••••••••••',
    models: ['gemini-1-5-pro', 'gemini-1-5-flash'],
    badge: '1M ctx',
    badgeColor: 'text-emerald-400 bg-emerald-500/10 border-emerald-500/20',
  },
  {
    id: 'mistral',
    name: 'Mistral',
    description: 'Mistral Large, Mixtral 8x22B — open-weight European models.',
    docsUrl: 'https://console.mistral.ai/api-keys/',
    keyPrefix: '',
    keyPlaceholder: '••••••••••••••••••••••••••••••••',
    models: ['mistral-large', 'mistral-medium', 'mixtral-8x22b'],
  },
  {
    id: 'groq',
    name: 'Groq',
    description: 'Ultra-fast inference for Llama 3 and Mixtral via LPU hardware.',
    docsUrl: 'https://console.groq.com/keys',
    keyPrefix: 'gsk_',
    keyPlaceholder: 'gsk_••••••••••••••••••••••••••••••••',
    models: ['llama-3-70b', 'llama-3-8b', 'mixtral-8x7b'],
    badge: 'Fast',
    badgeColor: 'text-amber-400 bg-amber-500/10 border-amber-500/20',
  },
];

interface ApiEntry {
  providerId: string;
  key: string;
  testStatus: TestStatus;
  testMessage: string;
}

// @ts-expect-error — MaskedKey is pre-built for future use in ProviderCard; not yet wired in
function MaskedKey({ value, visible }: { value: string; visible: boolean }) {
  if (!value) return <span className="text-slate-600 text-xs">Not set</span>;
  if (visible) return <span className="text-slate-300 text-xs font-mono break-all">{value}</span>;
  const shown = value.slice(0, 8);
  return (
    <span className="text-slate-400 text-xs font-mono">
      {shown}{'•'.repeat(Math.min(value.length - 8, 20))}
    </span>
  );
}

function ProviderCard({
  provider,
  entry,
  onChange,
  onTest,
  onRemove,
}: {
  provider: Provider;
  entry: ApiEntry | null;
  onChange: (key: string) => void;
  onTest: () => void;
  onRemove: () => void;
}) {
  const [visible, setVisible] = useState(false);
  const [inputValue, setInputValue] = useState(entry?.key ?? '');

  const handleBlur = () => {
    onChange(inputValue);
  };

  const status = entry?.testStatus ?? 'idle';
  const isConfigured = !!entry?.key;

  return (
    <div className={`rounded-lg border transition-colors ${isConfigured ? 'border-slate-700 bg-slate-900/50' : 'border-slate-800 bg-slate-900/25'
      }`}>
      <div className="flex items-start gap-3 px-4 py-3.5">
        <div className={`mt-0.5 w-2 h-2 rounded-full shrink-0 ${status === 'success' ? 'bg-emerald-400' :
          status === 'error' ? 'bg-red-400' :
            isConfigured ? 'bg-amber-400' : 'bg-slate-700'
          }`} />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-0.5">
            <span className="text-sm font-medium text-slate-200">{provider.name}</span>
            {provider.badge && (
              <span className={`text-[9px] font-semibold px-1.5 py-0.5 rounded border ${provider.badgeColor}`}>
                {provider.badge}
              </span>
            )}
            <a
              href="#"
              onClick={(e) => e.preventDefault()}
              className="ml-auto flex items-center gap-1 text-[10px] text-slate-500 hover:text-sky-400 transition-colors"
            >
              <ExternalLink className="w-2.5 h-2.5" />
              Get key
            </a>
          </div>
          <p className="text-[11px] text-slate-500 mb-2.5 leading-relaxed">{provider.description}</p>

          <div className="flex items-center gap-2 bg-slate-950 border border-slate-800 rounded-md px-3 py-2 focus-within:border-sky-500/50 transition-colors">
            <Shield className="w-3 h-3 text-slate-600 shrink-0" />
            <input
              type={visible ? 'text' : 'password'}
              value={inputValue}
              onChange={(e) => setInputValue(e.target.value)}
              onBlur={handleBlur}
              placeholder={provider.keyPlaceholder}
              className="flex-1 bg-transparent text-xs text-slate-300 placeholder:text-slate-700 font-mono focus:outline-none"
            />
            {inputValue && (
              <button
                onClick={() => setVisible((p) => !p)}
                className="text-slate-500 hover:text-slate-300 transition-colors shrink-0"
              >
                {visible ? <EyeOff className="w-3 h-3" /> : <Eye className="w-3 h-3" />}
              </button>
            )}
          </div>

          {isConfigured && (
            <div className="flex items-center gap-2 mt-2">
              <button
                onClick={onTest}
                disabled={status === 'testing'}
                className="flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-slate-800 hover:bg-slate-700 border border-slate-700 hover:border-slate-600 text-xs text-slate-300 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {status === 'testing' ? (
                  <Loader2 className="w-3 h-3 animate-spin" />
                ) : (
                  <Zap className="w-3 h-3 text-amber-400" />
                )}
                {status === 'testing' ? 'Testing...' : 'Test connection'}
              </button>

              {status === 'success' && (
                <span className="flex items-center gap-1 text-[11px] text-emerald-400">
                  <CheckCircle2 className="w-3 h-3" />
                  {entry?.testMessage ?? 'Connected'}
                </span>
              )}
              {status === 'error' && (
                <span className="flex items-center gap-1 text-[11px] text-red-400">
                  <AlertCircle className="w-3 h-3" />
                  {entry?.testMessage ?? 'Invalid key'}
                </span>
              )}

              <button
                onClick={onRemove}
                className="ml-auto flex items-center gap-1 text-[10px] text-slate-600 hover:text-red-400 transition-colors px-1.5 py-1 rounded hover:bg-red-500/10"
              >
                <Trash2 className="w-2.5 h-2.5" />
                Remove
              </button>
            </div>
          )}

          <div className="flex flex-wrap gap-1 mt-2.5">
            {provider.models.map((m) => (
              <span key={m} className="text-[9px] text-slate-500 bg-slate-800/60 border border-slate-800 rounded px-1.5 py-0.5">
                {m}
              </span>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

interface CustomEndpoint {
  id: string;
  name: string;
  baseUrl: string;
  key: string;
}

export function APIFeedSetupPage() {
  const [entries, setEntries] = useState<Record<string, ApiEntry>>({});
  const [customEndpoints, setCustomEndpoints] = useState<CustomEndpoint[]>([]);
  const [showAddCustom, setShowAddCustom] = useState(false);
  const [newEndpoint, setNewEndpoint] = useState({ name: '', baseUrl: '', key: '' });

  const updateKey = (providerId: string, key: string) => {
    if (!key) {
      setEntries((p) => {
        const next = { ...p };
        delete next[providerId];
        return next;
      });
      return;
    }
    setEntries((p) => ({
      ...p,
      [providerId]: { providerId, key, testStatus: 'idle', testMessage: '' },
    }));
  };

  const testConnection = async (providerId: string) => {
    setEntries((p) => ({
      ...p,
      [providerId]: { ...p[providerId], testStatus: 'testing', testMessage: '' },
    }));

    try {
      const apiBase = import.meta.env.VITE_API_BASE_URL?.trim();
      if (!apiBase) {
        throw new Error('VITE_API_BASE_URL is not configured');
      }

      const entry = entries[providerId];
      const res = await fetch(`${apiBase}/api/test-connection`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ provider: providerId, key: entry?.key }),
      });

      const data = await res.json();
      setEntries((p) => ({
        ...p,
        [providerId]: {
          ...p[providerId],
          testStatus: data.success ? 'success' : 'error',
          testMessage: data.message ?? (data.success ? 'API key valid' : 'Connection failed'),
        },
      }));
    } catch (err) {
      setEntries((p) => ({
        ...p,
        [providerId]: {
          ...p[providerId],
          testStatus: 'error',
          testMessage: err instanceof Error ? err.message : 'Connection test failed',
        },
      }));
    }
  };

  const removeEntry = (providerId: string) => {
    setEntries((p) => {
      const next = { ...p };
      delete next[providerId];
      return next;
    });
  };

  const addCustomEndpoint = () => {
    if (!newEndpoint.name || !newEndpoint.baseUrl) return;
    setCustomEndpoints((p) => [
      ...p,
      { id: `custom-${Date.now()}`, ...newEndpoint },
    ]);
    setNewEndpoint({ name: '', baseUrl: '', key: '' });
    setShowAddCustom(false);
  };

  const removeCustomEndpoint = (id: string) => {
    setCustomEndpoints((p) => p.filter((e) => e.id !== id));
  };

  const configuredCount = Object.keys(entries).length + customEndpoints.length;

  return (
    <div className="h-full overflow-y-auto">
      <div className="max-w-2xl mx-auto px-6 py-6 space-y-4">
        <div className="mb-2">
          <h2 className="text-base font-semibold text-slate-100 mb-1">AI API Feed Setup</h2>
          <p className="text-sm text-slate-500">
            Connect your API keys to enable agent model access. Keys are stored locally and never transmitted to third parties.
          </p>
        </div>

        <div className="flex items-center gap-4 px-4 py-3 rounded-lg bg-slate-900 border border-slate-800">
          <div className="text-center">
            <div className="text-xl font-bold text-slate-100">{configuredCount}</div>
            <div className="text-[10px] text-slate-500 uppercase tracking-wide">Connected</div>
          </div>
          <div className="w-px h-8 bg-slate-800" />
          <div className="text-center">
            <div className="text-xl font-bold text-slate-100">{PROVIDERS.length}</div>
            <div className="text-[10px] text-slate-500 uppercase tracking-wide">Available</div>
          </div>
          <div className="w-px h-8 bg-slate-800" />
          <div className="text-center">
            <div className="text-xl font-bold text-slate-100">{customEndpoints.length}</div>
            <div className="text-[10px] text-slate-500 uppercase tracking-wide">Custom</div>
          </div>
          <div className="ml-auto flex items-start gap-1.5">
            <Shield className="w-3.5 h-3.5 text-emerald-400 mt-0.5 shrink-0" />
            <span className="text-[11px] text-slate-500 leading-relaxed">
              Keys stored locally only
            </span>
          </div>
        </div>

        <div className="flex items-start gap-2.5 px-3 py-2.5 rounded-md bg-sky-500/5 border border-sky-500/20">
          <Info className="w-3.5 h-3.5 text-sky-400 shrink-0 mt-0.5" />
          <p className="text-[11px] text-sky-300/80 leading-relaxed">
            You only need to configure the providers used by your selected models in Agent Setup. At least one key is required to run agents.
          </p>
        </div>

        <div className="space-y-2">
          <h3 className="flex items-center gap-2 text-[11px] font-semibold text-slate-400 uppercase tracking-widest">
            <Globe className="w-3 h-3" />
            Hosted Providers
          </h3>
          {PROVIDERS.map((provider) => (
            <ProviderCard
              key={provider.id}
              provider={provider}
              entry={entries[provider.id] ?? null}
              onChange={(key) => updateKey(provider.id, key)}
              onTest={() => testConnection(provider.id)}
              onRemove={() => removeEntry(provider.id)}
            />
          ))}
        </div>

        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <h3 className="flex items-center gap-2 text-[11px] font-semibold text-slate-400 uppercase tracking-widest">
              <Zap className="w-3 h-3" />
              Custom / Self-hosted Endpoints
            </h3>
            <button
              onClick={() => setShowAddCustom((p) => !p)}
              className="flex items-center gap-1 px-2.5 py-1 rounded-md bg-slate-800 hover:bg-slate-700 border border-slate-700 text-xs text-slate-300 transition-colors"
            >
              <Plus className="w-3 h-3" />
              Add endpoint
            </button>
          </div>

          {showAddCustom && (
            <div className="rounded-lg border border-sky-500/30 bg-sky-500/5 p-4 space-y-3">
              <p className="text-[11px] text-slate-400">Add any OpenAI-compatible endpoint (Ollama, LM Studio, vLLM, etc.)</p>
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <label className="text-[10px] text-slate-500 uppercase tracking-wide mb-1 block">Name</label>
                  <input
                    type="text"
                    value={newEndpoint.name}
                    onChange={(e) => setNewEndpoint((p) => ({ ...p, name: e.target.value }))}
                    placeholder="e.g. Local Ollama"
                    className="w-full bg-slate-950 border border-slate-700 rounded px-2.5 py-1.5 text-xs text-slate-300 placeholder:text-slate-600 focus:outline-none focus:border-sky-500/60 transition-colors"
                  />
                </div>
                <div>
                  <label className="text-[10px] text-slate-500 uppercase tracking-wide mb-1 block">Base URL</label>
                  <input
                    type="text"
                    value={newEndpoint.baseUrl}
                    onChange={(e) => setNewEndpoint((p) => ({ ...p, baseUrl: e.target.value }))}
                    placeholder="http://localhost:11434/v1"
                    className="w-full bg-slate-950 border border-slate-700 rounded px-2.5 py-1.5 text-xs text-slate-300 placeholder:text-slate-600 focus:outline-none focus:border-sky-500/60 transition-colors"
                  />
                </div>
              </div>
              <div>
                <label className="text-[10px] text-slate-500 uppercase tracking-wide mb-1 block">API Key (optional)</label>
                <input
                  type="password"
                  value={newEndpoint.key}
                  onChange={(e) => setNewEndpoint((p) => ({ ...p, key: e.target.value }))}
                  placeholder="Leave blank for unauthenticated endpoints"
                  className="w-full bg-slate-950 border border-slate-700 rounded px-2.5 py-1.5 text-xs text-slate-300 placeholder:text-slate-600 font-mono focus:outline-none focus:border-sky-500/60 transition-colors"
                />
              </div>
              <div className="flex items-center gap-2 pt-1">
                <button
                  onClick={addCustomEndpoint}
                  disabled={!newEndpoint.name || !newEndpoint.baseUrl}
                  className="px-3 py-1.5 rounded-md bg-sky-600 hover:bg-sky-500 disabled:opacity-40 disabled:cursor-not-allowed text-white text-xs font-medium transition-colors"
                >
                  Add endpoint
                </button>
                <button
                  onClick={() => setShowAddCustom(false)}
                  className="px-3 py-1.5 rounded-md hover:bg-slate-800 text-slate-400 text-xs transition-colors"
                >
                  Cancel
                </button>
              </div>
            </div>
          )}

          {customEndpoints.length === 0 && !showAddCustom && (
            <div className="flex flex-col items-center justify-center py-6 rounded-lg border border-dashed border-slate-800 text-slate-600">
              <Zap className="w-5 h-5 mb-1.5" />
              <span className="text-xs">No custom endpoints configured</span>
            </div>
          )}

          {customEndpoints.map((ep) => (
            <div key={ep.id} className="flex items-center gap-3 px-4 py-3 rounded-lg border border-slate-700 bg-slate-900/50">
              <div className="w-2 h-2 rounded-full bg-emerald-400 shrink-0" />
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-medium text-slate-200">{ep.name}</span>
                  <span className="text-[9px] text-emerald-400 bg-emerald-500/10 border border-emerald-500/20 px-1.5 py-0.5 rounded">
                    Custom
                  </span>
                </div>
                <p className="text-[11px] text-slate-500 font-mono truncate">{ep.baseUrl}</p>
              </div>
              <button
                onClick={() => removeCustomEndpoint(ep.id)}
                className="p-1.5 rounded hover:bg-red-500/10 text-slate-600 hover:text-red-400 transition-colors"
              >
                <Trash2 className="w-3 h-3" />
              </button>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
