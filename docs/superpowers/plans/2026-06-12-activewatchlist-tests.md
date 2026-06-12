# Plan: ActiveWatchlist Test Coverage — Spec-Driven Suite

**Date**: 2026-06-12
**Issue**: [#312](https://github.com/omniscient/markethawk/issues/312) — test(frontend): scope-correct ActiveWatchlist tests
**Branch**: `refine/issue-312-test-frontend---scope-correct-activewatc`
**Spec**: [docs/superpowers/specs/2026-06-12-activewatchlist-tests-design.md](../specs/2026-06-12-activewatchlist-tests-design.md)

## Goal

Replace the gate-driven `ActiveWatchlist.test.tsx` accidental tests with intentional, spec-driven coverage. Extend it with loading state, at-limit state, and `AddSymbolForm` behavior tests. Create `WatchlistTable.test.tsx` from scratch covering all render-state and interaction scenarios from the spec. Keep the `vitest.config.ts` thresholds green. Leave `AlertBadges.test.tsx` unchanged.

## Architecture

All changes are confined to the test layer — no production code is modified. Two test files change:

| File | Status | Scope |
|------|--------|-------|
| `frontend/src/pages/ActiveWatchlist/ActiveWatchlist.test.tsx` | Modified | Add 7 tests (loading, at-limit ×3, AddSymbolForm ×3) |
| `frontend/src/pages/ActiveWatchlist/WatchlistTable.test.tsx` | Created | 19 tests (render-state ×15, interactions ×4) |
| `frontend/src/pages/ActiveWatchlist/AlertBadges.test.tsx` | No change | Already comprehensive per issue #250 |

Production files (`index.tsx`, `WatchlistTable.tsx`, `AlertBadges.tsx`) are read-only for this issue.

## Tech Stack

- **Test runner**: Vitest (`npx vitest run`)
- **Render**: `render` + `MemoryRouter` for `WatchlistTable.test.tsx`; `renderWithQuery` for `ActiveWatchlist.test.tsx`
- **Assertions**: `@testing-library/react` (`screen`, `fireEvent`)
- **Mocks**: `vi.mock` + `vi.hoisted` (per `frontend-patterns.md` issue #250 spy pattern)
- **Coverage**: v8 provider, `all: true`, thresholds 30/27/22/30

## File Structure

| Path | Change |
|------|--------|
| `frontend/src/pages/ActiveWatchlist/ActiveWatchlist.test.tsx` | Extend — add hoisted `mockAddMutate` spy, 7 new tests |
| `frontend/src/pages/ActiveWatchlist/WatchlistTable.test.tsx` | Create — new file with 19 tests |

---

## Task 1 — ActiveWatchlist: mock setup + loading and at-limit state tests

**Files**: `frontend/src/pages/ActiveWatchlist/ActiveWatchlist.test.tsx`

### TDD Steps

**Step 1.1** — Establish a green baseline:

```bash
cd frontend
npx vitest run src/pages/ActiveWatchlist/ActiveWatchlist.test.tsx
```

Expected: 7 tests pass.

**Step 1.2** — Replace the import block and mock preamble (lines 1–17) to add the hoisted `mockAddMutate` spy and `fireEvent` import. The `vi.hoisted` placement satisfies the `frontend-patterns.md` requirement that spies referenced in both the mock factory and test assertions must be hoisted.

Replace current content:
```ts
import { vi, describe, it, expect } from 'vitest';
import { screen } from '@testing-library/react';
import { renderWithQuery } from '../../test-utils/renderWithQuery';
import ActiveWatchlist from './index';

const mockUseWatchlist = vi.fn(() => ({ data: [], isLoading: false, isError: false }));

vi.mock('../../api/watchlist', () => ({
  useWatchlist: () => mockUseWatchlist(),
  useAddToWatchlist: () => ({ mutate: vi.fn(), isPending: false }),
  useRemoveFromWatchlist: () => ({ mutate: vi.fn(), isPending: false }),
  useUpdateWatchlistNotes: () => ({ mutate: vi.fn(), isPending: false }),
}));

vi.mock('../../hooks/useWatchlistLive', () => ({
  useWatchlistLive: () => ({ liveData: {}, connected: false }),
}));
```

With:
```ts
import { vi, describe, it, expect, beforeEach } from 'vitest';
import { screen, fireEvent } from '@testing-library/react';
import { renderWithQuery } from '../../test-utils/renderWithQuery';
import ActiveWatchlist from './index';
import type { WatchlistItem } from '../../api/watchlist';

const mockUseWatchlist = vi.fn(() => ({ data: [], isLoading: false, isError: false }));
const mockAddMutate = vi.hoisted(() => vi.fn());

vi.mock('../../api/watchlist', () => ({
  useWatchlist: () => mockUseWatchlist(),
  useAddToWatchlist: () => ({ mutate: mockAddMutate, isPending: false }),
  useRemoveFromWatchlist: () => ({ mutate: vi.fn(), isPending: false }),
  useUpdateWatchlistNotes: () => ({ mutate: vi.fn(), isPending: false }),
}));

vi.mock('../../hooks/useWatchlistLive', () => ({
  useWatchlistLive: () => ({ liveData: {}, connected: false }),
}));

beforeEach(() => {
  mockAddMutate.mockReset();
});
```

**Step 1.3** — Append a `describe('loading and at-limit states')` block inside the existing outer `describe('ActiveWatchlist', ...)`, after the existing 7 tests:

```ts
describe('loading and at-limit states', () => {
  const makeAtLimitItems = (): WatchlistItem[] =>
    Array.from({ length: 50 }, (_, i) => ({
      id: i + 1,
      symbol: `SYM${i}`,
      security_type: 'STK',
      exchange: null,
      notes: null,
      added_at: '2026-01-15T10:00:00Z',
    }));

  it('shows spinner when isLoading is true', () => {
    mockUseWatchlist.mockReturnValueOnce({ data: undefined, isLoading: true, isError: false });
    renderWithQuery(<ActiveWatchlist />);
    expect(screen.getByText(/Loading watchlist/i)).toBeInTheDocument();
  });

  it('count banner is red when at limit (50 items)', () => {
    mockUseWatchlist.mockReturnValueOnce({ data: makeAtLimitItems(), isLoading: false, isError: false });
    renderWithQuery(<ActiveWatchlist />);
    const countEl = screen.getByText('50');
    expect(countEl.className).toContain('text-red-400');
  });

  it('hides Add Symbol form when at limit', () => {
    mockUseWatchlist.mockReturnValueOnce({ data: makeAtLimitItems(), isLoading: false, isError: false });
    renderWithQuery(<ActiveWatchlist />);
    expect(screen.queryByText('Add Symbol')).not.toBeInTheDocument();
  });

  it('shows at-limit warning message when at limit', () => {
    mockUseWatchlist.mockReturnValueOnce({ data: makeAtLimitItems(), isLoading: false, isError: false });
    renderWithQuery(<ActiveWatchlist />);
    expect(screen.getByText(/Watchlist is full/i)).toBeInTheDocument();
  });
});
```

**Step 1.4** — Run to verify all 11 tests pass:

```bash
npx vitest run src/pages/ActiveWatchlist/ActiveWatchlist.test.tsx
```

Expected: `11 passed`.

**Step 1.5** — Commit:

```bash
git add frontend/src/pages/ActiveWatchlist/ActiveWatchlist.test.tsx
git commit -m "test(ActiveWatchlist): add loading and at-limit state tests (#312)"
```

---

## Task 2 — ActiveWatchlist: AddSymbolForm behavior tests

**Files**: `frontend/src/pages/ActiveWatchlist/ActiveWatchlist.test.tsx`

The `AddSymbolForm` is not exported — it is tested through the `ActiveWatchlist` page render. The form is visible when the default mock returns `data: []` (not at limit).

### TDD Steps

**Step 2.1** — Append a `describe('AddSymbolForm')` block inside `describe('ActiveWatchlist', ...)`, after the loading/at-limit describe:

```ts
describe('AddSymbolForm', () => {
  it('submit calls mutate with trimmed+uppercased symbol and correct payload', () => {
    renderWithQuery(<ActiveWatchlist />);
    const symbolInput = screen.getByPlaceholderText(/Symbol \(e\.g\. NVDA\)/i);
    // The input onChange uppercases; submit handler trims then uppercases again
    fireEvent.change(symbolInput, { target: { value: '  nvda  ' } });
    const form = symbolInput.closest('form')!;
    fireEvent.submit(form);
    expect(mockAddMutate).toHaveBeenCalledWith(
      { symbol: 'NVDA', security_type: 'STK', exchange: undefined, notes: undefined },
      expect.any(Object)
    );
  });

  it('changing security type to FUT auto-sets exchange to CME', () => {
    renderWithQuery(<ActiveWatchlist />);
    const secTypeSelect = screen.getByRole('combobox');
    fireEvent.change(secTypeSelect, { target: { value: 'FUT' } });
    // After the change, the placeholder updates and CME is filled
    const exchangeInput = screen.getByPlaceholderText('Exchange (e.g. CME)');
    expect(exchangeInput).toHaveValue('CME');
  });

  it('API error message renders when mutation returns an error', () => {
    mockAddMutate.mockImplementationOnce(
      (_payload: unknown, { onError }: { onError: (err: unknown) => void }) => {
        onError({ response: { data: { detail: 'Symbol already in watchlist.' } } });
      }
    );
    renderWithQuery(<ActiveWatchlist />);
    const symbolInput = screen.getByPlaceholderText(/Symbol \(e\.g\. NVDA\)/i);
    fireEvent.change(symbolInput, { target: { value: 'AAPL' } });
    fireEvent.submit(symbolInput.closest('form')!);
    expect(screen.getByText('Symbol already in watchlist.')).toBeInTheDocument();
  });
});
```

**Step 2.2** — Run to verify all 14 tests pass:

```bash
npx vitest run src/pages/ActiveWatchlist/ActiveWatchlist.test.tsx
```

Expected: `14 passed`.

**Step 2.3** — Commit:

```bash
git add frontend/src/pages/ActiveWatchlist/ActiveWatchlist.test.tsx
git commit -m "test(ActiveWatchlist): add AddSymbolForm behavior tests (#312)"
```

---

## Task 3 — Create WatchlistTable.test.tsx with render-state tests

**Files**: `frontend/src/pages/ActiveWatchlist/WatchlistTable.test.tsx` (new)

`WatchlistTable` imports `useRemoveFromWatchlist` and `useUpdateWatchlistNotes` (mocked) and `Link` from `react-router-dom` (satisfied via `MemoryRouter` wrapper). No `QueryClientProvider` is needed because the hooks are fully mocked. A local `renderTable` helper wraps in `MemoryRouter` using plain `render` from RTL.

### TDD Steps

**Step 3.1** — Create `frontend/src/pages/ActiveWatchlist/WatchlistTable.test.tsx`:

```ts
import { vi, describe, it, expect, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { WatchlistTable } from './WatchlistTable';
import type { WatchlistItem } from '../../api/watchlist';
import type { SymbolLiveData } from '../../hooks/useWatchlistLive';

// ── Mocks ────────────────────────────────────────────────────────────────────

const mockRemoveMutate = vi.hoisted(() => vi.fn());
const mockNotesMutate = vi.hoisted(() => vi.fn());

vi.mock('../../api/watchlist', () => ({
  useRemoveFromWatchlist: () => ({ mutate: mockRemoveMutate, isPending: false }),
  useUpdateWatchlistNotes: () => ({ mutate: mockNotesMutate, isPending: false }),
}));

// ── Fixtures ─────────────────────────────────────────────────────────────────

const makeItem = (overrides: Partial<WatchlistItem> = {}): WatchlistItem => ({
  id: 1,
  symbol: 'AAPL',
  security_type: 'STK',
  exchange: null,
  notes: null,
  added_at: '2026-01-15T10:00:00Z',
  ...overrides,
});

const makeLiveData = (overrides: Partial<SymbolLiveData> = {}): SymbolLiveData => ({
  price: 182.5,
  priceChangePct: 1.5,
  session: 'regular',
  sessionVolume: 1_500_000,
  lastTickAt: Date.now() - 5_000,
  alert: null,
  ...overrides,
});

const renderTable = (
  items: WatchlistItem[],
  liveData: Record<string, SymbolLiveData> = {}
) => render(<MemoryRouter><WatchlistTable items={items} liveData={liveData} /></MemoryRouter>);

// ── Render-state tests ────────────────────────────────────────────────────────

describe('WatchlistTable render-state', () => {
  it('formats price to 2 decimal places', () => {
    renderTable([makeItem()], { AAPL: makeLiveData({ price: 182.5 }) });
    expect(screen.getByText('182.50')).toBeInTheDocument();
  });

  it('dims price text when data is stale (>15s)', () => {
    renderTable([makeItem()], { AAPL: makeLiveData({ price: 182.5, lastTickAt: Date.now() - 20_000 }) });
    const priceEl = screen.getByText('182.50');
    expect(priceEl.className).toContain('text-gray-500');
  });

  it('colors priceChangePct green for positive', () => {
    renderTable([makeItem()], { AAPL: makeLiveData({ priceChangePct: 1.5 }) });
    const pctEl = screen.getByText('+1.50%');
    expect(pctEl.className).toContain('text-positive');
  });

  it('colors priceChangePct red for negative', () => {
    renderTable([makeItem()], { AAPL: makeLiveData({ priceChangePct: -0.8 }) });
    const pctEl = screen.getByText('-0.80%');
    expect(pctEl.className).toContain('text-negative');
  });

  it('colors priceChangePct gray for zero', () => {
    renderTable([makeItem()], { AAPL: makeLiveData({ priceChangePct: 0 }) });
    const pctEl = screen.getByText('+0.00%');
    expect(pctEl.className).toContain('text-gray-400');
  });

  it('shows PRE label in yellow for pre-market session', () => {
    renderTable([makeItem()], { AAPL: makeLiveData({ session: 'pre', sessionVolume: 500_000 }) });
    const sessionEl = screen.getByText('PRE');
    expect(sessionEl.className).toContain('text-yellow-400');
  });

  it('shows REG label in green for regular session', () => {
    renderTable([makeItem()], { AAPL: makeLiveData({ session: 'regular', sessionVolume: 1_000_000 }) });
    const sessionEl = screen.getByText('REG');
    expect(sessionEl.className).toContain('text-positive');
  });

  it('shows POST label in blue for post-market session', () => {
    renderTable([makeItem()], { AAPL: makeLiveData({ session: 'post', sessionVolume: 200_000 }) });
    const sessionEl = screen.getByText('POST');
    expect(sessionEl.className).toContain('text-blue-400');
  });

  it('formats sessionVolume >=1M as xM', () => {
    renderTable([makeItem()], { AAPL: makeLiveData({ session: 'regular', sessionVolume: 1_500_000 }) });
    expect(screen.getByText('1.5M')).toBeInTheDocument();
  });

  it('formats sessionVolume >=1K as xK', () => {
    renderTable([makeItem()], { AAPL: makeLiveData({ session: 'regular', sessionVolume: 750_000 }) });
    expect(screen.getByText('750K')).toBeInTheDocument();
  });

  it('formats sessionVolume <1K as raw number', () => {
    renderTable([makeItem()], { AAPL: makeLiveData({ session: 'regular', sessionVolume: 999 }) });
    expect(screen.getByText('999')).toBeInTheDocument();
  });

  it('renders STK badge with blue classes', () => {
    renderTable([makeItem({ security_type: 'STK' })], { AAPL: makeLiveData() });
    const badge = screen.getByText('STK');
    expect(badge.className).toContain('bg-blue-900');
  });

  it('renders FUT badge with purple classes', () => {
    renderTable([makeItem({ symbol: 'ES', security_type: 'FUT', exchange: 'CME' })], {
      ES: makeLiveData(),
    });
    const badge = screen.getByText('FUT');
    expect(badge.className).toContain('bg-purple-900');
  });

  it('shows notes text when notes is present', () => {
    renderTable([makeItem({ notes: 'Earnings play' })], { AAPL: makeLiveData() });
    expect(screen.getByText('Earnings play')).toBeInTheDocument();
  });

  it('shows dash when notes is absent', () => {
    // Live data provided so PriceCell and SessionCell don't also render dashes
    renderTable([makeItem({ notes: null })], { AAPL: makeLiveData() });
    expect(screen.getByText('—')).toBeInTheDocument();
  });
});

// ── Interaction tests ─────────────────────────────────────────────────────────

describe('WatchlistTable interactions', () => {
  beforeEach(() => {
    mockRemoveMutate.mockReset();
    mockNotesMutate.mockReset();
  });

  it('clicking edit-notes button switches row to inline-edit mode', () => {
    renderTable([makeItem({ notes: 'original' })], { AAPL: makeLiveData() });
    const editBtn = screen.getByRole('button', { name: /edit notes/i });
    fireEvent.click(editBtn);
    expect(screen.getByRole('textbox')).toBeInTheDocument();
  });

  it('pressing Enter on notes input calls useUpdateWatchlistNotes().mutate', () => {
    renderTable([makeItem({ symbol: 'AAPL', notes: 'old' })], { AAPL: makeLiveData() });
    fireEvent.click(screen.getByRole('button', { name: /edit notes/i }));
    const input = screen.getByRole('textbox');
    fireEvent.change(input, { target: { value: 'new notes' } });
    fireEvent.keyDown(input, { key: 'Enter' });
    expect(mockNotesMutate).toHaveBeenCalledWith(
      { symbol: 'AAPL', notes: 'new notes' },
      expect.any(Object)
    );
  });

  it('pressing Escape on notes input returns to display mode', () => {
    renderTable([makeItem({ notes: 'original' })], { AAPL: makeLiveData() });
    fireEvent.click(screen.getByRole('button', { name: /edit notes/i }));
    expect(screen.getByRole('textbox')).toBeInTheDocument();
    fireEvent.keyDown(screen.getByRole('textbox'), { key: 'Escape' });
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument();
  });

  it('clicking remove button calls useRemoveFromWatchlist().mutate with symbol', () => {
    renderTable([makeItem({ symbol: 'AAPL' })], { AAPL: makeLiveData() });
    const removeBtn = screen.getByRole('button', { name: /remove aapl/i });
    fireEvent.click(removeBtn);
    expect(mockRemoveMutate).toHaveBeenCalledWith('AAPL');
  });
});
```

**Step 3.2** — Run to verify all 19 tests pass:

```bash
npx vitest run src/pages/ActiveWatchlist/WatchlistTable.test.tsx
```

Expected: `19 passed`.

**Step 3.3** — Commit:

```bash
git add frontend/src/pages/ActiveWatchlist/WatchlistTable.test.tsx
git commit -m "test(WatchlistTable): add render-state and interaction tests (#312)"
```

---

## Task 4 — Coverage validation and TypeScript gate

**Files**: read-only validation pass

**Step 4.1** — Run the full test suite with coverage:

```bash
cd frontend
npx vitest run --coverage
```

**Step 4.2** — Verify the `vitest.config.ts` thresholds are all green:

```
Required (vitest.config.ts):
  statements: 30%
  branches:   27%
  functions:  22%
  lines:      30%
```

All four metrics must show actual ≥ threshold. If any threshold fails, add targeted tests to the affected file until it clears — the new `WatchlistTable.test.tsx` is the primary coverage contributor for the directory.

**Step 4.3** — Run the TypeScript check:

```bash
npx tsc --noEmit
```

Expected: 0 errors. The `tsconfig.json` `"exclude"` array already covers `**/*.test.tsx`, so test files are not compiled.

**Step 4.4** — Confirm the commit log shows the three expected commits:

```bash
git log --oneline -5
```

Expected (most recent first):
```
test(WatchlistTable): add render-state and interaction tests (#312)
test(ActiveWatchlist): add AddSymbolForm behavior tests (#312)
test(ActiveWatchlist): add loading and at-limit state tests (#312)
```
