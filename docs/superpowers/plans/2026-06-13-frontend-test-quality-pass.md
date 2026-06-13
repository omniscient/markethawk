# Frontend Test Quality Pass — Implementation Plan (issue #396)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Quality-pass 7 retained frontend test files from the #250 scope spillover — remove pure smoke tests, replace CSS class-name assertions with ARIA-semantic assertions, and add 3 small ARIA improvements to source components. All 7 sub-issues (#309, #311–#316) close from this PR; epic #383 closes when they do.

**Architecture:** Test-only change with minimal source augmentation. Four source files (`PageLoader.tsx`, `AlertBadges.tsx`, `ScorecardOverview.tsx`, `ScorecardDetail.tsx`) receive additive ARIA attributes that decouple tests from Tailwind class names and simultaneously fix real accessibility gaps (`role="status"` for screen-reader announcements, `aria-label` for color-only severity indicators, `aria-pressed` for toggle-button state). No structural or behavioral changes to the components.

**Tech Stack:** React 18 + TypeScript + Vitest + React Testing Library + `@testing-library/jest-dom`

**Spec:** `docs/superpowers/specs/2026-06-13-frontend-test-quality-pass-design.md`

**Working directory for all frontend commands:** `frontend/`

---

## File Structure

| File | Action | Change |
|------|--------|--------|
| `frontend/src/components/ui/PageLoader.tsx` | MODIFY | Add `role="status"` + `aria-label="Loading"` to spinner `<div>` |
| `frontend/src/components/ui/PageLoader.test.tsx` | MODIFY | Replace 2 tests with 1 behavioral `getByRole('status', { name: /loading/i })` test |
| `frontend/src/pages/ActiveWatchlist/AlertBadges.tsx` | MODIFY | Add `` aria-label={`${alert.severity} severity`} `` to badge `<span>` |
| `frontend/src/pages/ActiveWatchlist/AlertBadges.test.tsx` | MODIFY | Replace 3 className assertions with `getByLabelText(/severity/i)` |
| `frontend/src/pages/ActiveWatchlist/ActiveWatchlist.test.tsx` | MODIFY | Remove `renders without crashing` smoke test; delete `shows count in red` (covered by existing "Watchlist is full" test) |
| `frontend/src/pages/PreMarketMovers.test.tsx` | MODIFY | Remove `renders without crashing` smoke test |
| `frontend/src/pages/ScorecardOverview.tsx` | MODIFY | Add `aria-pressed={period === p.value}` to period buttons |
| `frontend/src/pages/ScorecardOverview.test.tsx` | MODIFY | Remove smoke test; replace `bg-financial-blue` className assertion with `toHaveAttribute('aria-pressed', 'true')` |
| `frontend/src/pages/ScorecardDetail.tsx` | MODIFY | Add `aria-pressed={period === p.value}` to period buttons |
| `frontend/src/pages/ScorecardDetail.test.tsx` | MODIFY | Remove smoke test; replace `bg-financial-blue` className assertion with `toHaveAttribute('aria-pressed', 'true')` |
| `frontend/src/pages/Settings.test.tsx` | NO CHANGE | Already quality-grade — behavioral assertions, tab interaction, async data |

---

## Pre-flight: verify coverage baseline

Before any deletions, confirm the current gates are healthy:

```bash
cd frontend && npx vitest run --coverage 2>&1 | tail -30
```

Expected: statements ≥ 30%, branches ≥ 22%. Note exact percentages — if a gate is currently within 2% of the floor, the smoke-test deletions may threaten it and Task 7 will need compensating tests. If gates are comfortable (≥ 33% / ≥ 25%), proceed.

---

## Task 1: PageLoader — role=status + behavioral test

**Files:**
- Modify: `frontend/src/components/ui/PageLoader.tsx`
- Modify: `frontend/src/components/ui/PageLoader.test.tsx`

- [ ] **Step 1: Write the failing test**

Replace all content of `frontend/src/components/ui/PageLoader.test.tsx`:

```tsx
import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { PageLoader } from './PageLoader';

describe('PageLoader', () => {
  it('renders a loading status region announced to screen readers', () => {
    render(<PageLoader />);
    expect(screen.getByRole('status', { name: /loading/i })).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Verify the test fails**

```bash
cd frontend && npx vitest run src/components/ui/PageLoader.test.tsx 2>&1
```

Expected: FAIL — `Unable to find an accessible element with the role "status"` (ARIA not yet on the element).

- [ ] **Step 3: Add ARIA to PageLoader.tsx**

Replace `frontend/src/components/ui/PageLoader.tsx`:

```tsx
export function PageLoader() {
  return (
    <div className="min-h-screen bg-financial-dark flex items-center justify-center">
      <div
        role="status"
        aria-label="Loading"
        className="w-10 h-10 rounded-full border-2 border-financial-light/20 border-t-financial-light animate-spin"
      />
    </div>
  );
}
```

- [ ] **Step 4: Verify it passes**

```bash
cd frontend && npx vitest run src/components/ui/PageLoader.test.tsx 2>&1
```

Expected: PASS — 1 test.

- [ ] **Step 5: TypeScript gate + commit**

```bash
cd frontend && npx tsc --noEmit 2>&1
git add frontend/src/components/ui/PageLoader.tsx frontend/src/components/ui/PageLoader.test.tsx
git commit -m "test(frontend): PageLoader behavioral test via role=status aria-label (issue #396, closes #311)"
```

---

## Task 2: AlertBadges — aria-label + semantic severity assertions

**Files:**
- Modify: `frontend/src/pages/ActiveWatchlist/AlertBadges.tsx`
- Modify: `frontend/src/pages/ActiveWatchlist/AlertBadges.test.tsx`

- [ ] **Step 1: Write the failing tests**

Replace all content of `frontend/src/pages/ActiveWatchlist/AlertBadges.test.tsx` — keep the 4 existing behavioral tests, replace the 3 className tests with `getByLabelText` assertions:

```tsx
import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { AlertBadge } from './AlertBadges';
import type { LiveAlert } from '../../hooks/useWatchlistLive';

const recentTimestamp = new Date(Date.now() - 60000).toISOString(); // 1 minute ago

const makeAlert = (overrides: Partial<LiveAlert> = {}): LiveAlert => ({
  type: 'alert',
  symbol: 'AAPL',
  scanner_type: 'live_volume_spike',
  summary: 'Volume spike detected',
  severity: 'high',
  indicators: {},
  timestamp: recentTimestamp,
  ...overrides,
});

describe('AlertBadge', () => {
  it('renders null when alert is null', () => {
    const { container } = render(<AlertBadge alert={null} />);
    expect(container.firstChild).toBeNull();
  });

  it('renders null when alert is older than 1 hour', () => {
    const oldAlert = makeAlert({
      timestamp: new Date(Date.now() - 3_700_000).toISOString(),
    });
    const { container } = render(<AlertBadge alert={oldAlert} />);
    expect(container.firstChild).toBeNull();
  });

  it('shows "VOL" badge for live_volume_spike scanner type', () => {
    render(<AlertBadge alert={makeAlert({ scanner_type: 'live_volume_spike' })} />);
    expect(screen.getByText('VOL')).toBeInTheDocument();
  });

  it('shows "MOVE" badge for other scanner types', () => {
    render(<AlertBadge alert={makeAlert({ scanner_type: 'pre_market_volume_spike' })} />);
    expect(screen.getByText('MOVE')).toBeInTheDocument();
  });

  it('labels high severity badge accessibly', () => {
    render(<AlertBadge alert={makeAlert({ severity: 'high' })} />);
    expect(screen.getByLabelText(/high severity/i)).toBeInTheDocument();
  });

  it('labels medium severity badge accessibly', () => {
    render(<AlertBadge alert={makeAlert({ severity: 'medium' })} />);
    expect(screen.getByLabelText(/medium severity/i)).toBeInTheDocument();
  });

  it('labels low severity badge accessibly', () => {
    render(<AlertBadge alert={makeAlert({ severity: 'low' })} />);
    expect(screen.getByLabelText(/low severity/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Verify the new severity tests fail**

```bash
cd frontend && npx vitest run src/pages/ActiveWatchlist/AlertBadges.test.tsx 2>&1
```

Expected: FAIL — `Unable to find a label with the text: /high severity/i` (aria-label not yet on element).

- [ ] **Step 3: Add aria-label to AlertBadges.tsx**

In `frontend/src/pages/ActiveWatchlist/AlertBadges.tsx`, add `aria-label` to the return `<span>`:

```tsx
  return (
    <span
      className={`inline-block text-xs px-1.5 py-0.5 rounded border ${color}`}
      aria-label={`${alert.severity} severity`}
      title={alert.summary}
    >
      {alert.scanner_type === 'live_volume_spike' ? 'VOL' : 'MOVE'}
    </span>
  );
```

- [ ] **Step 4: Verify all tests pass**

```bash
cd frontend && npx vitest run src/pages/ActiveWatchlist/AlertBadges.test.tsx 2>&1
```

Expected: PASS — 7 tests.

- [ ] **Step 5: TypeScript gate + commit**

```bash
cd frontend && npx tsc --noEmit 2>&1
git add frontend/src/pages/ActiveWatchlist/AlertBadges.tsx frontend/src/pages/ActiveWatchlist/AlertBadges.test.tsx
git commit -m "test(frontend): AlertBadges severity assertions via aria-label (issue #396, closes #313)"
```

---

## Task 3: ActiveWatchlist — remove smoke test + remove className assertion

**Files:**
- Modify: `frontend/src/pages/ActiveWatchlist/ActiveWatchlist.test.tsx`

Two tests are removed:
1. `'renders without crashing'` (line 35) — covered by `'shows Active Watchlist heading'`
2. `'shows count in red when at limit (50 symbols)'` (line 76) — uses `className.toContain('text-red-400')`; the at-limit state is already verified by the existing `'shows "Watchlist is full" warning when at limit'` test (line 88)

- [ ] **Step 1: Verify current tests pass as baseline**

```bash
cd frontend && npx vitest run src/pages/ActiveWatchlist/ActiveWatchlist.test.tsx 2>&1
```

Expected: PASS — 14 tests before changes.

- [ ] **Step 2: Remove the two tests**

Delete these two `it(...)` blocks from `ActiveWatchlist.test.tsx`:

```
// REMOVE — smoke test:
it('renders without crashing', () => {
  renderWithQuery(<ActiveWatchlist />);
});

// REMOVE — className assertion; at-limit state covered by 'shows "Watchlist is full"':
it('shows count in red when at limit (50 symbols)', () => {
  mockUseWatchlist.mockReturnValueOnce({ data: fiftyItems, isLoading: false, isError: false });
  renderWithQuery(<ActiveWatchlist />);
  expect(screen.getByText('50').className).toContain('text-red-400');
});
```

- [ ] **Step 3: Verify remaining tests pass**

```bash
cd frontend && npx vitest run src/pages/ActiveWatchlist/ActiveWatchlist.test.tsx 2>&1
```

Expected: PASS — 12 tests.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/ActiveWatchlist/ActiveWatchlist.test.tsx
git commit -m "test(frontend): remove smoke test + className assertion from ActiveWatchlist (issue #396, closes #312)"
```

---

## Task 4: ScorecardOverview — aria-pressed + replace period assertion + remove smoke test

**Files:**
- Modify: `frontend/src/pages/ScorecardOverview.tsx`
- Modify: `frontend/src/pages/ScorecardOverview.test.tsx`

- [ ] **Step 1: Write the failing test**

In `frontend/src/pages/ScorecardOverview.test.tsx`:
- Remove `it('renders without crashing', ...)` from the `describe('ScorecardOverview')` block
- Replace `it('changes active period button styling when clicked', ...)` with an `aria-pressed` assertion:

```tsx
  it('marks the clicked period button active via aria-pressed', () => {
    renderWithQuery(<ScorecardOverview />);
    fireEvent.click(screen.getByRole('button', { name: /7D/i }));
    expect(screen.getByRole('button', { name: /7D/i })).toHaveAttribute('aria-pressed', 'true');
    // 30D (the previous default) should now be inactive
    expect(screen.getByRole('button', { name: /30D/i })).toHaveAttribute('aria-pressed', 'false');
  });
```

- [ ] **Step 2: Verify the new test fails**

```bash
cd frontend && npx vitest run src/pages/ScorecardOverview.test.tsx 2>&1
```

Expected: FAIL — `expected element to have attribute "aria-pressed"` (not yet on element).

- [ ] **Step 3: Add aria-pressed to ScorecardOverview.tsx**

In `frontend/src/pages/ScorecardOverview.tsx`, add `aria-pressed` to the period buttons in the `PERIODS.map(...)` block:

```tsx
          {PERIODS.map((p) => (
            <button
              key={p.value}
              onClick={() => setPeriod(p.value)}
              aria-pressed={period === p.value}
              className={`px-3 py-1.5 text-xs font-bold uppercase tracking-wider rounded transition-all ${
                period === p.value
                  ? 'bg-financial-blue text-white shadow-lg'
                  : 'text-gray-500 hover:text-white'
              }`}
            >
              {p.label}
            </button>
          ))}
```

- [ ] **Step 4: Verify all tests pass**

```bash
cd frontend && npx vitest run src/pages/ScorecardOverview.test.tsx 2>&1
```

Expected: PASS — all tests green.

- [ ] **Step 5: TypeScript gate + commit**

```bash
cd frontend && npx tsc --noEmit 2>&1
git add frontend/src/pages/ScorecardOverview.tsx frontend/src/pages/ScorecardOverview.test.tsx
git commit -m "test(frontend): ScorecardOverview period selector via aria-pressed (issue #396, closes #315)"
```

---

## Task 5: ScorecardDetail — aria-pressed + replace period assertion + remove smoke test

**Files:**
- Modify: `frontend/src/pages/ScorecardDetail.tsx`
- Modify: `frontend/src/pages/ScorecardDetail.test.tsx`

**Note on `.animate-pulse` assertion (spec open question):** The loading skeleton test at `describe('ScorecardDetail — render branches')` uses `container.querySelectorAll('.animate-pulse').length > 0`. Keep this assertion as-is — `.animate-pulse` signals Tailwind's loading skeleton convention (a behavior indicator, not a layout class) and no visible label exists on the skeleton. Add a brief PR comment: `// animate-pulse: Tailwind skeleton loading convention — behavioral, not cosmetic` alongside it.

- [ ] **Step 1: Write the failing test**

In `frontend/src/pages/ScorecardDetail.test.tsx`:
- Remove `it('renders without crashing', ...)` from `describe('ScorecardDetail — shell')`
- In `describe('ScorecardDetail — period selector')`, replace:

```tsx
  it('marks ALL button active with bg-financial-blue after clicking it', () => {
    renderWithQuery(<ScorecardDetail />);
    const allButton = screen.getByRole('button', { name: /^ALL$/i });
    fireEvent.click(allButton);
    expect(allButton.className).toContain('bg-financial-blue');
    expect(screen.getByRole('button', { name: /^7D$/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^30D$/i })).toBeInTheDocument();
  });
```

with:

```tsx
  it('marks ALL button active via aria-pressed after clicking it', () => {
    renderWithQuery(<ScorecardDetail />);
    const allButton = screen.getByRole('button', { name: /^ALL$/i });
    fireEvent.click(allButton);
    expect(allButton).toHaveAttribute('aria-pressed', 'true');
    // 30D (the previous default) should now be inactive
    expect(screen.getByRole('button', { name: /^30D$/i })).toHaveAttribute('aria-pressed', 'false');
  });
```

- [ ] **Step 2: Verify the new test fails**

```bash
cd frontend && npx vitest run src/pages/ScorecardDetail.test.tsx 2>&1
```

Expected: FAIL — `expected element to have attribute "aria-pressed"`.

- [ ] **Step 3: Add aria-pressed to ScorecardDetail.tsx**

In `frontend/src/pages/ScorecardDetail.tsx`, add `aria-pressed` to the period buttons in the `PERIODS.map(...)` block (around line 69):

```tsx
            {PERIODS.map((p) => (
              <button
                key={p.value}
                onClick={() => setPeriod(p.value)}
                aria-pressed={period === p.value}
                className={`px-3 py-1.5 text-xs font-bold uppercase tracking-wider rounded transition-all ${
                  period === p.value
                    ? 'bg-financial-blue text-white shadow-lg'
                    : 'text-gray-500 hover:text-white'
                }`}
              >
                {p.label}
              </button>
            ))}
```

- [ ] **Step 4: Verify all tests pass**

```bash
cd frontend && npx vitest run src/pages/ScorecardDetail.test.tsx 2>&1
```

Expected: PASS — all tests green.

- [ ] **Step 5: TypeScript gate + commit**

```bash
cd frontend && npx tsc --noEmit 2>&1
git add frontend/src/pages/ScorecardDetail.tsx frontend/src/pages/ScorecardDetail.test.tsx
git commit -m "test(frontend): ScorecardDetail period selector via aria-pressed (issue #396, closes #309)"
```

---

## Task 6: PreMarketMovers — remove smoke test

**Files:**
- Modify: `frontend/src/pages/PreMarketMovers.test.tsx`

- [ ] **Step 1: Verify current tests pass**

```bash
cd frontend && npx vitest run src/pages/PreMarketMovers.test.tsx 2>&1
```

Expected: PASS — 5 tests.

- [ ] **Step 2: Remove smoke test**

Delete the `'renders without crashing'` block from `PreMarketMovers.test.tsx`:

```
// REMOVE:
it('renders without crashing', () => {
  renderWithQuery(<PreMarketMovers />);
});
```

- [ ] **Step 3: Verify remaining tests pass**

```bash
cd frontend && npx vitest run src/pages/PreMarketMovers.test.tsx 2>&1
```

Expected: PASS — 4 tests.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/PreMarketMovers.test.tsx
git commit -m "test(frontend): remove smoke test from PreMarketMovers (issue #396, closes #314)"
```

---

## Task 7: Gate check + Settings verification + close sub-issues

- [ ] **Step 1: Full TypeScript gate**

```bash
cd frontend && npx tsc --noEmit 2>&1
```

Expected: No errors.

- [ ] **Step 2: Full test suite + coverage gate**

```bash
cd frontend && npx vitest run --coverage 2>&1 | tail -30
```

Expected: statements ≥ 30%, branches ≥ 22%, lines ≥ 30%, functions ≥ 22%. If any gate fails, the smoke-test deletions dropped coverage — add a targeted behavioral test in the affected file to compensate before proceeding.

- [ ] **Step 3: Settings.test.tsx verification (no changes, stays green)**

```bash
cd frontend && npx vitest run src/pages/Settings.test.tsx 2>&1
```

Expected: PASS — all tests green, no changes needed.

- [ ] **Step 4: Close sub-issues**

Sub-issues are closed by the commits above via `closes #NNN` in the message. Verify GitHub picked them up, or close explicitly:

```bash
gh issue close 309 --repo omniscient/markethawk
gh issue close 311 --repo omniscient/markethawk
gh issue close 312 --repo omniscient/markethawk
gh issue close 313 --repo omniscient/markethawk
gh issue close 314 --repo omniscient/markethawk
gh issue close 315 --repo omniscient/markethawk
gh issue close 316 --repo omniscient/markethawk
```

Epic #383 closes automatically when all sub-issues above are closed.
