# Ratchet Frontend Coverage Thresholds to 30%/22% — Design Spec

**Date:** 2026-06-10
**Issue:** #250
**Status:** Spec generated — pending review
**Author:** Refinement Pipeline (Dark Factory)

## Summary

Issue #198 raised frontend test coverage from zero to ~21–22% statements/lines by adding
14 test files and switching from a pinned 7-file include to `all: true` over the full
`src/` tree. The larger denominator exposed many files at 0%. This issue adds high-value
tests for the highest-yield 0%-covered files to reach a **30% statements/lines, 22%
branches/functions** gate, then updates `vitest.config.ts` with new thresholds that
preserve the project's established ~3pp CI headroom.

## Goals

- Add meaningful tests (real assertions, not render-and-pass) for untested source files
  in priority order until coverage actuals clear ~32%/24%, making a 30%/22% gate stable.
- Update the gate in `frontend/vitest.config.ts` using the measured-minus-headroom
  formula already documented in the config.
- Keep CI green throughout: no broken imports, no chart-library jsdom incompatibilities.

## Non-Goals

- Reaching the final 35%/25% target — that is the *next* ratchet increment.
- Testing chart-rendering files (`ChartPanel.tsx`, `DistributionChart.tsx`,
  `EdgeDecayChart.tsx`, `ScorecardDetail.tsx` Recharts sections) — these require
  canvas/jsdom infrastructure that does not exist in this project and would produce
  thin wrappers with no real assertions. They roll forward.
- Refactoring components to extract testable logic — if a file mixes chart rendering
  with data shaping, the spec notes it as a future candidate; no refactor is in scope.

## Decisions (locked during brainstorming)

| # | Decision | Choice |
|---|----------|--------|
| D1 | Scope | Dynamic: write tests in priority order, stop once actuals clear ~32%/24% |
| D2 | Test strategy for chart libs | Selective skip — no vi.mock for chart libraries |
| D3 | Threshold update method | `floor(actual) - 3`, clamped to 30/22 floor (existing headroom pattern) |
| D4 | Test philosophy | Real assertions (rendered output, prop branches, logic correctness) — no thin wrappers |

## Priority Order

Files are ordered by estimated coverage yield (lines × testability). Stop adding test
files once coverage actuals clear 32%/24%.

| Priority | File | Lines | Why Testable |
|----------|------|-------|--------------|
| 1 | `src/utils/indicators.ts` | 105 | Pure TypeScript logic; zero JSX dependencies |
| 2 | `src/pages/StockDetailPage/MetadataPanel.tsx` | 43 | Presentational; props-in, no hooks |
| 3 | `src/pages/StockDetailPage/ScannerHistoryPanel.tsx` | 122 | Presentational; mock-props renders |
| 4 | `src/pages/AutoTrading/AccountPanel.tsx` | 173 | Presentational; props-in pattern matching `components.test.tsx` |
| 5 | `src/pages/AutoTrading/OrdersPanel.tsx` | 87 | Presentational; filter-button branches testable |
| 6 | `src/components/scorecard/HeroMetrics.tsx` | 94 | Presentational; colorByThreshold branches |
| 7 | `src/components/scorecard/IntervalTable.tsx` | 97 | Presentational; table render |
| 8 | `src/components/scorecard/SignalTable.tsx` | 239 | Largest presentational candidate |
| 9 | `src/components/scorecard/BackfillPanel.tsx` | 97 | Presentational |
| — | `src/pages/StockDetailPage/ChartPanel.tsx` | 182 | **SKIP** — Lightweight Charts (jsdom-incompatible) |
| — | `src/components/scorecard/DistributionChart.tsx` | 122 | **SKIP** — Recharts (jsdom-incompatible) |
| — | `src/components/scorecard/EdgeDecayChart.tsx` | 106 | **SKIP** — Recharts (jsdom-incompatible) |

Expectation: priorities 1–5 (sum ~530 lines) should comfortably clear ~32%/24% actuals
given the existing 21%/21%/17%/22% baseline. Verify with `npx vitest run --coverage`
after each file; stop adding files once the gate is provably met with headroom.

## Test Approach by File Type

### Pure logic (`indicators.ts`)

Unit-test `calculateDoubleSuperTrend` directly — import the function, pass synthetic
OHLCV arrays, assert on `tsl1`, `tsl2`, and `trend` fields. Cover:
- Input shorter than `atrPeriod` → returns `[]`
- Warm-up period (i < atrPeriod) vs. steady-state RMA
- Trend direction transitions (1 → -1 → 1)

### Presentational components (props-in, no hooks)

Pattern already established in `components.test.tsx` and `ConfigPanel.test.tsx`:
- Import the named component directly (not the page `index.tsx`)
- Render with `renderWithQuery` or bare `render` from `@testing-library/react`
- Assert on visible text, role-accessible elements, and conditional branches
  (loading state vs. data state vs. empty state)
- No `vi.mock` of data libraries — only mock API hooks if the component imports them

### `StockDetailPage/index.tsx` (not in priority list)

The full `StockDetailPage` (297 lines, heavy hooks) is **not** a priority target in this
increment. Its sub-components (`MetadataPanel`, `ScannerHistoryPanel`) are listed
individually because they can be tested without the page-level hook setup. The full
index.tsx is a candidate for the next ratchet.

## Threshold Update Process

After adding tests and confirming CI is green:

1. Run: `npx vitest run --coverage --reporter=json`
2. Note actuals for `statements`, `branches`, `functions`, `lines`
3. Set each threshold: `floor(actual) - 3`
4. Apply floor: `statements >= 30`, `branches >= 22`, `functions >= 22`, `lines >= 30`
5. Update the comment block in `vitest.config.ts` to record new actuals (continuing the
   pattern at lines 22–24 of the current config)
6. Run coverage once more to confirm the gate is green

Example: if actuals land at 32.4 / 23.8 / 23.1 / 33.1, thresholds become:
`statements: 30` (floor(32.4)-3=29 → clamped to 30), `branches: 20`, `functions: 20`,
`lines: 30`.

## Alternatives Considered

### Alt 1: Hard-code thresholds at exactly 30/22

**Rejected.** v8 coverage can drift by fractions of a percent between environments.
Setting `statements: 30` when actuals are 30.4% leaves 0.4pp margin — a single CI
environment difference could flip the gate red. The existing pattern (3pp headroom) was
chosen precisely because of this; continuing it costs nothing.

### Alt 2: Mock chart libraries (vi.mock) to cover ChartPanel and chart scorecard components

**Rejected.** No existing test mocks a chart library; all 21 prior tests leave chart
files untouched. Mocking `createChart` or Recharts' `ResponsiveContainer` to return
`null` and rendering the empty shell is coverage theater — it produces a line-hit with
no real assertion, exactly the "padding" the #198 spec warned against. These files
roll forward as candidates for a future increment that properly addresses jsdom +
chart-library incompatibility (e.g. extracting data-transform logic into pure helpers).

### Alt 3: Cover all listed candidates regardless of threshold

**Rejected.** The issue's acceptance criterion is threshold-defined, not file-defined.
The candidate list is explicitly framed as "Candidates for the next increment" — a menu.
Covering files that are not needed to meet the gate is unnecessary scope; those files
roll forward to the 35%/25% ratchet issue.

## Assumptions

- [ASSUMPTION] The `renderWithQuery` test utility in `frontend/src/test-utils/` provides
  enough wrapping (QueryClient + Provider) for all presentational components in this list.
  If a component requires Router context (e.g. `Link` elements in `ScannerHistoryPanel`),
  a `MemoryRouter` wrapper will be needed — add it per file as required.
- [ASSUMPTION] Priorities 1–5 will yield enough coverage to clear the 30%/22% gate.
  If actuals after priorities 1–5 are still below 32%/24%, continue to priority 6–9
  before raising thresholds.
- [ASSUMPTION] Vitest v8 coverage numbers are stable across the project's CI environment
  to within ±0.5pp. The 3pp headroom accounts for this.

## Open Questions (non-blocking)

- `ScorecardDetail.tsx` and `ScorecardOverview.tsx` (pages) are at 0% and not in the
  priority list — they depend on Recharts and the `useScorecard` hook. Future increment
  could test the hook-layer separately (the `useScorecard.test.ts` already does this)
  and skip the chart render.
- `ChartPanel.tsx` mixes Lightweight Charts rendering with data-shaping logic. A future
  increment could extract the shaping helpers into a pure utility and test those without
  touching the chart render.
- Once both this ratchet (#250) and the #249 supertrend issue land, confirm coverage
  doesn't regress — the `indicators.ts` tests added here and the potential #249 changes
  may overlap.
