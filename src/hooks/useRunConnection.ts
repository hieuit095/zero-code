/**
 * ==========================================
 * Author: Hieu Nguyen - Codev Team
 * Email: hieuit095@gmail.com
 * Project: ZeroCode - Autonomous Multi-Agent IDE
 * ==========================================
 */
/**
 * WebSocket + REST bridge for the run lifecycle defined in `plan.md` section 3.
 *
 * REST request shape sent to `POST /api/runs`:
 * {
 *   "goal": "Build the first version of a multi-agent IDE backend",
 *   "workspaceId": "repo-main",
 *   "agentConfig": {
 *     "tech-lead": { "model": "gpt-4o" },
 *     "dev": { "model": "gpt-4o" },
 *     "qa": { "model": "gpt-4o-mini" }
 *   }
 * }
 *
 * WebSocket server envelope shape expected from the backend:
 * {
 *   "type": "agent:status",
 *   "runId": "run_01JXYZ...",
 *   "seq": 42,
 *   "timestamp": "2026-03-16T05:20:14.221Z",
 *   "data": {}
 * }
 */

import { useEffect, useRef, useState } from 'react';
import { useAgentStore } from '../stores/agentStore';
import { useFileStore } from '../stores/fileStore';
import { useTerminalStore } from '../stores/terminalStore';
import type {
  ConnectionReadyEvent,
  RunSocketClientEvent,
  RunSocketServerEvent,
  RunStartData,
} from '../types/runEvents';

const DEFAULT_API_BASE_URL = import.meta.env.VITE_API_BASE_URL?.trim() || '';
const MAX_RECONNECT_ATTEMPTS = 10;
const TERMINAL_EVENT_TYPES = new Set(['run:complete', 'run:error']);
const SERVER_EVENT_TYPES = new Set<RunSocketServerEvent['type']>([
  'connection:ready',
  'run:created',
  'run:state',
  'run:complete',
  'run:error',
  'agent:status',
  'agent:message:start',
  'agent:message:delta',
  'agent:message',
  'task:snapshot',
  'task:update',
  'fs:tree',
  'dev:start-edit',
  'fs:update',
  'dev:stop-edit',
  'terminal:command',
  'terminal:output',
  'terminal:exit',
  'qa:report',
  'qa:passed',
]);

export interface RunConnectionState {
  runId: string | null;
  runStatus: string | null;
  runPhase: string | null;
  runProgress: number;
  isConnected: boolean;
  isConnecting: boolean;
  reconnectAttempt: number;
  lastEvent: RunSocketServerEvent | null;
  connectionReady: ConnectionReadyEvent['data'] | null;
  error: string | null;
}

export type StartRunOptions = RunStartData;

export interface UseRunConnectionReturn extends RunConnectionState {
  startRun: (options: StartRunOptions) => Promise<{ runId: string; wsUrl: string }>;
  disconnect: () => void;
  sendMessage: (event: RunSocketClientEvent) => boolean;
  cancelRun: (reason?: string) => boolean;
  refreshWorkspace: (reason?: string) => boolean;
  interruptRun: (message: string) => boolean;
}

interface RunCreateResponse {
  runId: string;
  workspaceId: string;
  status: string;
  wsUrl: string;
}

function getApiBaseUrl() {
  return import.meta.env.VITE_API_BASE_URL?.trim() || DEFAULT_API_BASE_URL;
}

function getAbsoluteWebSocketUrl(input: string) {
  if (input.startsWith('ws://') || input.startsWith('wss://')) {
    return input;
  }

  const apiBaseUrl = getApiBaseUrl();
  const apiUrl = new URL(apiBaseUrl);
  const wsProtocol = apiUrl.protocol === 'https:' ? 'wss:' : 'ws:';

  if (input.startsWith('/')) {
    return `${wsProtocol}//${apiUrl.host}${input}`;
  }

  return `${wsProtocol}//${apiUrl.host}/${input.replace(/^\/+/, '')}`;
}

function isRunSocketServerEvent(value: unknown): value is RunSocketServerEvent {
  if (typeof value !== 'object' || value === null) return false;

  const candidate = value as Record<string, unknown>;
  return (
    typeof candidate.type === 'string' &&
    SERVER_EVENT_TYPES.has(candidate.type as RunSocketServerEvent['type']) &&
    typeof candidate.seq === 'number' &&
    typeof candidate.timestamp === 'string' &&
    'data' in candidate
  );
}

async function createRunRequest(options: StartRunOptions) {
  const response = await fetch(`${getApiBaseUrl()}/api/runs`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(options),
  });

  if (!response.ok) {
    throw new Error(`Failed to create run: ${response.status} ${response.statusText}`);
  }

  return (await response.json()) as RunCreateResponse;
}

export function useRunConnection(): UseRunConnectionReturn {
  const addMessageFromServer = useAgentStore((state) => state.addMessageFromServer);
  const updateAgentStatus = useAgentStore((state) => state.updateAgentStatus);
  const updateTask = useAgentStore((state) => state.updateTask);
  const setTasks = useAgentStore((state) => state.setTasks);
  const setRunStatus = useAgentStore((state) => state.setRunStatus);
  const setRunProgress = useAgentStore((state) => state.setRunProgress);
  const setQaRetryState = useAgentStore((state) => state.setQaRetryState);
  const clearQaRetryState = useAgentStore((state) => state.clearQaRetryState);
  const setConnectionStatus = useAgentStore((state) => state.setConnectionStatus);
  const setFileTree = useFileStore((state) => state.setFileTree);
  const setFileFromServer = useFileStore((state) => state.setFileFromServer);
  const setAIControlMode = useFileStore((state) => state.setAIControlMode);
  const appendTerminalLine = useTerminalStore((state) => state.appendLine);
  const clearTerminal = useTerminalStore((state) => state.clearTerminal);
  const setTerminalStreaming = useTerminalStore((state) => state.setStreaming);

  // Phase 1: Streaming buffer actions
  const startStreamingMessage = useAgentStore((state) => state.startStreamingMessage);
  const appendStreamingDelta = useAgentStore((state) => state.appendStreamingDelta);
  const finalizeStreamingMessage = useAgentStore((state) => state.finalizeStreamingMessage);

  // Phase 2: QA history actions
  const pushQaScore = useAgentStore((state) => state.pushQaScore);
  const clearQaScoreHistory = useAgentStore((state) => state.clearQaScoreHistory);

  const socketRef = useRef<WebSocket | null>(null);
  const reconnectTimerRef = useRef<number | null>(null);
  const shouldReconnectRef = useRef(false);
  const lastWsUrlRef = useRef<string | null>(null);

  // AUDIT FIX: Hydration gate — queues WS messages while snapshot fetch
  // is in-flight, then flushes them after snapshot applies. This prevents
  // stale REST data from overwriting newer real-time WS events.
  const isHydratingRef = useRef(false);
  const pendingEventsRef = useRef<RunSocketServerEvent[]>([]);

  // AUDIT FIX: Mutable refs for reconnection state. The socket.onopen
  // closure traps stale React state — these refs are always current.
  const reconnectAttemptRef = useRef(0);
  const runIdRef = useRef<string | null>(null);

  const [state, setState] = useState<RunConnectionState>({
    runId: null,
    runStatus: null,
    runPhase: null,
    runProgress: 0,
    isConnected: false,
    isConnecting: false,
    reconnectAttempt: 0,
    lastEvent: null,
    connectionReady: null,
    error: null,
  });

  const clearReconnectTimer = () => {
    if (reconnectTimerRef.current !== null) {
      window.clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = null;
    }
  };

  const disconnect = () => {
    shouldReconnectRef.current = false;
    clearReconnectTimer();
    socketRef.current?.close();
    socketRef.current = null;
    lastWsUrlRef.current = null;
    reconnectAttemptRef.current = 0;
    runIdRef.current = null;
    isHydratingRef.current = false;
    pendingEventsRef.current = [];

    setState((current) => ({
      ...current,
      isConnected: false,
      isConnecting: false,
      reconnectAttempt: 0,
    }));
  };

  const sendMessage = (event: RunSocketClientEvent) => {
    const socket = socketRef.current;
    if (!socket || socket.readyState !== WebSocket.OPEN) {
      return false;
    }

    socket.send(JSON.stringify(event));
    return true;
  };

  const dispatchServerEvent = (event: RunSocketServerEvent) => {
    // AUDIT FIX: Keep the mutable ref in sync for reconnect hydration.
    if (event.runId) {
      runIdRef.current = event.runId;
    }

    setState((current) => ({
      ...current,
      runId: event.runId ?? current.runId,
      lastEvent: event,
      error: event.type === 'run:error' ? event.data.message : current.error,
    }));

    switch (event.type) {
      case 'connection:ready': {
        setState((current) => ({
          ...current,
          connectionReady: event.data,
          isConnected: true,
          isConnecting: false,
          error: null,
        }));
        break;
      }

      case 'run:created': {
        clearTerminal();
        clearQaScoreHistory();
        setState((current) => ({
          ...current,
          runId: event.runId,
          runStatus: event.data.status,
          error: null,
        }));
        break;
      }

      case 'run:state': {
        setState((current) => ({
          ...current,
          runStatus: event.data.status,
          runPhase: event.data.phase,
          runProgress: event.data.progress,
        }));

        setRunStatus(event.data.status);
        setRunProgress(event.data.progress);

        if (event.data.status !== 'completed' && event.data.status !== 'failed') {
          setTerminalStreaming(true);
        }
        break;
      }

      case 'run:complete':
      case 'run:error': {
        setTerminalStreaming(false);
        shouldReconnectRef.current = false;

        setRunStatus(event.data.status);
        if (event.type === 'run:complete') {
          setRunProgress(100);
        }

        setState((current) => ({
          ...current,
          runStatus: event.data.status,
          runProgress: event.type === 'run:complete' ? 100 : current.runProgress,
          error: event.type === 'run:error' ? event.data.message : null,
        }));
        break;
      }

      case 'agent:status': {
        // @ai-integration-point: agent:status -> agentStore.updateAgentStatus - Replace this direct dispatch with a backend-authoritative hydration path once `agentStore` supports snapshots and server IDs.
        updateAgentStatus(event.data.role, event.data.state, event.data.activity);
        break;
      }

      case 'agent:message:start': {
        // Phase 1: Initialize the streaming buffer for this message
        startStreamingMessage(event.data.messageId, event.data.role);
        break;
      }

      case 'agent:message:delta': {
        // Phase 1: Append real LLM token delta to the streaming buffer
        appendStreamingDelta(event.data.messageId, event.data.delta);
        break;
      }

      case 'agent:message': {
        // Phase 1: Finalize the streaming buffer — remove the in-flight entry
        finalizeStreamingMessage(event.data.id);

        // Server-authoritative: preserves backend-provided id and timestamp
        addMessageFromServer({
          id: event.data.id,
          agent: event.data.agent,
          agentLabel: event.data.agentLabel,
          content: event.data.content,
          timestamp: event.data.timestamp,
        });
        break;
      }

      case 'task:snapshot': {
        setTasks(event.data.tasks);
        break;
      }

      case 'task:update': {
        // @ai-integration-point: task:update -> agentStore.updateTask - This is the minimal live-task path until the store supports full snapshot hydration.
        updateTask(event.data.taskId, event.data.status);
        break;
      }

      case 'fs:tree': {
        setFileTree(event.data.tree);
        break;
      }

      case 'dev:start-edit': {
        // @ai-integration-point: dev:start-edit -> fileStore.setAIControlMode - Keep Monaco readOnly while the Dev agent owns the active file.
        setAIControlMode(true, event.data.fileName);
        break;
      }

      case 'fs:update': {
        setFileFromServer(event.data.name, event.data.path, event.data.language, event.data.content);
        break;
      }

      case 'dev:stop-edit': {
        // @ai-integration-point: dev:stop-edit -> fileStore.setAIControlMode - Release Monaco back to user-editable mode when the Dev agent finishes.
        setAIControlMode(false, event.data.fileName);
        break;
      }

      case 'terminal:command': {
        // @ai-integration-point: terminal:command -> terminalStore.appendLine - Surface the sandbox command before stdout/stderr events begin streaming.
        appendTerminalLine(`$ ${event.data.command}`, 'command');
        setTerminalStreaming(true);
        break;
      }

      case 'terminal:output': {
        // @ai-integration-point: terminal:output -> terminalStore.appendLine - Replace line-by-line writes with buffered batch flushing if the sandbox starts chunking output.
        appendTerminalLine(event.data.text, event.data.logType);
        break;
      }

      case 'terminal:exit': {
        appendTerminalLine(
          `[process exited with code ${event.data.exitCode} in ${event.data.durationMs}ms]`,
          event.data.exitCode === 0 ? 'success' : 'warn'
        );
        break;
      }

      case 'qa:report': {
        // QA defect report — update retry state with dimensional scores
        setQaRetryState({
          taskId: event.data.taskId,
          attempt: event.data.attempt,
          maxAttempts: 3,
          status: event.data.retryable ? 'retrying' : 'failed',
          failingCommand: event.data.failingCommand,
          defectSummary: event.data.summary,
          scores: event.data.scores ?? null,
          failingDimensions: event.data.failingDimensions ?? [],
        });

        addMessageFromServer({
          id: `qa-report-${event.seq}`,
          agent: 'qa',
          agentLabel: 'QA',
          content: event.data.summary,
          timestamp: event.timestamp,
        });

        // Phase 2: Persist QA evaluation to score history for the dashboard
        if (event.data.scores && Object.keys(event.data.scores).length > 0) {
          pushQaScore({
            taskId: event.data.taskId,
            attempt: event.data.attempt,
            status: 'failed',
            scores: event.data.scores,
            failingDimensions: event.data.failingDimensions ?? [],
            summary: event.data.summary,
            timestamp: event.timestamp,
          });
        }

        event.data.rawLogTail.forEach((line) => {
          appendTerminalLine(line, 'error');
        });
        break;
      }

      case 'qa:passed': {
        // QA passed — show passing scores briefly, then auto-clear
        if (event.data.scores && Object.keys(event.data.scores).length > 0) {
          setQaRetryState({
            taskId: event.data.taskId,
            attempt: event.data.attempt,
            maxAttempts: 3,
            status: 'passed',
            failingCommand: null,
            defectSummary: event.data.summary,
            scores: event.data.scores,
            failingDimensions: [],
          });
          // Auto-clear the success banner after 5 seconds
          setTimeout(() => clearQaRetryState(), 5000);

          // Phase 2: Persist QA pass to score history for the dashboard
          pushQaScore({
            taskId: event.data.taskId,
            attempt: event.data.attempt,
            status: 'passed',
            scores: event.data.scores,
            failingDimensions: [],
            summary: event.data.summary,
            timestamp: event.timestamp,
          });
        } else {
          clearQaRetryState();
        }

        addMessageFromServer({
          id: `qa-passed-${event.seq}`,
          agent: 'qa',
          agentLabel: 'QA',
          content: event.data.summary,
          timestamp: event.timestamp,
        });
        break;
      }
    }

    if (TERMINAL_EVENT_TYPES.has(event.type)) {
      setTerminalStreaming(false);
    }
  };

  // ── Reconnect Hydration ───────────────────────────────────────────────
  // When the WebSocket reconnects after a drop, Redis Pub/Sub events
  // fired during the gap are lost forever. This function fetches the
  // latest run snapshot from REST and pushes it into Zustand stores
  // to recover missed state transitions (tasks, agent updates, etc.).

  const hydrateFromSnapshot = async (runId: string) => {
    isHydratingRef.current = true;
    try {
      const res = await fetch(`${getApiBaseUrl()}/api/runs/${runId}/snapshot`);
      if (!res.ok) {
        console.warn(`[reconnect-hydrate] Snapshot fetch failed: ${res.status}`);
        return;
      }

      const snapshot = await res.json();

      // Hydrate tasks
      if (Array.isArray(snapshot.tasks)) {
        setTasks(snapshot.tasks);
      }

      // Hydrate run status + progress
      if (snapshot.status) {
        setRunStatus(snapshot.status);
        setState((current) => ({
          ...current,
          runStatus: snapshot.status,
          runPhase: snapshot.phase ?? current.runPhase,
          runProgress: snapshot.progress ?? current.runProgress,
        }));
      }

      if (typeof snapshot.progress === 'number') {
        setRunProgress(snapshot.progress);
      }

      console.info(
        `[reconnect-hydrate] Recovered state for run ${runId}: ` +
        `status=${snapshot.status}, tasks=${snapshot.tasks?.length ?? 0}`
      );
    } catch (err) {
      console.error('[reconnect-hydrate] Failed to hydrate from snapshot:', err);
    } finally {
      // AUDIT FIX: Release the gate and flush any WS events that arrived
      // during the snapshot fetch. These are NEWER than the snapshot.
      isHydratingRef.current = false;
      const queued = pendingEventsRef.current;
      pendingEventsRef.current = [];
      for (const event of queued) {
        dispatchServerEvent(event);
      }
      if (queued.length > 0) {
        console.info(`[reconnect-hydrate] Flushed ${queued.length} queued WS events`);
      }
    }
  };

  const connect = (wsUrl: string) => {
    clearReconnectTimer();
    shouldReconnectRef.current = true;
    lastWsUrlRef.current = wsUrl;

    socketRef.current?.close();

    const socket = new WebSocket(wsUrl);
    socketRef.current = socket;

    setState((current) => ({
      ...current,
      isConnecting: true,
      isConnected: false,
      error: null,
    }));

    socket.onopen = () => {
      setConnectionStatus('connected');

      // AUDIT FIX: Read from mutable refs, not the stale closure `state`.
      const wasReconnect = reconnectAttemptRef.current > 0;
      const currentRunId = runIdRef.current;

      reconnectAttemptRef.current = 0;

      setState((current) => ({
        ...current,
        isConnected: true,
        isConnecting: false,
        reconnectAttempt: 0,
        error: null,
      }));

      // ── Reconnect hydration ────────────────────────────────
      // When reconnecting after a drop, Redis Pub/Sub events were
      // lost. Fetch the latest snapshot from REST to recover state.
      if (wasReconnect && currentRunId) {
        hydrateFromSnapshot(currentRunId);
      }
    };

    socket.onmessage = (messageEvent) => {
      try {
        const parsed: unknown = JSON.parse(messageEvent.data);

        if (!isRunSocketServerEvent(parsed)) {
          throw new Error('Received an unknown websocket message shape.');
        }

        // AUDIT FIX: If snapshot hydration is in-flight, queue the
        // event instead of dispatching immediately. The hydration
        // callback will flush these AFTER applying the snapshot.
        if (isHydratingRef.current) {
          pendingEventsRef.current.push(parsed);
          return;
        }

        dispatchServerEvent(parsed);
      } catch (error) {
        const message = error instanceof Error ? error.message : 'Failed to parse websocket event.';
        setState((current) => ({
          ...current,
          error: message,
        }));
      }
    };

    socket.onerror = () => {
      setConnectionStatus('disconnected');
      setState((current) => ({
        ...current,
        error: 'The websocket connection encountered an error.',
      }));
    };

    socket.onclose = () => {
      socketRef.current = null;
      setConnectionStatus('disconnected');

      setState((current) => ({
        ...current,
        isConnected: false,
        isConnecting: false,
      }));

      if (!shouldReconnectRef.current || !lastWsUrlRef.current) {
        return;
      }

      setConnectionStatus('reconnecting');
      setState((current) => {
        const reconnectAttempt = current.reconnectAttempt + 1;
        // AUDIT FIX: Keep the mutable ref in sync so onopen reads fresh data.
        reconnectAttemptRef.current = reconnectAttempt;

        // ── Cap reconnect attempts to prevent infinite loop ──────
        if (reconnectAttempt > MAX_RECONNECT_ATTEMPTS) {
          shouldReconnectRef.current = false;
          setConnectionStatus('disconnected');
          return {
            ...current,
            reconnectAttempt,
            isConnecting: false,
            error: `Cannot connect to server after ${MAX_RECONNECT_ATTEMPTS} attempts. Please check your network and refresh the page.`,
          };
        }

        const reconnectDelay = Math.min(1000 * 2 ** (reconnectAttempt - 1), 10_000);

        reconnectTimerRef.current = window.setTimeout(() => {
          connect(lastWsUrlRef.current!);
        }, reconnectDelay);

        return {
          ...current,
          reconnectAttempt,
          isConnecting: true,
        };
      });
    };
  };

  const startRun = async (options: StartRunOptions) => {
    disconnect();

    setState((current) => ({
      ...current,
      runStatus: 'queued',
      runPhase: 'creating-run',
      runProgress: 0,
      error: null,
    }));

    const run = await createRunRequest(options);
    const absoluteWsUrl = getAbsoluteWebSocketUrl(run.wsUrl);

    setState((current) => ({
      ...current,
      runId: run.runId,
      runStatus: run.status,
      runPhase: 'connecting',
    }));
    // AUDIT FIX: Keep the mutable ref in sync for reconnect hydration.
    runIdRef.current = run.runId;

    connect(absoluteWsUrl);
    return { runId: run.runId, wsUrl: absoluteWsUrl };
  };

  const cancelRun = (reason = 'user_cancelled') => {
    const runId = state.runId;
    if (!runId) return false;

    return sendMessage({
      type: 'run:cancel',
      runId,
      data: { reason },
    });
  };

  const refreshWorkspace = (reason = 'manual_refresh') => {
    const runId = state.runId;
    if (!runId) return false;

    return sendMessage({
      type: 'workspace:refresh',
      runId,
      data: { reason },
    });
  };

  const interruptRun = (message: string) => {
    const runId = state.runId;
    if (!runId) return false;

    return sendMessage({
      type: 'user:interrupt',
      runId,
      data: { message },
    });
  };

  useEffect(() => {
    return () => {
      shouldReconnectRef.current = false;
      clearReconnectTimer();
      socketRef.current?.close();
      socketRef.current = null;
    };
  }, []);

  return {
    ...state,
    startRun,
    disconnect,
    sendMessage,
    cancelRun,
    refreshWorkspace,
    interruptRun,
  };
}

// @ai-integration-point: Header Wiring - Replace `useSimulation()` in `Header.tsx` with this hook once the backend stub is live and the stores gain snapshot hydration actions.
