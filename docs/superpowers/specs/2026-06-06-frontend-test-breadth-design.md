# Frontend Test Breadth + Honest Coverage — Design Spec

**Date:** 2026-06-06
**Issue:** #198 — [arch-v2][MED] Expand frontend test breadth (pages/components) + honest coverage
**Status:** Spec generated — pending review
**Author:** MarketHawk Refinement Pipeline

## Overview

Vitest and React Testing Library are installed and 8 test files exist, but the
coverage is misleading: only 6/6 hooks, 0/15 pages, and 1/37 components have
tests. Worse, `vitest.config.ts` hard-pins `coverage.include` to 7 files with a
20% threshold — the headline number describes a cherry-picked slice, not the app.
This spec defines which pages and components to test, how to structure the tests,
and how to reconfigure coverage so the threshold is honest.

## Problem Statement

1. **Coverage illusion** — `coverage.include` naming 7 files means uncovered pages
   and components are invisible to the reporter. 40+ files can be at 0% without
   tripping any CI gate.
2. **Zero page tests** — no smoke-test exists for the 15 routes. A typo in an import
   or a missing provider wrapper can silently break a page in production.
3. **Zero component tests** (except `GlobalErrorToast`) — shared components like
   `ScannerResults` (400 lines) and `UniverseFormModal` (492 lines) carry real
   rendering and form logic that is untested.

## Requirements

| # | Requirement |
|---|-------------|
| R1 | Add smoke tests for the 5 highest-value page shells. |
| R2 | Add interaction tests for the 4 highest-value shared components in `src/components/`. |
| R3 | Add interaction tests for the 4 highest-value page-embedded panels. |
| R4 | Create a shared `renderWithQuery` test utility (QueryClient + MemoryRouter). |
| R5 | Remove the hand-pinned `coverage.include` block; add `all: true` so untested files appear at 0%. |
| R6 | Set global coverage thresholds: **35% statements/lines, 25% branches/functions**. |
| R7 | Explicitly exclude non-testable glue files from coverage denominator. |
| R8 | All existing 8 test files pass without modification. |

**Out of scope:** E2E tests (Playwright/Cypress), backend test changes, thin
pass-through panel wrappers (ResultsPanel at 28 lines, StrategyPanel at 53 lines),
and standalone api-wrapper hooks in `src/api/` (covered indirectly by smoke tests).

## Decisions (locked during brainstorming)

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Page test depth | Smoke tests (render + key headings) | Pages are thin orchestrators delegating to panels; interaction logic lives in panels and hooks |
| Mocking strategy | `vi.mock('../../api/*')` — mock API modules, use real React Query | Existing hook tests (useScorecard) already do this; keeps React Query cache/refetch behavior in the test |
| Router wrapper | Include `MemoryRouter` in shared util | Pages use `<Link>` and `useNavigate`; without it, `render` throws |
| React Query wrapper | Real `QueryClient` with `retry: false` | Pattern established in `useScorecard.test.ts`; avoids React Query mock brittleness |
| Shared util location | `src/test-utils/renderWithQuery.tsx` | Extends existing `src/test-utils/` (currently holds `MockWebSocket.ts`) |
| Coverage `all: true` | Yes | Without it, untested files are invisible — same problem as the pinned include |
| Coverage threshold | 35% statements/lines, 25% branches/functions | 91 non-test files in src; 40% forces thin-wrapper padding; 30% too easy given dense hooks already covered |
| Hooks | No new hook tests | All 6 hooks in `src/hooks/` already have `.test.ts` files; the issue's "6/12 untested hooks" count was stale |

## Scope Inventory

### Hook tests — already complete (no work needed)

All 6 hooks in `src/hooks/` have test files:
`useLiveStockData`, `useScanTask`, `useScannerState`, `useScannerWs`, `useScorecard`, `useWatchlistLive`

The issue's "6/12 hooks, cover remaining" criterion is satisfied by the current
state of the repo. No additional hook tests are required.

### New page smoke tests (5 files)

| Page | Location | Test type | Key assertions |
|------|----------|-----------|----------------|
| `Scanner` | `pages/Scanner/index.tsx` | Smoke | Renders without crashing; "Scanner" heading visible |
| `Alerts` | `pages/Alerts/index.tsx` | Smoke | Renders without crashing; "Alert Center" or similar heading |
| `AutoTrading` | `pages/AutoTrading/index.tsx` | Smoke | Renders without crashing; trading section present |
| `Dashboard` | `pages/Dashboard.tsx` | Smoke | Renders without crashing; key metric sections present |
| `Login` | `pages/Login/index.tsx` | Light interaction | Renders login form; submit with empty fields shows validation; redirects on success (mocked auth call) |

Test files co-located: `pages/Scanner/Scanner.test.tsx`, `pages/Alerts/Alerts.test.tsx`, etc.

### New shared component tests (4 files)

| Component | Location | Test type | Key cases |
|-----------|----------|-----------|-----------|
| `ScannerResults` | `components/ScannerResults.tsx` | Interaction | Renders event rows; sort controls change order; empty state shows placeholder |
| `UniverseFormModal` | `components/UniverseFormModal.tsx` | Interaction | Opens/closes; submits valid form; shows validation on empty name |
| `QualityReportModal` | `components/QualityReportModal.tsx` | Interaction | Renders grade/score; closes on button click |
| `Layout` | `components/Layout.tsx` | Smoke | Nav renders; children are mounted; active route link is styled |

### New panel tests (4 files)

| Panel | Location | Complexity | Key cases |
|-------|----------|------------|-----------|
| `ScanConfigPanel` | `pages/Scanner/ScanConfigPanel.tsx` | 186 lines | Config selects render; Run button triggers scan mutation |
| `AlertRuleModal` | `pages/Alerts/AlertRuleModal.tsx` | 298 lines | Form fields render; submit fires mutation with typed values |
| `AutoTrading/ConfigPanel` | `pages/AutoTrading/ConfigPanel.tsx` | 250 lines | Config form renders; save mutation wired |
| `AutoTrading/components` | `pages/AutoTrading/components.tsx` | 293 lines | Key sub-components render; status badges display correctly |

### Excluded from new tests (intentional)

- `Scanner/ResultsPanel.tsx` (28L) — pass-through to `ScannerResults`; covered transitively
- `Scanner/LiveProgressPanel.tsx` — thin progress wrapper
- `AutoTrading/StrategyPanel.tsx` (53L) — thin wrapper
- `src/api/*.ts` — thin axios factories; covered indirectly by page smoke tests
- Scorecard sub-components (`components/scorecard/*`) — assessed as low independent value

## Architecture

### Test utility: `src/test-utils/renderWithQuery.tsx`

```tsx
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { render } from '@testing-library/react';
import type { RenderOptions } from '@testing-library/react';

function makeQueryClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
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

### Page smoke test pattern

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
}));

describe('Scanner page', () => {
  it('renders without crashing', () => {
    renderWithQuery(<Scanner />);
  });

  it('shows loading state on initial render', () => {
    renderWithQuery(<Scanner />);
    // loading skeleton or spinner visible before data resolves
    expect(screen.getByRole('status') /* or getByTestId */).toBeInTheDocument();
  });
});
```

### Coverage config change

**Before** (current `vitest.config.ts`):
```ts
coverage: {
  provider: 'v8',
  include: [
    'src/hooks/useScannerState.ts',
    // ... 6 more pinned files
  ],
  thresholds: { statements: 20, branches: 20, functions: 20, lines: 20 },
}
```

**After:**
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
  thresholds: { statements: 35, lines: 35, branches: 25, functions: 25 },
}
```

`all: true` forces all source files into the report (at 0% when untested) so the
denominator is the full app, not just files touched by the test run.

## Alternatives Considered

### A. Full interaction tests for all pages
Comprehensive but impractical for an L-sized issue across 15 pages — most page
shells are thin orchestrators and the interaction logic lives in panels/hooks.
Smoke tests catch the highest-severity regressions (import errors, provider
misconfiguration, rendering crashes) for the lowest test-writing cost.

### B. Mock React Query entirely (swap `useQuery` with a mock)
Some projects mock the React Query hooks themselves rather than the API layer.
Rejected because the existing `useScorecard.test.ts` pattern (real QueryClient +
`vi.mock(api)`) already exists in this codebase and mocking React Query would
make tests fragile to hook renames/refactors.

### C. Raise threshold to 50%
Would require testing thin api wrappers and trivial UI components purely to clear
the bar — classic padding-test antipattern. 35%/25% is set to a level where only
meaningful test additions (the files in the inventory above) can move the needle.

## Assumptions

- **[ASSUMPTION]** React Router and QueryClient are not mocked globally in
  `test-setup.ts` — the shared renderWithQuery utility adds them per test. If a
  global provider is added to test-setup.ts in the future, the utility should be
  simplified.
- **[ASSUMPTION]** The page shells (`pages/Scanner/index.tsx`, etc.) are
  importable without crashing in jsdom — they should not depend on canvas or
  WebSocket at module load time. If a page imports `lightweight-charts` or similar
  canvas-dependent library at the top level, a `vi.mock` stub will be needed.
- **[ASSUMPTION]** The 35%/25% threshold is achievable with the planned 13
  test targets above. If actual coverage lands below 35% after all tests are
  written (due to large untested components like `QualityReportModal` being harder
  to test than estimated), the threshold should be reported accurately and a
  follow-up issue filed to ratchet it up rather than padding tests.

## Open Questions (non-blocking)

- **`App.tsx` test**: App.tsx (90 lines, routing/provider composition) is excluded
  from the required test scope but is a natural, low-effort smoke test (`renders
  the login page at /`). Implementer may add it if time allows.
- **`ScannerResults` sort interaction**: depends on whether sort triggers a new API
  call (React Query re-fetch) or is a client-side sort. Implementer should check
  `ScannerResults.tsx` and adapt the test accordingly.
- **MSW**: The current project does not use MSW (Mock Service Worker). If the team
  adds it later, the `vi.mock(api)` pattern can be migrated incrementally.

## File Delivery Checklist

```
frontend/src/test-utils/renderWithQuery.tsx          ← NEW shared util
frontend/src/pages/Scanner/Scanner.test.tsx           ← NEW page smoke
frontend/src/pages/Alerts/Alerts.test.tsx             ← NEW page smoke
frontend/src/pages/AutoTrading/AutoTrading.test.tsx   ← NEW page smoke
frontend/src/pages/Dashboard.test.tsx                 ← NEW page smoke
frontend/src/pages/Login/Login.test.tsx               ← NEW light interaction
frontend/src/components/ScannerResults.test.tsx       ← NEW component
frontend/src/components/UniverseFormModal.test.tsx    ← NEW component
frontend/src/components/QualityReportModal.test.tsx   ← NEW component
frontend/src/components/Layout.test.tsx               ← NEW component
frontend/src/pages/Scanner/ScanConfigPanel.test.tsx   ← NEW panel
frontend/src/pages/Alerts/AlertRuleModal.test.tsx     ← NEW panel
frontend/src/pages/AutoTrading/ConfigPanel.test.tsx   ← NEW panel
frontend/src/pages/AutoTrading/components.test.tsx    ← NEW panel
frontend/vitest.config.ts                             ← MODIFY coverage config
```
