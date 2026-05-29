import { useState, useEffect, useRef } from 'react';

export type ScanTaskStatus = 'idle' | 'connecting' | 'running' | 'completed' | 'failed';

export interface ScanTaskState {
  status: ScanTaskStatus;
  done: number;
  total: number;
  currentDay: string | null;
  eventsDetected: number;
  error: string | null;
}

const INITIAL_STATE: ScanTaskState = {
  status: 'idle',
  done: 0,
  total: 0,
  currentDay: null,
  eventsDetected: 0,
  error: null,
};

export const useScanTask = (
  taskId: string | null,
  onComplete?: () => void,
): ScanTaskState => {
  const [state, setState] = useState<ScanTaskState>(INITIAL_STATE);
  const wsRef = useRef<WebSocket | null>(null);
  const onCompleteRef = useRef(onComplete);
  // eslint-disable-next-line react-hooks/refs -- writing to ref outside of effect is intentional ref sync pattern
  onCompleteRef.current = onComplete;

  useEffect(() => {
    if (!taskId) {
      setState(INITIAL_STATE);
      return;
    }

    setState({ ...INITIAL_STATE, status: 'connecting' });

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/api/live/ws/scan-task/${taskId}`;

    let isMounted = true;

    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;

    ws.onopen = () => {
      if (!isMounted) { ws.close(); return; }
      setState(prev => ({ ...prev, status: 'running' }));
    };

    ws.onmessage = (event) => {
      if (!isMounted) return;
      try {
        const msg = JSON.parse(event.data);
        if (msg.status === 'progress') {
          setState(prev => ({
            ...prev,
            status: 'running',
            done: msg.done,
            total: msg.total,
            currentDay: msg.day,
          }));
        } else if (msg.status === 'completed') {
          setState(prev => ({
            ...prev,
            status: 'completed',
            eventsDetected: msg.events_detected,
          }));
          onCompleteRef.current?.();
          ws.close();
        } else if (msg.status === 'failed') {
          setState(prev => ({ ...prev, status: 'failed', error: msg.error }));
          ws.close();
        }
      } catch {
        // ignore malformed messages
      }
    };

    ws.onerror = () => {
      if (!isMounted) return;
      setState(prev => ({ ...prev, status: 'failed', error: 'WebSocket connection error' }));
    };

    ws.onclose = () => {
      if (!isMounted) return;
      setState(prev => {
        if (prev.status === 'running' || prev.status === 'connecting') {
          return { ...prev, status: 'failed', error: 'Connection closed unexpectedly' };
        }
        return prev;
      });
    };

    return () => {
      isMounted = false;
      ws.onopen = null;
      ws.onmessage = null;
      ws.onerror = null;
      ws.onclose = null;
      if (ws.readyState === WebSocket.OPEN) ws.close();
      wsRef.current = null;
    };
  }, [taskId]);

  return state;
};
