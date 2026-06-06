import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import type { SetStateAction } from 'react';
import { renderHook, act } from '@testing-library/react';
import { QueryClient } from '@tanstack/react-query';
import { MockWebSocket, installMockWebSocket } from '../test-utils/MockWebSocket';
import { useScannerWs } from './useScannerWs';
import { EMPTY_PROGRESS, type LiveProgress } from './useScannerState';

// Mock the createScanRunWebSocket factory to use our MockWebSocket
vi.mock('../api/scanner', () => ({
  createScanRunWebSocket: (taskId: string) => new MockWebSocket(`ws://localhost/api/scanner/ws/runs/${taskId}`),
}));

function makeStateSlice() {
  const wsRef = { current: null as WebSocket | null };
  const setIsScanning = vi.fn();
  const setActiveScan = vi.fn();
  const setScanError = vi.fn();
  let progress: LiveProgress = { ...EMPTY_PROGRESS };
  const setLiveProgress = vi.fn((updater: SetStateAction<LiveProgress>) => {
    if (typeof updater === 'function') progress = updater(progress);
    else progress = updater;
  });
  return { wsRef, setIsScanning, setActiveScan, setScanError, setLiveProgress, getProgress: () => progress };
}

describe('useScannerWs', () => {
  let restore: () => void;

  beforeEach(() => {
    restore = installMockWebSocket();
  });

  afterEach(() => {
    restore();
    vi.restoreAllMocks();
    localStorage.clear();
  });

  it('attachWebSocket creates a WS and assigns it to wsRef', () => {
    const state = makeStateSlice();
    const qc = new QueryClient();
    const { result } = renderHook(() => useScannerWs(state, qc));

    act(() => { result.current.attachWebSocket('task-1'); });

    expect(MockWebSocket.lastInstance).not.toBeNull();
    expect(state.wsRef.current).toBe(MockWebSocket.lastInstance);
  });

  it('handles "started" message — sets total_days and total_tickers', () => {
    const state = makeStateSlice();
    const qc = new QueryClient();
    const { result } = renderHook(() => useScannerWs(state, qc));

    act(() => { result.current.attachWebSocket('task-1'); });
    act(() => { MockWebSocket.lastInstance!.simulateMessage({ type: 'started', total_days: 10, tickers: 200 }); });

    expect(state.setLiveProgress).toHaveBeenCalled();
    const p = state.getProgress();
    expect(p.total_days).toBe(10);
    expect(p.total_tickers).toBe(200);
  });

  it('handles "day_started" message', () => {
    const state = makeStateSlice();
    const qc = new QueryClient();
    const { result } = renderHook(() => useScannerWs(state, qc));

    act(() => { result.current.attachWebSocket('task-1'); });
    act(() => { MockWebSocket.lastInstance!.simulateMessage({ type: 'day_started', day_index: 3, total_days: 10, date: '2025-01-07' }); });

    const p = state.getProgress();
    expect(p.day_index).toBe(3);
    expect(p.last_day).toBe('2025-01-07');
  });

  it('handles "day_completed" message — updates counters', () => {
    const state = makeStateSlice();
    const qc = new QueryClient();
    const { result } = renderHook(() => useScannerWs(state, qc));

    act(() => { result.current.attachWebSocket('task-1'); });
    act(() => {
      MockWebSocket.lastInstance!.simulateMessage({
        type: 'day_completed',
        day_index: 5,
        date: '2025-01-08',
        evaluated: 50,
        fired_pre: 3,
        events_detected: 7,
      });
    });

    const p = state.getProgress();
    expect(p.day_index).toBe(5);
    expect(p.evaluated).toBe(50);
    expect(p.fired_pre).toBe(3);
    expect(p.events_detected).toBe(7);
  });

  it('handles "completed" message — calls finishScan', () => {
    const state = makeStateSlice();
    const qc = new QueryClient();
    const { result } = renderHook(() => useScannerWs(state, qc));

    act(() => { result.current.attachWebSocket('task-1'); });
    act(() => { MockWebSocket.lastInstance!.simulateMessage({ type: 'completed' }); });

    expect(state.setIsScanning).toHaveBeenCalledWith(false);
    expect(state.setActiveScan).toHaveBeenCalledWith(null);
    expect(state.setScanError).not.toHaveBeenCalled();
  });

  it('handles "failed" message — calls finishScan with error', () => {
    const state = makeStateSlice();
    const qc = new QueryClient();
    const { result } = renderHook(() => useScannerWs(state, qc));

    act(() => { result.current.attachWebSocket('task-1'); });
    act(() => { MockWebSocket.lastInstance!.simulateMessage({ type: 'failed', error: 'boom' }); });

    expect(state.setIsScanning).toHaveBeenCalledWith(false);
    expect(state.setScanError).toHaveBeenCalledWith('boom');
  });

  it('handles "cancelled" message — sets error to "Scan cancelled"', () => {
    const state = makeStateSlice();
    const qc = new QueryClient();
    const { result } = renderHook(() => useScannerWs(state, qc));

    act(() => { result.current.attachWebSocket('task-1'); });
    act(() => { MockWebSocket.lastInstance!.simulateMessage({ type: 'cancelled' }); });

    expect(state.setScanError).toHaveBeenCalledWith('Scan cancelled');
  });

  it('clears wsRef on cleanup', () => {
    const state = makeStateSlice();
    const qc = new QueryClient();
    const { result, unmount } = renderHook(() => useScannerWs(state, qc));

    act(() => { result.current.attachWebSocket('task-1'); });
    expect(state.wsRef.current).not.toBeNull();

    unmount();
    expect(state.wsRef.current).toBeNull();
  });
});
