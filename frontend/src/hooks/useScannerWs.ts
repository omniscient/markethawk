import { useEffect } from 'react';
import type { MutableRefObject } from 'react';
import type { QueryClient } from '@tanstack/react-query';
import { createScanRunWebSocket } from '../api/scanner';
import { ACTIVE_SCAN_LS_KEY, type LiveProgress } from './useScannerState';

interface WsStateSlice {
  wsRef: MutableRefObject<WebSocket | null>;
  setIsScanning: (v: boolean) => void;
  setActiveScan: (v: any) => void;
  setScanError: (v: string | null) => void;
  setLiveProgress: React.Dispatch<React.SetStateAction<LiveProgress>>;
}

export function useScannerWs(state: WsStateSlice, queryClient: QueryClient) {
  const finishScan = (
    finalStatus: 'completed' | 'failed' | 'cancelled',
    errorMsg?: string,
  ) => {
    state.setIsScanning(false);
    state.setActiveScan(null);
    localStorage.removeItem(ACTIVE_SCAN_LS_KEY);
    if (state.wsRef.current) {
      try { state.wsRef.current.close(); } catch { /* ignore */ }
      state.wsRef.current = null;
    }
    if (finalStatus === 'failed' && errorMsg) state.setScanError(errorMsg);
    else if (finalStatus === 'cancelled') state.setScanError('Scan cancelled');
    queryClient.invalidateQueries({ queryKey: ['scannerHistory'] });
    queryClient.invalidateQueries({ queryKey: ['scannerConfigs'] });
    queryClient.invalidateQueries({ queryKey: ['scannerResults'] });
    queryClient.invalidateQueries({ queryKey: ['scanStatusBlock'] });
  };

  const handleWsMessage = (msg: any) => {
    if (!msg || typeof msg !== 'object') return;
    state.setLiveProgress((prev: LiveProgress) => {
      const next = { ...prev };
      if (msg.type === 'snapshot' || msg.type === 'started') {
        next.total_days = msg.total_days ?? next.total_days;
        next.total_tickers = msg.total_tickers ?? msg.tickers ?? next.total_tickers;
        next.estimated_pairs = msg.estimated_pairs ?? (next.total_days * next.total_tickers);
      }
      if (msg.type === 'snapshot') {
        for (const k of [
          'day_index', 'total_days', 'evaluated', 'no_data', 'no_prior_close',
          'no_baseline', 'fired_pre', 'fired_post', 'errors', 'events_detected',
        ] as (keyof LiveProgress)[]) {
          if (msg[k] != null) (next[k] as any) = msg[k];
        }
      }
      if (msg.type === 'day_started') {
        next.day_index = msg.day_index ?? next.day_index;
        next.total_days = msg.total_days ?? next.total_days;
        next.last_day = msg.date ?? next.last_day;
      }
      if (msg.type === 'day_completed') {
        next.day_index = msg.day_index ?? next.day_index;
        next.last_day = msg.date ?? next.last_day;
        for (const k of [
          'evaluated', 'no_data', 'no_prior_close', 'no_baseline',
          'fired_pre', 'fired_post', 'errors', 'events_detected',
        ] as (keyof LiveProgress)[]) {
          if (msg[k] != null) (next[k] as any) = msg[k];
        }
      }
      return next;
    });
    if (msg.type === 'completed') finishScan('completed');
    else if (msg.type === 'failed') finishScan('failed', msg.error || 'Scan failed');
    else if (msg.type === 'cancelled') finishScan('cancelled');
  };

  const attachWebSocket = (taskId: string) => {
    if (state.wsRef.current) {
      try { state.wsRef.current.close(); } catch { /* ignore */ }
    }
    const ws = createScanRunWebSocket(taskId);
    if (!ws) return;
    state.wsRef.current = ws;
    ws.onmessage = (ev) => {
      try { handleWsMessage(JSON.parse(ev.data)); }
      catch (e) { console.error('[scanner WS] invalid payload', e); }
    };
    ws.onclose = () => { if (state.wsRef.current === ws) state.wsRef.current = null; };
    ws.onerror = (e) => { console.error('[scanner WS] error', e); };
  };

  useEffect(() => {
    return () => {
      if (state.wsRef.current) {
        try { state.wsRef.current.close(); } catch { /* ignore */ }
        state.wsRef.current = null;
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return { attachWebSocket };
}
