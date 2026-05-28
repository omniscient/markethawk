import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import {
  useScannerState,
  loadPersistedSelection,
  lastCompletedWeekday,
  SELECTION_LS_KEY,
  EMPTY_PROGRESS,
} from './useScannerState';

describe('loadPersistedSelection', () => {
  beforeEach(() => localStorage.clear());

  it('returns empty object when nothing stored', () => {
    expect(loadPersistedSelection()).toEqual({});
  });

  it('returns parsed object when valid JSON is stored', () => {
    localStorage.setItem(SELECTION_LS_KEY, JSON.stringify({ scanner_type: 'pre_market', universe_id: 3 }));
    expect(loadPersistedSelection()).toEqual({ scanner_type: 'pre_market', universe_id: 3 });
  });

  it('returns empty object for invalid JSON', () => {
    localStorage.setItem(SELECTION_LS_KEY, 'not-json');
    expect(loadPersistedSelection()).toEqual({});
  });

  it('returns empty object when stored value is not an object', () => {
    localStorage.setItem(SELECTION_LS_KEY, JSON.stringify(42));
    expect(loadPersistedSelection()).toEqual({});
  });
});

describe('lastCompletedWeekday', () => {
  it('returns a YYYY-MM-DD string', () => {
    const result = lastCompletedWeekday();
    expect(result).toMatch(/^\d{4}-\d{2}-\d{2}$/);
  });

  it('never returns a Saturday or Sunday', () => {
    // Run 14 times to cover a full 2-week span regardless of current day
    for (let i = 0; i < 14; i++) {
      const d = new Date(lastCompletedWeekday());
      expect(d.getDay()).not.toBe(0); // Sunday
      expect(d.getDay()).not.toBe(6); // Saturday
    }
  });

  it('returns yesterday when today is Tuesday', () => {
    // Freeze at a known Tuesday: 2025-01-07 (Tuesday)
    const tuesday = new Date('2025-01-07T12:00:00Z');
    vi.setSystemTime(tuesday);
    try {
      expect(lastCompletedWeekday()).toBe('2025-01-06');
    } finally {
      vi.useRealTimers();
    }
  });

  it('returns Friday when today is Monday', () => {
    // 2025-01-06 is Monday → last weekday is Friday 2025-01-03
    const monday = new Date('2025-01-06T12:00:00Z');
    vi.setSystemTime(monday);
    try {
      expect(lastCompletedWeekday()).toBe('2025-01-03');
    } finally {
      vi.useRealTimers();
    }
  });
});

describe('useScannerState', () => {
  beforeEach(() => localStorage.clear());
  afterEach(() => localStorage.clear());

  it('initialises with default values when nothing in localStorage', () => {
    const { result } = renderHook(() => useScannerState());
    expect(result.current.isScanning).toBe(false);
    expect(result.current.selectedConfig).toBe('pre_market_volume_spike');
    expect(result.current.selectedUniverse).toBeNull();
    expect(result.current.scanResults).toBeNull();
    expect(result.current.scanError).toBeNull();
    expect(result.current.sortBy).toBe('signal_quality_score');
    expect(result.current.sortOrder).toBe('desc');
    expect(result.current.activeScan).toBeNull();
    expect(result.current.liveProgress).toEqual(EMPTY_PROGRESS);
  });

  it('hydrates selectedConfig and selectedUniverse from localStorage', () => {
    localStorage.setItem(SELECTION_LS_KEY, JSON.stringify({ scanner_type: 'post_market', universe_id: 7 }));
    const { result } = renderHook(() => useScannerState());
    expect(result.current.selectedConfig).toBe('post_market');
    expect(result.current.selectedUniverse).toBe(7);
  });

  it('persists selection changes to localStorage', () => {
    const { result } = renderHook(() => useScannerState());
    act(() => { result.current.setSelectedConfig('post_market'); });
    const stored = JSON.parse(localStorage.getItem(SELECTION_LS_KEY)!);
    expect(stored.scanner_type).toBe('post_market');
  });

  it('persists universe_id change to localStorage', () => {
    const { result } = renderHook(() => useScannerState());
    act(() => { result.current.setSelectedUniverse(99); });
    const stored = JSON.parse(localStorage.getItem(SELECTION_LS_KEY)!);
    expect(stored.universe_id).toBe(99);
  });

  it('setIsScanning updates isScanning', () => {
    const { result } = renderHook(() => useScannerState());
    act(() => { result.current.setIsScanning(true); });
    expect(result.current.isScanning).toBe(true);
  });

  it('setScanError updates scanError', () => {
    const { result } = renderHook(() => useScannerState());
    act(() => { result.current.setScanError('something went wrong'); });
    expect(result.current.scanError).toBe('something went wrong');
  });
});
