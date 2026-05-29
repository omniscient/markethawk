import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { MockWebSocket, installMockWebSocket } from '../test-utils/MockWebSocket';
import { useWatchlistLive } from './useWatchlistLive';

describe('useWatchlistLive', () => {
  let restore: () => void;

  beforeEach(() => {
    restore = installMockWebSocket();
  });

  afterEach(() => {
    restore();
  });

  it('starts with empty liveData and connected=false', () => {
    const { result } = renderHook(() => useWatchlistLive());
    expect(result.current.liveData).toEqual({});
    expect(result.current.connected).toBe(false);
  });

  it('sets connected=true when WS opens', () => {
    const { result } = renderHook(() => useWatchlistLive());

    act(() => { MockWebSocket.lastInstance!.simulateOpen(); });

    expect(result.current.connected).toBe(true);
  });

  it('updates liveData on "quote" message', () => {
    const { result } = renderHook(() => useWatchlistLive());

    act(() => { MockWebSocket.lastInstance!.simulateOpen(); });
    act(() => {
      MockWebSocket.lastInstance!.simulateMessage({ type: 'quote', symbol: 'AAPL', last: 195.5, bid: 195.4, ask: 195.6, time: 1000 });
    });

    expect(result.current.liveData['AAPL'].price).toBe(195.5);
  });

  it('updates liveData on "tick" message', () => {
    const { result } = renderHook(() => useWatchlistLive());

    act(() => { MockWebSocket.lastInstance!.simulateOpen(); });
    act(() => {
      MockWebSocket.lastInstance!.simulateMessage({ type: 'tick', symbol: 'TSLA', close: 250, open: 248, high: 252, low: 247, volume: 5000, wap: 249, time: 2000 });
    });

    expect(result.current.liveData['TSLA']).toBeDefined();
  });

  it('updates price and session on "minute_bar" message', () => {
    const { result } = renderHook(() => useWatchlistLive());

    act(() => { MockWebSocket.lastInstance!.simulateOpen(); });
    act(() => {
      MockWebSocket.lastInstance!.simulateMessage({
        type: 'minute_bar', symbol: 'NVDA', close: 800, price_change_pct: 1.2,
        session: 'pre', session_volume: 10000, minute_ts: '2025-01-07T09:00:00Z',
        open: 795, high: 802, low: 793, volume: 500, vwap: 798,
        minutes_elapsed: 30, prior_close: 790,
      });
    });

    const nvda = result.current.liveData['NVDA'];
    expect(nvda.price).toBe(800);
    expect(nvda.priceChangePct).toBe(1.2);
    expect(nvda.session).toBe('pre');
    expect(nvda.sessionVolume).toBe(10000);
  });

  it('sets alert on "alert" message', () => {
    const { result } = renderHook(() => useWatchlistLive());

    act(() => { MockWebSocket.lastInstance!.simulateOpen(); });
    act(() => {
      MockWebSocket.lastInstance!.simulateMessage({
        type: 'alert', symbol: 'GME', scanner_type: 'pre_market', summary: 'Volume spike',
        severity: 'high', indicators: {}, timestamp: '2025-01-07T09:00:00Z',
      });
    });

    const gme = result.current.liveData['GME'];
    expect(gme.alert).not.toBeNull();
    expect(gme.alert!.summary).toBe('Volume spike');
  });

  it('ignores unknown message types', () => {
    const { result } = renderHook(() => useWatchlistLive());

    act(() => { MockWebSocket.lastInstance!.simulateOpen(); });
    act(() => {
      MockWebSocket.lastInstance!.simulateMessage({ type: 'unknown_type', symbol: 'X' });
    });

    expect(result.current.liveData).toEqual({});
  });

  it('sets connected=false on close and does not throw', () => {
    const { result } = renderHook(() => useWatchlistLive());

    act(() => { MockWebSocket.lastInstance!.simulateOpen(); });
    expect(result.current.connected).toBe(true);

    act(() => { MockWebSocket.lastInstance!.simulateClose(); });

    expect(result.current.connected).toBe(false);
  });
});
