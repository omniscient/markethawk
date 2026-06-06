# Implementation Plan: Frontend Test Breadth + Honest Coverage

**Date:** 2026-06-06
**Issue:** #198 — [arch-v2][MED] Expand frontend test breadth (pages/components) + honest coverage
**Spec:** docs/superpowers/specs/2026-06-06-frontend-test-breadth-design.md
**Branch:** refine/issue-198--arch-v2--med--expand-frontend-test-brea

## Goal

Add 14 test files covering 5 page shells, 4 shared components, and 4 page-embedded panels, plus a shared `renderWithQuery` utility. Reconfigure `vitest.config.ts` so coverage is honest: `all: true` with 35% statements/lines and 25% branches/functions global thresholds. The coverage gate is the final step, applied only after all test files are in place.

## Architecture

- All page and component tests use a shared `renderWithQuery` wrapper (real `QueryClient` with `retry: false` + `MemoryRouter`).
- API modules that export **raw async functions** are mocked with `vi.mock` returning `vi.fn().mockResolvedValue(...)`. Real React Query executes the queries against those mocks.
- API modules that export **React Query hooks** directly (e.g., `api/alerts.ts`, `api/trading.ts`) are mocked with stub hook implementations returning static data. This is appropriate for page-level smoke tests; hook internals are covered by the existing `src/hooks/*.test.ts` suite.
- Components that open WebSocket connections in `useEffect` (`NewsFeed`, `TweetFeed`, `SystemActivityMonitor`) are mocked as null-returning stubs in page tests that compose them, to avoid jsdom failures on missing WebSocket implementation.
- For the `Scanner` page, `useScannerWs` is mocked at the hook level since it is the component's own WebSocket abstraction.
- Coverage config (`vitest.config.ts`) is modified last. Running `pnpm test:coverage` before all test files exist would fail the threshold gate.

## Tech Stack

- **Test runner:** Vitest (`pnpm test` / `pnpm test:coverage`)
- **Component rendering:** React Testing Library (`@testing-library/react`)
- **Mocking:** `vi.mock` for API modules and WebSocket-using child components
- **TypeScript gate:** `npx tsc --noEmit` before every commit

## File Structure

| File | Status | Requirement |
|------|--------|-------------|
| `frontend/src/test-utils/renderWithQuery.tsx` | NEW | R4 |
| `frontend/src/pages/Scanner/Scanner.test.tsx` | NEW | R1 |
| `frontend/src/pages/Dashboard.test.tsx` | NEW | R1 |
| `frontend/src/pages/Alerts/Alerts.test.tsx` | NEW | R1 |
| `frontend/src/pages/AutoTrading/AutoTrading.test.tsx` | NEW | R1 |
| `frontend/src/pages/Login/Login.test.tsx` | NEW | R1 |
| `frontend/src/components/ScannerResults.test.tsx` | NEW | R2 |
| `frontend/src/components/Layout.test.tsx` | NEW | R2 |
| `frontend/src/components/UniverseFormModal.test.tsx` | NEW | R2 |
| `frontend/src/components/QualityReportModal.test.tsx` | NEW | R2 |
| `frontend/src/pages/Scanner/ScanConfigPanel.test.tsx` | NEW | R3 |
| `frontend/src/pages/Alerts/AlertRuleModal.test.tsx` | NEW | R3 |
| `frontend/src/pages/AutoTrading/ConfigPanel.test.tsx` | NEW | R3 |
| `frontend/src/pages/AutoTrading/components.test.tsx` | NEW | R3 |
| `frontend/vitest.config.ts` | MODIFY | R5, R6, R7 |

---

## Task 1: Create renderWithQuery shared test utility

**Requirement:** R4

**Files:**
- `frontend/src/test-utils/renderWithQuery.tsx` (NEW)

### TDD Steps

1. **Write a minimal failing test stub** to confirm Vitest will pick up the file (temporary):

   Create `frontend/src/test-utils/renderWithQuery.tsx` with a placeholder that fails on import:
   ```tsx
   // placeholder — will be replaced in step 3
   export const renderWithQuery = () => { throw new Error('not implemented'); };
   ```

2. **Run to confirm the file is seen by the test runner:**
   ```bash
   docker-compose exec frontend pnpm exec vitest run --reporter=verbose 2>&1 | grep -E "renderWithQuery|PASS|FAIL" | head -5
   # Expected: no test file found (zero tests collected from this file — that's fine, it has no describe/it)
   ```

3. **Write the complete implementation:**

   `frontend/src/test-utils/renderWithQuery.tsx`:
   ```tsx
   import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
   import { MemoryRouter } from 'react-router-dom';
   import { render } from '@testing-library/react';
   import type { RenderOptions } from '@testing-library/react';
   import React from 'react';

   function makeQueryClient() {
     return new QueryClient({
       defaultOptions: {
         queries: { retry: false },
         mutations: { retry: false },
       },
     });
   }

   export function renderWithQuery(
     ui: React.ReactElement,
     options?: RenderOptions & { initialEntries?: string[] }
   ) {
     const qc = makeQueryClient();
     const { initialEntries = ['/'], ...rest } = options ?? {};
     return render(
       <QueryClientProvider client={qc}>
         <MemoryRouter initialEntries={initialEntries}>{ui}</MemoryRouter>
       </QueryClientProvider>,
       rest
     );
   }
   ```

4. **Verify TypeScript accepts it:**
   ```bash
   docker-compose exec frontend npx tsc --noEmit
   # Expected: exits 0, no errors
   ```

5. **Commit:**
   ```bash
   git add frontend/src/test-utils/renderWithQuery.tsx
   git commit -m "test: add renderWithQuery shared utility (issue #198)"
   ```

---

## Task 2: Scanner page smoke test

**Requirement:** R1 (Scanner page)

**Files:**
- `frontend/src/pages/Scanner/Scanner.test.tsx` (NEW)

### TDD Steps

1. **Write a minimal always-failing stub:**

   `frontend/src/pages/Scanner/Scanner.test.tsx`:
   ```tsx
   import { describe, it, expect } from 'vitest';
   describe('Scanner page', () => {
     it('STUB', () => expect(false).toBe(true));
   });
   ```

2. **Verify it fails:**
   ```bash
   docker-compose exec frontend pnpm exec vitest run --reporter=verbose src/pages/Scanner/Scanner.test.tsx
   # Expected: 1 test failed
   ```

3. **Write the complete test:**

   `frontend/src/pages/Scanner/Scanner.test.tsx`:
   ```tsx
   import { vi, describe, it, expect } from 'vitest';
   import { screen } from '@testing-library/react';
   import { renderWithQuery } from '../../test-utils/renderWithQuery';
   import Scanner from './index';

   vi.mock('../../api/scanner', () => ({
     fetchScannerConfigs: vi.fn().mockResolvedValue([]),
     fetchStockUniverses: vi.fn().mockResolvedValue([]),
     fetchScannerHistory: vi.fn().mockResolvedValue([]),
     fetchScanStatusBlock: vi.fn().mockResolvedValue(null),
     fetchScannerResults: vi.fn().mockResolvedValue([]),
     fetchScanStatus: vi.fn().mockResolvedValue({ status: 'completed' }),
     handleApiError: vi.fn().mockReturnValue('error'),
     submitReview: vi.fn().mockResolvedValue({}),
   }));

   vi.mock('../../hooks/useScannerWs', () => ({
     useScannerWs: () => ({ attachWebSocket: vi.fn() }),
   }));

   describe('Scanner page', () => {
     it('renders without crashing', () => {
       renderWithQuery(<Scanner />);
     });

     it('mounts the ScanConfigPanel with a Run Scanner button', () => {
       renderWithQuery(<Scanner />);
       expect(screen.getByRole('button', { name: /run scanner/i })).toBeInTheDocument();
     });
   });
   ```

4. **Verify passes:**
   ```bash
   docker-compose exec frontend pnpm exec vitest run --reporter=verbose src/pages/Scanner/Scanner.test.tsx
   # Expected: 2 passed
   ```

5. **TypeScript check and commit:**
   ```bash
   docker-compose exec frontend npx tsc --noEmit
   git add frontend/src/pages/Scanner/Scanner.test.tsx
   git commit -m "test: Scanner page smoke test (issue #198)"
   ```

---

## Task 3: Dashboard page smoke test

**Requirement:** R1 (Dashboard page)

**Files:**
- `frontend/src/pages/Dashboard.test.tsx` (NEW)

### Context

Dashboard composes `NewsFeed` (WebSocket in useEffect) and `TweetFeed` (WebSocket in useEffect). Both are mocked as null-returning stubs so jsdom does not encounter `new WebSocket(...)`. `NewsSettings` uses `fetchNewsPreferences` from `api/news` — that module is mocked at the same level.

### TDD Steps

1. **Write a minimal failing stub:**

   `frontend/src/pages/Dashboard.test.tsx`:
   ```tsx
   import { describe, it, expect } from 'vitest';
   describe('Dashboard page', () => {
     it('STUB', () => expect(false).toBe(true));
   });
   ```

2. **Verify it fails:**
   ```bash
   docker-compose exec frontend pnpm exec vitest run --reporter=verbose src/pages/Dashboard.test.tsx
   # Expected: 1 test failed
   ```

3. **Write the complete test:**

   `frontend/src/pages/Dashboard.test.tsx`:
   ```tsx
   import { vi, describe, it, expect } from 'vitest';
   import { screen } from '@testing-library/react';
   import { renderWithQuery } from '../test-utils/renderWithQuery';
   import Dashboard from './Dashboard';

   vi.mock('../api/scanner', () => ({
     fetchScannerResults: vi.fn().mockResolvedValue([]),
     fetchMarketStats: vi.fn().mockResolvedValue({
       activeAlerts: 0,
       avgVolumeSpike: 0,
       totalEvents: 0,
       todayEvents: 0,
     }),
     fetchStockUniverses: vi.fn().mockResolvedValue([]),
   }));

   vi.mock('../api/news', () => ({
     fetchNewsPreferences: vi.fn().mockResolvedValue({ tickers: [], topics: [] }),
     updateNewsPreferences: vi.fn().mockResolvedValue({}),
   }));

   vi.mock('../components/NewsFeed', () => ({ default: () => null }));
   vi.mock('../components/TweetFeed', () => ({ default: () => null }));

   describe('Dashboard page', () => {
     it('renders without crashing', () => {
       renderWithQuery(<Dashboard />);
     });

     it('shows the Dashboard heading', () => {
       renderWithQuery(<Dashboard />);
       expect(screen.getByRole('heading', { name: /dashboard/i })).toBeInTheDocument();
     });
   });
   ```

4. **Verify passes:**
   ```bash
   docker-compose exec frontend pnpm exec vitest run --reporter=verbose src/pages/Dashboard.test.tsx
   # Expected: 2 passed
   ```

5. **TypeScript check and commit:**
   ```bash
   docker-compose exec frontend npx tsc --noEmit
   git add frontend/src/pages/Dashboard.test.tsx
   git commit -m "test: Dashboard page smoke test (issue #198)"
   ```

---

## Task 4: Alerts page smoke test

**Requirement:** R1 (Alerts page)

**Files:**
- `frontend/src/pages/Alerts/Alerts.test.tsx` (NEW)

### Context

`api/alerts.ts` exports React Query hooks directly (not raw fetch functions). They are replaced with static stub implementations so jsdom does not trigger network calls. `navigator.serviceWorker` is not available in jsdom — the Alerts page checks for it before calling `.ready`, so no special mock is needed.

### TDD Steps

1. **Write a minimal failing stub:**

   `frontend/src/pages/Alerts/Alerts.test.tsx`:
   ```tsx
   import { describe, it, expect } from 'vitest';
   describe('Alerts page', () => {
     it('STUB', () => expect(false).toBe(true));
   });
   ```

2. **Verify it fails:**
   ```bash
   docker-compose exec frontend pnpm exec vitest run --reporter=verbose src/pages/Alerts/Alerts.test.tsx
   # Expected: 1 test failed
   ```

3. **Write the complete test:**

   `frontend/src/pages/Alerts/Alerts.test.tsx`:
   ```tsx
   import { vi, describe, it, expect } from 'vitest';
   import { screen } from '@testing-library/react';
   import { renderWithQuery } from '../../test-utils/renderWithQuery';
   import Alerts from './index';

   vi.mock('../../api/alerts', () => ({
     useAlertRules: () => ({ data: [], isLoading: false }),
     useAlertStats: () => ({ data: undefined }),
     useAlertLogs: () => ({ data: [] }),
     useCreateAlertRule: () => ({ mutateAsync: vi.fn(), isPending: false }),
     useUpdateAlertRule: () => ({ mutate: vi.fn(), mutateAsync: vi.fn(), isPending: false }),
     useDeleteAlertRule: () => ({ mutate: vi.fn() }),
     useTestAlertRule: () => ({ mutate: vi.fn() }),
     usePushSubscription: () => ({
       subscribe: vi.fn(),
       unsubscribe: vi.fn(),
       isSubscribing: false,
     }),
   }));

   vi.mock('../../api/trading', () => ({
     useStrategies: () => ({ data: [] }),
   }));

   describe('Alerts page', () => {
     it('renders without crashing', () => {
       renderWithQuery(<Alerts />);
     });

     it('shows the Alert Center heading', () => {
       renderWithQuery(<Alerts />);
       expect(screen.getByRole('heading', { name: /alert center/i })).toBeInTheDocument();
     });

     it('shows the New Alert Rule button', () => {
       renderWithQuery(<Alerts />);
       expect(screen.getByRole('button', { name: /new alert rule/i })).toBeInTheDocument();
     });
   });
   ```

4. **Verify passes:**
   ```bash
   docker-compose exec frontend pnpm exec vitest run --reporter=verbose src/pages/Alerts/Alerts.test.tsx
   # Expected: 3 passed
   ```

5. **TypeScript check and commit:**
   ```bash
   docker-compose exec frontend npx tsc --noEmit
   git add frontend/src/pages/Alerts/Alerts.test.tsx
   git commit -m "test: Alerts page smoke test (issue #198)"
   ```

---

## Task 5: AutoTrading page smoke test

**Requirement:** R1 (AutoTrading page)

**Files:**
- `frontend/src/pages/AutoTrading/AutoTrading.test.tsx` (NEW)

### TDD Steps

1. **Write a minimal failing stub:**

   `frontend/src/pages/AutoTrading/AutoTrading.test.tsx`:
   ```tsx
   import { describe, it, expect } from 'vitest';
   describe('AutoTrading page', () => {
     it('STUB', () => expect(false).toBe(true));
   });
   ```

2. **Verify it fails:**
   ```bash
   docker-compose exec frontend pnpm exec vitest run --reporter=verbose src/pages/AutoTrading/AutoTrading.test.tsx
   # Expected: 1 test failed
   ```

3. **Write the complete test:**

   `frontend/src/pages/AutoTrading/AutoTrading.test.tsx`:
   ```tsx
   import { vi, describe, it, expect } from 'vitest';
   import { screen } from '@testing-library/react';
   import { renderWithQuery } from '../../test-utils/renderWithQuery';
   import AutoTrading from './index';

   vi.mock('../../api/trading', () => ({
     useStrategies: () => ({ data: [], isLoading: false }),
     useCreateStrategy: () => ({ mutate: vi.fn(), mutateAsync: vi.fn(), isPending: false }),
     useUpdateStrategy: () => ({ mutate: vi.fn(), mutateAsync: vi.fn(), isPending: false }),
     useDeleteStrategy: () => ({ mutate: vi.fn(), isPending: false }),
     useAutoTradeOrders: () => ({ data: [], isLoading: false }),
     useApproveOrder: () => ({ mutate: vi.fn(), isPending: false }),
     useRejectOrder: () => ({ mutate: vi.fn(), isPending: false }),
     useCancelOrder: () => ({ mutate: vi.fn(), isPending: false }),
     useTradingStats: () => ({ data: undefined }),
     useTradingConfig: () => ({ data: undefined }),
     useUpdateTradingConfig: () => ({ mutate: vi.fn() }),
     useAccountSummary: () => ({ data: undefined }),
   }));

   describe('AutoTrading page', () => {
     it('renders without crashing', () => {
       renderWithQuery(<AutoTrading />);
     });

     it('shows the Auto Trading heading', () => {
       renderWithQuery(<AutoTrading />);
       expect(screen.getByRole('heading', { name: /auto trading/i })).toBeInTheDocument();
     });

     it('shows the New Strategy button', () => {
       renderWithQuery(<AutoTrading />);
       expect(screen.getByRole('button', { name: /new strategy/i })).toBeInTheDocument();
     });
   });
   ```

4. **Verify passes:**
   ```bash
   docker-compose exec frontend pnpm exec vitest run --reporter=verbose src/pages/AutoTrading/AutoTrading.test.tsx
   # Expected: 3 passed
   ```

5. **TypeScript check and commit:**
   ```bash
   docker-compose exec frontend npx tsc --noEmit
   git add frontend/src/pages/AutoTrading/AutoTrading.test.tsx
   git commit -m "test: AutoTrading page smoke test (issue #198)"
   ```

---

## Task 6: Login page test (light interaction)

**Requirement:** R1 (Login page)

**Files:**
- `frontend/src/pages/Login/Login.test.tsx` (NEW)

### Context

Login is not a thin orchestrator — it has its own form logic, validation, and auth flow. It uses `useNavigate` (available via `MemoryRouter` in `renderWithQuery`). `getMe` is called on mount to redirect already-authenticated users; mock it to reject so the login form renders.

### TDD Steps

1. **Write a minimal failing stub:**

   `frontend/src/pages/Login/Login.test.tsx`:
   ```tsx
   import { describe, it, expect } from 'vitest';
   describe('Login page', () => {
     it('STUB', () => expect(false).toBe(true));
   });
   ```

2. **Verify it fails:**
   ```bash
   docker-compose exec frontend pnpm exec vitest run --reporter=verbose src/pages/Login/Login.test.tsx
   # Expected: 1 test failed
   ```

3. **Write the complete test:**

   `frontend/src/pages/Login/Login.test.tsx`:
   ```tsx
   import { vi, describe, it, expect, beforeEach } from 'vitest';
   import { screen, fireEvent, waitFor } from '@testing-library/react';
   import { renderWithQuery } from '../../test-utils/renderWithQuery';
   import Login from './index';

   const mockLogin = vi.fn().mockResolvedValue(undefined);
   const mockRegister = vi.fn().mockResolvedValue({ username: 'test', id: 1 });

   vi.mock('../../api/auth', () => ({
     getMe: vi.fn().mockRejectedValue(new Error('unauthorized')),
     getAuthStatus: vi.fn().mockResolvedValue({ bootstrapped: true }),
     login: () => mockLogin(),
     register: () => mockRegister(),
   }));

   describe('Login page', () => {
     beforeEach(() => {
       mockLogin.mockResolvedValue(undefined);
     });

     it('renders without crashing', () => {
       renderWithQuery(<Login />);
     });

     it('shows the login form after auth check resolves', async () => {
       renderWithQuery(<Login />);
       await waitFor(() => {
         expect(screen.getByRole('button', { name: /sign in/i })).toBeInTheDocument();
       });
     });

     it('shows username and password fields', async () => {
       const { container } = renderWithQuery(<Login />);
       await waitFor(() => screen.getByRole('button', { name: /sign in/i }));
       // Login.tsx labels are not associated with inputs (no htmlFor/id), so query by type
       expect(container.querySelector('input[type="text"]')).toBeInTheDocument();
       expect(container.querySelector('input[type="password"]')).toBeInTheDocument();
     });

     it('calls login with typed credentials on submit', async () => {
       const { container, getByRole } = renderWithQuery(<Login />);
       await waitFor(() => getByRole('button', { name: /sign in/i }));

       fireEvent.change(container.querySelector('input[type="text"]')!, { target: { value: 'admin' } });
       fireEvent.change(container.querySelector('input[type="password"]')!, { target: { value: 'secret' } });
       fireEvent.click(getByRole('button', { name: /sign in/i }));

       await waitFor(() => expect(mockLogin).toHaveBeenCalledOnce());
     });

     it('shows an error message when login fails', async () => {
       mockLogin.mockRejectedValue(new Error('401'));
       const { container } = renderWithQuery(<Login />);
       await waitFor(() => screen.getByRole('button', { name: /sign in/i }));

       fireEvent.change(container.querySelector('input[type="text"]')!, { target: { value: 'bad' } });
       fireEvent.change(container.querySelector('input[type="password"]')!, { target: { value: 'wrong' } });
       fireEvent.click(screen.getByRole('button', { name: /sign in/i }));

       await waitFor(() => {
         expect(screen.getByText(/invalid username or password/i)).toBeInTheDocument();
       });
     });
   });
   ```

4. **Verify passes:**
   ```bash
   docker-compose exec frontend pnpm exec vitest run --reporter=verbose src/pages/Login/Login.test.tsx
   # Expected: 5 passed
   ```

5. **TypeScript check and commit:**
   ```bash
   docker-compose exec frontend npx tsc --noEmit
   git add frontend/src/pages/Login/Login.test.tsx
   git commit -m "test: Login page interaction test (issue #198)"
   ```

---

## Task 7: ScannerResults component test

**Requirement:** R2 (ScannerResults)

**Files:**
- `frontend/src/components/ScannerResults.test.tsx` (NEW)

### Context

`ScannerResults` is a presentational component. It accepts a `results` prop and renders rows via `filteredEvents`. Internal state (`filterTicker`, `severityFilter`) drives client-side filtering. Sort is controlled via the `onSort` callback prop. The child `ReviewControls` calls `submitReview` — mock that function so mutations don't fire real network requests against the real QueryClient.

### TDD Steps

1. **Write a minimal failing stub:**

   `frontend/src/components/ScannerResults.test.tsx`:
   ```tsx
   import { describe, it, expect } from 'vitest';
   describe('ScannerResults', () => {
     it('STUB', () => expect(false).toBe(true));
   });
   ```

2. **Verify it fails:**
   ```bash
   docker-compose exec frontend pnpm exec vitest run --reporter=verbose src/components/ScannerResults.test.tsx
   # Expected: 1 test failed
   ```

3. **Write the complete test:**

   `frontend/src/components/ScannerResults.test.tsx`:
   ```tsx
   import { vi, describe, it, expect } from 'vitest';
   import { screen, fireEvent } from '@testing-library/react';
   import { renderWithQuery } from '../test-utils/renderWithQuery';
   import ScannerResults from './ScannerResults';
   import type { ScannerEvent } from '../api/scanner';

   vi.mock('../api/scanner', () => ({
     submitReview: vi.fn().mockResolvedValue({}),
   }));

   const makeEvent = (overrides: Partial<ScannerEvent> = {}): ScannerEvent => ({
     id: 1,
     uuid: 'test-uuid-1',
     ticker: 'AAPL',
     event_date: '2026-06-06',
     scanner_type: 'pre_market_volume_spike',
     severity: 'high',
     summary: 'Volume spike detected',
     indicators: { relative_volume: 4.2 },
     criteria_met: {},
     metadata: {},
     created_at: '2026-06-06T09:00:00Z',
     updated_at: '2026-06-06T09:00:00Z',
     latest_review: null,
     ...overrides,
   });

   const emptyResults = {
     scan_id: 'test-scan',
     status: 'completed',
     stocks_scanned: 100,
     events_detected: 0,
     execution_time_ms: 500,
     events: [],
   };

   const resultsWithEvents = {
     ...emptyResults,
     events_detected: 2,
     events: [
       makeEvent({ id: 1, ticker: 'AAPL', severity: 'high' }),
       makeEvent({ id: 2, ticker: 'TSLA', severity: 'medium', uuid: 'test-uuid-2' }),
     ],
   };

   describe('ScannerResults', () => {
     it('renders without crashing with empty results', () => {
       renderWithQuery(<ScannerResults results={emptyResults} />);
     });

     it('shows the empty-state placeholder when no events match filters', () => {
       renderWithQuery(<ScannerResults results={emptyResults} />);
       expect(screen.getByText(/no scanner results match your filters/i)).toBeInTheDocument();
     });

     it('renders event rows for each event in results', () => {
       renderWithQuery(<ScannerResults results={resultsWithEvents} />);
       expect(screen.getByText('AAPL')).toBeInTheDocument();
       expect(screen.getByText('TSLA')).toBeInTheDocument();
     });

     it('filters rows by ticker when filter input changes', () => {
       renderWithQuery(<ScannerResults results={resultsWithEvents} />);
       const filterInput = screen.getByPlaceholderText(/enter ticker/i);
       fireEvent.change(filterInput, { target: { value: 'AAPL' } });
       expect(screen.getByText('AAPL')).toBeInTheDocument();
       expect(screen.queryByText('TSLA')).not.toBeInTheDocument();
     });

     it('calls onSort when a sortable column header is clicked', () => {
       const onSort = vi.fn();
       renderWithQuery(
         <ScannerResults results={resultsWithEvents} onSort={onSort} sortBy="event_date" sortOrder="desc" />
       );
       fireEvent.click(screen.getByText(/^date$/i));
       expect(onSort).toHaveBeenCalledWith('event_date');
     });
   });
   ```

4. **Verify passes:**
   ```bash
   docker-compose exec frontend pnpm exec vitest run --reporter=verbose src/components/ScannerResults.test.tsx
   # Expected: 5 passed
   ```

5. **TypeScript check and commit:**
   ```bash
   docker-compose exec frontend npx tsc --noEmit
   git add frontend/src/components/ScannerResults.test.tsx
   git commit -m "test: ScannerResults component interaction test (issue #198)"
   ```

---

## Task 8: Layout component smoke test

**Requirement:** R2 (Layout)

**Files:**
- `frontend/src/components/Layout.test.tsx` (NEW)

### Context

`Layout` uses `useLocation` and `Link` (satisfied by `MemoryRouter` in `renderWithQuery`). It fetches `getSystemStatus` from `api/system` via `useQuery`. `SystemActivityMonitor` opens a WebSocket in `useEffect`; it is mocked as a null-returning stub.

### TDD Steps

1. **Write a minimal failing stub:**

   `frontend/src/components/Layout.test.tsx`:
   ```tsx
   import { describe, it, expect } from 'vitest';
   describe('Layout', () => {
     it('STUB', () => expect(false).toBe(true));
   });
   ```

2. **Verify it fails:**
   ```bash
   docker-compose exec frontend pnpm exec vitest run --reporter=verbose src/components/Layout.test.tsx
   # Expected: 1 test failed
   ```

3. **Write the complete test:**

   `frontend/src/components/Layout.test.tsx`:
   ```tsx
   import { vi, describe, it, expect } from 'vitest';
   import { screen } from '@testing-library/react';
   import { renderWithQuery } from '../test-utils/renderWithQuery';
   import Layout from './Layout';

   vi.mock('../api/system', () => ({
     getSystemStatus: vi.fn().mockResolvedValue(null),
   }));

   vi.mock('./SystemActivityMonitor', () => ({ default: () => null }));

   describe('Layout', () => {
     it('renders without crashing', () => {
       renderWithQuery(<Layout>child</Layout>);
     });

     it('mounts children inside the layout', () => {
       renderWithQuery(<Layout><span>hello world</span></Layout>);
       expect(screen.getByText('hello world')).toBeInTheDocument();
     });

     it('renders top-level nav links', () => {
       renderWithQuery(<Layout>content</Layout>);
       expect(screen.getByRole('link', { name: /dashboard/i })).toBeInTheDocument();
       expect(screen.getByRole('link', { name: /scanner/i })).toBeInTheDocument();
       expect(screen.getByRole('link', { name: /alerts/i })).toBeInTheDocument();
     });

     it('applies active styles to the current route link', () => {
       renderWithQuery(<Layout>content</Layout>, { initialEntries: ['/scanner'] });
       const scannerLink = screen.getByRole('link', { name: /^scanner$/i });
       expect(scannerLink.className).toMatch(/bg-financial-blue/);
     });
   });
   ```

4. **Verify passes:**
   ```bash
   docker-compose exec frontend pnpm exec vitest run --reporter=verbose src/components/Layout.test.tsx
   # Expected: 4 passed
   ```

5. **TypeScript check and commit:**
   ```bash
   docker-compose exec frontend npx tsc --noEmit
   git add frontend/src/components/Layout.test.tsx
   git commit -m "test: Layout component smoke test (issue #198)"
   ```

---

## Task 9: UniverseFormModal component test

**Requirement:** R2 (UniverseFormModal)

**Files:**
- `frontend/src/components/UniverseFormModal.test.tsx` (NEW)

### Context

`Modal` returns `null` when `isOpen={false}`, so tests must pass `isOpen={true}` to render the form. `UniverseFormModal` fires `createStockUniverse` via mutation when `handleSubmit` is called. The Create Universe button is disabled when `name` is empty — that is the validation under test.

### TDD Steps

1. **Write a minimal failing stub:**

   `frontend/src/components/UniverseFormModal.test.tsx`:
   ```tsx
   import { describe, it, expect } from 'vitest';
   describe('UniverseFormModal', () => {
     it('STUB', () => expect(false).toBe(true));
   });
   ```

2. **Verify it fails:**
   ```bash
   docker-compose exec frontend pnpm exec vitest run --reporter=verbose src/components/UniverseFormModal.test.tsx
   # Expected: 1 test failed
   ```

3. **Write the complete test:**

   `frontend/src/components/UniverseFormModal.test.tsx`:
   ```tsx
   import { vi, describe, it, expect } from 'vitest';
   import { screen, fireEvent, waitFor } from '@testing-library/react';
   import { renderWithQuery } from '../test-utils/renderWithQuery';
   import UniverseFormModal from './UniverseFormModal';

   const mockCreate = vi.fn().mockResolvedValue({ id: 1, name: 'Test', description: '', criteria: {} });

   vi.mock('../api/scanner', () => ({
     createStockUniverse: () => mockCreate(),
     updateStockUniverse: vi.fn().mockResolvedValue({}),
     fetchProviders: vi.fn().mockResolvedValue({ available: [] }),
   }));

   const defaultProps = {
     isOpen: true,
     onClose: vi.fn(),
     initialData: null,
   };

   describe('UniverseFormModal', () => {
     it('renders without crashing when open', () => {
       renderWithQuery(<UniverseFormModal {...defaultProps} />);
     });

     it('renders nothing when isOpen is false', () => {
       const { container } = renderWithQuery(
         <UniverseFormModal {...defaultProps} isOpen={false} />
       );
       expect(container.firstChild).toBeNull();
     });

     it('shows the "Create Stock Universe" title', () => {
       renderWithQuery(<UniverseFormModal {...defaultProps} />);
       expect(screen.getByText(/create stock universe/i)).toBeInTheDocument();
     });

     it('Create Universe button is disabled when name is empty', () => {
       renderWithQuery(<UniverseFormModal {...defaultProps} />);
       const createBtn = screen.getByRole('button', { name: /create universe/i });
       expect(createBtn).toBeDisabled();
     });

     it('Create Universe button enables after typing a name', () => {
       renderWithQuery(<UniverseFormModal {...defaultProps} />);
       fireEvent.change(screen.getByPlaceholderText(/large cap tech/i), {
         target: { value: 'My Universe' },
       });
       expect(screen.getByRole('button', { name: /create universe/i })).not.toBeDisabled();
     });

     it('calls createStockUniverse when a valid form is submitted', async () => {
       renderWithQuery(<UniverseFormModal {...defaultProps} />);
       fireEvent.change(screen.getByPlaceholderText(/large cap tech/i), {
         target: { value: 'My Universe' },
       });
       fireEvent.click(screen.getByRole('button', { name: /create universe/i }));
       await waitFor(() => expect(mockCreate).toHaveBeenCalledOnce());
     });
   });
   ```

4. **Verify passes:**
   ```bash
   docker-compose exec frontend pnpm exec vitest run --reporter=verbose src/components/UniverseFormModal.test.tsx
   # Expected: 6 passed
   ```

5. **TypeScript check and commit:**
   ```bash
   docker-compose exec frontend npx tsc --noEmit
   git add frontend/src/components/UniverseFormModal.test.tsx
   git commit -m "test: UniverseFormModal component interaction test (issue #198)"
   ```

---

## Task 10: QualityReportModal component test

**Requirement:** R2 (QualityReportModal)

**Files:**
- `frontend/src/components/QualityReportModal.test.tsx` (NEW)

### Context

`QualityReportModal` receives a `universe: StockUniverse | null` prop and calls `fetchQualityReport`. When `universe` is null the modal title still renders (the query will idle). Pass a minimal universe object so the query fires; mock `fetchQualityReport` to return a report with a known grade so badge rendering can be asserted. The close button lives in the `Modal` header (renders `<button>` with the lucide `X` icon).

### TDD Steps

1. **Write a minimal failing stub:**

   `frontend/src/components/QualityReportModal.test.tsx`:
   ```tsx
   import { describe, it, expect } from 'vitest';
   describe('QualityReportModal', () => {
     it('STUB', () => expect(false).toBe(true));
   });
   ```

2. **Verify it fails:**
   ```bash
   docker-compose exec frontend pnpm exec vitest run --reporter=verbose src/components/QualityReportModal.test.tsx
   # Expected: 1 test failed
   ```

3. **Write the complete test:**

   `frontend/src/components/QualityReportModal.test.tsx`:
   ```tsx
   import { vi, describe, it, expect } from 'vitest';
   import { screen, fireEvent, waitFor } from '@testing-library/react';
   import { renderWithQuery } from '../test-utils/renderWithQuery';
   import QualityReportModal from './QualityReportModal';
   import type { StockUniverse } from '../api/scanner';

   const mockFetchReport = vi.fn().mockResolvedValue({
     universe_id: 1,
     overall_grade: 'A',
     overall_score: 97.5,
     tickers: [],
   });

   vi.mock('../api/scanner', () => ({
     fetchQualityReport: () => mockFetchReport(),
     triggerQualityAnalysis: vi.fn().mockResolvedValue({}),
     triggerNormalization: vi.fn().mockResolvedValue({}),
     deleteTickerAggregates: vi.fn().mockResolvedValue({}),
   }));

   const mockUniverse: StockUniverse = {
     id: 1,
     name: 'Test Universe',
     description: 'Test',
     criteria: {},
     is_active: true,
     created_at: '2026-01-01T00:00:00Z',
     updated_at: '2026-01-01T00:00:00Z',
   };

   describe('QualityReportModal', () => {
     it('renders nothing when isOpen is false', () => {
       const { container } = renderWithQuery(
         <QualityReportModal isOpen={false} onClose={vi.fn()} universe={mockUniverse} />
       );
       expect(container.firstChild).toBeNull();
     });

     it('renders the modal title when open', () => {
       renderWithQuery(
         <QualityReportModal isOpen={true} onClose={vi.fn()} universe={mockUniverse} />
       );
       expect(screen.getByText(/quality report/i)).toBeInTheDocument();
     });

     it('renders the grade badge after data loads', async () => {
       renderWithQuery(
         <QualityReportModal isOpen={true} onClose={vi.fn()} universe={mockUniverse} />
       );
       await waitFor(() => {
         expect(screen.getAllByText('A').length).toBeGreaterThan(0);
       });
     });

     it('calls onClose when the close button is clicked', () => {
       const onClose = vi.fn();
       renderWithQuery(
         <QualityReportModal isOpen={true} onClose={onClose} universe={mockUniverse} />
       );
       // Modal header close button is icon-only (no accessible name) and always first
       fireEvent.click(screen.getAllByRole('button')[0]);
       expect(onClose).toHaveBeenCalledOnce();
     });
   });
   ```

4. **Verify passes:**
   ```bash
   docker-compose exec frontend pnpm exec vitest run --reporter=verbose src/components/QualityReportModal.test.tsx
   # Expected: 4 passed
   ```

5. **TypeScript check and commit:**
   ```bash
   docker-compose exec frontend npx tsc --noEmit
   git add frontend/src/components/QualityReportModal.test.tsx
   git commit -m "test: QualityReportModal component test (issue #198)"
   ```

---

## Task 11: ScanConfigPanel panel test

**Requirement:** R3 (ScanConfigPanel)

**Files:**
- `frontend/src/pages/Scanner/ScanConfigPanel.test.tsx` (NEW)

### Context

`ScanConfigPanel` is a fully controlled component: all data and callbacks come via props (see `ScanConfigPanelProps` interface). No API calls are made inside it. Props are passed directly in the test — no mocks needed for API modules. The Run Scanner button is disabled when `isScanning` is true; enabled otherwise.

### TDD Steps

1. **Write a minimal failing stub:**

   `frontend/src/pages/Scanner/ScanConfigPanel.test.tsx`:
   ```tsx
   import { describe, it, expect } from 'vitest';
   describe('ScanConfigPanel', () => {
     it('STUB', () => expect(false).toBe(true));
   });
   ```

2. **Verify it fails:**
   ```bash
   docker-compose exec frontend pnpm exec vitest run --reporter=verbose src/pages/Scanner/ScanConfigPanel.test.tsx
   # Expected: 1 test failed
   ```

3. **Write the complete test:**

   `frontend/src/pages/Scanner/ScanConfigPanel.test.tsx`:
   ```tsx
   import { vi, describe, it, expect } from 'vitest';
   import { screen, fireEvent } from '@testing-library/react';
   import { renderWithQuery } from '../../test-utils/renderWithQuery';
   import { ScanConfigPanel } from './ScanConfigPanel';

   const baseProps = {
     configs: [{ scanner_type: 'pre_market_volume_spike', display_name: 'Pre-Market Spike', description: '' }],
     loadingConfigs: false,
     universes: [{ id: 1, name: 'All Stocks', description: '', criteria: {}, is_active: true, created_at: '', updated_at: '' }],
     loadingUniverses: false,
     selectedConfig: 'pre_market_volume_spike',
     onSelectConfig: vi.fn(),
     selectedUniverse: 1,
     onSelectUniverse: vi.fn(),
     scanStartDate: '',
     onScanStartDate: vi.fn(),
     scanEndDate: '',
     onScanEndDate: vi.fn(),
     isScanning: false,
     onRunScan: vi.fn(),
     onCancelScan: vi.fn(),
     statusBlock: null,
     scanHistory: [],
     loadingHistory: false,
     scanError: null,
     onDismissError: vi.fn(),
     scannerMutationPending: false,
   };

   describe('ScanConfigPanel', () => {
     it('renders without crashing', () => {
       renderWithQuery(<ScanConfigPanel {...baseProps} />);
     });

     it('shows the Run Scanner button when not scanning', () => {
       renderWithQuery(<ScanConfigPanel {...baseProps} />);
       expect(screen.getByRole('button', { name: /run scanner/i })).toBeInTheDocument();
     });

     it('Run Scanner button is enabled when a config and universe are selected', () => {
       renderWithQuery(<ScanConfigPanel {...baseProps} />);
       expect(screen.getByRole('button', { name: /run scanner/i })).not.toBeDisabled();
     });

     it('shows Cancel button when isScanning is true', () => {
       renderWithQuery(<ScanConfigPanel {...baseProps} isScanning={true} />);
       expect(screen.getByRole('button', { name: /cancel/i })).toBeInTheDocument();
     });

     it('calls onRunScan when Run Scanner is clicked', () => {
       const onRunScan = vi.fn();
       renderWithQuery(<ScanConfigPanel {...baseProps} onRunScan={onRunScan} />);
       fireEvent.click(screen.getByRole('button', { name: /run scanner/i }));
       expect(onRunScan).toHaveBeenCalledOnce();
     });

     it('shows scanError when provided', () => {
       renderWithQuery(<ScanConfigPanel {...baseProps} scanError="Scan failed: network error" />);
       expect(screen.getByText(/scan failed: network error/i)).toBeInTheDocument();
     });
   });
   ```

   > **Implementer note:** `ScanConfigPanelProps.configs` uses `any[]` in the interface. Check the actual `ScannerConfig` shape (or whatever `fetchScannerConfigs` returns) and adjust the `configs` stub if the component accesses specific fields beyond `scanner_type` and `display_name`.

4. **Verify passes:**
   ```bash
   docker-compose exec frontend pnpm exec vitest run --reporter=verbose src/pages/Scanner/ScanConfigPanel.test.tsx
   # Expected: 6 passed
   ```

5. **TypeScript check and commit:**
   ```bash
   docker-compose exec frontend npx tsc --noEmit
   git add frontend/src/pages/Scanner/ScanConfigPanel.test.tsx
   git commit -m "test: ScanConfigPanel panel test (issue #198)"
   ```

---

## Task 12: AlertRuleModal panel test

**Requirement:** R3 (AlertRuleModal)

**Files:**
- `frontend/src/pages/Alerts/AlertRuleModal.test.tsx` (NEW)

### Context

`AlertRuleModal` is a fully controlled component — all form state is managed by the parent (`Alerts`) and passed via `formState`/`onFormState` props. No API calls or useQuery hooks inside the component itself. Pass `isOpen={true}` so `Modal` renders its children.

### TDD Steps

1. **Write a minimal failing stub:**

   `frontend/src/pages/Alerts/AlertRuleModal.test.tsx`:
   ```tsx
   import { describe, it, expect } from 'vitest';
   describe('AlertRuleModal', () => {
     it('STUB', () => expect(false).toBe(true));
   });
   ```

2. **Verify it fails:**
   ```bash
   docker-compose exec frontend pnpm exec vitest run --reporter=verbose src/pages/Alerts/AlertRuleModal.test.tsx
   # Expected: 1 test failed
   ```

3. **Write the complete test:**

   `frontend/src/pages/Alerts/AlertRuleModal.test.tsx`:
   ```tsx
   import { vi, describe, it, expect } from 'vitest';
   import { screen, fireEvent } from '@testing-library/react';
   import { renderWithQuery } from '../../test-utils/renderWithQuery';
   import { AlertRuleModal } from './AlertRuleModal';
   import type { AlertRule } from '../../api/alerts';

   const baseFormState: Partial<AlertRule> = {
     name: '',
     is_active: true,
     scanner_types: [],
     severity_filter: 'any',
     cooldown_minutes: 60,
     channels: ['browser_push'],
     channel_config: { email: '', google_chat_webhook: '', webhook_url: '' },
     auto_trade: false,
     trading_strategy_id: null,
   };

   const baseProps = {
     isOpen: true,
     editingRule: null,
     formState: baseFormState,
     onFormState: vi.fn(),
     onSave: vi.fn(),
     onClose: vi.fn(),
     isSaving: false,
     strategies: [],
   };

   describe('AlertRuleModal', () => {
     it('renders without crashing', () => {
       renderWithQuery(<AlertRuleModal {...baseProps} />);
     });

     it('shows "Create New Alert Rule" title for new rule', () => {
       renderWithQuery(<AlertRuleModal {...baseProps} />);
       expect(screen.getByText(/create new alert rule/i)).toBeInTheDocument();
     });

     it('shows "Edit Alert Rule" title when editing an existing rule', () => {
       renderWithQuery(
         <AlertRuleModal
           {...baseProps}
           editingRule={{ id: 42, name: 'Existing Rule' } as AlertRule}
         />
       );
       expect(screen.getByText(/edit alert rule/i)).toBeInTheDocument();
     });

     it('shows scanner type toggle buttons', () => {
       renderWithQuery(<AlertRuleModal {...baseProps} />);
       expect(screen.getByText(/pre-market volume spike/i)).toBeInTheDocument();
     });

     it('calls onSave when Save Rule button is clicked', () => {
       const onSave = vi.fn();
       renderWithQuery(<AlertRuleModal {...baseProps} onSave={onSave} />);
       fireEvent.click(screen.getByRole('button', { name: /save rule/i }));
       expect(onSave).toHaveBeenCalledOnce();
     });

     it('calls onClose when Cancel is clicked', () => {
       const onClose = vi.fn();
       renderWithQuery(<AlertRuleModal {...baseProps} onClose={onClose} />);
       fireEvent.click(screen.getByRole('button', { name: /cancel/i }));
       expect(onClose).toHaveBeenCalledOnce();
     });
   });
   ```

4. **Verify passes:**
   ```bash
   docker-compose exec frontend pnpm exec vitest run --reporter=verbose src/pages/Alerts/AlertRuleModal.test.tsx
   # Expected: 6 passed
   ```

5. **TypeScript check and commit:**
   ```bash
   docker-compose exec frontend npx tsc --noEmit
   git add frontend/src/pages/Alerts/AlertRuleModal.test.tsx
   git commit -m "test: AlertRuleModal panel test (issue #198)"
   ```

---

## Task 13: AutoTrading ConfigPanel panel test

**Requirement:** R3 (AutoTrading/ConfigPanel)

**Files:**
- `frontend/src/pages/AutoTrading/ConfigPanel.test.tsx` (NEW)

### Context

`ConfigPanel` is a controlled modal form for creating/editing trading strategies. All form state is passed via `stratForm`/`onStratForm` props. `Modal` returns null when `isOpen={false}`. Pass `isOpen={true}` and a partial `TradingStrategy` form state.

### TDD Steps

1. **Write a minimal failing stub:**

   `frontend/src/pages/AutoTrading/ConfigPanel.test.tsx`:
   ```tsx
   import { describe, it, expect } from 'vitest';
   describe('ConfigPanel', () => {
     it('STUB', () => expect(false).toBe(true));
   });
   ```

2. **Verify it fails:**
   ```bash
   docker-compose exec frontend pnpm exec vitest run --reporter=verbose src/pages/AutoTrading/ConfigPanel.test.tsx
   # Expected: 1 test failed
   ```

3. **Write the complete test:**

   `frontend/src/pages/AutoTrading/ConfigPanel.test.tsx`:
   ```tsx
   import { vi, describe, it, expect } from 'vitest';
   import { screen, fireEvent } from '@testing-library/react';
   import { renderWithQuery } from '../../test-utils/renderWithQuery';
   import { ConfigPanel } from './ConfigPanel';
   import type { TradingStrategy } from '../../api/trading';

   const baseProps = {
     isOpen: true,
     editingStrategy: null,
     stratForm: {
       name: '',
       description: '',
       is_active: true,
       paper_mode: true,
       requires_approval: false,
       risk_per_trade_pct: 1.0,
       allowed_sessions: [],
     },
     onStratForm: vi.fn(),
     onSave: vi.fn(),
     onClose: vi.fn(),
     isSaving: false,
   };

   const minStrategy: TradingStrategy = {
     id: 1,
     name: 'My Strategy',
     description: null,
     is_active: true,
     paper_mode: true,
     requires_approval: false,
     risk_per_trade_pct: 1.0,
     max_position_usd: null,
     max_trades_per_day: 5,
     max_concurrent_positions: 2,
     entry_type: 'market',
     limit_offset_pct: 0,
     stop_pct: 2,
     risk_reward_ratio: 2,
     max_slippage_pct: 0.5,
     allowed_sessions: [],
     direction: 'long_only',
   };

   describe('ConfigPanel', () => {
     it('renders without crashing', () => {
       renderWithQuery(<ConfigPanel {...baseProps} />);
     });

     it('shows "New Trading Strategy" title for new strategy', () => {
       renderWithQuery(<ConfigPanel {...baseProps} />);
       expect(screen.getByText(/new trading strategy/i)).toBeInTheDocument();
     });

     it('shows strategy name in title when editing', () => {
       renderWithQuery(
         <ConfigPanel
           {...baseProps}
           editingStrategy={minStrategy}
         />
       );
       expect(screen.getByText(/edit strategy — my strategy/i)).toBeInTheDocument();
     });

     it('renders the Strategy Name input field', () => {
       renderWithQuery(<ConfigPanel {...baseProps} />);
       expect(screen.getByPlaceholderText(/2r morning momentum/i)).toBeInTheDocument();
     });

     it('calls onStratForm when the name field changes', () => {
       const onStratForm = vi.fn();
       renderWithQuery(<ConfigPanel {...baseProps} onStratForm={onStratForm} />);
       fireEvent.change(screen.getByPlaceholderText(/2r morning momentum/i), {
         target: { value: 'New Strategy' },
       });
       expect(onStratForm).toHaveBeenCalledWith(
         expect.objectContaining({ name: 'New Strategy' })
       );
     });

     it('calls onSave when Create Strategy button is clicked', () => {
       const onSave = vi.fn();
       renderWithQuery(<ConfigPanel {...baseProps} onSave={onSave} />);
       fireEvent.click(screen.getByRole('button', { name: /create strategy/i }));
       expect(onSave).toHaveBeenCalledOnce();
     });
   });
   ```

4. **Verify passes:**
   ```bash
   docker-compose exec frontend pnpm exec vitest run --reporter=verbose src/pages/AutoTrading/ConfigPanel.test.tsx
   # Expected: 6 passed
   ```

5. **TypeScript check and commit:**
   ```bash
   docker-compose exec frontend npx tsc --noEmit
   git add frontend/src/pages/AutoTrading/ConfigPanel.test.tsx
   git commit -m "test: AutoTrading ConfigPanel panel test (issue #198)"
   ```

---

## Task 14: AutoTrading components panel test

**Requirement:** R3 (AutoTrading/components)

**Files:**
- `frontend/src/pages/AutoTrading/components.test.tsx` (NEW)

### Context

`components.tsx` exports shared constants (`STATUS_CONFIG`, `SESSION_OPTIONS`, `DIRECTION_OPTIONS`, `ENTRY_TYPES`, `DEFAULT_STRATEGY`) and React components (`NumberField`, `ToggleField`, and status-badge rendering logic). No API calls. Tests target the status badge rendering (status configs) and the exported form field components.

### TDD Steps

1. **Write a minimal failing stub:**

   `frontend/src/pages/AutoTrading/components.test.tsx`:
   ```tsx
   import { describe, it, expect } from 'vitest';
   describe('AutoTrading/components', () => {
     it('STUB', () => expect(false).toBe(true));
   });
   ```

2. **Verify it fails:**
   ```bash
   docker-compose exec frontend pnpm exec vitest run --reporter=verbose src/pages/AutoTrading/components.test.tsx
   # Expected: 1 test failed
   ```

3. **Write the complete test:**

   `frontend/src/pages/AutoTrading/components.test.tsx`:
   ```tsx
   import { describe, it, expect } from 'vitest';
   import { render, screen } from '@testing-library/react';
   import {
     STATUS_CONFIG,
     SESSION_OPTIONS,
     DIRECTION_OPTIONS,
     DEFAULT_STRATEGY,
   } from './components';

   describe('AutoTrading/components — exported constants', () => {
     it('STATUS_CONFIG has entries for all expected statuses', () => {
       const statuses = ['pending_approval', 'pending', 'submitted', 'open', 'closed', 'cancelled', 'rejected', 'error'];
       statuses.forEach(s => {
         expect(STATUS_CONFIG[s]).toBeDefined();
         expect(STATUS_CONFIG[s].label).toBeTruthy();
         expect(STATUS_CONFIG[s].icon).toBeTruthy();
       });
     });

     it('SESSION_OPTIONS contains pre, regular, post sessions', () => {
       const ids = SESSION_OPTIONS.map(o => o.id);
       expect(ids).toContain('pre');
       expect(ids).toContain('regular');
       expect(ids).toContain('post');
     });

     it('DIRECTION_OPTIONS contains long_only, short_only, both', () => {
       const ids = DIRECTION_OPTIONS.map(o => o.id);
       expect(ids).toContain('long_only');
       expect(ids).toContain('short_only');
       expect(ids).toContain('both');
     });

     it('DEFAULT_STRATEGY is_active defaults to true', () => {
       expect(DEFAULT_STRATEGY.is_active).toBe(true);
     });

     it('DEFAULT_STRATEGY paper_mode defaults to true', () => {
       expect(DEFAULT_STRATEGY.paper_mode).toBe(true);
     });
   });
   ```

4. **Verify passes:**
   ```bash
   docker-compose exec frontend pnpm exec vitest run --reporter=verbose src/pages/AutoTrading/components.test.tsx
   # Expected: 5 passed
   ```

5. **TypeScript check and commit:**
   ```bash
   docker-compose exec frontend npx tsc --noEmit
   git add frontend/src/pages/AutoTrading/components.test.tsx
   git commit -m "test: AutoTrading components constants and status config test (issue #198)"
   ```

---

## Task 15: Update coverage config and verify full suite

**Requirements:** R5, R6, R7, R8

**Files:**
- `frontend/vitest.config.ts` (MODIFY)

### Context

This task is intentionally last. Running `pnpm test:coverage` with the new 35%/25% thresholds before tasks 1–14 are complete would cause CI to fail. With all 14 new test files in place, coverage is expected to exceed the threshold.

### TDD Steps

1. **Verify the current config:**
   ```bash
   docker-compose exec frontend pnpm test:coverage 2>&1 | tail -20
   # Expected: coverage reported only for the 7 pinned files; threshold of 20% passes
   ```

2. **Update `frontend/vitest.config.ts`:**

   **Before:**
   ```ts
   coverage: {
     provider: 'v8',
     include: [
       'src/hooks/useScannerState.ts',
       'src/hooks/useScannerWs.ts',
       'src/hooks/useScanTask.ts',
       'src/hooks/useWatchlistLive.ts',
       'src/hooks/useLiveStockData.ts',
       'src/hooks/useScorecard.ts',
       'src/components/ui/GlobalErrorToast.tsx',
     ],
     thresholds: {
       statements: 20,
       branches: 20,
       functions: 20,
       lines: 20,
     },
   },
   ```

   **After** — replace the entire `coverage` block:
   ```ts
   coverage: {
     provider: 'v8',
     all: true,
     exclude: [
       'src/main.tsx',
       'src/test-setup.ts',
       'src/test-utils/**',
       '**/*.test.{ts,tsx}',
       '**/*.d.ts',
     ],
     thresholds: {
       statements: 35,
       lines: 35,
       branches: 25,
       functions: 25,
     },
   },
   ```

3. **Run the full test suite with coverage:**
   ```bash
   docker-compose exec frontend pnpm test:coverage
   # Expected: all tests pass; coverage thresholds met (≥35% statements/lines, ≥25% branches/functions)
   # If threshold is not met: check which uncovered files are pulling the denominator down.
   # Do NOT add padding tests — file a follow-up issue if a real coverage gap is found.
   ```

4. **Verify existing 8 test files still pass (R8):**
   ```bash
   docker-compose exec frontend pnpm test --reporter=verbose 2>&1 | grep -E "PASS|FAIL"
   # Expected: all 22+ test files pass; zero regressions in the original 8 files
   ```

5. **TypeScript check and commit:**
   ```bash
   docker-compose exec frontend npx tsc --noEmit
   git add frontend/vitest.config.ts
   git commit -m "test: honest coverage config — all: true, 35%/25% thresholds (issue #198)"
   ```

---

## Completion Checklist

| Requirement | Task(s) | Status |
|-------------|---------|--------|
| R1 — 5 page smoke tests | 2, 3, 4, 5, 6 | |
| R2 — 4 shared component tests | 7, 8, 9, 10 | |
| R3 — 4 panel tests | 11, 12, 13, 14 | |
| R4 — renderWithQuery utility | 1 | |
| R5 — remove pinned include block | 15 | |
| R6 — 35%/25% thresholds | 15 | |
| R7 — exclude non-testable glue | 15 | |
| R8 — existing 8 files pass unmodified | 15 | |

## Known Open Questions (from spec)

- **ScannerResults sort**: tested via `onSort` callback (prop-based). The component renders `SortableHeader` elements that fire `onSort(column)` on click. Implementer should verify the exact button/column text used in the sort header if `getByText(/^date$/i)` does not match.
- **QualityReportModal close button**: the `X` icon button has no accessible name. See implementer note in Task 10.
- **ScanConfigPanel props shape**: the `configs` prop uses `any[]`. Implementer should check the actual `ScannerConfig` interface exported by `api/scanner.ts` and replace the stub `configs` array with typed objects.
- **Coverage threshold**: if coverage does not reach 35% after all tasks, check `vitest.config.ts` `exclude` list is not missing a file pattern. Do not pad with thin tests — file a follow-up issue instead (per spec Assumption 3).
