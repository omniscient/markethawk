# Frontend Vitest Setup and Critical-Path Tests

**Date:** 2026-05-28  
**Issue:** #89  
**Branch:** `refine/issue-89-install-vitest-and-add-frontend-tests-fo`  
**Status:** Draft

---

## Goal

Install Vitest + React Testing Library + jsdom, write tests for the 6 highest-priority custom hooks and `GlobalErrorToast`, enforce a 20% coverage threshold on those 7 files, and add a parallel `frontend-test` CI job that blocks PRs on failure.

---

## Architecture

No structural changes. Test files are colocated next to their source files (e.g. `src/hooks/useScannerState.test.ts`). A shared `MockWebSocket` utility lives in `src/test-utils/MockWebSocket.ts`. A `vitest.config.ts` at the root of `frontend/` drives the test runner and coverage; `src/test-setup.ts` imports jest-dom matchers once.

---

## Tech Stack

| Addition | Version | Purpose |
|----------|---------|---------|
| `vitest` | `^3` | Vite-native test runner |
| `@vitest/coverage-v8` | `^3` | V8 coverage provider |
| `@testing-library/react` | `^16` | React 19-compatible render + queries |
| `@testing-library/jest-dom` | `^6` | DOM matchers (`.toBeInTheDocument()`, etc.) |
| `@testing-library/user-event` | `^14` | Realistic pointer + keyboard simulation |
| `jsdom` | `^26` | DOM environment for Vitest |

---

## File Structure

| File | Status | Purpose |
|------|--------|---------|
| `frontend/vitest.config.ts` | New | Vitest config + coverage thresholds |
| `frontend/src/test-setup.ts` | New | Global jest-dom matcher import |
| `frontend/src/test-utils/MockWebSocket.ts` | New | Shared WebSocket mock for hook tests |
| `frontend/src/hooks/useScannerState.test.ts` | New | State + localStorage tests |
| `frontend/src/hooks/useScannerWs.test.ts` | New | WS message handler tests |
| `frontend/src/hooks/useScanTask.test.ts` | New | State-machine tests |
| `frontend/src/hooks/useWatchlistLive.test.ts` | New | Watchlist streaming tests |
| `frontend/src/hooks/useLiveStockData.test.ts` | New | Single-symbol streaming tests |
| `frontend/src/hooks/useScorecard.test.ts` | New | React Query composition tests |
| `frontend/src/components/ui/GlobalErrorToast.test.tsx` | New | DOM event + timer tests |
| `frontend/package.json` | Modified | Add devDeps + test scripts |
| `.github/workflows/ci.yml` | Modified | Add `frontend-test` parallel job |

---

## Tasks

---

### Task 1 — Install packages and scaffold test infrastructure

**Files:** `frontend/package.json`, `frontend/vitest.config.ts`, `frontend/src/test-setup.ts`

#### Step 1.1 — Install dev dependencies

```bash
cd frontend
npm install --save-dev vitest @vitest/coverage-v8 "@testing-library/react@^16" "@testing-library/jest-dom" "@testing-library/user-event" jsdom
```

Expected: packages appear in `devDependencies` in `package.json`; `package-lock.json` updated.

#### Step 1.2 — Add test scripts to `package.json`

In the `"scripts"` block, add after `"lint"`:

```json
"test": "vitest run",
"test:coverage": "vitest run --coverage"
```

#### Step 1.3 — Create `frontend/vitest.config.ts`

```typescript
import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test-setup.ts'],
  },
  coverage: {
    provider: 'v8',
    include: [
      'src/hooks/**/*.{ts,tsx}',
      'src/components/ui/GlobalErrorToast.tsx',
    ],
    thresholds: {
      lines: 20,
      functions: 20,
      branches: 20,
      statements: 20,
    },
    reporter: ['text', 'xml'],
    reportsDirectory: 'coverage',
  },
});
```

#### Step 1.4 — Create `frontend/src/test-setup.ts`

```typescript
import '@testing-library/jest-dom';
```

#### Step 1.5 — Verify scaffold

```bash
cd frontend && npm run test
```

Expected output (no test files yet):
```
No test files found, exiting with code 0
```

#### Step 1.6 — Commit

```bash
git add frontend/package.json frontend/package-lock.json frontend/vitest.config.ts frontend/src/test-setup.ts
git commit -m "feat(frontend): install Vitest + RTL + jsdom and scaffold test config"
```

---

### Task 2 — MockWebSocket utility

**Files:** `frontend/src/test-utils/MockWebSocket.ts`

#### Step 2.1 — Create `frontend/src/test-utils/MockWebSocket.ts`

```typescript
export let lastMockWs: MockWebSocket | null = null;

export function resetMockWs() {
  lastMockWs = null;
}

export class MockWebSocket {
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSED = 3;

  readyState = MockWebSocket.OPEN;
  onopen: ((e: Event) => void) | null = null;
  onmessage: ((e: MessageEvent) => void) | null = null;
  onclose: ((e: CloseEvent) => void) | null = null;
  onerror: ((e: Event) => void) | null = null;

  constructor(public url: string) {
    lastMockWs = this;
    queueMicrotask(() => this.onopen?.(new Event('open')));
  }

  send(_data: string) {}

  close() {
    this.readyState = MockWebSocket.CLOSED;
    this.onclose?.(new CloseEvent('close'));
  }

  simulateMessage(data: object) {
    this.onmessage?.(
      new MessageEvent('message', { data: JSON.stringify(data) }),
    );
  }

  simulateError() {
    this.onerror?.(new Event('error'));
  }
}
```

Key design decisions:
- `readyState` starts at `OPEN` (1) so hooks that guard on `!== CONNECTING` call `close()` correctly on cleanup.
- `CONNECTING = 0` matches the real WebSocket constant used in source guards (`useLiveStockData`, `useWatchlistLive`).
- `simulateMessage` JSON-stringifies so `JSON.parse(ev.data)` in `onmessage` handlers works correctly.
- `lastMockWs` captures the most recently created instance; `resetMockWs()` clears it between tests.

#### Step 2.2 — Type-check

```bash
cd frontend && npx tsc --noEmit
```

Expected: 0 errors.

#### Step 2.3 — Commit

```bash
git add frontend/src/test-utils/MockWebSocket.ts
git commit -m "test(frontend): add shared MockWebSocket test utility"
```

---

### Task 3 — `useScannerState` tests

**Files:** `frontend/src/hooks/useScannerState.test.ts`

#### Step 3.1 — Write `frontend/src/hooks/useScannerState.test.ts`

```typescript
import { renderHook, act } from '@testing-library/react';
import {
  useScannerState,
  loadPersistedSelection,
  lastCompletedWeekday,
  SELECTION_LS_KEY,
} from './useScannerState';

beforeEach(() => {
  localStorage.clear();
});

describe('useScannerState — initial defaults', () => {
  it('defaults selectedConfig to pre_market_volume_spike', () => {
    const { result } = renderHook(() => useScannerState());
    expect(result.current.selectedConfig).toBe('pre_market_volume_spike');
  });

  it('defaults selectedUniverse to null', () => {
    const { result } = renderHook(() => useScannerState());
    expect(result.current.selectedUniverse).toBeNull();
  });
});

describe('useScannerState — localStorage hydration', () => {
  it('reads scanner_type from localStorage on mount', () => {
    localStorage.setItem(
      SELECTION_LS_KEY,
      JSON.stringify({ scanner_type: 'post_market_volume_spike' }),
    );
    const { result } = renderHook(() => useScannerState());
    expect(result.current.selectedConfig).toBe('post_market_volume_spike');
  });

  it('reads universe_id from localStorage on mount', () => {
    localStorage.setItem(
      SELECTION_LS_KEY,
      JSON.stringify({ scanner_type: 'pre_market_volume_spike', universe_id: 7 }),
    );
    const { result } = renderHook(() => useScannerState());
    expect(result.current.selectedUniverse).toBe(7);
  });
});

describe('useScannerState — localStorage persistence', () => {
  it('writes scanner_type to localStorage when selectedConfig changes', () => {
    const { result } = renderHook(() => useScannerState());
    act(() => {
      result.current.setSelectedConfig('post_market_volume_spike');
    });
    const stored = JSON.parse(localStorage.getItem(SELECTION_LS_KEY)!);
    expect(stored.scanner_type).toBe('post_market_volume_spike');
  });

  it('writes universe_id to localStorage when selectedUniverse changes', () => {
    const { result } = renderHook(() => useScannerState());
    act(() => {
      result.current.setSelectedUniverse(42);
    });
    const stored = JSON.parse(localStorage.getItem(SELECTION_LS_KEY)!);
    expect(stored.universe_id).toBe(42);
  });
});

describe('lastCompletedWeekday', () => {
  it('returns an ISO date string (YYYY-MM-DD)', () => {
    expect(lastCompletedWeekday()).toMatch(/^\d{4}-\d{2}-\d{2}$/);
  });

  it('returns a weekday (Monday–Friday)', () => {
    const day = new Date(lastCompletedWeekday()).getDay();
    expect([1, 2, 3, 4, 5]).toContain(day);
  });
});

describe('loadPersistedSelection', () => {
  it('returns {} when localStorage is empty', () => {
    expect(loadPersistedSelection()).toEqual({});
  });

  it('returns {} on malformed JSON', () => {
    localStorage.setItem(SELECTION_LS_KEY, 'not-valid-json{{{');
    expect(loadPersistedSelection()).toEqual({});
  });

  it('returns {} when stored value is not an object', () => {
    localStorage.setItem(SELECTION_LS_KEY, '"just-a-string"');
    expect(loadPersistedSelection()).toEqual({});
  });
});
```

#### Step 3.2 — Run and verify

```bash
cd frontend && npm run test -- src/hooks/useScannerState.test.ts
```

Expected: 11 tests pass, 0 failures.

#### Step 3.3 — Commit

```bash
git add frontend/src/hooks/useScannerState.test.ts
git commit -m "test(frontend): add useScannerState tests for defaults, hydration, and persistence"
```

---

### Task 4 — `useScannerWs` tests

**Files:** `frontend/src/hooks/useScannerWs.test.ts`

The hook receives a state slice and a QueryClient. `handleWsMessage` is an internal function — it is exercised indirectly by calling `attachWebSocket` (with a mocked `createScanRunWebSocket`) and then simulating messages on the returned mock WS. `setLiveProgress` is called with a functional updater; tests capture that updater and apply it against `EMPTY_PROGRESS` to assert the resulting state.

#### Step 4.1 — Write `frontend/src/hooks/useScannerWs.test.ts`

```typescript
import { renderHook, act } from '@testing-library/react';
import { QueryClient } from '@tanstack/react-query';
import { useScannerWs } from './useScannerWs';
import { EMPTY_PROGRESS, type LiveProgress } from './useScannerState';
import { MockWebSocket, resetMockWs } from '../test-utils/MockWebSocket';
import * as scannerApi from '../api/scanner';

vi.mock('../api/scanner', () => ({
  createScanRunWebSocket: vi.fn(),
}));

const mockedCreate = vi.mocked(scannerApi.createScanRunWebSocket);

function applyLastUpdater(
  mockFn: ReturnType<typeof vi.fn>,
  base: LiveProgress = EMPTY_PROGRESS,
): LiveProgress {
  const calls = mockFn.mock.calls;
  const updater = calls[calls.length - 1][0] as (prev: LiveProgress) => LiveProgress;
  return updater(base);
}

describe('useScannerWs', () => {
  let mockState: {
    wsRef: { current: WebSocket | null };
    setIsScanning: ReturnType<typeof vi.fn>;
    setActiveScan: ReturnType<typeof vi.fn>;
    setScanError: ReturnType<typeof vi.fn>;
    setLiveProgress: ReturnType<typeof vi.fn>;
  };
  let queryClient: QueryClient;
  let ws: MockWebSocket;

  beforeEach(() => {
    resetMockWs();
    ws = new MockWebSocket('/ws/test');
    mockedCreate.mockReturnValue(ws as unknown as WebSocket);
    mockState = {
      wsRef: { current: null },
      setIsScanning: vi.fn(),
      setActiveScan: vi.fn(),
      setScanError: vi.fn(),
      setLiveProgress: vi.fn(),
    };
    queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  });

  function renderAndAttach() {
    const hookResult = renderHook(() => useScannerWs(mockState, queryClient));
    act(() => {
      hookResult.result.current.attachWebSocket('task-1');
    });
    return hookResult;
  }

  it('attachWebSocket wires onmessage, onclose, and onerror handlers on the WS', () => {
    renderAndAttach();
    expect(ws.onmessage).toBeTruthy();
    expect(ws.onclose).toBeTruthy();
    expect(ws.onerror).toBeTruthy();
  });

  it('snapshot message updates total_days, total_tickers, evaluated, and day_index', () => {
    renderAndAttach();
    act(() => {
      ws.simulateMessage({
        type: 'snapshot',
        total_days: 10,
        total_tickers: 500,
        evaluated: 250,
        day_index: 5,
      });
    });
    const next = applyLastUpdater(mockState.setLiveProgress);
    expect(next.total_days).toBe(10);
    expect(next.total_tickers).toBe(500);
    expect(next.evaluated).toBe(250);
    expect(next.day_index).toBe(5);
  });

  it('started message updates total_days and total_tickers (via tickers field)', () => {
    renderAndAttach();
    act(() => {
      ws.simulateMessage({ type: 'started', total_days: 20, tickers: 300 });
    });
    const next = applyLastUpdater(mockState.setLiveProgress);
    expect(next.total_days).toBe(20);
    expect(next.total_tickers).toBe(300);
    expect(next.estimated_pairs).toBe(20 * 300);
  });

  it('day_started message updates day_index, total_days, and last_day', () => {
    renderAndAttach();
    act(() => {
      ws.simulateMessage({
        type: 'day_started',
        day_index: 3,
        total_days: 10,
        date: '2024-01-15',
      });
    });
    const next = applyLastUpdater(mockState.setLiveProgress);
    expect(next.day_index).toBe(3);
    expect(next.total_days).toBe(10);
    expect(next.last_day).toBe('2024-01-15');
  });

  it('day_completed message updates day_index, last_day, and counter fields', () => {
    renderAndAttach();
    act(() => {
      ws.simulateMessage({
        type: 'day_completed',
        day_index: 2,
        date: '2024-01-16',
        evaluated: 80,
        fired_pre: 4,
        errors: 1,
        events_detected: 4,
      });
    });
    const next = applyLastUpdater(mockState.setLiveProgress);
    expect(next.day_index).toBe(2);
    expect(next.last_day).toBe('2024-01-16');
    expect(next.evaluated).toBe(80);
    expect(next.fired_pre).toBe(4);
    expect(next.errors).toBe(1);
  });

  it('completed message calls finishScan: setIsScanning false, setActiveScan null, invalidates queries', () => {
    renderAndAttach();
    const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries');
    act(() => {
      ws.simulateMessage({ type: 'completed' });
    });
    expect(mockState.setIsScanning).toHaveBeenCalledWith(false);
    expect(mockState.setActiveScan).toHaveBeenCalledWith(null);
    expect(invalidateSpy).toHaveBeenCalledWith(
      expect.objectContaining({ queryKey: ['scannerHistory'] }),
    );
  });

  it('failed message calls finishScan with the error message', () => {
    renderAndAttach();
    act(() => {
      ws.simulateMessage({ type: 'failed', error: 'Out of memory' });
    });
    expect(mockState.setIsScanning).toHaveBeenCalledWith(false);
    expect(mockState.setScanError).toHaveBeenCalledWith('Out of memory');
  });

  it('cancelled message sets scanError to "Scan cancelled"', () => {
    renderAndAttach();
    act(() => {
      ws.simulateMessage({ type: 'cancelled' });
    });
    expect(mockState.setScanError).toHaveBeenCalledWith('Scan cancelled');
  });

  it('cleanup on unmount closes the WebSocket', () => {
    const { unmount } = renderAndAttach();
    unmount();
    expect(ws.readyState).toBe(MockWebSocket.CLOSED);
  });
});
```

#### Step 4.2 — Run and verify

```bash
cd frontend && npm run test -- src/hooks/useScannerWs.test.ts
```

Expected: 9 tests pass, 0 failures.

#### Step 4.3 — Commit

```bash
git add frontend/src/hooks/useScannerWs.test.ts
git commit -m "test(frontend): add useScannerWs tests for message handling and lifecycle"
```

---

### Task 5 — `useScanTask` tests

**Files:** `frontend/src/hooks/useScanTask.test.ts`

This hook constructs the WebSocket URL itself using `window.location.protocol/host`. Stubbing `window.WebSocket` with `MockWebSocket` intercepts `new WebSocket(wsUrl)`. The mock's `queueMicrotask` in the constructor fires `onopen` asynchronously — flush with `await act(async () => {})`.

#### Step 5.1 — Write `frontend/src/hooks/useScanTask.test.ts`

```typescript
import { renderHook, act } from '@testing-library/react';
import { useScanTask } from './useScanTask';
import { MockWebSocket, resetMockWs, lastMockWs } from '../test-utils/MockWebSocket';

beforeEach(() => {
  resetMockWs();
  vi.stubGlobal('WebSocket', MockWebSocket);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('useScanTask — idle', () => {
  it('stays idle and opens no WS when taskId is null', () => {
    const { result } = renderHook(() => useScanTask(null));
    expect(result.current.status).toBe('idle');
    expect(lastMockWs).toBeNull();
  });
});

describe('useScanTask — connecting → running', () => {
  it('transitions to connecting immediately when taskId is provided', () => {
    const { result } = renderHook(() => useScanTask('task-1'));
    expect(result.current.status).toBe('connecting');
    expect(lastMockWs).not.toBeNull();
  });

  it('transitions to running when the WebSocket opens', async () => {
    const { result } = renderHook(() => useScanTask('task-1'));
    await act(async () => {}); // flush queueMicrotask → onopen fires
    expect(result.current.status).toBe('running');
  });
});

describe('useScanTask — message handling', () => {
  async function openHook(taskId = 'task-1') {
    const hookResult = renderHook(() => useScanTask(taskId));
    await act(async () => {});
    return hookResult;
  }

  it('progress message updates done, total, and currentDay', async () => {
    const { result } = await openHook();
    act(() => {
      lastMockWs!.simulateMessage({ status: 'progress', done: 5, total: 20, day: '2024-01-15' });
    });
    expect(result.current.done).toBe(5);
    expect(result.current.total).toBe(20);
    expect(result.current.currentDay).toBe('2024-01-15');
  });

  it('completed message transitions to completed and calls onComplete callback', async () => {
    const onComplete = vi.fn();
    const { result } = renderHook(() => useScanTask('task-1', onComplete));
    await act(async () => {});
    act(() => {
      lastMockWs!.simulateMessage({ status: 'completed', events_detected: 7 });
    });
    expect(result.current.status).toBe('completed');
    expect(result.current.eventsDetected).toBe(7);
    expect(onComplete).toHaveBeenCalledOnce();
  });

  it('failed message transitions to failed with the error string', async () => {
    const { result } = await openHook();
    act(() => {
      lastMockWs!.simulateMessage({ status: 'failed', error: 'Timeout' });
    });
    expect(result.current.status).toBe('failed');
    expect(result.current.error).toBe('Timeout');
  });
});

describe('useScanTask — error and disconnect paths', () => {
  it('WS error event transitions to failed with the standard message', async () => {
    const { result } = renderHook(() => useScanTask('task-1'));
    await act(async () => {});
    act(() => {
      lastMockWs!.simulateError();
    });
    expect(result.current.status).toBe('failed');
    expect(result.current.error).toBe('WebSocket connection error');
  });

  it('unexpected WS close while running transitions to failed', async () => {
    const { result } = renderHook(() => useScanTask('task-1'));
    await act(async () => {});
    expect(result.current.status).toBe('running');
    act(() => {
      lastMockWs!.close();
    });
    expect(result.current.status).toBe('failed');
    expect(result.current.error).toBe('Connection closed unexpectedly');
  });
});

describe('useScanTask — cleanup', () => {
  it('nulls all handlers and closes the WS on unmount', async () => {
    const { unmount } = renderHook(() => useScanTask('task-1'));
    await act(async () => {});
    const ws = lastMockWs!;
    unmount();
    expect(ws.onopen).toBeNull();
    expect(ws.onmessage).toBeNull();
    expect(ws.onerror).toBeNull();
    expect(ws.readyState).toBe(MockWebSocket.CLOSED);
  });

  it('opens a new WS and closes the old one when taskId changes', async () => {
    const { rerender } = renderHook(({ id }: { id: string }) => useScanTask(id), {
      initialProps: { id: 'task-1' },
    });
    const firstWs = lastMockWs!;
    rerender({ id: 'task-2' });
    expect(firstWs.readyState).toBe(MockWebSocket.CLOSED);
    expect(lastMockWs).not.toBe(firstWs);
  });
});
```

#### Step 5.2 — Run and verify

```bash
cd frontend && npm run test -- src/hooks/useScanTask.test.ts
```

Expected: 10 tests pass, 0 failures.

#### Step 5.3 — Commit

```bash
git add frontend/src/hooks/useScanTask.test.ts
git commit -m "test(frontend): add useScanTask state-machine tests"
```

---

### Task 6 — `useWatchlistLive` tests

**Files:** `frontend/src/hooks/useWatchlistLive.test.ts`

This hook calls `connect()` directly in the effect (no delay). After `renderHook`, flush the `queueMicrotask` (mock onopen) with `await act(async () => {})`. The hook auto-reconnects on close — the reconnect timer is cancelled on unmount.

#### Step 6.1 — Write `frontend/src/hooks/useWatchlistLive.test.ts`

```typescript
import { renderHook, act } from '@testing-library/react';
import { useWatchlistLive } from './useWatchlistLive';
import { MockWebSocket, resetMockWs, lastMockWs } from '../test-utils/MockWebSocket';

beforeEach(() => {
  resetMockWs();
  vi.useFakeTimers();
  vi.stubGlobal('WebSocket', MockWebSocket);
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe('useWatchlistLive', () => {
  it('starts with empty liveData and connected false', () => {
    const { result } = renderHook(() => useWatchlistLive());
    expect(result.current.liveData).toEqual({});
    expect(result.current.connected).toBe(false);
  });

  it('sets connected true when the WebSocket opens', async () => {
    const { result } = renderHook(() => useWatchlistLive());
    await act(async () => {}); // flush onopen microtask
    expect(result.current.connected).toBe(true);
  });

  it('quote message updates the symbol price in liveData', async () => {
    const { result } = renderHook(() => useWatchlistLive());
    await act(async () => {});
    act(() => {
      lastMockWs!.simulateMessage({
        type: 'quote',
        symbol: 'AAPL',
        last: 150.5,
        bid: null,
        ask: null,
        time: 1000,
      });
    });
    expect(result.current.liveData['AAPL'].price).toBe(150.5);
  });

  it('tick message updates the symbol price using close field', async () => {
    const { result } = renderHook(() => useWatchlistLive());
    await act(async () => {});
    act(() => {
      lastMockWs!.simulateMessage({
        type: 'tick',
        symbol: 'MSFT',
        time: 1000,
        open: 300,
        high: 301,
        low: 299,
        close: 300.5,
        volume: 1000,
        wap: 300.2,
      });
    });
    // tick uses prev[symbol]?.price || msg.close → no prior entry, so msg.close
    expect(result.current.liveData['MSFT'].price).toBe(300.5);
  });

  it('minute_bar message updates price, priceChangePct, session, and sessionVolume', async () => {
    const { result } = renderHook(() => useWatchlistLive());
    await act(async () => {});
    act(() => {
      lastMockWs!.simulateMessage({
        type: 'minute_bar',
        symbol: 'TSLA',
        minute_ts: '2024-01-15T09:31:00',
        open: 200,
        high: 202,
        low: 199,
        close: 201,
        volume: 5000,
        vwap: 200.5,
        session: 'pre',
        session_volume: 50000,
        minutes_elapsed: 1,
        prior_close: 198,
        price_change_pct: 1.5,
      });
    });
    expect(result.current.liveData['TSLA'].price).toBe(201);
    expect(result.current.liveData['TSLA'].priceChangePct).toBe(1.5);
    expect(result.current.liveData['TSLA'].session).toBe('pre');
    expect(result.current.liveData['TSLA'].sessionVolume).toBe(50000);
  });

  it('unknown message type does not crash and leaves liveData unchanged', async () => {
    const { result } = renderHook(() => useWatchlistLive());
    await act(async () => {});
    act(() => {
      lastMockWs!.simulateMessage({ type: 'heartbeat' });
    });
    expect(result.current.liveData).toEqual({});
  });

  it('closes the WebSocket on unmount', async () => {
    const { unmount } = renderHook(() => useWatchlistLive());
    await act(async () => {});
    const ws = lastMockWs!;
    unmount();
    expect(ws.readyState).toBe(MockWebSocket.CLOSED);
  });
});
```

#### Step 6.2 — Run and verify

```bash
cd frontend && npm run test -- src/hooks/useWatchlistLive.test.ts
```

Expected: 7 tests pass, 0 failures.

#### Step 6.3 — Commit

```bash
git add frontend/src/hooks/useWatchlistLive.test.ts
git commit -m "test(frontend): add useWatchlistLive streaming and cleanup tests"
```

---

### Task 7 — `useLiveStockData` tests

**Files:** `frontend/src/hooks/useLiveStockData.test.ts`

This hook delays connection by 50 ms via `window.setTimeout`. Tests use `vi.useFakeTimers()` to control timing. After advancing past 50 ms inside `act(async () => { ... })`, the microtask for `onopen` is also flushed, making `isConnected` true in the same `await act`.

The hook calls `setLiveData(parsed)` for every incoming message without message-type discrimination — tests verify raw data passthrough.

#### Step 7.1 — Write `frontend/src/hooks/useLiveStockData.test.ts`

```typescript
import { renderHook, act } from '@testing-library/react';
import { useLiveStockData } from './useLiveStockData';
import { MockWebSocket, resetMockWs, lastMockWs } from '../test-utils/MockWebSocket';

beforeEach(() => {
  resetMockWs();
  vi.useFakeTimers();
  vi.stubGlobal('WebSocket', MockWebSocket);
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe('useLiveStockData', () => {
  it('opens no WebSocket when symbol is undefined', async () => {
    renderHook(() => useLiveStockData(undefined));
    await act(async () => { vi.advanceTimersByTime(100); });
    expect(lastMockWs).toBeNull();
  });

  it('connects to the correct WS URL for the symbol after 50 ms', async () => {
    renderHook(() => useLiveStockData('AAPL'));
    expect(lastMockWs).toBeNull(); // before 50 ms, no WS
    await act(async () => { vi.advanceTimersByTime(51); });
    expect(lastMockWs).not.toBeNull();
    expect(lastMockWs!.url).toContain('AAPL');
    expect(lastMockWs!.url).toContain('minute');
  });

  it('sets isConnected true when WS opens', async () => {
    const { result } = renderHook(() => useLiveStockData('AAPL'));
    await act(async () => { vi.advanceTimersByTime(51); });
    expect(result.current.isConnected).toBe(true);
  });

  it('sets liveData to the parsed message payload', async () => {
    const { result } = renderHook(() => useLiveStockData('AAPL'));
    await act(async () => { vi.advanceTimersByTime(51); });
    const bar = { ev: 'AM', sym: 'AAPL', v: 1000, o: 150, c: 151, h: 152, l: 149, vw: 150.5, s: 1000, e: 2000 };
    act(() => { lastMockWs!.simulateMessage(bar); });
    expect(result.current.liveData).toMatchObject({ sym: 'AAPL', c: 151 });
  });

  it('closes the WS and sets isConnected false on unmount', async () => {
    const { result, unmount } = renderHook(() => useLiveStockData('AAPL'));
    await act(async () => { vi.advanceTimersByTime(51); });
    const ws = lastMockWs!;
    unmount();
    expect(ws.readyState).toBe(MockWebSocket.CLOSED);
    expect(result.current.isConnected).toBe(false);
  });

  it('opens a new WS when the symbol changes', async () => {
    const { rerender } = renderHook(
      ({ sym }: { sym: string }) => useLiveStockData(sym),
      { initialProps: { sym: 'AAPL' } },
    );
    await act(async () => { vi.advanceTimersByTime(51); });
    const firstWs = lastMockWs!;
    rerender({ sym: 'MSFT' });
    await act(async () => { vi.advanceTimersByTime(51); });
    expect(lastMockWs).not.toBe(firstWs);
    expect(lastMockWs!.url).toContain('MSFT');
  });
});
```

#### Step 7.2 — Run and verify

```bash
cd frontend && npm run test -- src/hooks/useLiveStockData.test.ts
```

Expected: 6 tests pass, 0 failures.

#### Step 7.3 — Commit

```bash
git add frontend/src/hooks/useLiveStockData.test.ts
git commit -m "test(frontend): add useLiveStockData connection, data, and cleanup tests"
```

---

### Task 8 — `useScorecard` tests

**Files:** `frontend/src/hooks/useScorecard.test.ts`

`useScorecard` is a thin React Query wrapper. Mock `fetchScorecard` from `'../api/outcomes'` at the module level. Use a `QueryClientProvider` wrapper with `retry: false` so errors settle immediately.

#### Step 8.1 — Write `frontend/src/hooks/useScorecard.test.ts`

```typescript
import React from 'react';
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { useScorecard } from './useScorecard';
import { fetchScorecard } from '../api/outcomes';

vi.mock('../api/outcomes', () => ({
  fetchScorecard: vi.fn(),
  fetchEdgeDecay: vi.fn(),
  fetchIntervals: vi.fn(),
  fetchDistribution: vi.fn(),
  fetchSignals: vi.fn(),
  triggerBackfill: vi.fn(),
}));

const mockedFetchScorecard = vi.mocked(fetchScorecard);

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
}

describe('useScorecard', () => {
  it('returns isLoading true while the query is in flight', () => {
    mockedFetchScorecard.mockReturnValue(new Promise(() => {})); // never resolves
    const { result } = renderHook(
      () => useScorecard('pre_market_volume_spike'),
      { wrapper: createWrapper() },
    );
    expect(result.current.isLoading).toBe(true);
  });

  it('is not enabled when scannerType is undefined', () => {
    const { result } = renderHook(
      () => useScorecard(undefined),
      { wrapper: createWrapper() },
    );
    expect(result.current.isLoading).toBe(false);
    expect(result.current.fetchStatus).toBe('idle');
  });

  it('returns scorecard data when the query resolves', async () => {
    const mockData = {
      scanner_type: 'pre_market_volume_spike',
      win_rate: 0.65,
      total_signals: 100,
    };
    mockedFetchScorecard.mockResolvedValue(mockData as any);
    const { result } = renderHook(
      () => useScorecard('pre_market_volume_spike'),
      { wrapper: createWrapper() },
    );
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual(mockData);
  });

  it('returns isError true when the query fails', async () => {
    mockedFetchScorecard.mockRejectedValue(new Error('API unavailable'));
    const { result } = renderHook(
      () => useScorecard('pre_market_volume_spike'),
      { wrapper: createWrapper() },
    );
    await waitFor(() => expect(result.current.isError).toBe(true));
  });
});
```

#### Step 8.2 — Run and verify

```bash
cd frontend && npm run test -- src/hooks/useScorecard.test.ts
```

Expected: 4 tests pass, 0 failures.

#### Step 8.3 — Commit

```bash
git add frontend/src/hooks/useScorecard.test.ts
git commit -m "test(frontend): add useScorecard React Query composition tests"
```

---

### Task 9 — `GlobalErrorToast` tests

**Files:** `frontend/src/components/ui/GlobalErrorToast.test.tsx`

The component listens on `window` for `'server-error'` CustomEvents and auto-dismisses after 20 s. Fake timers are scoped to the auto-dismiss test using a nested `describe` block. Other tests use real timers and `userEvent` for button interactions.

#### Step 9.1 — Write `frontend/src/components/ui/GlobalErrorToast.test.tsx`

```tsx
import React from 'react';
import { render, screen, act } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { GlobalErrorToast } from './GlobalErrorToast';

interface ServerErrorDetail {
  message: string;
  error_id?: string | null;
  detail?: string | null;
  stack_trace?: string | null;
}

function dispatchServerError(detail: ServerErrorDetail) {
  window.dispatchEvent(new CustomEvent('server-error', { detail }));
}

afterEach(() => {
  // Unmount between tests so event listeners are cleaned up
});

describe('GlobalErrorToast — default state', () => {
  it('renders nothing by default', () => {
    render(<GlobalErrorToast />);
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });
});

describe('GlobalErrorToast — event handling', () => {
  it('shows the toast and message when server-error fires', () => {
    render(<GlobalErrorToast />);
    act(() => { dispatchServerError({ message: 'Something went wrong', error_id: null }); });
    expect(screen.getByRole('alert')).toBeInTheDocument();
    expect(screen.getByText('Something went wrong')).toBeInTheDocument();
  });

  it('displays error_id code and constructs a Seq link', () => {
    render(<GlobalErrorToast />);
    act(() => {
      dispatchServerError({ message: 'DB error', error_id: 'abc-123', stack_trace: null });
    });
    expect(screen.getByText('abc-123')).toBeInTheDocument();
    const seqLink = screen.getByRole('link');
    expect(seqLink).toHaveAttribute('href', expect.stringContaining('abc-123'));
  });

  it('does not render the Seq link section when error_id is null', () => {
    render(<GlobalErrorToast />);
    act(() => { dispatchServerError({ message: 'Error', error_id: null }); });
    expect(screen.queryByRole('link')).not.toBeInTheDocument();
  });
});

describe('GlobalErrorToast — dismiss', () => {
  it('dismiss button (X) hides the toast', async () => {
    const user = userEvent.setup();
    render(<GlobalErrorToast />);
    act(() => { dispatchServerError({ message: 'Error', error_id: null }); });
    expect(screen.getByRole('alert')).toBeInTheDocument();
    await user.click(screen.getByLabelText('Dismiss error notification'));
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });
});

describe('GlobalErrorToast — developer details', () => {
  it('does not render Developer details button when no stack_trace or detail', () => {
    render(<GlobalErrorToast />);
    act(() => {
      dispatchServerError({ message: 'Error', error_id: null, stack_trace: null, detail: null });
    });
    expect(screen.queryByText('Developer details')).not.toBeInTheDocument();
  });

  it('clicking Developer details reveals the stack trace', async () => {
    const user = userEvent.setup();
    render(<GlobalErrorToast />);
    act(() => {
      dispatchServerError({ message: 'Error', error_id: null, stack_trace: 'Traceback: line 1' });
    });
    await user.click(screen.getByText('Developer details'));
    expect(screen.getByText('Traceback: line 1')).toBeInTheDocument();
  });

  it('clicking Developer details again hides the stack trace', async () => {
    const user = userEvent.setup();
    render(<GlobalErrorToast />);
    act(() => {
      dispatchServerError({ message: 'Error', error_id: null, stack_trace: 'Traceback: line 1' });
    });
    await user.click(screen.getByText('Developer details'));
    expect(screen.getByText('Traceback: line 1')).toBeInTheDocument();
    await user.click(screen.getByText('Developer details'));
    expect(screen.queryByText('Traceback: line 1')).not.toBeInTheDocument();
  });
});

describe('GlobalErrorToast — auto-dismiss', () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it('auto-dismisses the toast after 20 seconds', () => {
    render(<GlobalErrorToast />);
    act(() => { dispatchServerError({ message: 'Error', error_id: null }); });
    expect(screen.getByRole('alert')).toBeInTheDocument();
    act(() => { vi.advanceTimersByTime(20_001); });
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });
});
```

#### Step 9.2 — Run and verify

```bash
cd frontend && npm run test -- src/components/ui/GlobalErrorToast.test.tsx
```

Expected: 9 tests pass, 0 failures.

#### Step 9.3 — Run coverage and verify threshold passes

```bash
cd frontend && npm run test:coverage
```

Expected output (abbreviated):
```
✓ src/hooks/useScannerState.test.ts (9)
✓ src/hooks/useScannerWs.test.ts (8)
✓ src/hooks/useScanTask.test.ts (10)
✓ src/hooks/useWatchlistLive.test.ts (6)
✓ src/hooks/useLiveStockData.test.ts (6)
✓ src/hooks/useScorecard.test.ts (4)
✓ src/components/ui/GlobalErrorToast.test.tsx (9)

Coverage thresholds satisfied ✓
```

If the threshold check fails, inspect the per-file report and add targeted tests for uncovered branches. Do not lower the threshold.

#### Step 9.4 — Commit

```bash
git add frontend/src/components/ui/GlobalErrorToast.test.tsx
git commit -m "test(frontend): add GlobalErrorToast event, dismiss, and auto-dismiss tests"
```

---

### Task 10 — CI integration

**Files:** `.github/workflows/ci.yml`

Add a `frontend-test` job that runs in parallel with the existing backend `test` job. Uses `npm run test:coverage` (not `test`) so that the 20% coverage threshold is enforced on every PR; the XML report is uploaded as an artifact.

#### Step 10.1 — Append the `frontend-test` job to `.github/workflows/ci.yml`

In `.github/workflows/ci.yml`, after the closing of the `test` job, add:

```yaml
  frontend-test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up Node.js
        uses: actions/setup-node@v4
        with:
          node-version: '20'
          cache: npm
          cache-dependency-path: frontend/package-lock.json

      - name: Install dependencies
        working-directory: frontend
        run: npm ci

      - name: Run frontend tests with coverage
        working-directory: frontend
        run: npm run test:coverage

      - name: Upload coverage report
        uses: actions/upload-artifact@v4
        with:
          name: frontend-coverage-xml
          path: frontend/coverage/coverage.xml
```

The two jobs (`test` and `frontend-test`) are top-level peers under `jobs:` with no dependency between them — they run in parallel. Either failing blocks the PR.

#### Step 10.2 — Verify YAML is valid

```bash
python3 -c "import yaml, sys; yaml.safe_load(open('.github/workflows/ci.yml'))" && echo "YAML OK"
```

Expected: `YAML OK`

#### Step 10.3 — Type-check the full frontend

```bash
cd frontend && npx tsc --noEmit
```

Expected: 0 errors.

#### Step 10.4 — Run the full test suite one final time

```bash
cd frontend && npm run test:coverage
```

Expected: all 56 tests pass, coverage thresholds satisfied.

#### Step 10.5 — Commit

```bash
git add .github/workflows/ci.yml
git commit -m "ci: add frontend-test job running Vitest with coverage threshold"
```

---

## Summary

| Task | Tests Added | Key Files |
|------|-------------|-----------|
| 1 — Scaffold | — | `vitest.config.ts`, `test-setup.ts`, `package.json` |
| 2 — MockWebSocket | — | `src/test-utils/MockWebSocket.ts` |
| 3 — `useScannerState` | 11 | `useScannerState.test.ts` |
| 4 — `useScannerWs` | 9 | `useScannerWs.test.ts` |
| 5 — `useScanTask` | 10 | `useScanTask.test.ts` |
| 6 — `useWatchlistLive` | 7 | `useWatchlistLive.test.ts` |
| 7 — `useLiveStockData` | 6 | `useLiveStockData.test.ts` |
| 8 — `useScorecard` | 4 | `useScorecard.test.ts` |
| 9 — `GlobalErrorToast` | 9 | `GlobalErrorToast.test.tsx` |
| 10 — CI | — | `.github/workflows/ci.yml` |
| **Total** | **56 tests** | **12 files** |
