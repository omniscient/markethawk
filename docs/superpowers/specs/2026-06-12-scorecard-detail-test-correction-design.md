# ScorecardDetail Test Correction — Design (issue #309)

**Date**: 2026-06-12
**Issue**: [#309](https://github.com/omniscient/markethawk/issues/309) — test(frontend): scope-correct ScorecardDetail tests (spec #250 non-goal)

## Problem

During the issue #250 frontend coverage ratchet, `frontend/src/pages/ScorecardDetail.test.tsx`
was added out-of-scope to clear the coverage gate. Spec #250 explicitly listed `ScorecardDetail.tsx`
as a non-goal ("Recharts sections roll forward"), and the test was flagged by scope enforcement and
filed as a backlog ticket. The test was retained because removing it drops coverage below the 30%/22%
thresholds.

The test uses a static hook mock factory — all hooks return fixed values regardless of which state
is under test — so all 8 existing tests exercise only the no-data render branch. This is a
coverage-ratchet artifact, not intentional orchestration coverage.

## Goal

Turn the file into a valid permanent addition: restructure it to cover the four conditional render
branches that `ScorecardDetail.tsx` owns, plus the two derived values (`displayName` and period
active state). Use the module-scope `vi.fn()` pattern from `SignalTable.test.tsx` so state is
per-test rather than frozen at module load.

## Requirements

### R1 — Hook mock refactoring
Replace the static `vi.mock('../hooks/useScorecard', () => ({ ... }))` factory with per-hook
`vi.fn()` spies declared at module scope (e.g. `const mockUseScorecard = vi.fn()`), and set
`beforeEach` defaults. Individual tests override via `mockReturnValueOnce` or `mockReturnValue`.

### R2 — Four render branches covered
Test each branch that `ScorecardDetail.tsx` directly owns (lines 99–128):

| Branch | Trigger | Assertion |
|--------|---------|-----------|
| No-data | `useScorecard` returns `{ data: null, isLoading: false, isError: false }` | "No outcome data yet" present |
| Loading | `useScorecard` returns `{ isLoading: true }` | `.animate-pulse` skeleton present, no-data message absent |
| Error | `useScorecard` returns `{ isError: true }` | "Failed to load scorecard data" present |
| With-data | `useScorecard` returns a minimal `Scorecard` object | no-data message absent, HeroMetrics DOM subtree mounted |

For the with-data branch: assert *presence* only — do not re-test metric values, which
`HeroMetrics.test.tsx` owns.

### R3 — Two derived values covered
- **`displayName`** — `scannerType = 'pre_market_volume_spike'` → heading renders `PRE MARKET VOLUME SPIKE`
  (the component applies `.replace(/_/g, ' ')`, title-cases, then `.toUpperCase()`, line 62).
- **Period selector active state** — clicking the `ALL` button makes it the active selection
  (assert the `bg-financial-blue` class appears on the ALL button; assert 7D/30D buttons remain present).

### R4 — Static shell (keep)
Consolidate the existing static-shell tests into one describe block: severity combobox, "All
Severities" option, "Signal quality analysis" subtitle, "Backfill Outcomes" toggle, back arrow link.

### R5 — Chart mocking (keep)
`EdgeDecayChart` and `DistributionChart` remain mocked via `vi.mock(...)`. This is correct:
Recharts components fail in jsdom and both charts have their own test files or are explicitly
deferred. Do not add chart-rendering assertions.

### R6 — Child re-testing excluded
Do not assert on rendered values that belong to child component contracts (`HeroMetrics`,
`SignalTable`, `IntervalTable`, `BackfillPanel`). Each has its own dedicated test file.

### R7 — Coverage remains above gate
After restructure, `npx vitest run --coverage` must report statements/lines ≥ 30%,
branches ≥ 27%, functions ≥ 22% (current thresholds in `frontend/vitest.config.ts`).

## Approach

**Single-file restructure.** Rewrite `ScorecardDetail.test.tsx` in place:

1. Hoist mocks to module scope using `vi.fn()` (same pattern as `SignalTable.test.tsx`).
2. Add `beforeEach` that sets default no-data state.
3. Split into `describe` blocks: `shell`, `render branches`, `period selector`, `derived values`.
4. Add a minimal `Scorecard` fixture (modelled on `HeroMetrics.test.tsx`'s `baseScorecard`).
5. No changes to `ScorecardDetail.tsx` itself.

No new files, no backend changes, no migrations.

### Nice-to-have (non-blocking)
Export `periodToDates` from `ScorecardDetail.tsx` and unit-test the date arithmetic directly
(7-day window produces correct `start_date`/`end_date`; `'all'` returns `{}`). Worthwhile if
the implementer finds the branch tests don't exercise the math, but not required to close #309.

## Alternatives considered

**A — Keep existing 8 tests as-is.** Valid from a "does it pass" perspective, but leaves three
of the four component-owned render branches untested and signals the file was written to pass a
gate rather than to test behavior. Rejected.

**B — Expand to include hook call-signature assertions.** Rejected. Coupling tests to React Query
hook call arguments (which params `useScorecard` receives after a period click) is brittle and
is what `useScorecard.test.ts` should own, not the page test.

**C — Delete the file and compensate with tests elsewhere.** Excision breaks the coverage gate
and was already ruled out by scope enforcement. Rejected.

## Assumptions

- `[ASSUMPTION]` The 4 render branches and 2 derived values in R2/R3 are sufficient to keep
  coverage above the current gate. If running coverage after the restructure shows any shortfall,
  add tests before committing (gate is statements/lines ≥ 30%, branches ≥ 27%, functions ≥ 22%).
- `[ASSUMPTION]` `HeroMetrics`, `SignalTable`, `IntervalTable`, and `BackfillPanel` all have
  dedicated test files (confirmed: `components/scorecard/*.test.tsx` and `hooks/useScorecard.test.ts`).

## Open questions

- None blocking.
