# Decompose Frontend God Files: api/scanner.ts + QualityReportModal.tsx

**Date:** 2026-06-13
**Issue:** #294
**Status:** Spec

---

## Problem

Two frontend files have been flagged as god files across the last three
architecture reviews and have not been addressed:

- `frontend/src/api/scanner.ts` — **808 lines**. Originally a scanner API
  client, it accumulated universe CRUD, quality-report types, historical
  stock data, futures providers, and system storage — all unrelated to
  scanner concerns — through convenience additions over time.

- `frontend/src/components/QualityReportModal.tsx` — **754 lines**. A modal
  that performs all its own data fetching, three mutations, polling, and
  renders five visually distinct panels, all inlined in one component.

Both violate the ~400-line ceiling and hinder comprehension, testing, and
safe change.

---

## Requirements

1. No frontend file produced by this decomposition exceeds ~400 lines.
2. All 33 existing `import { X } from '../api/scanner'` (and `../../api/scanner`)
   call sites continue to compile and work unchanged — no consumer edits
   required to satisfy this constraint.
3. Universe-specific consumers (the ~6 components that deal exclusively with
   universe/quality-report types) are updated to import from the new
   `api/universe.ts` directly — removing their dependence on the scanner facade.
4. `tsc --noEmit` passes after the change.
5. `npx vitest run` passes after the change.
6. Each extracted panel in `QualityReportModal/` gains at least one render
   test (new test files added as part of this issue).

---

## Architecture / Approach

### Part 1: api/scanner.ts → api/scanner/ + api/universe.ts

#### New directory layout

```
frontend/src/api/
  universe.ts              ← NEW: all universe/quality types + functions
  scanner/                 ← replaces scanner.ts
    index.ts               ← facade: re-exports all scanner/* symbols +
    │                         deprecated re-exports of universe symbols
    types.ts               ← all scanner-domain types
    runs.ts                ← enqueue, status, cancel, range, status-block
    results.ts             ← fetch results, clear events, signal quality
    configs.ts             ← fetch configs, fetch history
    reviews.ts             ← submit review, fetch review stats, fetch market stats, movers
    ws.ts                  ← createScannerWebSocket, createScanRunWebSocket
    misc.ts                ← OHLCVRow/fetchHistoricalData, DataProvider/fetchProviders,
                              StorageStats/fetchStorageStats, handleApiError
```

#### api/universe.ts contents

Universe types and functions currently in `api/scanner.ts` move here
verbatim:

| Symbols moved |
|---|
| `StockUniverse`, `UniverseSyncStatus`, `UniverseSummary`, `TaskEnqueueResponse`, `RefreshUniverseResponse`, `SyncAggregatesOptions` |
| `QualityGapEntry`, `CoveragePartialDay`, `CoverageDetail`, `QualityTickerResult`, `NormalizationProgress`, `QualityReport`, `ExportAggregatesOptions` |
| `MonitoredStock` |
| `fetchStockUniverses`, `fetchUniversesForTicker`, `refreshUniverseStats`, `createStockUniverse`, `deleteStockUniverse`, `updateStockUniverse` |
| `syncFundamentals`, `syncMetrics`, `syncTickerDetails`, `stopSync`, `refreshUniverse`, `fetchUniverseStocks` |
| `syncMissingAggregates`, `fetchUniverseSyncStatus`, `exportUniverseAggregates`, `syncUniverseAggregates` |
| `deleteTickerAggregates`, `triggerQualityAnalysis`, `triggerNormalization`, `fetchQualityReport` |

#### api/scanner/index.ts facade

Re-exports **everything** from the scanner sub-files, plus deprecated
re-exports of all universe symbols from `api/universe.ts`:

```ts
// scanner sub-files
export * from './types';
export * from './runs';
export * from './results';
export * from './configs';
export * from './reviews';
export * from './ws';
export * from './misc';

// Universe symbols — deprecated, import from 'api/universe' instead
export type { StockUniverse, UniverseSyncStatus, ... } from '../universe';
export { fetchStockUniverses, ... } from '../universe';
```

The `@deprecated` JSDoc annotation on each re-export signals intent to
editors and future consumers without breaking anything.

#### Universe-specific consumers updated

These six files currently import universe symbols from `api/scanner`. They
are updated to import from `api/universe` directly:

- `components/CreateUniverseModal.tsx`
- `components/ExportUniverseModal.tsx`
- `components/SyncUniverseModal.tsx`
- `components/UniverseDetailsModal.tsx`
- `components/UniverseFormModal.tsx`
- `pages/Universes.tsx`
- `components/QualityReportModal.tsx` (also addressed in Part 2)

Scanner-page consumers that import both scanner and universe symbols (e.g.
`pages/Scanner/index.tsx`) may keep importing from `api/scanner` — the
facade continues to satisfy those imports.

#### Expected line counts

| File | Estimated lines |
|---|---|
| `api/universe.ts` | ~370 |
| `api/scanner/types.ts` | ~200 |
| `api/scanner/runs.ts` | ~110 |
| `api/scanner/results.ts` | ~70 |
| `api/scanner/configs.ts` | ~20 |
| `api/scanner/reviews.ts` | ~60 |
| `api/scanner/ws.ts` | ~30 |
| `api/scanner/misc.ts` | ~100 |
| `api/scanner/index.ts` | ~80 |

All are under 400 lines. ✓

---

### Part 2: QualityReportModal.tsx → directory + hook

#### New directory layout

```
frontend/src/
  hooks/
    useQualityReport.ts         ← NEW: query + 3 mutations + polling + derived flags
    useQualityReport.test.ts    ← unit tests for the hook
  components/
    QualityReportModal/
      index.tsx                 ← modal shell; filter/sort state; connects panels
      index.test.tsx            ← updated from QualityReportModal.test.tsx
      GradeBadge.tsx            ← pure display — grade label + color
      GradeBadge.test.tsx
      ScoreBar.tsx              ← pure display — percentage bar
      ScoreBar.test.tsx
      NormalizationProgressPanel.tsx
      NormalizationProgressPanel.test.tsx
      CoverageBreakdown.tsx
      CoverageBreakdown.test.tsx
      TickerRow.tsx             ← expandable row; owns its local expanded state
      TickerRow.test.tsx
      DeleteConfirmDialog.tsx   ← confirmation overlay
      DeleteConfirmDialog.test.tsx
      QualityOverviewCard.tsx   ← overall grade/score section
      QualityOverviewCard.test.tsx
      QualityFiltersBar.tsx     ← timespan + score-slider + selection count
      QualityFiltersBar.test.tsx
```

#### hooks/useQualityReport.ts

Owns everything that touches React Query and shared async state:

- `useQuery` for `['qualityReport', universeId]`
- `useMutation` for analyze, normalize, delete
- `useEffect` polling loop (2 s interval while pending/running)
- `useEffect` to clear `removedTickers` on fresh complete
- `useEffect` to adopt in-progress normalization on open
- Derived flags: `isAnalyzing`, `isNormalizing`, `isBusy`
- State: `removedTickers`, `normalizationTriggered`

Returns a typed object of data, flags, and mutation trigger functions.
No JSX. Pure-UI state (filters, sort, pendingDelete) stays in
`index.tsx`.

#### components/QualityReportModal/index.tsx

Receives `isOpen`, `onClose`, `universe` props (unchanged interface).
Calls `useQualityReport(universe?.id, isOpen)`.
Owns: `sortKey`, `sortAsc`, `gradeFilter`, `timespanFilter`, `minScore`,
`pendingDelete`, `deleteError` — all local UI state.
Computes `sorted` array from hook data + local filters.
Renders the panels as props-only children.

#### Expected line counts

| File | Estimated lines |
|---|---|
| `hooks/useQualityReport.ts` | ~130 |
| `QualityReportModal/index.tsx` | ~220 |
| `QualityReportModal/QualityOverviewCard.tsx` | ~75 |
| `QualityReportModal/QualityFiltersBar.tsx` | ~65 |
| `QualityReportModal/TickerRow.tsx` | ~100 |
| `QualityReportModal/CoverageBreakdown.tsx` | ~80 |
| `QualityReportModal/NormalizationProgressPanel.tsx` | ~75 |
| `QualityReportModal/DeleteConfirmDialog.tsx` | ~50 |
| `QualityReportModal/GradeBadge.tsx` | ~25 |
| `QualityReportModal/ScoreBar.tsx` | ~20 |

All under 400 lines. ✓

#### Test requirements

Each panel test is a render test confirming the component mounts and
displays key content. No deep mock plumbing required since panels receive
typed props only. Minimum assertions per panel:

- `GradeBadge` — renders the grade letter; applies the correct color class
- `ScoreBar` — renders the bar at the expected width
- `NormalizationProgressPanel` — renders `null` when status is null;
  renders progress text when running
- `CoverageBreakdown` — renders the full-day count; shows partial-day list
- `TickerRow` — renders ticker symbol; expands on click if expandable
- `DeleteConfirmDialog` — renders the ticker name; calls handlers on
  confirm/cancel
- `QualityOverviewCard` — renders the overall grade badge and score
- `QualityFiltersBar` — renders timespan buttons; calls setter on click

The existing `QualityReportModal.test.tsx` moves to
`QualityReportModal/index.test.tsx` with its import updated.

---

## Alternatives Considered

### A. Keep universe code inside api/scanner/ rather than extracting to api/universe.ts

Universe code landing in `scanner.ts` was accidental — the scanner page
needed universe data and convenience won. Keeping it under `api/scanner/`
perpetuates that coupling and creates an odd situation where every domain
lives at the api/ top level *except* universe, hidden inside an unrelated
directory. Option B (top-level `api/universe.ts`) matches the established
`api/stocks.ts`, `api/system.ts`, etc. convention and is the chosen
approach. The ~6 universe-specific consumers are updated to use the direct
path.

### B. Co-locate useQualityReport hook inside components/QualityReportModal/

The existing convention is that all custom hooks — even page-specific,
single-use ones (useScanTask, useScannerState, useScorecard) — live in
`frontend/src/hooks/`. The Alerts page decomposition referenced by the
issue follows this: panels in `pages/Alerts/`, hooks in `hooks/`. The hook
goes to `hooks/useQualityReport.ts` to match that convention.

### C. Inline split only (no domain extraction, no hook)

Split both files purely by line count without extracting domains or hooks.
This satisfies the ~400-line criterion mechanically but produces no
structural improvement — tests remain hard to write, universe code stays
misplaced. Rejected.

---

## Assumptions

- Vite's module resolution treats `import from './api/scanner'` and
  `import from './api/scanner/index'` identically, so converting
  `api/scanner.ts` to `api/scanner/index.ts` requires no changes in
  importers. *(If this assumption is wrong, `tsc --noEmit` will immediately
  surface it.)*

- `StorageStats`/`fetchStorageStats` (currently in scanner.ts, talks to
  `/system/storage`) is kept in `api/scanner/misc.ts` for now rather than
  moved to `api/system.ts`. The blast radius of moving it is low, but it
  is out of scope for this issue. A follow-up issue can finish that
  migration.

- `OHLCVRow`/`fetchHistoricalData` are kept in `api/scanner/misc.ts` for
  the same reason; there is an `api/stocks.ts` but we have not confirmed
  whether a duplicate exists there.

---

## Open Questions (non-blocking)

- Should `handleApiError` move to a shared `api/utils.ts` rather than
  staying in `api/scanner/misc.ts`? (It is used only in scanner-consuming
  components today, but it is utility-shaped.)

- Should `OHLCVRow`/`fetchHistoricalData` be consolidated with or replace
  the stocks-fetch logic in `api/stocks.ts`? (Requires reading both files
  to check for duplication.)
