# Plan: ScorecardOverview — Scope-Correct Tests

**Goal:** Implement the 8 behaviorally-specified test cases for `ScorecardOverview` (issue #315), plus unit tests for the `periodToDates` helper. Fix the out-of-scope `useScorecard` mock arg-dropping bug as a prerequisite for the period call-arg assertion.

**Architecture:** Frontend-only. Two files change: `ScorecardOverview.tsx` gains a named `export` on `periodToDates`; `ScorecardOverview.test.tsx` is revised and extended. No new packages, no backend changes, no routing changes.

**Tech Stack:** React 18 / TypeScript, Vitest + React Testing Library, `vi.setSystemTime()` for deterministic date tests.

---

## File Structure

| File | Change |
|---|---|
| `frontend/src/pages/ScorecardOverview.tsx` | Add `export` keyword to `periodToDates` (one word change, no behavioral impact) |
| `frontend/src/pages/ScorecardOverview.test.tsx` | Revise mock infrastructure; revise 2 existing tests; add 5 new tests |

---

## Task 1 — Export `periodToDates`

**Files:** `frontend/src/pages/ScorecardOverview.tsx`

This is the prerequisite for Task 5's direct unit tests. The function body is unchanged; only the export keyword is added.

### TDD steps

**Write failing test (verify it fails):**

In `ScorecardOverview.test.tsx`, **replace line 4** (the existing default import) with:

```ts
import ScorecardOverview, { periodToDates } from './ScorecardOverview';
```

Do not add a second `import ScorecardOverview` line — that would be a TS2300 redeclare error.

Run TypeScript check — expect a compile error because `periodToDates` is not currently exported:

```bash
cd frontend && npx tsc -p tsconfig.test.json --noEmit 2>&1 | grep periodToDates
```

Expected output (an error referencing the missing export):
```
ScorecardOverview.test.tsx:4:30 - error TS2305: Module '"./ScorecardOverview"' has no exported member 'periodToDates'.
```

**Implement:**

In `frontend/src/pages/ScorecardOverview.tsx`, line 7, change:

```ts
const periodToDates = (period: Period): { start_date?: string; end_date?: string } => {
```

to:

```ts
export const periodToDates = (period: Period): { start_date?: string; end_date?: string } => {
```

**Verify pass:**

```bash
cd frontend && npx tsc -p tsconfig.test.json --noEmit 2>&1 | grep periodToDates
```

Expected: no output (no errors for `periodToDates`).

Also verify the production build still type-checks:

```bash
cd frontend && npx tsc --noEmit 2>&1 | head -5
```

Expected: no errors.

**Commit:**

```bash
git add frontend/src/pages/ScorecardOverview.tsx
git commit -m "feat: export periodToDates from ScorecardOverview for unit testing (#315)"
```

---

## Task 2 — Fix Mock Infrastructure

**Files:** `frontend/src/pages/ScorecardOverview.test.tsx`

Two mock fixes are required before the new assertions can work:

1. **`useScorecard` arg forwarding** — the current factory `useScorecard: () => mockUseScorecard()` drops all arguments, making `mockUseScorecard.mock.calls` always `[[]]`. The fix forwards args so call-arg assertions are accurate.
2. **`ScannerSummaryCard` stub** — add `data-loading` attribute so the loading-skeleton test can assert `isLoading=true` on each skeleton card.

### TDD steps

Also update the vitest import at the top of the file to include `beforeEach` and `afterEach` (needed by Tasks 4 and 5):

```ts
import { vi, describe, it, expect, beforeEach, afterEach } from 'vitest';
```

**Write failing test (verify loading assertion fails before the stub fix):**

In the existing "shows loading skeleton cards" test, add an assertion that currently fails:

```ts
it('shows loading skeleton cards with isLoading=true', () => {
  mockUseScannerConfigs.mockReturnValueOnce({ data: undefined, isLoading: true });
  renderWithQuery(<ScorecardOverview />);
  const cards = screen.getAllByTestId('summary-card');
  expect(cards).toHaveLength(2);
  cards.forEach((card) => expect(card).toHaveAttribute('data-loading', 'true'));
});
```

Run tests — the `toHaveAttribute('data-loading', 'true')` assertion fails because the stub does not emit that attribute yet:

```bash
cd frontend && npx vitest run src/pages/ScorecardOverview.test.tsx 2>&1 | tail -20
```

Expected: failing assertion on `data-loading`.

**Implement:**

Replace the entire mock block in `ScorecardOverview.test.tsx`:

```ts
// BEFORE
vi.mock('../hooks/useScorecard', () => ({
  useScannerConfigs: () => mockUseScannerConfigs(),
  useScorecard: () => mockUseScorecard(),
}));

vi.mock('../components/scorecard/ScannerSummaryCard', () => ({
  default: ({ scannerName }: { scannerName: string }) => <div data-testid="summary-card">{scannerName}</div>,
}));
```

```ts
// AFTER
vi.mock('../hooks/useScorecard', () => ({
  useScannerConfigs: () => mockUseScannerConfigs(),
  useScorecard: (...args: unknown[]) => mockUseScorecard(...args),
}));

vi.mock('../components/scorecard/ScannerSummaryCard', () => ({
  default: ({ scannerName, isLoading }: { scannerName: string; isLoading?: boolean }) => (
    <div data-testid="summary-card" data-loading={String(isLoading)}>{scannerName}</div>
  ),
}));
```

**Verify pass:**

```bash
cd frontend && npx vitest run src/pages/ScorecardOverview.test.tsx 2>&1 | tail -20
```

Expected: all currently-existing tests still pass. The new loading assertion also passes.

**Commit:**

```bash
git add frontend/src/pages/ScorecardOverview.test.tsx
git commit -m "fix(test): forward useScorecard args in mock; expose isLoading on stub card (#315)"
```

---

## Task 3 — Revise Existing Behavioral Tests

**Files:** `frontend/src/pages/ScorecardOverview.test.tsx`

Two existing tests need to be revised to match the spec:

1. **Active-config filtering (exact count)** — the current test uses `toBeGreaterThan(0)`. The spec requires an exact count assertion with a mixed input (1 active + 1 inactive → exactly 1 card rendered).
2. **Loading skeleton (exact count + `isLoading=true`)** — already converted in Task 2; rename the test description to match the spec language.

### TDD steps

**Write failing tests (revise assertions to fail before the change):**

Replace the existing "renders scanner summary cards when configs are present" test body:

```ts
it('renders scanner summary cards when configs are present', () => {
  mockUseScannerConfigs.mockReturnValueOnce({
    data: [
      { id: 1, name: 'Pre-Market Spike', scanner_type: 'pre_market_volume_spike', is_active: true },
      { id: 2, name: 'Inactive Scanner', scanner_type: 'trend_pullback', is_active: false },
    ],
    isLoading: false,
  });
  renderWithQuery(<ScorecardOverview />);
  expect(screen.getAllByTestId('summary-card')).toHaveLength(1);
});
```

Run tests — `toHaveLength(1)` fails because the old body uses `{ data: [one_active_config], ... }` and only checks `> 0`:

```bash
cd frontend && npx vitest run src/pages/ScorecardOverview.test.tsx 2>&1 | grep -A5 "renders scanner"
```

Expected: assertion failure on length.

**Implement:**

The test body above is already the correct implementation — simply save the revised test file. The component already filters `c.is_active`, so the assertion will now pass once the mock data includes an inactive entry.

**Verify pass:**

```bash
cd frontend && npx vitest run src/pages/ScorecardOverview.test.tsx 2>&1 | tail -20
```

Expected: all tests pass, including the revised exact-count assertion.

**Commit:**

```bash
git add frontend/src/pages/ScorecardOverview.test.tsx
git commit -m "test: exact count assertion for active-config card rendering (#315)"
```

---

## Task 4 — Add New Behavioral Tests

**Files:** `frontend/src/pages/ScorecardOverview.test.tsx`

Add three new tests:

1. **Empty state when all configs are inactive** (spec requirement 4)
2. **Period → `useScorecard` call args** (spec requirement 7) — uses `vi.setSystemTime()` in a dedicated `beforeEach`/`afterEach` pair inside a nested `describe` block so existing non-date tests are unaffected
3. **`isLoading=true` propagation in skeleton** — already covered by the Task 2 revision; confirmed present

### TDD steps

**Write failing tests — add to `ScorecardOverview.test.tsx`:**

Inside the main `describe('ScorecardOverview', ...)` block, add the all-inactive test right after "shows 'No scanner configurations found' when configs is empty":

```ts
it('shows empty state when all configs are inactive', () => {
  mockUseScannerConfigs.mockReturnValueOnce({
    data: [
      { id: 1, name: 'Scanner A', scanner_type: 'pre_market_volume_spike', is_active: false },
      { id: 2, name: 'Scanner B', scanner_type: 'trend_pullback', is_active: false },
    ],
    isLoading: false,
  });
  renderWithQuery(<ScorecardOverview />);
  expect(screen.getByText(/No scanner configurations found/i)).toBeInTheDocument();
});
```

Add a new `describe` block **after** the main `describe` block (not nested inside it) for the period call-arg test:

```ts
describe('ScorecardOverview — period → useScorecard call args', () => {
  const FIXED_DATE = new Date('2026-06-12T00:00:00.000Z');

  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(FIXED_DATE);
    mockUseScorecard.mockClear();
  });

  afterEach(() => {
    vi.useRealTimers();
    mockUseScannerConfigs.mockImplementation(() => ({ data: [], isLoading: false }));
  });

  it('passes 7D date window to useScorecard on period click', () => {
    mockUseScannerConfigs.mockReturnValue({
      data: [{ id: 1, name: 'Pre-Market Spike', scanner_type: 'pre_market_volume_spike', is_active: true }],
      isLoading: false,
    });
    renderWithQuery(<ScorecardOverview />);
    mockUseScorecard.mockClear(); // discard initial-render calls (period='30d')
    fireEvent.click(screen.getByRole('button', { name: /7D/i }));
    expect(mockUseScorecard).toHaveBeenCalledWith(
      'pre_market_volume_spike',
      { start_date: '2026-06-05', end_date: '2026-06-12' },
    );
  });
});
```

Run tests — the new "all inactive" test passes immediately (component logic already filters). The period test fails because `useScorecard` args are not forwarded before Task 2 — but Task 2 is already committed. Run to confirm both now pass:

```bash
cd frontend && npx vitest run src/pages/ScorecardOverview.test.tsx 2>&1 | tail -30
```

Expected: all tests pass.

**Commit:**

```bash
git add frontend/src/pages/ScorecardOverview.test.tsx
git commit -m "test: all-inactive empty state + period-to-useScorecard call arg assertions (#315)"
```

---

## Task 5 — Add `periodToDates` Unit Tests

**Files:** `frontend/src/pages/ScorecardOverview.test.tsx`

Add a `describe('periodToDates', ...)` block exercising all four branches with a fixed clock. The fixed date is `2026-06-12` — expected offsets:

| Period | `start_date` | `end_date` |
|---|---|---|
| `'all'` | — | — |
| `'7d'` | `2026-06-05` | `2026-06-12` |
| `'30d'` | `2026-05-13` | `2026-06-12` |
| `'90d'` | `2026-03-14` | `2026-06-12` |

### TDD steps

**Write failing tests — add after the period call-arg describe block:**

```ts
describe('periodToDates', () => {
  const FIXED_DATE = new Date('2026-06-12T00:00:00.000Z');

  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(FIXED_DATE);
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("returns {} for 'all'", () => {
    expect(periodToDates('all')).toEqual({});
  });

  it("returns 7-day window for '7d'", () => {
    expect(periodToDates('7d')).toEqual({
      start_date: '2026-06-05',
      end_date: '2026-06-12',
    });
  });

  it("returns 30-day window for '30d'", () => {
    expect(periodToDates('30d')).toEqual({
      start_date: '2026-05-13',
      end_date: '2026-06-12',
    });
  });

  it("returns 90-day window for '90d'", () => {
    expect(periodToDates('90d')).toEqual({
      start_date: '2026-03-14',
      end_date: '2026-06-12',
    });
  });
});
```

Before running: confirm the import line at the top of the test file already reads:

```ts
import ScorecardOverview, { periodToDates } from './ScorecardOverview';
```

(Added in Task 1.)

Run tests before the export is in place (if reverting Task 1 to test): TS compile error on import. With Task 1 committed, the import resolves and each `toEqual` assertion is verified by the fixed clock.

**Verify pass:**

```bash
cd frontend && npx vitest run src/pages/ScorecardOverview.test.tsx 2>&1 | tail -20
```

Expected output:
```
✓ src/pages/ScorecardOverview.test.tsx (N tests)
  ✓ ScorecardOverview (7 tests)
  ✓ ScorecardOverview — period → useScorecard call args (1 test)
  ✓ periodToDates (4 tests)
```

Run full coverage to confirm no threshold regression:

```bash
cd frontend && npx vitest run --coverage 2>&1 | grep -A10 "Coverage"
```

Expected: statements/lines ≥ existing threshold, branches/functions ≥ existing threshold.

Run TypeScript gate:

```bash
cd frontend && npx tsc --noEmit 2>&1 | head -10
```

Expected: no errors.

**Commit:**

```bash
git add frontend/src/pages/ScorecardOverview.test.tsx
git commit -m "test: periodToDates unit tests — all four period branches with fixed clock (#315)"
```

---

## Final Verification

```bash
cd frontend && npx vitest run src/pages/ScorecardOverview.test.tsx 2>&1 | tail -30
cd frontend && npx tsc --noEmit 2>&1 | head -10
```

Expected: 12 tests pass (7 in main describe + 1 period call-arg + 4 periodToDates), 0 TypeScript errors.
