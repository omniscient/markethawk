# ScorecardDetail Test Correction — Implementation Plan

**Date**: 2026-06-12  
**Issue**: [#309](https://github.com/omniscient/markethawk/issues/309) — test(frontend): scope-correct ScorecardDetail tests (spec #250 non-goal)  
**Spec**: [`docs/superpowers/specs/2026-06-12-scorecard-detail-test-correction-design.md`](../specs/2026-06-12-scorecard-detail-test-correction-design.md)

## Goal

Restructure `frontend/src/pages/ScorecardDetail.test.tsx` from a static-factory coverage artifact
into intentional orchestration coverage. Replace the frozen `vi.mock` factory (all hooks return
one fixed state) with module-scope `vi.fn()` spies and `beforeEach` defaults so each test can
set its own state. Add tests for the four conditional render branches the page directly owns,
two derived-value transforms (displayName and period active state), and consolidate the existing
static-shell assertions into a single describe block. Coverage gate must remain green.

## Architecture

Single-file restructure. No changes to `ScorecardDetail.tsx`, no new files, no backend changes,
no migrations. All work is within `frontend/src/pages/ScorecardDetail.test.tsx`.

## Tech Stack

- Vitest + `@testing-library/react`
- `renderWithQuery` test util from `frontend/src/test-utils/renderWithQuery.tsx`
- `fireEvent` for click interaction (period selector)

## File Structure

| File | Change |
|------|--------|
| `frontend/src/pages/ScorecardDetail.test.tsx` | Full restructure — new mock infrastructure + new describe blocks |

---

## Task 1: Replace static mock factory with module-scope `vi.fn()` spies

**Files**: `frontend/src/pages/ScorecardDetail.test.tsx`

### TDD steps

**Step 1 — Write one canary test that requires per-test mock control (it fails with the static factory).**

Add a canary test after the existing describe block (do not delete anything yet):

```typescript
// Temporary canary — add after the existing describe block
it('FAILS-WITH-STATIC: loading state shows skeleton', () => {
  // With the static factory, useScorecard always returns { isLoading: false }
  // so this test should fail (no skeleton visible)
  const { container } = renderWithQuery(<ScorecardDetail />);
  expect(container.querySelectorAll('.animate-pulse').length).toBeGreaterThan(0);
});
```

**Step 2 — Verify it fails:**

```bash
cd /workspace/markethawk/frontend
npx vitest run src/pages/ScorecardDetail.test.tsx 2>&1 | tail -20
# Expected: 1 failing (the canary)
```

**Step 3 — Implement: replace the entire file content with the restructured version.**

The new file uses module-scope `vi.fn()` spies, a `beforeEach` that sets default no-data state,
a minimal `Scorecard` fixture, and organises tests into describe blocks for shell, render
branches, period selector, and derived values.

```typescript
import { vi, describe, it, expect, beforeEach } from 'vitest';
import { screen, fireEvent } from '@testing-library/react';
import { renderWithQuery } from '../test-utils/renderWithQuery';
import ScorecardDetail from './ScorecardDetail';
import type { Scorecard } from '../api/outcomes';

// --------------------------------------------------------------------------
// Module-scope vi.fn() spies — same pattern as SignalTable.test.tsx
// --------------------------------------------------------------------------
const mockUseScorecard = vi.fn();
const mockUseEdgeDecay = vi.fn();
const mockUseIntervals = vi.fn();
const mockUseDistribution = vi.fn();
const mockUseBackfillMutation = vi.fn();
const mockUseSignals = vi.fn();

vi.mock('react-router-dom', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react-router-dom')>();
  return {
    ...actual,
    useParams: () => ({ scannerType: 'pre_market_volume_spike' }),
  };
});

vi.mock('../hooks/useScorecard', () => ({
  useScorecard: (...args: unknown[]) => mockUseScorecard(...args),
  useEdgeDecay: (...args: unknown[]) => mockUseEdgeDecay(...args),
  useIntervals: (...args: unknown[]) => mockUseIntervals(...args),
  useDistribution: (...args: unknown[]) => mockUseDistribution(...args),
  useBackfillMutation: (...args: unknown[]) => mockUseBackfillMutation(...args),
  useSignals: (...args: unknown[]) => mockUseSignals(...args),
}));

// Chart components fail in jsdom — keep mocked (R5)
vi.mock('../components/scorecard/EdgeDecayChart', () => ({ default: () => null }));
vi.mock('../components/scorecard/DistributionChart', () => ({ default: () => null }));

// --------------------------------------------------------------------------
// Minimal fixture — mirrors HeroMetrics.test.tsx baseScorecard shape
// --------------------------------------------------------------------------
const baseScorecard: Scorecard = {
  scanner_type: 'pre_market_volume_spike',
  period: '30d',
  total_signals: 10,
  complete_signals: 8,
  win_rate_pct: 62.5,
  avg_mfe_pct: 3.1,
  avg_mae_pct: -1.2,
  mfe_mae_ratio: 2.6,
  avg_r_multiple: 1.8,
  expectancy: 0.42,
  profit_factor: 1.9,
  follow_through_rate_pct: 75.0,
  edge_decay: [],
  interval_breakdown: {},
};

// --------------------------------------------------------------------------
// Default state for all tests: no-data, not loading, no error
// --------------------------------------------------------------------------
beforeEach(() => {
  mockUseScorecard.mockReturnValue({ data: null, isLoading: false, isError: false });
  mockUseEdgeDecay.mockReturnValue({ data: [], isLoading: false });
  mockUseIntervals.mockReturnValue({ data: {}, isLoading: false });
  mockUseDistribution.mockReturnValue({ data: [], isLoading: false });
  mockUseBackfillMutation.mockReturnValue({
    mutate: vi.fn(),
    isPending: false,
    isSuccess: false,
    isError: false,
    data: null,
    error: null,
  });
  mockUseSignals.mockReturnValue({
    data: { signals: [], total: 0, limit: 25, offset: 0 },
    isLoading: false,
  });
});

// --------------------------------------------------------------------------
// Shell — static elements present in every render state
// --------------------------------------------------------------------------
describe('ScorecardDetail — shell', () => {
  it('renders without crashing', () => {
    renderWithQuery(<ScorecardDetail />);
  });

  it('shows period selector buttons', () => {
    renderWithQuery(<ScorecardDetail />);
    expect(screen.getByRole('button', { name: /7D/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /30D/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /90D/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /ALL/i })).toBeInTheDocument();
  });

  it('shows severity combobox with "All Severities" option', () => {
    renderWithQuery(<ScorecardDetail />);
    expect(screen.getByRole('combobox')).toBeInTheDocument();
    expect(screen.getByText(/All Severities/i)).toBeInTheDocument();
  });

  it('shows "Signal quality analysis" subtitle', () => {
    renderWithQuery(<ScorecardDetail />);
    expect(screen.getByText(/Signal quality analysis/i)).toBeInTheDocument();
  });

  it('shows "Backfill Outcomes" toggle button', () => {
    renderWithQuery(<ScorecardDetail />);
    expect(screen.getByRole('button', { name: /Backfill Outcomes/i })).toBeInTheDocument();
  });

  it('shows back arrow link', () => {
    renderWithQuery(<ScorecardDetail />);
    expect(screen.getByRole('link')).toBeInTheDocument();
  });
});

// --------------------------------------------------------------------------
// Render branches — the four conditional paths ScorecardDetail.tsx owns
// (lines 99–128 of the source component)
// --------------------------------------------------------------------------
describe('ScorecardDetail — render branches', () => {
  it('no-data: shows "No outcome data yet" when scorecard is null and not loading', () => {
    // beforeEach default is already no-data state
    renderWithQuery(<ScorecardDetail />);
    expect(screen.getByText(/No outcome data yet/i)).toBeInTheDocument();
  });

  it('loading: shows animate-pulse skeleton and hides no-data message', () => {
    mockUseScorecard.mockReturnValue({ data: null, isLoading: true, isError: false });
    const { container } = renderWithQuery(<ScorecardDetail />);
    expect(container.querySelectorAll('.animate-pulse').length).toBeGreaterThan(0);
    expect(screen.queryByText(/No outcome data yet/i)).not.toBeInTheDocument();
  });

  it('error: shows "Failed to load scorecard data" message', () => {
    mockUseScorecard.mockReturnValue({ data: null, isLoading: false, isError: true });
    renderWithQuery(<ScorecardDetail />);
    expect(screen.getByText(/Failed to load scorecard data/i)).toBeInTheDocument();
  });

  it('with-data: hides no-data message and mounts HeroMetrics subtree', () => {
    mockUseScorecard.mockReturnValue({ data: baseScorecard, isLoading: false, isError: false });
    renderWithQuery(<ScorecardDetail />);
    // No-data message must be absent (R6: do not assert child component metric values)
    expect(screen.queryByText(/No outcome data yet/i)).not.toBeInTheDocument();
    // HeroMetrics DOM subtree is present — assert static label, not metric value
    expect(screen.getByText(/Win Rate/i)).toBeInTheDocument();
  });
});

// --------------------------------------------------------------------------
// Period selector — active-state styling
// --------------------------------------------------------------------------
describe('ScorecardDetail — period selector', () => {
  it('clicking ALL button makes it the active selection (bg-financial-blue class)', () => {
    renderWithQuery(<ScorecardDetail />);
    const allButton = screen.getByRole('button', { name: /ALL/i });
    fireEvent.click(allButton);
    expect(allButton).toHaveClass('bg-financial-blue');
  });

  it('7D and 30D buttons remain present after clicking ALL', () => {
    renderWithQuery(<ScorecardDetail />);
    fireEvent.click(screen.getByRole('button', { name: /ALL/i }));
    expect(screen.getByRole('button', { name: /7D/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /30D/i })).toBeInTheDocument();
  });
});

// --------------------------------------------------------------------------
// Derived values — transforms owned by ScorecardDetail.tsx
// --------------------------------------------------------------------------
describe('ScorecardDetail — derived values', () => {
  it('displayName: pre_market_volume_spike renders as "PRE MARKET VOLUME SPIKE" in heading', () => {
    // useParams mock returns scannerType: 'pre_market_volume_spike'
    // Component applies .replace(/_/g, ' ') + title-case + .toUpperCase() → "PRE MARKET VOLUME SPIKE"
    renderWithQuery(<ScorecardDetail />);
    // Case-sensitive: verifies .toUpperCase() was applied (not just title-case intermediate)
    expect(screen.getByRole('heading', { name: 'PRE MARKET VOLUME SPIKE' })).toBeInTheDocument();
  });
});
```

**Step 4 — Verify all tests pass:**

```bash
cd /workspace/markethawk/frontend
npx vitest run src/pages/ScorecardDetail.test.tsx 2>&1 | tail -30
# Expected: all tests pass, no failures
```

**Step 5 — Commit:**

```bash
cd /workspace/markethawk
git add frontend/src/pages/ScorecardDetail.test.tsx
git commit -m "test(frontend): restructure ScorecardDetail tests — module-scope vi.fn() spies + render branches + derived values (issue #309)"
```

---

## Task 2: Verify coverage gate

**Files**: `frontend/vitest.config.ts` (read-only verify — no changes expected)

### TDD steps

**Step 1 — Run full coverage suite:**

```bash
cd /workspace/markethawk/frontend
npx vitest run --coverage 2>&1 | tail -30
# Expected output (thresholds from vitest.config.ts):
# statements : ≥ 30%
# branches   : ≥ 27%
# functions  : ≥ 22%
```

**Step 2 — If coverage drops below any threshold:**

The restructure adds tests for three previously untested branches (loading, error, with-data) and
two new derive-state paths. Coverage should rise, not fall. If a threshold is missed:

a. Run with `--reporter=verbose` to identify which file regressed:
```bash
cd /workspace/markethawk/frontend
npx vitest run --coverage --reporter=verbose 2>&1 | grep -E "ScorecardDetail|threshold"
```

b. Add one focused test for the uncovered branch per the spec's assumption note (R7):
   - If the `with-data` branch test does not exercise the `scorecard && <HeroMetrics>` line,
     confirm `baseScorecard` is being passed via `mockReturnValue` (not `mockReturnValueOnce`)
     since `useScorecard` is called once per render.
   - Re-run until gate is green.

**Step 3 — Commit (only if vitest.config.ts thresholds needed updating):**

If actual coverage rose above the current thresholds and the coverage pattern requires updating,
use the formula `floor(actual) - 3` clamped to min 30 (stmts/lines) / 22 (branches/functions):

```bash
# Example — only commit if thresholds changed
git add frontend/vitest.config.ts
git commit -m "test(frontend): bump coverage thresholds post-ScorecardDetail restructure (issue #309)"
```

---

## Summary

| Task | Files | Tests | Steps |
|------|-------|-------|-------|
| 1. Restructure test file | `ScorecardDetail.test.tsx` | +9 new, 7 consolidated | 5 |
| 2. Verify coverage gate | `vitest.config.ts` (read-verify) | — | 3 |

**Total**: 2 tasks, 8 steps. Single-file change. No backend, no migrations.
