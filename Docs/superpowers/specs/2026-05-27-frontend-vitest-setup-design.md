# Frontend Vitest Setup and Critical-Path Tests

**Date:** 2026-05-27  
**Status:** Pending review  
**Issue:** #89  
**Scope:** `frontend/` — Vitest installation, configuration, hook + component tests, coverage gate, CI integration

---

## Problem

The frontend has 86 TypeScript/TSX files (~15,100 lines) with zero test coverage. No test framework is configured. The risk is that regressions in critical paths (WebSocket state machines, localStorage persistence, error display) are only caught in production.

The recent page-decomposition refactoring extracted 6 standalone custom hooks with pure state logic — the highest-value test targets because they contain the most complex behavior and are easiest to test in isolation from rendering.

---

## Goals

1. **Test framework in place** — Vitest + React Testing Library + jsdom installed and configured
2. **Critical-path tests written** — all 6 custom hooks and `GlobalErrorToast` covered
3. **Coverage gate enforced** — 20% line/function/branch/statement threshold on the tested files
4. **CI integration** — frontend tests run on every PR alongside backend tests

---

## Infrastructure

### Packages to Add (`devDependencies`)

| Package | Purpose |
|---------|---------|
| `vitest` | Test runner (Vite-native, fast, no separate config) |
| `@vitest/coverage-v8` | V8-based coverage provider (no extra binaries) |
| `@testing-library/react` | React render + query utilities |
| `@testing-library/jest-dom` | Custom matchers (`.toBeInTheDocument()`, etc.) |
| `@testing-library/user-event` | Realistic user interaction simulation (pointer + keyboard) |
| `jsdom` | DOM environment for the test runner |

React 19 is supported by `@testing-library/react` v16+. Pin to `^16`.

### `vitest.config.ts` (new file, root of `frontend/`)

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
  },
});
```

Coverage is scoped to the 7 files under test. Including all 86 files at this stage would require a threshold of ~5% (meaningless), while scoping to tested files enforces meaningful quality on the code that matters now. As future PRs add tests, expand `include` and raise thresholds.

### `src/test-setup.ts` (new file)

```typescript
import '@testing-library/jest-dom';
```

Extended matchers are imported once here; `globals: true` makes `describe`/`it`/`expect`/`vi` available without imports in test files.

### `package.json` Scripts

```json
"test": "vitest run",
"test:coverage": "vitest run --coverage"
```

`vitest run` is the non-watch (CI-safe) mode. `vitest` alone launches watch mode for local development.

### MockWebSocket Utility

Four of six hooks open native WebSocket connections. jsdom has no real WebSocket. Create a shared mock in `src/test-utils/MockWebSocket.ts`:

```typescript
// Captured instances so tests can access the active WS and trigger events
export let lastMockWs: MockWebSocket | null = null;

export class MockWebSocket {
  static OPEN = 1;
  static CLOSED = 3;
  readyState = MockWebSocket.OPEN;
  onopen: ((e: Event) => void) | null = null;
  onmessage: ((e: MessageEvent) => void) | null = null;
  onclose: ((e: CloseEvent) => void) | null = null;
  onerror: ((e: Event) => void) | null = null;

  constructor(public url: string) {
    lastMockWs = this;
    // Simulate async open (matches real WS behaviour)
    queueMicrotask(() => this.onopen?.(new Event('open')));
  }

  send(_data: string) {}

  close() {
    this.readyState = MockWebSocket.CLOSED;
    this.onclose?.(new CloseEvent('close'));
  }

  // Test helpers
  simulateMessage(data: object) {
    this.onmessage?.(new MessageEvent('message', { data: JSON.stringify(data) }));
  }

  simulateError() {
    this.onerror?.(new Event('error'));
  }

  simulateClose(wasRunning = false) {
    this.readyState = MockWebSocket.CLOSED;
    this.onclose?.(new CloseEvent('close'));
  }
}
```

Stub it globally in tests that need it:
```typescript
beforeEach(() => { vi.stubGlobal('WebSocket', MockWebSocket); });
afterEach(() => { vi.unstubAllGlobals(); });
```

---

## Test Files

All test files are colocated next to their source files (e.g., `useScannerState.test.ts` lives in `src/hooks/`). This matches React/TypeScript convention and keeps navigation natural in the editor.

### 1. `src/hooks/useScannerState.test.ts`

Pure state hook with localStorage side effects — no WebSocket needed.

| Test | What it verifies |
|------|-----------------|
| initial state: `selectedConfig` defaults to `'pre_market_volume_spike'` | Default value is correct |
| initial state: reads from `localStorage` on mount | `loadPersistedSelection` hydrates state |
| changing `selectedConfig` writes to `localStorage` | Persistence side effect fires |
| changing `selectedUniverse` writes to `localStorage` | Same |
| `lastCompletedWeekday()` returns a weekday (Mon–Fri) | Date helper skips weekends |
| `loadPersistedSelection()` returns `{}` on JSON parse error | Graceful fallback |

### 2. `src/hooks/useScannerWs.test.ts`

`handleWsMessage` is a pure function embedded in the hook — mock the state slice and verify it processes all message types correctly.

| Test | What it verifies |
|------|-----------------|
| `snapshot` message updates all progress fields | All `LiveProgress` fields populated |
| `started` message sets `total_days` and `total_tickers` | Partial snapshot handled |
| `day_started` message updates `day_index` and `last_day` | Day tracking |
| `day_completed` message updates counter fields | Accumulation |
| `completed` message calls `finishScan('completed')` | Invalidates query cache, closes WS |
| `failed` message calls `finishScan('failed', errorMsg)` | Sets `scanError` |
| `cancelled` message calls `finishScan('cancelled')` | Sets `scanError` to 'Scan cancelled' |
| `attachWebSocket` sets up `onmessage`/`onclose`/`onerror` | WS event wiring |
| Cleanup on unmount closes the WebSocket | No leak |

### 3. `src/hooks/useScanTask.test.ts`

State machine: `idle → connecting → running → completed | failed`.

| Test | What it verifies |
|------|-----------------|
| `taskId = null` → stays `idle` | No WS opened |
| `taskId` provided → transitions to `connecting` | Immediate state update |
| WS opens → transitions to `running` | `onopen` handler |
| `progress` message → updates `done`, `total`, `currentDay` | Progress tracking |
| `completed` message → transitions to `completed`, calls `onComplete` | Completion callback |
| `failed` message → transitions to `failed` with error string | Failure path |
| WS error event → `failed` with 'WebSocket connection error' | Error path |
| WS closes unexpectedly while `running` → `failed` | Disconnect guard |
| Unmount cleans up WS and sets handlers to null | No stale handlers |
| `taskId` changes → new WS opened, old one closed | Re-subscribe |

### 4. `src/hooks/useWatchlistLive.test.ts`

WebSocket streaming for the active watchlist. Focus on message type dispatch and aggregation.

| Test | What it verifies |
|------|-----------------|
| Initial state is empty | No data before WS connects |
| `quote` message updates the correct symbol's price | Symbol-keyed map update |
| `tick` message updates OHLCV for the correct symbol | Tick aggregation |
| Unknown message type is ignored | No crash |
| Unmount closes WS | Cleanup |

### 5. `src/hooks/useLiveStockData.test.ts`

WebSocket bar streaming for a single symbol on the stock detail page.

| Test | What it verifies |
|------|-----------------|
| No WS opened when `ticker = null` | Guard condition |
| `minute_bar` message appends to bars array | Bar accumulation |
| `quote` message updates last price | Quote tracking |
| Cleanup on unmount or ticker change | No leak |

### 6. `src/hooks/useScorecard.test.ts`

React Query composition hook — mock `useQuery` to verify the hook surfaces the right data shapes.

| Test | What it verifies |
|------|-----------------|
| Returns `isLoading = true` while query is in flight | Loading state forwarded |
| Returns scorecard data when query resolves | Data shape |
| Returns error state when query fails | Error forwarded |

Use `@tanstack/react-query`'s `QueryClientProvider` wrapper in a test utility.

### 7. `src/components/ui/GlobalErrorToast.test.tsx`

DOM event-driven component. Use `@testing-library/user-event` for button clicks; `fireEvent.dispatchEvent` for the custom `server-error` event.

| Test | What it verifies |
|------|-----------------|
| Renders nothing by default | No toast visible |
| `server-error` event → toast appears with message | Event handler wired |
| Error ID is displayed and Seq link is constructed correctly | `buildSeqLink` interpolation |
| Dismiss button (X) hides the toast | `dismiss()` |
| "Developer details" button shows stack trace | Expand toggle |
| "Developer details" button again hides stack trace | Collapse toggle |
| Toast auto-dismisses after 20 s | `setTimeout` with `vi.useFakeTimers()` |
| No error_id → Seq link section not rendered | Conditional rendering |
| No stack_trace/detail → expand button not rendered | Conditional rendering |

---

## CI Integration

Add a new `frontend-test` job to `.github/workflows/ci.yml`, parallel to the existing `test` job:

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

    - name: Run frontend tests
      working-directory: frontend
      run: npm run test

    - name: Upload coverage report
      uses: actions/upload-artifact@v4
      with:
        name: frontend-coverage-xml
        path: frontend/coverage.xml
```

The `frontend-test` job is independent — it runs in parallel with `test` (backend). If either fails, the PR is blocked. No dependency between the two jobs is needed.

---

## Alternatives Considered

### A: Defer CI integration to #88

The issue lists CI as item 7 and calls out #88 as a dependency. However, shipping tests without CI means coverage enforcement is purely manual. Adding one new job to `ci.yml` is low-effort and within the natural scope of "install and wire up Vitest." Deferred to #88 only if that PR lands first and adds the frontend job itself.

**Rejected**: It takes 10 lines of YAML and protects the threshold gate from day one.

### B: Use `vitest-websocket-mock` instead of hand-rolled MockWebSocket

A library alternative that provides a server-side push API. Adds a dependency for functionality achievable in ~60 lines of plain TypeScript.

**Rejected**: The WebSocket patterns in these hooks are simple (onopen/onmessage/onclose/onerror without subprotocols or binary frames). A hand-rolled mock is more transparent and doesn't require learning another library.

### C: Instrument all 86 frontend files for coverage

Matches the backend's all-files approach. At this stage, 7 tested files out of 86 produce ~4% overall coverage — the 20% threshold would fail immediately unless expanded to cover many more files.

**Rejected**: The 20% threshold is explicitly framed as "start here, increase over time." Scoping instrumentation to tested files makes 20% meaningful and achievable now.

---

## Assumptions

- `@testing-library/react` v16+ is compatible with React 19 (the project uses `react: ^19.2.5`). If not, pin to the latest compatible version.
- `useWatchlistLive.ts` and `useLiveStockData.ts` follow the same WebSocket construction pattern as `useScanTask.ts` (verified by grep — both use `new WebSocket(...)`). Tests will be similar.
- `useScorecard.ts` is a thin React Query wrapper with no complex internal logic; 20% branch coverage is achievable with 2-3 tests.
- The `api/scanner.ts` export `createScanRunWebSocket` wraps `new WebSocket(...)` — mocking the global `WebSocket` is sufficient for `useScannerWs.ts` tests (no need to separately mock the import).

---

## Open Questions (non-blocking)

- Should `npm run test` also run in watch mode when invoked locally (i.e., use `vitest` instead of `vitest run` for the `test` script)? The spec uses `vitest run` for CI safety; local dev can run `vitest` directly. A `test:watch` alias could be added.
- When #88 lands: if it adds its own frontend CI job, the `frontend-test` job from this issue should be merged or deduplicated to avoid double-running tests.
