import type { Job } from './types';

export type WSMessage =
  | { type: 'jobs:list'; jobs: Job[] }
  | { type: 'job:update'; job: Job }
  | { type: 'job:delete'; id: string };

type Listener = (msg: WSMessage) => void;

let ws: WebSocket | null = null;
let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
let currentPodUrl: string | null = null;
const listeners = new Set<Listener>();

function getWsUrl() {
  // If a pod URL is set, connect directly to the pod's WebSocket
  if (currentPodUrl) {
    const url = new URL(currentPodUrl);
    const proto = url.protocol === 'https:' ? 'wss:' : 'ws:';
    return `${proto}//${url.host}/ws`;
  }
  // Local dev: use page host (proxied by Vite)
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${proto}//${location.host}/ws`;
}

export function connect(podUrl?: string | null) {
  // If pod URL changed, close existing connection
  if (podUrl !== undefined && podUrl !== currentPodUrl) {
    currentPodUrl = podUrl;
    if (ws) {
      ws.onclose = null; // prevent reconnect to old URL
      ws.close();
      ws = null;
    }
  }

  if (ws && (ws.readyState === WebSocket.CONNECTING || ws.readyState === WebSocket.OPEN)) return;

  ws = new WebSocket(getWsUrl());

  ws.onmessage = (e) => {
    try {
      const msg: WSMessage = JSON.parse(e.data);
      listeners.forEach((l) => l(msg));
    } catch {
      // ignore malformed messages
    }
  };

  ws.onclose = () => {
    ws = null;
    if (!reconnectTimer) {
      reconnectTimer = setTimeout(() => {
        reconnectTimer = null;
        connect();
      }, 2000);
    }
  };

  ws.onerror = () => {
    // onclose will fire after onerror, triggering reconnect
  };
}

export function disconnect() {
  if (reconnectTimer) {
    clearTimeout(reconnectTimer);
    reconnectTimer = null;
  }
  if (ws) {
    ws.onclose = null;
    ws.close();
    ws = null;
  }
}

export function subscribe(listener: Listener): () => void {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
}
