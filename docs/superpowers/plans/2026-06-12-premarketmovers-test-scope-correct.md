# Plan: PreMarketMovers Test Scope-Correction (Issue #314)

**Date**: 2026-06-12
**Issue**: [#314](https://github.com/omniscient/markethawk/issues/314) — test(frontend): scope-correct PreMarketMovers tests
**Spec**: `docs/superpowers/specs/2026-06-12-premarketmovers-test-scope-correct-design.md`

## Goal

Fix the spurious `fetchStorageStats` mock in `PreMarketMovers.test.tsx`, correct the mock response shape (add the missing `status` field), and add three behavioral tests: error state, empty state, and ticker filter. The source component (`PreMarketMovers.tsx`) is out of scope — no component changes.

## Architecture

Test-file only. A single file changes: `frontend/src/pages/PreMarketMovers.test.tsx`. The component uses `useState` + `useEffect` (not React Query); tests must account for the async fetch and assert via `waitFor`. No migration, no new files, no router changes.

## Tech Stack

- Vitest + @testing-library/react (`screen`, `waitFor`, `fireEvent`)
- `renderWithQuery` (`frontend/src/test-utils/renderWithQuery.tsx`) — wraps React Query client + MemoryRouter
- `vi.mock`, `vi.mocked` for per-test mock overrides

## File Structure

| File | Change |
|------|--------|
| `frontend/src/pages/PreMarketMovers.test.tsx` | All changes — fix mock, add 3 behavioral tests |

---

## Tasks

### Task 1: Fix the vi.mock factory

**Files**: `frontend/src/pages/PreMarketMovers.test.tsx`

Remove `fetchStorageStats` (not imported by `PreMarketMovers.tsx`) from the `vi.mock('../api/scanner', ...)` factory. Add `status: 'ok'` to the mock response to match `PreMarketMoversResponse`.

**Key interfaces** (from `frontend/src/api/scanner.ts`):
```typescript
// PreMarketMoversResponse requires:
interface PreMarketMoversResponse {
  status: string;   // ← missing from current mock
  movers: PreMarketMover[];
  timestamp: string;
}
```

**TDD steps**:

1. Run baseline:
   ```bash
   cd /workspace/markethawk/frontend
   npx vitest run src/pages/PreMarketMovers.test.tsx
   ```
   Expected: 2 tests pass.

2. Replace the `vi.mock('../api/scanner', ...)` block in `PreMarketMovers.test.tsx`:

   **Before** (current state):
   ```typescript
   vi.mock('../api/scanner', () => ({
     fetchPreMarketMovers: vi.fn().mockResolvedValue({
       movers: [],
       timestamp: new Date().toISOString(),
     }),
     fetchStorageStats: vi.fn().mockResolvedValue({}),
   }));
   ```

   **After**:
   ```typescript
   vi.mock('../api/scanner', () => ({
     fetchPreMarketMovers: vi.fn().mockResolvedValue({
       status: 'ok',
       movers: [],
       timestamp: new Date().toISOString(),
     }),
   }));
   ```

3. Run tests:
   ```bash
   npx vitest run src/pages/PreMarketMovers.test.tsx
   ```
   Expected: 2 tests pass; no `fetchStorageStats` reference anywhere.

4. Commit:
   ```bash
   git add frontend/src/pages/PreMarketMovers.test.tsx
   git commit -m "test(#314): remove spurious fetchStorageStats mock, add status: ok to response shape"
   ```

---

### Task 2: Add error state and empty state tests

**Files**: `frontend/src/pages/PreMarketMovers.test.tsx`

Add `waitFor` and `beforeEach` to support async assertions and per-test mock resets. Add two behavioral tests:
- **Error state**: when `fetchPreMarketMovers` rejects, the component renders the error message text and a Retry button.
- **Empty state**: when the API returns `movers: []`, the component renders the "No movers found" row after the fetch resolves.

**Memory note (frontend-patterns.md)**: Use `getByRole('button', { name: /Retry/i })` to target the Retry button by accessible name — not `getAllByRole('button')[N]` (DOM-order coupling).

**TDD steps**:

1. Update the import lines at the top of the test file:

   ```typescript
   // vitest import — add beforeEach
   import { vi, describe, it, expect, beforeEach } from 'vitest';
   // RTL import — add waitFor
   import { screen, waitFor } from '@testing-library/react';
   // Add scanner module import for vi.mocked() overrides
   import * as scannerApi from '../api/scanner';
   ```

2. Add a `beforeEach` inside the `describe` block (immediately before the first `it`):
   ```typescript
   beforeEach(() => {
     vi.clearAllMocks();
     vi.mocked(scannerApi.fetchPreMarketMovers).mockResolvedValue({
       status: 'ok',
       movers: [],
       timestamp: new Date().toISOString(),
     });
   });
   ```
   This resets the mock before every test, so `mockRejectedValueOnce` / `mockResolvedValueOnce` overrides in individual tests are clean.

3. Add the error state test inside the `describe` block (after the existing smoke tests):
   ```typescript
   it('shows error message and Retry button when fetch fails', async () => {
     vi.mocked(scannerApi.fetchPreMarketMovers).mockRejectedValueOnce(
       new Error('Network error')
     );
     renderWithQuery(<PreMarketMovers />);
     await waitFor(() =>
       expect(screen.getByText(/Network error/i)).toBeInTheDocument()
     );
     expect(screen.getByRole('button', { name: /Retry/i })).toBeInTheDocument();
   });
   ```
   How this works: the component's catch block sets `error = err.message`. The render branch `error ? <...>{error}<button>Retry</button>` becomes active after loading completes with a rejection.

4. Add the empty state test:
   ```typescript
   it('shows empty-state row after fetch returns no movers', async () => {
     renderWithQuery(<PreMarketMovers />);
     await waitFor(() =>
       expect(screen.getByText(/No movers found/i)).toBeInTheDocument()
     );
   });
   ```
   How this works: the default `beforeEach` mock returns `movers: []`. After fetch resolves, `loading: false` and `filteredMovers: []`, so the `filteredMovers.length === 0 && !loading` branch renders "No movers found matching your filters."

5. Run tests:
   ```bash
   npx vitest run src/pages/PreMarketMovers.test.tsx
   ```
   Expected: 4 tests pass.

6. Commit:
   ```bash
   git add frontend/src/pages/PreMarketMovers.test.tsx
   git commit -m "test(#314): add error state and empty state behavioral tests"
   ```

---

### Task 3: Add ticker filter test

**Files**: `frontend/src/pages/PreMarketMovers.test.tsx`

Add a `makeMover` helper and the ticker filter test: load two movers with distinct tickers and names, type a partial ticker into the search input, assert matching row stays and non-matching row disappears.

**Memory notes**:
- `frontend-patterns.md`: for `input[type="text"]`, use `getByRole('textbox')` — not `container.querySelector` and not DOM-order indexing.
- `frontend-patterns.md`: derive mock objects from the actual TypeScript interface, not ad-hoc field names (wrong shapes silently pass).

The component's filter logic (`filterTicker` state → `filteredMovers`) is synchronous inside the render, so no extra `waitFor` is needed after `fireEvent.change` — only the initial fetch needs `waitFor`.

Volume note: component default `minVolume` is `50000`; the `makeMover` helper must default to `volume >= 50000` to pass the volume gate.

**TDD steps**:

1. Add `fireEvent` to the RTL import:
   ```typescript
   import { screen, waitFor, fireEvent } from '@testing-library/react';
   ```

2. Add a `PreMarketMover` type import (placed above the `vi.mock` call):
   ```typescript
   import type { PreMarketMover } from '../api/scanner';
   ```

3. Add the `makeMover` helper (placed above the `vi.mock` call, below the type import):
   ```typescript
   const makeMover = (
     ticker: string,
     name: string,
     overrides: Partial<PreMarketMover> = {}
   ): PreMarketMover => ({
     ticker,
     name,
     price: 100.00,
     change_percent: 1.5,
     change_value: 1.50,
     volume: 100000,   // exceeds default minVolume: 50000
     prev_close: 98.50,
     ...overrides,
   });
   ```

4. Add the filter test inside the `describe` block:
   ```typescript
   it('filters table rows by ticker text input', async () => {
     const moverAAPL = makeMover('AAPL', 'Apple Inc');
     const moverNVDA = makeMover('NVDA', 'Nvidia Corp');
     vi.mocked(scannerApi.fetchPreMarketMovers).mockResolvedValueOnce({
       status: 'ok',
       movers: [moverAAPL, moverNVDA],
       timestamp: new Date().toISOString(),
     });

     renderWithQuery(<PreMarketMovers />);

     // Wait for the fetch to complete and both rows to appear
     await waitFor(() =>
       expect(screen.getByText('Apple Inc')).toBeInTheDocument()
     );
     expect(screen.getByText('Nvidia Corp')).toBeInTheDocument();

     // Type partial ticker — filteredMovers recomputed synchronously
     fireEvent.change(screen.getByRole('textbox'), { target: { value: 'AAP' } });

     // AAPL row stays; NVDA row disappears
     expect(screen.getByText('Apple Inc')).toBeInTheDocument();
     expect(screen.queryByText('Nvidia Corp')).not.toBeInTheDocument();
   });
   ```
   How this works: `filterTicker` state is set to `'AAP'`; `'aapl'.includes('aap')` is true; `'nvda'.includes('aap')` is false. The `name` field (`{mover.name || 'Stock'}`) is rendered as text in a `<span>` inside the row, making it reliably queryable via `getByText`.

5. Run tests:
   ```bash
   npx vitest run src/pages/PreMarketMovers.test.tsx
   ```
   Expected: 5 tests pass.

6. Run TypeScript check (CLAUDE.md gate — must pass before commit):
   ```bash
   npx tsc --noEmit
   ```
   Expected: no errors.

7. Commit:
   ```bash
   git add frontend/src/pages/PreMarketMovers.test.tsx
   git commit -m "test(#314): add ticker filter behavioral test"
   ```

---

### Task 4 (Optional): Add column sort and MetricCard computed-value tests

**Condition**: Implement only if the assertions are straightforward; skip if they produce flakiness. Per spec, auto-refresh tests are explicitly excluded (require `vi.useFakeTimers()`).

**Column sort test** — clicking a sortable header toggles sort order (synchronous state change):

```typescript
it('toggles sort order when a sortable column header is clicked', async () => {
  const moverAAPL = makeMover('AAPL', 'Apple Inc', { change_percent: 3.0 });
  const moverNVDA = makeMover('NVDA', 'Nvidia Corp', { change_percent: 1.0 });
  vi.mocked(scannerApi.fetchPreMarketMovers).mockResolvedValueOnce({
    status: 'ok',
    movers: [moverAAPL, moverNVDA],
    timestamp: new Date().toISOString(),
  });

  const { container } = renderWithQuery(<PreMarketMovers />);

  await waitFor(() => expect(screen.getByText('Apple Inc')).toBeInTheDocument());

  // Default sort: change_percent desc → AAPL (3.0) first
  const rowsBefore = container.querySelectorAll('tbody tr');
  expect(rowsBefore[0]).toHaveTextContent('Apple Inc');

  // Click % Change header → toggles to asc → NVDA (1.0) first
  fireEvent.click(screen.getByText('% Change'));

  const rowsAfter = container.querySelectorAll('tbody tr');
  expect(rowsAfter[0]).toHaveTextContent('Nvidia Corp');
});
```

Note: the initial `sortBy` is `'change_percent'` and `sortOrder` is `'desc'`. Clicking the `% Change` header when it is already the active sort key toggles `sortOrder` to `'asc'`. This is synchronous state change — no `waitFor` needed after the click.

**MetricCard computed values test** — verifies the top gainer/loser/volume titles derive from fetched data:

```typescript
it('displays top gainer, loser, and highest volume in MetricCards from fetched data', async () => {
  const moverAAPL = makeMover('AAPL', 'Apple Inc', { change_percent: 3.0, volume: 200000 });
  const moverNVDA = makeMover('NVDA', 'Nvidia Corp', { change_percent: -1.5, volume: 100000 });
  vi.mocked(scannerApi.fetchPreMarketMovers).mockResolvedValueOnce({
    status: 'ok',
    movers: [moverAAPL, moverNVDA],
    timestamp: new Date().toISOString(),
  });

  renderWithQuery(<PreMarketMovers />);

  await waitFor(() =>
    expect(screen.getByText(/Top Gainer: AAPL/i)).toBeInTheDocument()
  );
  expect(screen.getByText(/Top Loser: NVDA/i)).toBeInTheDocument();
  expect(screen.getByText(/Highest Volume: AAPL/i)).toBeInTheDocument();
});
```

How this works: the component derives `topGainer`, `topLoser`, `maxVolume` from the raw `movers` array. The MetricCard `title` prop uses the ticker name directly: `title={`Top Gainer: ${topGainer?.ticker || ''}`}`.

**After adding optional tests, run and commit**:
```bash
npx vitest run src/pages/PreMarketMovers.test.tsx
npx tsc --noEmit
git add frontend/src/pages/PreMarketMovers.test.tsx
git commit -m "test(#314): add optional sort and MetricCard computed-value tests"
```

---

## Final State: Complete Test File

After all tasks, `PreMarketMovers.test.tsx` will look like:

```typescript
import { vi, describe, it, expect, beforeEach } from 'vitest';
import { screen, waitFor, fireEvent } from '@testing-library/react';
import { renderWithQuery } from '../test-utils/renderWithQuery';
import * as scannerApi from '../api/scanner';
import type { PreMarketMover } from '../api/scanner';
import PreMarketMovers from './PreMarketMovers';

const makeMover = (
  ticker: string,
  name: string,
  overrides: Partial<PreMarketMover> = {}
): PreMarketMover => ({
  ticker,
  name,
  price: 100.00,
  change_percent: 1.5,
  change_value: 1.50,
  volume: 100000,
  prev_close: 98.50,
  ...overrides,
});

vi.mock('../api/scanner', () => ({
  fetchPreMarketMovers: vi.fn().mockResolvedValue({
    status: 'ok',
    movers: [],
    timestamp: new Date().toISOString(),
  }),
}));

vi.mock('../components/Ticker', () => ({ default: () => null }));

describe('PreMarketMovers page', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(scannerApi.fetchPreMarketMovers).mockResolvedValue({
      status: 'ok',
      movers: [],
      timestamp: new Date().toISOString(),
    });
  });

  it('renders without crashing', () => {
    renderWithQuery(<PreMarketMovers />);
  });

  it('shows loading spinner initially', () => {
    renderWithQuery(<PreMarketMovers />);
    expect(screen.getByText(/Loading/i)).toBeInTheDocument();
  });

  it('shows error message and Retry button when fetch fails', async () => {
    vi.mocked(scannerApi.fetchPreMarketMovers).mockRejectedValueOnce(
      new Error('Network error')
    );
    renderWithQuery(<PreMarketMovers />);
    await waitFor(() =>
      expect(screen.getByText(/Network error/i)).toBeInTheDocument()
    );
    expect(screen.getByRole('button', { name: /Retry/i })).toBeInTheDocument();
  });

  it('shows empty-state row after fetch returns no movers', async () => {
    renderWithQuery(<PreMarketMovers />);
    await waitFor(() =>
      expect(screen.getByText(/No movers found/i)).toBeInTheDocument()
    );
  });

  it('filters table rows by ticker text input', async () => {
    const moverAAPL = makeMover('AAPL', 'Apple Inc');
    const moverNVDA = makeMover('NVDA', 'Nvidia Corp');
    vi.mocked(scannerApi.fetchPreMarketMovers).mockResolvedValueOnce({
      status: 'ok',
      movers: [moverAAPL, moverNVDA],
      timestamp: new Date().toISOString(),
    });

    renderWithQuery(<PreMarketMovers />);

    await waitFor(() =>
      expect(screen.getByText('Apple Inc')).toBeInTheDocument()
    );
    expect(screen.getByText('Nvidia Corp')).toBeInTheDocument();

    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'AAP' } });

    expect(screen.getByText('Apple Inc')).toBeInTheDocument();
    expect(screen.queryByText('Nvidia Corp')).not.toBeInTheDocument();
  });
});
```
