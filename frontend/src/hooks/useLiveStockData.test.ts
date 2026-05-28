import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { MockWebSocket, installMockWebSocket } from '../test-utils/MockWebSocket';
import { useLiveStockData } from './useLiveStockData';

describe('useLiveStockData', () => {
  let restore: () => void;

  beforeEach(() => {
    restore = installMockWebSocket();
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    restore();
  });

  it('returns null liveData and isConnected=false initially', () => {
    const { result } = renderHook(() => useLiveStockData('AAPL'));
    expect(result.current.liveData).toBeNull();
    expect(result.current.isConnected).toBe(false);
  });

  it('does not open a WebSocket when symbol is undefined', () => {
    renderHook(() => useLiveStockData(undefined));
    // advance past the 50ms delay
    act(() => { vi.advanceTimersByTime(100); });
    expect(MockWebSocket.lastInstance).toBeNull();
  });

  it('opens a WebSocket after 50ms delay', () => {
    renderHook(() => useLiveStockData('TSLA'));
    expect(MockWebSocket.lastInstance).toBeNull();

    act(() => { vi.advanceTimersByTime(50); });

    expect(MockWebSocket.lastInstance).not.toBeNull();
    expect(MockWebSocket.lastInstance!.url).toContain('TSLA');
  });

  it('sets isConnected=true on WS open', () => {
    const { result } = renderHook(() => useLiveStockData('MSFT'));

    act(() => { vi.advanceTimersByTime(50); });
    act(() => { MockWebSocket.lastInstance!.simulateOpen(); });

    expect(result.current.isConnected).toBe(true);
  });

  it('updates liveData on message', () => {
    const { result } = renderHook(() => useLiveStockData('NVDA'));
    const bar = { ev: 'AM', sym: 'NVDA', v: 1000, o: 500, c: 505, h: 510, l: 498, vw: 502, s: 0, e: 60000 };

    act(() => { vi.advanceTimersByTime(50); });
    act(() => { MockWebSocket.lastInstance!.simulateOpen(); });
    act(() => { MockWebSocket.lastInstance!.simulateMessage(bar); });

    expect(result.current.liveData).toMatchObject({ sym: 'NVDA', c: 505 });
  });

  it('cleans up timers and socket on unmount', () => {
    const { unmount } = renderHook(() => useLiveStockData('GME'));

    // Unmount before the 50ms timer fires
    unmount();
    // Advancing time after unmount should not create a WS
    act(() => { vi.advanceTimersByTime(100); });

    expect(MockWebSocket.lastInstance).toBeNull();
  });
});
