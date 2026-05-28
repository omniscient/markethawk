# TypeScript Strict Mode — Incremental Rollout Implementation Plan

**Date**: 2026-05-28
**Issue**: [#92 — Enable TypeScript strict mode incrementally](https://github.com/omniscient/markethawk/issues/92)
**Spec**: `Docs/superpowers/specs/2026-05-27-typescript-strict-mode-design.md`
**Status**: Pending Architect Review

---

## Goal

Enable TypeScript strict mode in four sequential PRs, each adding one or more `tsconfig.json` compiler flags and replacing the `any` annotations those flags expose. The end state is `"strict": true` with zero `any` in the api/ layer and all `@ts-expect-error` suppressions documented and counted.

---

## Architecture

This is a frontend-only change. No backend code, no migrations. Each phase:
1. Updates `frontend/tsconfig.json`
2. Fixes compiler errors surfaced by the new flag(s)
3. Replaces `any` in the api/ layer files mandated by spec requirement 3
4. Passes `npx tsc --noEmit` with zero errors before committing

Phases must be implemented sequentially — Phase N depends on Phase N-1 being merged.

---

## Tech Stack

- **TypeScript compiler**: `npx tsc --noEmit` run from `frontend/`
- **No new tooling required** — all changes are type annotations in existing `.ts`/`.tsx` files

---

## File Structure

| File | Change |
|------|--------|
| `frontend/tsconfig.json` | Incremental flag additions across all 4 phases |
| `frontend/src/api/watchlist.ts` | Phase 1: add explicit return type to `removeFromWatchlist` callback |
| `frontend/src/api/journal.ts` | Phase 1: replace 5 `any` with 4 new request/response interfaces |
| `frontend/src/api/scanner.ts` | Phase 1–3: replace `handleApiError` param, index sig, OHLCVRow, Record types, sync return types |
| `frontend/src/utils/indicators.ts` | Phase 2: annotate `results` array and `data` param type |
| `frontend/src/components/ui/StockChart.tsx` | Phase 2: annotate `allMarkers` array |
| `frontend/src/api/stocks.ts` | Phase 3: replace 2 `Promise<any>` with typed response interface |
| `frontend/src/components/scorecard/DistributionChart.tsx` | Phase 4: Recharts formatter cast |
| `frontend/src/pages/EdgeExplorer.tsx` | Phase 4: Recharts formatter cast |

---

## Tasks

### Task 1 — Phase 1 PR: `noImplicitAny`

**Files**:
- `frontend/tsconfig.json`
- `frontend/src/api/watchlist.ts`
- `frontend/src/api/journal.ts`
- `frontend/src/api/scanner.ts`

---

**Step 1.1 — Verify the baseline error count**

Run the compiler with only `noImplicitAny` to confirm the 1 expected error before making changes:

```bash
cd frontend
npx tsc --noEmit --noImplicitAny 2>&1 | head -20
```

Expected output:
```
src/api/watchlist.ts(XX,XX): error TS7011: Function implicitly has return type 'any'...
Found 1 error.
```

---

**Step 1.2 — Fix `watchlist.ts`: add explicit return type to the callback in `removeFromWatchlist`**

The error is at `watchlist.ts(29,49)` — the `.then(() => undefined)` callback's return type cannot be inferred. Add an explicit `: void` return type to the callback:

```typescript
// frontend/src/api/watchlist.ts line 28-29 — before:
const removeFromWatchlist = (symbol: string): Promise<void> =>
  apiClient.delete(`/watchlist/${symbol}`).then(() => undefined);

// After:
const removeFromWatchlist = (symbol: string): Promise<void> =>
  apiClient.delete(`/watchlist/${symbol}`).then((): void => undefined);
```

After fixing:

```bash
npx tsc --noEmit --noImplicitAny 2>&1 | tail -3
# Expected: Found 0 errors.
```

---

**Step 1.3 — Add interfaces to `journal.ts` and replace the 5 `any` annotations**

Add the four new interfaces at the top of the types section in `frontend/src/api/journal.ts`, then update the function signatures.

```typescript
// frontend/src/api/journal.ts — add after existing interfaces

export interface CreateTradeRequest {
  symbol: string;
  side?: string;
  open_date?: string;
  quantity?: number;
  avg_entry_price?: number;
  notes?: string;
}

export interface CreateJournalEntryRequest {
  entry_date: string;
  content: string;
  sentiment?: string;
}

export interface CreateTagRequest {
  name: string;
  color?: string;
}

export interface ImportTradesResponse {
  imported: number;
  skipped: number;
  errors: string[];
}
```

Update the function signatures in `journalApi`:

```typescript
// Line 76 — before:
createTrade: async (trade: any): Promise<Trade> => {
// After:
createTrade: async (trade: CreateTradeRequest): Promise<Trade> => {

// Line 81 — before:
updateTrade: async (tradeId: number, data: any): Promise<Trade> => {
// After:
updateTrade: async (tradeId: number, data: Partial<CreateTradeRequest>): Promise<Trade> => {

// Line 91 — before:
importTrades: async (file: File, broker: string): Promise<any> => {
// After:
importTrades: async (file: File, broker: string): Promise<ImportTradesResponse> => {

// Line 106 — before:
createEntry: async (data: any): Promise<JournalEntry> => {
// After:
createEntry: async (data: CreateJournalEntryRequest): Promise<JournalEntry> => {

// Line 116 — before:
createTag: async (data: any): Promise<Tag> => {
// After:
createTag: async (data: CreateTagRequest): Promise<Tag> => {
```

---

**Step 1.4 — Fix `scanner.ts` line 758: change `error: any` to `error: unknown`**

`handleApiError` currently takes `error: any`. With `noImplicitAny`, callers that pass an inferred-`any` catch variable would error. Replace with `error: unknown` and add an `instanceof` guard:

```typescript
// frontend/src/api/scanner.ts line 758 — before:
export const handleApiError = (error: any): string => {
  if (error.response) {
    return error.response.data?.detail ?? error.response.statusText;
  }
  if (error.request) {
    return 'Unable to connect to server';
  }
  return error.message ?? 'An unexpected error occurred';
};

// After:
export const handleApiError = (error: unknown): string => {
  if (error && typeof error === 'object' && 'response' in error) {
    const e = error as { response: { data?: { detail?: string }; statusText: string } };
    return e.response.data?.detail ?? e.response.statusText;
  }
  if (error && typeof error === 'object' && 'request' in error) {
    return 'Unable to connect to server';
  }
  if (error instanceof Error) {
    return error.message;
  }
  return 'An unexpected error occurred';
};
```

---

**Step 1.5 — Enable `noImplicitAny` in `tsconfig.json` and verify**

```typescript
// frontend/tsconfig.json — update the "Linting" block:
/* Linting - Relaxed for existing code */
"strict": false,
"noImplicitAny": true,
"noUnusedLocals": false,
"noUnusedParameters": false,
"noFallthroughCasesInSwitch": true
```

Run the full check:

```bash
cd frontend
npx tsc --noEmit
```

Expected:
```
# No output — zero errors
```

If any errors appear from component files accessing `error.message` on the narrowed `handleApiError` callers, those callers were already passing `any` explicitly — fix by adding `instanceof Error` guard at the call site.

---

**Step 1.6 — Commit Phase 1**

```bash
cd frontend && npx tsc --noEmit
# Confirm zero errors

cd /workspace/markethawk
git add frontend/tsconfig.json \
        frontend/src/api/watchlist.ts \
        frontend/src/api/journal.ts \
        frontend/src/api/scanner.ts
git commit -m "feat(ts): Phase 1 — enable noImplicitAny, type api/journal layer

- Adds noImplicitAny to tsconfig.json
- Replaces 5 explicit any in journalApi with CreateTradeRequest,
  Partial<CreateTradeRequest>, CreateJournalEntryRequest, CreateTagRequest,
  ImportTradesResponse interfaces
- Changes handleApiError param from any to unknown with instanceof guard
- Adds explicit ': void' return type to removeFromWatchlist .then() callback (fixes the 1 implicit-any error)

Closes part of #92"
```

---

### Task 2 — Phase 2 PR: `strictNullChecks`

**Files**:
- `frontend/tsconfig.json`
- `frontend/src/utils/indicators.ts`
- `frontend/src/components/ui/StockChart.tsx`
- `frontend/src/api/scanner.ts`

---

**Step 2.1 — Verify the baseline error count**

With Phase 1 merged, run with both cumulative flags:

```bash
cd frontend
npx tsc --noEmit --noImplicitAny --strictNullChecks 2>&1 | head -40
```

Note: the spec's baseline of 16 errors was measured on the original codebase before Phase 1 was applied. After Phase 1, this command may produce **zero compiler errors** — this is expected and does not mean Steps 2.2–2.4 can be skipped. Those steps are required by spec Req 3 (api/ layer zero `any`) regardless of whether the compiler reports errors; the explicit `: any` and `as any` patterns are already syntactically valid and suppress the errors they would otherwise emit.

---

**Step 2.2 — Fix `indicators.ts`: annotate the `results` array and the `data` parameter**

The error is on line 18: `const results = []` — TypeScript infers `never[]` when `strictNullChecks` is active and no push has happened yet.

First, define a return type interface for the SuperTrend calculation (at the top of the file):

```typescript
// frontend/src/utils/indicators.ts — add before the function:
export interface DoubleSuperTrendPoint {
  time: unknown;
  tsl1: number;
  tsl2: number;
  trend: number;
}

export interface OHLCVInput {
  High: number;
  Low: number;
  Close: number;
  time: unknown;
}
```

Update the function signature and array initialization:

```typescript
// frontend/src/utils/indicators.ts — before:
export function calculateDoubleSuperTrend(
  data: any[],
  factor: number = 3,
  atrPeriod: number = 12
) {
  if (data.length < atrPeriod) return [];
  const results = [];

// After:
export function calculateDoubleSuperTrend(
  data: OHLCVInput[],
  factor: number = 3,
  atrPeriod: number = 12
): DoubleSuperTrendPoint[] {
  if (data.length < atrPeriod) return [];
  const results: DoubleSuperTrendPoint[] = [];
```

---

**Step 2.3 — Fix `StockChart.tsx`: annotate the `allMarkers` array**

The error is on line 348: `let allMarkers: any[] = []`. With `strictNullChecks` active and the `data: any[]` prop now typed, this narrows to `never[]`. Replace with the correct marker type from `lightweight-charts`:

```typescript
// frontend/src/components/ui/StockChart.tsx
// Add SeriesMarker to the existing import from 'lightweight-charts':
import {
  createChart,
  ColorType,
  IChartApi,
  ISeriesApi,
  CandlestickData,
  LineData,
  AreaData,
  Time,
  CandlestickSeries,
  AreaSeries,
  LineSeries,
  HistogramSeries,
  createSeriesMarkers,
  SeriesMarker,     // ADD THIS
} from 'lightweight-charts';

// Line 348 — before:
let allMarkers: any[] = [];
// After:
let allMarkers: SeriesMarker<Time>[] = [];
```

Also update the `StockChartProps` interface to replace `data: any[]` and `events?: any[]`:

```typescript
// frontend/src/components/ui/StockChart.tsx — update the interface:
interface StockChartProps {
  data: OHLCVInput[];    // import OHLCVInput from '../../utils/indicators'
  type: 'candlestick' | 'area' | 'line';
  timespan?: string;
  height?: number;
  events?: ScannerEvent[];  // import ScannerEvent from '../../api/scanner'
  highlightDate?: string;
  symbol?: string;
  liveData?: {
    ev: string;
    sym: string;
    v: number;
    // ... remaining fields unchanged
  };
}
```

If the `events` prop typing causes downstream issues with non-ScannerEvent event shapes, keep `events?: unknown[]` until those call sites are audited, but do not use `any[]`.

Update the `markersPluginRef` type:

```typescript
// Add SeriesMarker to the lightweight-charts import line (SeriesType NOT needed)
import {
  ...,
  SeriesMarker,
} from 'lightweight-charts';

// Before:
const markersPluginRef = useRef<any | null>(null);
// After:
const markersPluginRef = useRef<ReturnType<typeof createSeriesMarkers> | null>(null);
```

For `seriesRef`, keep `ISeriesApi<any>` — lightweight-charts does not export a base series interface, and `ISeriesApi<SeriesType>` would make `setData` require the intersection of all series data types (unsatisfiable at call sites). This is a library type limitation per spec Req 7; add a comment:

```typescript
// Before:
const seriesRef = useRef<ISeriesApi<any> | null>(null);
// After — keep ISeriesApi<any>: lightweight-charts has no base series interface;
// ISeriesApi<SeriesType> would make setData unsatisfiable at call sites (Req 7 library limitation).
const seriesRef = useRef<ISeriesApi<any> | null>(null);
```

Note: Phase 2's `StockChartProps.events` typing may affect `components/ui/Chart.tsx` (the wrapper). After applying the `events?: ScannerEvent[]` change, run:

```bash
cd frontend && npx tsc --noEmit 2>&1 | grep "Chart.tsx"
```

If `Chart.tsx` has a type error at its `events` pass-through, change `StockChart.tsx`'s `events` prop to `events?: unknown[]` instead of `events?: ScannerEvent[]` — this eliminates the type error while still removing `any`. Do not use `any[]`.

For `stCloudSeriesRef.current?.setData(cloudData as any)` on line 344 — `stCloudSeriesRef` is `ISeriesApi<'Candlestick'>` (see line 84 of StockChart.tsx), so its `setData` expects `CandlestickData[]`. Use the precise target type:

```typescript
// Before (line 344):
stCloudSeriesRef.current?.setData(cloudData as any);
// After — per spec Req 7: library cast exempt from @ts-expect-error budget.
// lightweight-charts CandlestickSeries is used for the SuperTrend cloud band;
// cloudData matches CandlestickData shape at runtime (OHLC fields present).
stCloudSeriesRef.current?.setData(cloudData as unknown as CandlestickData[]);
```

Also fix line 396: `seenTimes.has(m.time as any)` → `seenTimes.has(m.time as Time)`.

---

**Step 2.4 — Add `OHLCVRow` interface to `scanner.ts` and replace the 3 remaining `any`**

```typescript
// frontend/src/api/scanner.ts — add after existing interfaces (before fetchHistoricalData):

export interface OHLCVRow {
  Date: string;
  Open: number;
  High: number;
  Low: number;
  Close: number;
  Volume: number;
  vwap?: number;
  transactions?: number;
  vwap_intraday?: number;
  marker_type?: string;
  contract_month?: string;
  [k: string]: string | number | undefined;
}
```

Update `fetchHistoricalData` return type (line 614):

```typescript
// frontend/src/api/scanner.ts
// Before (inside the return type of fetchHistoricalData):
  data: any[];
// After:
  data: OHLCVRow[];
```

Update the two `const row: any = {}` occurrences (lines 637 and 662):

```typescript
// Line 637 — before:
const row: any = {};
// After:
const row: OHLCVRow = {} as OHLCVRow;

// Line 662 — before:
const row: any = {};
// After:
const row: OHLCVRow = {} as OHLCVRow;
```

Update `ScannerRunStatus` index signature (line 246):

```typescript
// Before:
[k: string]: any;
// After:
[k: string]: string | number | boolean | null | undefined;
```

---

**Step 2.5 — Enable `strictNullChecks` in `tsconfig.json` and verify**

```json
{
  "compilerOptions": {
    "strict": false,
    "noImplicitAny": true,
    "strictNullChecks": true,
    "noUnusedLocals": false,
    "noUnusedParameters": false,
    "noFallthroughCasesInSwitch": true
  }
}
```

```bash
cd frontend
npx tsc --noEmit
# Expected: zero errors
```

If there are additional errors beyond the expected files, resolve them following the budget policy: api/ layer files must be fixed with proper types; UI files may use `@ts-expect-error` with explanation (≤5 total this phase).

---

**Step 2.6 — Commit Phase 2**

```bash
cd frontend && npx tsc --noEmit

cd /workspace/markethawk
git add frontend/tsconfig.json \
        frontend/src/utils/indicators.ts \
        frontend/src/components/ui/StockChart.tsx \
        frontend/src/api/scanner.ts
git commit -m "feat(ts): Phase 2 — enable strictNullChecks, add OHLCVRow and SuperTrend types

- Adds strictNullChecks to tsconfig.json
- Defines DoubleSuperTrendPoint + OHLCVInput in indicators.ts; annotates results array
- Replaces any[] props in StockChart with OHLCVInput[] and ScannerEvent[]
- Annotates allMarkers as SeriesMarker<Time>[] in StockChart
- Adds OHLCVRow interface in scanner.ts; replaces 3 any row/data annotations
- Narrows ScannerRunStatus index sig from any to primitive union

Closes part of #92"
```

---

### Task 3 — Phase 3 PR: Remaining strict flags + Recharts casts

**Files**:
- `frontend/tsconfig.json`
- `frontend/src/api/scanner.ts`
- `frontend/src/api/stocks.ts`
- `frontend/src/components/ScannerResults.tsx` (Record<string, unknown> consumer fix)
- `frontend/src/components/scorecard/DistributionChart.tsx` (Recharts formatter cast — surfaces with strictFunctionTypes)
- `frontend/src/pages/EdgeExplorer.tsx` (Recharts formatter cast — surfaces with strictFunctionTypes)

---

**Step 3.1 — Verify compiler errors before adding any annotations**

`strictPropertyInitialization` requires `strictNullChecks` — include all cumulative flags:

```bash
cd frontend
npx tsc --noEmit \
  --noImplicitAny \
  --strictNullChecks \
  --strictFunctionTypes \
  --strictBindCallApply \
  --strictPropertyInitialization \
  --noImplicitThis \
  --alwaysStrict \
  --useUnknownInCatchVariables 2>&1 | head -20
```

Expected: exactly 2 errors — Recharts TS2322 formatter type mismatches in `DistributionChart.tsx` and `EdgeExplorer.tsx`. These appear because `strictFunctionTypes` is enabled in Phase 3, not Phase 4 as the spec states. They are fixed in Steps 3.5 and 3.6 below.

If any errors beyond these 2 appear, fix them before updating tsconfig.

---

**Step 3.2 — Audit `catch` blocks in all api/ files**

`useUnknownInCatchVariables` changes all untyped `catch (e)` parameters to `unknown`. Audit every catch block in `src/api/` to verify none accesses `e.message`, `e.response`, or other properties without narrowing.

```bash
cd frontend
grep -n "catch" src/api/scanner.ts src/api/journal.ts src/api/stocks.ts src/api/watchlist.ts
```

The two catch blocks in `scanner.ts` (lines 271 and 707) pass `e` directly to `console.error(...)` — `console.error` accepts `...data: any[]` so `unknown` is compatible. No change needed.

`handleApiError` in `scanner.ts` was already fixed in Phase 1 (parameter is `unknown` with `instanceof` guard). No change needed.

If any new `catch (e: any)` pattern is found during the audit, remove the explicit `: any` annotation so TypeScript treats `e` as `unknown`, then add the appropriate narrowing (`instanceof Error`) before accessing properties.

---

**Step 3.3 — Replace remaining `Record<string, any>` in `scanner.ts` api/ interfaces**

The ScannerEvent, ScannerConfig, StockUniverse interfaces still have `Record<string, any>` for dynamic backend data fields. Replace with `Record<string, unknown>`:

```typescript
// frontend/src/api/scanner.ts

// ScannerEvent (lines 21-23) — before:
indicators: Record<string, any>;
criteria_met: Record<string, any>;
metadata: Record<string, any>;
// After:
indicators: Record<string, unknown>;
criteria_met: Record<string, unknown>;
metadata: Record<string, unknown>;

// ScannerConfig (lines 67-68) — before:
parameters: Record<string, any>;
criteria: Record<string, any>[];
// After:
parameters: Record<string, unknown>;
criteria: Record<string, unknown>[];

// StockUniverse (line 80) — before:
criteria: Record<string, any>;
// After:
criteria: Record<string, unknown>;

// createStockUniverse argument (line 396) — before:
criteria: Record<string, any>;
// After:
criteria: Record<string, unknown>;

// updateStockUniverse argument (line 411) — before:
criteria?: Record<string, any>;
// After:
criteria?: Record<string, unknown>;
```

Note: These changes may cause type errors in UI component files that access `.indicators.someField` and use the result as a typed number/string. Those call sites are UI-local and may use `// @ts-expect-error` within the 5-per-phase budget, or narrow with `typeof value === 'number' ? value : 0`. Check by running `npx tsc --noEmit` after this step.

---

**Step 3.3b — Fix `ScannerResults.tsx`: narrow `Record<string, unknown>` access**

Changing `ScannerEvent.indicators` to `Record<string, unknown>` in Step 3.3 will break `ScannerResults.tsx:263` where indicators values are used in arithmetic comparisons (e.g., `event.indicators[key] > 0`). Fix by adding type narrowing at each access site:

```bash
cd frontend
npx tsc --noEmit 2>&1 | grep "ScannerResults" | head -20
```

For each error, narrow the `unknown` value before use:

```typescript
// frontend/src/components/ScannerResults.tsx
// Before (example — exact line from tsc output):
event.indicators[key] > 0

// After:
(typeof event.indicators[key] === 'number' ? event.indicators[key] : 0) > 0
```

If the narrowing is non-trivial (e.g., nested property access on `unknown`), use `@ts-expect-error` within the 5-per-phase budget:

```typescript
// @ts-expect-error — indicators value is unknown; narrowing requires runtime shape inspection
event.indicators[key] > 0
```

---

**Step 3.4 — Replace `Promise<any>` on sync functions in `scanner.ts`**

Add a typed response interface and update the four sync functions:

```typescript
// frontend/src/api/scanner.ts — add near the top of the types section:
export interface TaskEnqueueResponse {
  task_id: string;
  status: string;
  message?: string;
}
```

Update the four functions (all hit universe/sync endpoints — `TaskEnqueueResponse` is an appropriate shape for all; `stopSync` returns the same `{task_id, status, message?}` structure when it confirms the stop request):

```typescript
// frontend/src/api/scanner.ts line 419 — before:
export const syncFundamentals = async (delay: number = 15.0): Promise<any> => {
// After:
export const syncFundamentals = async (delay: number = 15.0): Promise<TaskEnqueueResponse> => {

// Line 424 — before:
export const syncMetrics = async (): Promise<any> => {
// After:
export const syncMetrics = async (): Promise<TaskEnqueueResponse> => {

// Line 429 — before:
export const syncTickerDetails = async (delay: number = 15.0): Promise<any> => {
// After:
export const syncTickerDetails = async (delay: number = 15.0): Promise<TaskEnqueueResponse> => {

// Line 434 — before:
export const stopSync = async (): Promise<any> => {
// After:
export const stopSync = async (): Promise<TaskEnqueueResponse> => {
```

---

**Step 3.5 — Replace `Promise<any>` in `stocks.ts`**

Add a response interface and update both functions:

```typescript
// frontend/src/api/stocks.ts — add after StockDetailConsolidated interface:
export interface StockDataTaskResponse {
  status: string;
  message?: string;
  task_id?: string;
}
```

Update the two functions:

```typescript
// Line 43 — before:
): Promise<any> => {
// After:
): Promise<StockDataTaskResponse> => {

// Line 55 — before:
export const syncMissingStockAggregates = async (ticker: string): Promise<any> => {
// After:
export const syncMissingStockAggregates = async (ticker: string): Promise<StockDataTaskResponse> => {
```

---

**Step 3.5b — Fix Recharts formatter cast in `DistributionChart.tsx`**

The `strictFunctionTypes` flag surfaces the Recharts formatter errors in Phase 3 (not Phase 4 as stated in the spec). Fix them here so Phase 3 compiles cleanly. `Formatter` is not exported from the recharts main index — derive the type from `Tooltip`'s public ComponentProps:

```typescript
// frontend/src/components/scorecard/DistributionChart.tsx
// Tooltip is already imported from 'recharts'. Add React import if not present:
import React from 'react';

// Derive the formatter type from the already-imported Tooltip component:
type TooltipFormatterFn = NonNullable<React.ComponentProps<typeof Tooltip>['formatter']>;

// Line 103 — before:
formatter={(value: number) => [`${value} events`, 'Count']}
// After — per spec Req 7: library cast, does not count against @ts-expect-error budget.
// strictFunctionTypes: (value: number) not assignable to (value: TValue) because TValue
// includes string and array; runtime behavior correct — this chart only passes numbers.
formatter={((value: number) => [`${value} events`, 'Count']) as unknown as TooltipFormatterFn}
```

---

**Step 3.5c — Fix Recharts formatter cast in `EdgeExplorer.tsx`**

```typescript
// frontend/src/pages/EdgeExplorer.tsx
// Tooltip is already imported from 'recharts'. Derive the type locally:
type TooltipFormatterFn = NonNullable<React.ComponentProps<typeof Tooltip>['formatter']>;

// Line 381 — before:
formatter={(value: number, name: string) => {
  if (name === 'avg_eod_pct') return [`${value?.toFixed(2)}%`, 'Avg EOD %'];
  if (name === 'follow_through_rate') return [`${(value * 100).toFixed(1)}%`, 'Follow-through'];
  return [value, name];
}}
// After — per spec Req 7: library cast, does not count against @ts-expect-error budget.
// Same Recharts strictFunctionTypes limitation as DistributionChart.
formatter={((value: number, name: string) => {
  if (name === 'avg_eod_pct') return [`${value?.toFixed(2)}%`, 'Avg EOD %'];
  if (name === 'follow_through_rate') return [`${(value * 100).toFixed(1)}%`, 'Follow-through'];
  return [value, name];
}) as unknown as TooltipFormatterFn}
```

---

**Step 3.6 — Enable remaining strict flags in `tsconfig.json` and verify**

```json
{
  "compilerOptions": {
    "strict": false,
    "noImplicitAny": true,
    "strictNullChecks": true,
    "strictFunctionTypes": true,
    "strictBindCallApply": true,
    "strictPropertyInitialization": true,
    "noImplicitThis": true,
    "alwaysStrict": true,
    "useUnknownInCatchVariables": true,
    "noUnusedLocals": false,
    "noUnusedParameters": false,
    "noFallthroughCasesInSwitch": true
  }
}
```

```bash
cd frontend
npx tsc --noEmit
# Expected: zero errors
```

If `Record<string, unknown>` changes in Step 3.3 caused UI component errors: tally the `@ts-expect-error` suppressions. If the count would exceed 5, split the largest UI fix into a separate follow-up issue before merging.

---

**Step 3.7 — Commit Phase 3**

```bash
cd frontend && npx tsc --noEmit
# Expected: zero errors

cd /workspace/markethawk
git add frontend/tsconfig.json \
        frontend/src/api/scanner.ts \
        frontend/src/api/stocks.ts \
        frontend/src/components/ScannerResults.tsx \
        frontend/src/components/scorecard/DistributionChart.tsx \
        frontend/src/pages/EdgeExplorer.tsx
git commit -m "feat(ts): Phase 3 — remaining strict flags, type api/ remaining any, Recharts casts

- Adds strictFunctionTypes, strictBindCallApply, strictPropertyInitialization,
  noImplicitThis, alwaysStrict, useUnknownInCatchVariables to tsconfig.json
- Replaces Record<string,any> in ScannerEvent, ScannerConfig, StockUniverse
  with Record<string,unknown>; adds narrowing in ScannerResults.tsx consumers
- Adds TaskEnqueueResponse; types the 4 sync* functions in scanner.ts
- Adds StockDataTaskResponse; types refreshStockData and syncMissingStockAggregates
- Adds Recharts formatter casts in DistributionChart.tsx and EdgeExplorer.tsx
  (strictFunctionTypes surfaces these in Phase 3, not Phase 4 as spec states;
  library cast per Req 7, exempt from @ts-expect-error budget)

Closes part of #92"
```

---

### Task 4 — Phase 4 PR: `strict: true` + `noUnusedLocals` + `noUnusedParameters`

**Files**:
- `frontend/tsconfig.json`
- Various UI files surfaced by `noUnusedLocals`/`noUnusedParameters` (identified at runtime — approximately 14 files with `import React from 'react'` removals plus scattered unused params)

---

**Step 4.1 — Enable `strict: true` in tsconfig and measure the errors**

```json
{
  "compilerOptions": {
    "strict": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "noFallthroughCasesInSwitch": true
  }
}
```

Note: `"strict": true` is a shorthand for all individual strict flags from Phases 1–3 (including `useUnknownInCatchVariables` added in TS 4.4+). Remove the individual `noImplicitAny`, `strictNullChecks`, etc. entries.

```bash
cd frontend
npx tsc --noEmit 2>&1 | sort | uniq -c | sort -rn | head -30
```

Expected: Only TS6133 errors for unused locals and parameters. The 2 Recharts errors were already fixed in Phase 3.

---

**Step 4.2 — Fix unused locals and unused parameters**

Run:

```bash
cd frontend
npx tsc --noEmit 2>&1 | grep "TS6133" | head -40
# TS6133 covers both unused locals AND unused parameters
```

The full TS6133 set is approximately 20 errors: ~14 are `import React from 'react'` (unused with the `react-jsx` transform), and ~6 are non-React unused locals (e.g., `EMPTY_PROGRESS`, `strategies`, `formatDistanceToNow`, `_isFlush`). Fix the React imports first as a batch:

```bash
cd frontend
npx tsc --noEmit 2>&1 | grep "TS6133" | head -30
# Address ALL 20 errors, not just the React ones
```

Remove `import React from 'react'` from each file listed. For each remaining unused **local variable**: remove it if genuinely unused.

For each unused **parameter in a callback signature**: prefix with `_`:

```typescript
// Example:
someArray.map((item, index) => item.value)
// After:
someArray.map((item, _index) => item.value)
```

For unused parameters in destructured props (common React pattern): `({ id: _id, ...rest })`.

For exported API function parameters required by an interface: keep with `_` prefix to preserve the call signature.

Run `npx tsc --noEmit` after each batch of fixes to track progress.

---

**Step 4.3 — Remaining explicit `any` cleanup in UI files**

By Phase 4 all api/ layer `any` is eliminated. Run a final audit of UI files:

```bash
cd frontend
grep -rn ": any\|as any\|any\[\]" src/ --include="*.tsx" --include="*.ts" | \
  grep -v "src/api/" | head -30
```

Apply the tiered policy:
- **Replace if straightforward**: component props, local state, event handlers where the type is obvious.
- **`@ts-expect-error` if non-trivial**: deep chart library integration, dynamic data shapes:
  ```typescript
  // @ts-expect-error — <one-line reason>
  ```

Track the count. If > 5, file follow-up issue `track: ts-strict-deferred-suppressions` before merging.

---

**Step 4.4 — Final verification**

```bash
cd frontend
npx tsc --noEmit
# Expected: zero errors

grep -E '"strict"|"noUnusedLocals"|"noUnusedParameters"' tsconfig.json
# Expected:
# "strict": true,
# "noUnusedLocals": true,
# "noUnusedParameters": true,

git diff HEAD --unified=0 | grep "@ts-expect-error" | wc -l
# Must be ≤ 5; if > 5, file a follow-up issue before committing
```

---

**Step 4.5 — Commit Phase 4**

```bash
cd /workspace/markethawk
# List changed files before staging:
git diff --name-only frontend/src/

# Stage each changed file explicitly by name (tsc output will have identified them):
git add frontend/tsconfig.json
# Add each additional file from tsc output, e.g.:
# git add frontend/src/pages/SomeComponent.tsx frontend/src/hooks/useFoo.ts

git commit -m "feat(ts): Phase 4 — strict: true, noUnusedLocals, noUnusedParameters

- Sets strict: true, noUnusedLocals: true, noUnusedParameters: true in tsconfig.json
- Removes ~14 unused 'import React from react' declarations (react-jsx transform)
- Prefixes unused callback parameters with _ across UI files
- api/ layer has zero any annotations

Closes #92"
```

---

## Summary

| Phase | tsconfig flag(s) | Compiler errors fixed | api/ any replaced | PR |
|-------|-----------------|----------------------|-------------------|-----|
| 1 | `noImplicitAny` | 1 (watchlist.ts) | journal.ts ×5, scanner.ts ×1 | #1 |
| 2 | `strictNullChecks` | up to 16 (indicators.ts + StockChart.tsx) | scanner.ts ×4 | #2 |
| 3 | remaining 6 strict flags | 2 Recharts TS2322 (surface with `strictFunctionTypes`) + ScannerResults narrowing | scanner.ts ×8, stocks.ts ×2 | #3 |
| 4 | `strict: true` + unused | TS6133 unused locals/params (~14 React imports + scattered) | — (all api/ done) | #4 |

Total commands to validate each phase:
```bash
cd frontend && npx tsc --noEmit   # must print nothing (zero errors)
```
