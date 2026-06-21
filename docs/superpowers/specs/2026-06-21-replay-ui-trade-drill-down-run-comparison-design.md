# Replay Engine UI: Per-Signal Drill-Down + Run Comparison — Design Spec

**Date:** 2026-06-21
**Status:** Design (brainstorm complete)
**Issue:** #490 — Replay engine UI: per-signal drill-down + run comparison
**Epic:** #483 — Canonical Signal Replay Engine
**Depends on:** #488 (REST API), #489 (Replay.tsx base page + api/replay.ts)

---

## 1. Problem

The replay engine's base UI (#489) lets users create runs and view headline metrics + analytics charts. Without a way to drill into individual trades on a price chart, users cannot inspect *why* a specific signal succeeded or failed. Without a run-comparison view, they cannot evaluate parameter variants side-by-side. This spec covers View 3 (per-signal drill-down) and View 4 (run comparison) that extend the `Replay.tsx` page created by #489.

---

## 2. Requirements

Distilled from the issue body and Q&A:

- **R1** — Add a "Trades" tab to the per-run detail view in `Replay.tsx` (View 3). The tab is visible once a run is selected from the run list.
- **R2** — The Trades tab shows a sortable, pageable-to-500 table of `replay_trade` rows: ticker, signal date, entry date, exit date, return %, return R, MFE %, MAE %, exit reason, regime trend.
- **R3** — Clicking a trade row opens a chart modal (inline expandable panel or Modal component) showing a daily candlestick chart for the ticker centred on the trade window (entry_date − 5 days to exit_date + 5 days).
- **R4** — The trade chart renders 2 date markers (entry: green arrowUp belowBar; exit: color-coded by exit_reason) and 2 horizontal price lines (stop: red; target: green) via the existing LightweightCharts series.
- **R5** — When the returned trade count reaches 500, display a "Showing first 500 trades" notice below the table.
- **R6** — Table sorting is client-side (all 500 trades fetched once on tab activation). Header clicks toggle asc/desc for ticker, signal_date, return_r, return_pct.
- **R7** — Add multi-select checkboxes to the run list sidebar in `Replay.tsx`. A "Compare Selected" button is enabled when 2–5 runs are checked; disabled below 2 or above 5.
- **R8** — "Compare Selected" replaces the main-panel detail view with a side-by-side comparison grid (View 4). Each column = one run; rows = headline metrics (win_rate, expectancy_r, profit_factor, max_drawdown_r, avg_hold_sessions, total_trades, skipped_count, data_hash).
- **R9** — When `all_hashes_match === false`, show a yellow warning banner above the comparison grid. Add a ⚠ inline icon next to each run's column header that participates in at least one mismatched pair.
- **R10** — `StockChart.tsx` gains two optional props: `replayMarkers?: SeriesMarker<Time>[]` and `priceLines?: Array<{ value: number; color: string; label: string }>` for rendering trade overlays without breaking any existing callers.
- **R11** — `npx tsc --noEmit` passes. The feature is verified in the browser.

---

## 3. Architecture / Approach

### 3.1 Files to create or modify

| File | Change |
|------|--------|
| `frontend/src/components/ui/StockChart.tsx` | Add `replayMarkers` + `priceLines` optional props (see §3.2) |
| `frontend/src/utils/replayChartOverlays.ts` | Pure helper — build markers + price-line specs from a `ReplayTradeResponse` |
| `frontend/src/pages/Replay.tsx` | Extend with View 3 (Trades tab) + View 4 (comparison mode) |
| `frontend/src/api/replay.ts` | Add `fetchReplayTrades(runUuid)` and `fetchReplayCompare(uuids)` hooks (created by #489 — extend here) |

No new routes. No new pages. No backend changes in scope.

### 3.2 Extending `StockChart.tsx`

Add two optional props:

```ts
replayMarkers?: SeriesMarker<Time>[];
priceLines?: Array<{ value: number; color: string; label: string }>;
```

**Markers**: In the existing `useEffect` that builds `allMarkers`, append `replayMarkers ?? []` before calling `markersPluginRef.current.setMarkers()`. No change to existing marker logic.

**Price lines**: Add a separate `useEffect` keyed on `priceLines`. On each update:
1. Call `seriesRef.current?.removePriceLine(pl)` for each previously created price line (tracked via a `useRef<IPriceLine[]>`).
2. For each entry in `priceLines`, call `seriesRef.current?.createPriceLine({ price: entry.value, color: entry.color, lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: true, title: entry.label })`. Store the returned handle.

Cleanup: `useEffect` return removes all price lines.

### 3.3 `replayChartOverlays.ts`

Pure function (no React):

```ts
export function buildReplayOverlays(trade: ReplayTradeResponse): {
  markers: SeriesMarker<Time>[];
  priceLines: Array<{ value: number; color: string; label: string }>;
}
```

Exit reason → exit marker color mapping:
- `target` → `#10b981` (green)
- `stop` → `#ef4444` (red)
- `time_stop` | `delisted_or_data_end` | `no_entry_bar` | unknown → `#f59e0b` (amber)

Price lines:
- Stop: `{ value: trade.stop_price, color: '#ef4444', label: 'Stop' }`
- Target: `{ value: trade.target_price, color: '#10b981', label: 'Target' }`
- Omit if value is null.

### 3.4 View 3 — Trades tab in `Replay.tsx`

**Data fetch** (add to `api/replay.ts`):
```ts
export const fetchReplayTrades = (runUuid: string) =>
  apiClient.get<{ trades: ReplayTradeResponse[]; total: number }>(
    `/replay/runs/${runUuid}/trades?limit=500`
  ).then(r => r.data);
```

React Query key: `['replayTrades', runUuid]`. Enabled only when the "Trades" tab is active.

**Table columns**: Ticker | Signal Date | Entry Date | Exit Date | Return % | R | MFE % | MAE % | Exit Reason | Regime.

**Sort state**: `useState<{ col: string; dir: 'asc' | 'desc' }>({ col: 'signal_date', dir: 'asc' })`. `useMemo` to sort rows without re-fetching.

**500-cap notice**: rendered below table when `trades.length >= 500`.

**Chart modal**: clicking a row sets `selectedTrade: ReplayTradeResponse | null`. If non-null, render a `<Modal>` (reuse `components/ui/Modal.tsx`) containing:

```tsx
<Chart
  data={ohlcvData}          // fetched via existing /stocks/{ticker}/history endpoint
  type="candlestick"
  xKey="Date"
  timespan="day"
  height={400}
  replayMarkers={overlays.markers}
  priceLines={overlays.priceLines}
/>
```

Where `overlays = buildReplayOverlays(selectedTrade)`.

OHLCV fetch: `useQuery(['stockHistory', ticker, period], () => fetchHistoricalData(ticker, period, 'day'))` from `api/scanner/misc.ts`, enabled only when `selectedTrade != null`.

Period selection: compute from signal_date to today. If signal_date is within 30 days → `'90d'`; within 90 days → `'1y'`; within 1 year → `'2y'`; older → `'all'`. This ensures the trade window (signal → exit) is always within the fetched range without requiring custom date params. The chart auto-fits to show all returned bars; entry/exit markers will be present in the visible range.

### 3.5 View 4 — Run comparison mode in `Replay.tsx`

**Run list checkbox**: add a `checked` checkbox cell to the left of each run row. State: `selectedRunUuids: string[]` (useState). Checkbox change toggles the UUID in/out of the array. "Compare Selected" button: enabled when `selectedRunUuids.length >= 2 && selectedRunUuids.length <= 5`.

**Comparison panel**: when the button is clicked, set `compareMode: boolean = true`. The main panel renders the comparison grid instead of the run-detail tabs. A "← Back to run detail" button exits compare mode.

**Data fetch** (add to `api/replay.ts`):
```ts
export const fetchReplayCompare = (uuids: string[]) =>
  apiClient.get<ReplayCompareResponse>(
    `/replay/runs/compare?ids=${uuids.join(',')}`
  ).then(r => r.data);
```

React Query key: `['replayCompare', ...selectedRunUuids]`.

**Grid layout**: Tailwind `grid` with `grid-cols-[auto,repeat(N,1fr)]`. First column = metric label; subsequent columns = one per run.

**Run column header**: `run.uuid.slice(0, 8)` + status badge + scanner_type + date range. If the run participates in any mismatched pair from `comparisons`, append `⚠` in `text-yellow-400`.

**Warning banner** (when `all_hashes_match === false`):
```tsx
<div className="bg-yellow-500/20 border border-yellow-500/30 rounded-lg p-3 text-yellow-400 text-sm flex items-center gap-2">
  <AlertTriangle className="h-4 w-4 flex-shrink-0" />
  These runs used different input data (data-hash mismatch) and are not strictly comparable.
</div>
```

Rendered above the grid.

**Metrics rows**: win_rate (%), expectancy_r (R), profit_factor, max_drawdown_r (R), avg_hold_sessions, total_trades, skipped_count, data_hash (truncated to 8 chars).

---

## 4. Alternatives Considered

### Alt A: Separate sub-routes (`/replay/:runUuid/trades`, `/replay/compare`)

**Pros**: Clean URL-addressable state; browser back/forward navigation. **Cons**: Contradicts "builds on sub-issue 6's page" framing; adds React Router route wiring + two new page files; a navigation context change breaks the single-page replay workflow. **Rejected**: the issue explicitly says "builds on sub-issue 6's page," implying tab extension.

### Alt B: New `TradeReplayChart` wrapper component

**Pros**: Encapsulates all trade-specific chart logic in one file. **Cons**: Duplicates or reaches into StockChart refs/lifecycle, creates two chart components to maintain. The issue says "reuse the existing price-chart component," which means extending it. **Rejected**: extend StockChart with typed optional props instead.

### Alt C: Server-side trade pagination

**Pros**: Handles arbitrarily large run trade counts. **Cons**: Adds page control UI + extra API round-trips for a problem that doesn't exist — the API caps at 500 trades per call and typical runs have 50–300. A "first 500" notice is sufficient. **Rejected**: client-side sort/fetch matches existing table patterns (EdgeExplorer, Scanner).

---

## 5. Assumptions

- **[A1]** Issue #489 is implemented before this: `Replay.tsx`, `api/replay.ts`, the run-list sidebar, and the per-run detail panel all exist. This spec only extends them.
- **[A2]** Issue #488 (REST API) is implemented: `/api/v1/replay/runs/{uuid}/trades` and `/api/v1/replay/runs/compare` are live.
- **[A3]** The `Modal` component at `frontend/src/components/ui/Modal.tsx` exists and is generic enough to host a chart. If not, a simple fixed-position overlay div with backdrop is used.
- **[A4]** `fetchHistoricalData(ticker, period, 'day')` from `frontend/src/api/scanner/misc.ts` returns `OHLCVRow[]` compatible with `StockBarRow`. The period parameter (`'30d'`, `'90d'`, `'1y'`, `'2y'`, `'all'`) is selected dynamically to cover the trade's date range.
- **[A5]** `lightweight-charts` v5 `IPriceLine` type and `series.createPriceLine()` are available in the already-installed package version.

---

## 6. Open Questions (non-blocking)

- **OQ1**: Should the trade chart modal also show the signal-date ScannerEvent marker (linking back to the scanner event that triggered the trade)? Not in scope per issue, but `source_event_id` is available if desired in a follow-up.
- **OQ2**: Should the comparison grid highlight the "best" cell in each metric row? Omitted for now — straightforward to add in a follow-up.
- **OQ3**: What happens when `entry_date` or `exit_date` is null (no_entry_bar trades)? Show chart centred on `signal_date` ± 10 days; omit the entry/exit markers that have no date.
