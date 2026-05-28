import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { MockWebSocket, installMockWebSocket } from '../test-utils/MockWebSocket';
import { useScanTask } from './useScanTask';

describe('useScanTask', () => {
  let restore: () => void;

  beforeEach(() => {
    restore = installMockWebSocket();
  });

  afterEach(() => {
    restore();
  });

  it('returns idle state when taskId is null', () => {
    const { result } = renderHook(() => useScanTask(null));
    expect(result.current.status).toBe('idle');
    expect(result.current.done).toBe(0);
    expect(result.current.error).toBeNull();
  });

  it('moves to "connecting" immediately when taskId is provided', () => {
    const { result } = renderHook(() => useScanTask('task-abc'));
    expect(result.current.status).toBe('connecting');
  });

  it('moves to "running" when WebSocket opens', () => {
    const { result } = renderHook(() => useScanTask('task-abc'));

    act(() => { MockWebSocket.lastInstance!.simulateOpen(); });

    expect(result.current.status).toBe('running');
  });

  it('updates progress on "progress" message', () => {
    const { result } = renderHook(() => useScanTask('task-abc'));

    act(() => { MockWebSocket.lastInstance!.simulateOpen(); });
    act(() => {
      MockWebSocket.lastInstance!.simulateMessage({ status: 'progress', done: 5, total: 20, day: '2025-01-07' });
    });

    expect(result.current.status).toBe('running');
    expect(result.current.done).toBe(5);
    expect(result.current.total).toBe(20);
    expect(result.current.currentDay).toBe('2025-01-07');
  });

  it('moves to "completed" on completed message and calls onComplete', () => {
    const onComplete = (() => { let called = false; return { fn: () => { called = true; }, wasCalled: () => called }; })();
    const { result } = renderHook(() => useScanTask('task-abc', onComplete.fn));

    act(() => { MockWebSocket.lastInstance!.simulateOpen(); });
    act(() => {
      MockWebSocket.lastInstance!.simulateMessage({ status: 'completed', events_detected: 42 });
    });

    expect(result.current.status).toBe('completed');
    expect(result.current.eventsDetected).toBe(42);
    expect(onComplete.wasCalled()).toBe(true);
  });

  it('moves to "failed" on failed message', () => {
    const { result } = renderHook(() => useScanTask('task-abc'));

    act(() => { MockWebSocket.lastInstance!.simulateOpen(); });
    act(() => {
      MockWebSocket.lastInstance!.simulateMessage({ status: 'failed', error: 'out of memory' });
    });

    expect(result.current.status).toBe('failed');
    expect(result.current.error).toBe('out of memory');
  });

  it('moves to "failed" on WS error event', () => {
    const { result } = renderHook(() => useScanTask('task-abc'));

    act(() => { MockWebSocket.lastInstance!.simulateOpen(); });
    act(() => { MockWebSocket.lastInstance!.simulateError(); });

    expect(result.current.status).toBe('failed');
    expect(result.current.error).toBe('WebSocket connection error');
  });

  it('moves to "failed" when connection closes unexpectedly while running', () => {
    const { result } = renderHook(() => useScanTask('task-abc'));

    act(() => { MockWebSocket.lastInstance!.simulateOpen(); });
    act(() => { MockWebSocket.lastInstance!.simulateClose(false); });

    expect(result.current.status).toBe('failed');
    expect(result.current.error).toBe('Connection closed unexpectedly');
  });

  it('resets to idle when taskId becomes null', () => {
    let taskId: string | null = 'task-abc';
    const { result, rerender } = renderHook(() => useScanTask(taskId));

    act(() => { MockWebSocket.lastInstance!.simulateOpen(); });
    taskId = null;
    rerender();

    expect(result.current.status).toBe('idle');
  });
});
