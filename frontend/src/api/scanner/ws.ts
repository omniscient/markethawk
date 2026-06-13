import { wsUrl } from '../client';

/** Open a WebSocket that streams progress for one running scan task. */
export const createScanRunWebSocket = (taskId: string): WebSocket | null => {
  try {
    return new WebSocket(wsUrl(`/scanner/ws/runs/${taskId}`));
  } catch (e) {
    console.error('[WS] Failed to open scanner run WS', e);
    return null;
  }
};

/** Create a raw WebSocket for real-time scanner updates. */
export const createScannerWebSocket = (): WebSocket | null => {
  try {
    const ws = new WebSocket(wsUrl('/ws/scanner'));
    ws.onopen = () => console.log('[WS] Scanner connected');
    ws.onclose = () => console.log('[WS] Scanner disconnected');
    ws.onerror = (e) => console.error('[WS] Scanner error', e);
    return ws;
  } catch (e) {
    console.error('[WS] Failed to create connection', e);
    return null;
  }
};
