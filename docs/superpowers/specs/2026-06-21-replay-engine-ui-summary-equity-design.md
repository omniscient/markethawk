# Replay Engine UI — Run Summary, Equity Curve, Edge-Decay & Regime Charts

**Issue:** #489  
**Date:** 2026-06-21  
**Epic:** Canonical Signal Replay Engine (#483)  
**Depends on:** Issue #488 (REST API `/api/v1/replay`) — must be deployed before this UI is implemented.  
**Out of scope:** Per-signal drill-down + run comparison (issue #490).

---

## Overview

The `/replay` page is the primary interactive UI for the Canonical Signal Replay Engine. It lets users create a new replay run, monitor its progress, and inspect the completed run's analytics: headline performance metrics, an equity curve, edge-decay charts, and a regime breakdown grid.

The existing `/api/v1/backtest/` surface (issue #300/301) remains untouched. This page targets the new `/api/v1/replay/` endpoints defined in issue #488 only.

---

## Requirements

### R1 — Route and navigation

- Register `/replay` as a lazy-loaded route in `frontend/src/App.tsx` following the existing `lazy(() => import('./pages/...'))` pattern.
- Add **"Signal Replay"** as a nav entry in `frontend/src/components/Layout.tsx` in the analytics cluster, immediately after **Scorecard**:
  - `href: /replay`
  - `icon: History` (from `lucide-react`)
  - `name: 'Signal Replay'`

### R2 — API client (`api/replay.ts`)

Create `frontend/src/api/replay.ts` with typed functions and interfaces for:

| Function | HTTP call |
|----------|-----------|
| `createReplayRun(payload)` | `POST /api/v1/replay/runs` |
| `listReplayRuns(filters?)` | `GET /api/v1/replay/runs` |
| `getReplayRun(id)` | `GET /api/v1/replay/runs/{id}` |
| `getReplayAnalytics(id)` | `GET /api/v1/replay/runs/{id}/analytics` |

All calls use `apiClient` from `frontend/src/api/client.ts` (never raw `fetch`).

Key TypeScript interfaces (source of truth for this spec; adjust names to match #488 Pydantic schemas once finalized):

```typescript
// POST /runs request
interface CreateReplayRunPayload {
  scanner_type: string;
  trading_strategy_id: number;
  universe_id: number;
  start_date: string;        // YYYY-MM-DD
  end_date: string;          // YYYY-MM-DD
  max_hold_days: number;     // 1–252
  exit_fidelity?: 'intraday' | 'daily';  // default: 'intraday'
  benchmark_symbol?: string; // default: 'SPY'
}

// GET /runs, GET /runs/{id}
interface ReplayRunSummary {
  id: number;
  status: 'queued' | 'running' | 'completed' | 'failed';
  scanner_type: string;
  start_date: string;
  end_date: string;
  error_message?: string | null;
  // Headline stats (null until completed)
  hit_rate?: number | null;
  expectancy_r?: number | null;
  profit_factor?: number | null;
  max_drawdown_r?: number | null;
  avg_hold_days?: number | null;
  total_trades?: number | null;
  signals_skipped?: number | null;
  created_at: string;
  completed_at?: string | null;
}

// GET /runs/{id}/analytics
interface ReplayAnalytics {
  equity_curve: Array<{ date: string; cumulative_r: number }>;
  calendar_decay: Array<{
    quarter: string;       // e.g. "2025-Q3"
    hit_rate: number;
    expectancy_r: number;
    trade_count: number;
  }>;
  holding_period_decay: Array<{
    day: number;           // 1 … max_hold_days
    avg_return: number;
    avg_mfe: number;
  }>;
  regime_breakdown: Array<{
    trend: 'up' | 'down' | 'flat';
    vol: 'high' | 'low';
    hit_rate: number;
    expectancy_r: number;
    trade_count: number;
  }>;
}
```

### R3 — Page layout (`pages/Replay/index.tsx`)

The page shell owns all React Query calls and state. Panels receive data via props only (per ARCHITECTURE.md frontend conventions).

**Top zone — run controls:**

1. **Recent runs selector**: a dropdown (`<select>`) populated by `listReplayRuns({ status: 'completed' })`. Selecting a run loads it as the active run. Label: "Select completed run…". Refreshes its list every 30 s via `refetchInterval`.

2. **Run creation form** (always visible below selector, never hidden): see R4.

3. **Status bar**: when the active run's status is `queued` or `running`, show a polling status indicator with the status text. Poll `getReplayRun(activeRunId)` every 5 s via `refetchInterval: 5000`. Stop polling on `completed` or `failed`.

**Bottom zone — run detail (shown only when active run is completed):**

- View 1: Run Summary + Equity Curve (`RunSummaryPanel`)
- View 2: Edge-Decay & Regime Charts (`AnalyticsPanel`)

Both panels fetch from `getReplayAnalytics(activeRunId)` (a single React Query call shared across both panels via the page shell).

### R4 — Run creation form (`pages/Replay/RunCreateForm.tsx`)

Form fields:

| Field | Type | Options / validation |
|-------|------|---------------------|
| Scanner type | `<select>` | Populated from `GET /api/v1/scanner/types`; required |
| Strategy | `<select>` | Populated from `GET /api/v1/trading/strategies`; required |
| Universe | `<select>` | Populated from `GET /api/v1/universe/`; required |
| Start date | `<input type="date">` | Required; date preset buttons (7D, 30D, 90D, 1Y) same as ScanConfigPanel |
| End date | `<input type="date">` | Required; ≥ start_date |
| Max hold (days) | `<input type="number">` | 1–252; default 10 |
| Exit fidelity | `<select>` | `intraday` (default, label "Intraday — minute bars") \| `daily` (label "Daily — OHLC only") |
| Benchmark | `<input type="text">` | Uppercase, alphanumeric, 1–6 chars; default "SPY" |

On submit: call `createReplayRun(payload)` via `useMutation`. On success, set the returned run as the active run and start polling. On error, show the error message inline.

Submit button disabled while any required field is missing or mutation is pending.

### R5 — View 1: Run Summary + Equity Curve (`pages/Replay/RunSummaryPanel.tsx`)

**Headline metrics panel** — 7 metric cards displayed in a grid (follow MetricCard component from `components/ui/MetricCard`):

| Metric | Source field |
|--------|-------------|
| Hit rate | `hit_rate` (as %) |
| Expectancy (R) | `expectancy_r` |
| Profit factor | `profit_factor` |
| Max drawdown | `max_drawdown_r` (as R, negative) |
| Avg hold (days) | `avg_hold_days` |
| Total trades | `total_trades` |
| Signals skipped | `signals_skipped` |

**Equity curve** — a Recharts `AreaChart` with:
- X-axis: `date` (formatted as "MMM 'yy")
- Y-axis: `cumulative_r` in R-multiples
- Data: `analytics.equity_curve`; exclude points with no `cumulative_r` (open/skipped trades are not included in the server-side series)
- Reference line at y=0
- Library: Recharts `AreaChart` + `Area` (existing analytics chart pattern from `EdgeExplorer.tsx`)

### R6 — View 2: Edge-Decay & Regime Charts (`pages/Replay/AnalyticsPanel.tsx`)

**Calendar-decay chart** — `BarChart` (Recharts):
- X-axis: `quarter` labels
- Y-axis: `hit_rate` (primary) — `expectancy_r` shown in tooltip
- Data: `analytics.calendar_decay`
- Title: "Calendar Decay (by quarter)"

**Holding-period decay chart** — `LineChart` (Recharts):
- X-axis: `day` (1 … max_hold_days)
- Y-axis: `avg_return` (primary line) + `avg_mfe` (secondary line)
- Data: `analytics.holding_period_decay`
- Title: "Holding-Period Decay"
- Two lines: "Avg Return" and "Avg MFE"

**Regime grid** — an HTML table (not a chart), 3 columns (trend: `up` / `down` / `flat`) × 2 rows (vol: `high` / `low`), yielding 6 cells. Each cell displays `hit_rate` (%) and `expectancy_r` (R) from `analytics.regime_breakdown` filtered by `{ trend, vol }`. Empty cells (no trades in that regime) show "—". Color-code by expectancy: positive → green-tinted, negative → red-tinted. Title: "Regime Breakdown (trend × vol)".

### R7 — Loading and error states

- While `listReplayRuns` or any prerequisite query is loading: show a spinner.
- While the active run is `queued` or `running`: show a status badge ("Queued" / "Running…") with an animated indicator in the top zone; suppress View 1 and View 2 panels.
- If the active run is `failed`: show `run.error_message` in a red error banner; suppress View 1 and View 2 panels.
- If the analytics query is loading (after status = completed): show a skeleton loader in both View panels.

### R8 — TypeScript

`npx tsc --noEmit` passes with no new errors. No `any` types in `api/replay.ts` or the Replay page components.

---

## Approach

**Single analytics endpoint for both views.** The `GET /api/v1/replay/runs/{id}/analytics` response includes all data for View 1 and View 2 (equity curve, calendar decay, holding-period decay, regime breakdown), all cached in `replay_run.metrics` JSONB by MetricsComputer (#487). The page shell fetches this once and passes slices to each panel. No client-side metric recomputation.

**File structure:**
```
frontend/src/
  api/
    replay.ts                   ← new
  pages/
    Replay/
      index.tsx                 ← shell: React Query, state, layout
      RunCreateForm.tsx         ← creation form (R4)
      RunSummaryPanel.tsx       ← headline metrics + equity curve (R5)
      AnalyticsPanel.tsx        ← calendar decay + holding-period + regime grid (R6)
```

**React Query keys:**
```
['replay-runs']                           # list (refetchInterval: 30s)
['replay-run', runId]                     # single run for polling (refetchInterval: 5s while not terminal)
['replay-analytics', runId]               # analytics (fetched once per completed run)
['scanner-types']                         # reuse existing key if already cached
['trading-strategies']                    # list of strategies for form dropdown
['universes']                             # list of universes for form dropdown
```

---

## Alternatives Considered

### A — Client-side equity curve from trade ledger

Fetch `GET /runs/{id}/trades` (paginated) and compute the running R sum in the browser.

**Rejected:** MetricsComputer (#487) already materializes the equity series during max-drawdown computation — persisting it to `metrics` JSONB is free. Forcing a paginated trades fetch duplicates server-side logic in JS and requires multiple requests for large trade ledgers. The acceptance criteria phrase "from the API" confirms server-derived data is the intent.

### B — Tab-based layout (New Run / Recent Runs / Results)

A tabbed page that hides the creation form behind a tab once a run completes.

**Rejected:** The Scanner page (ScanConfigPanel) establishes the pattern of showing the form and results simultaneously (form up top, results below). Tabs would hide form context and make it harder to compare the active run's inputs with its outputs.

### C — Ticker autocomplete for benchmark_symbol

Use `GET /api/v1/stocks/search` to power a combobox autocomplete.

**Rejected:** No reusable combobox component exists in the frontend today. The valid benchmark set is small and well-known (SPY, QQQ, IWM, DIA). A plain text input with light validation (uppercase, 1–6 alphanumeric chars) is simpler; invalid symbols fail server-side with a clear error from issue #486's benchmark ingestion step.

---

## Open Questions (non-blocking)

1. **`replay_run.metrics` exact field names** — Issue #488/487 schemas are not yet finalized. TypeScript types in `api/replay.ts` may need field-name adjustments once those schemas are locked. The spec uses `snake_case` throughout, consistent with existing backend conventions.

2. **Strategy endpoint** — Assumed to be `GET /api/v1/trading/strategies`. Verify this endpoint returns a list with `{ id, name }` fields before implementing the dropdown.

3. **Regime grid empty-cell treatment** — A regime cell with zero trades displays "—". A future enhancement could grey out the cell to distinguish "no data in this regime" from "data present but no trades passed."

---

## Assumptions

- **[ASSUMPTION]** The `/api/v1/replay/runs` REST API (issue #488) is deployed and returns responses matching the types in R2 before this UI is implemented.
- **[ASSUMPTION]** `exit_fidelity` accepted values are `"intraday"` and `"daily"` — derived from the intraday-accurate exit simulator in issue #485.
- **[ASSUMPTION]** `GET /runs/{id}/analytics` returns a top-level `equity_curve` array (list of `{date, cumulative_r}` objects), even though issue #488 describes the endpoint as "calendar decay + holding-period decay + regime breakdown." The MetricsComputer (#487) builds the equity curve for max-drawdown computation and should cache it in `metrics` alongside the other analytics.
- **[ASSUMPTION]** Regime breakdown uses the **new** #486 regime classifier (trend: up/down/flat × vol: high/low — 6 cells), independent of the existing `RegimeService` HMM whose labels (`risk_on`, `risk_off`, `high_volatility`, `low_vol_drift`, `transition`) do not map to orthogonal 2D axes.
- **[ASSUMPTION]** `History` from `lucide-react` is available in the existing version installed in the frontend. If not present, use `Rewind` or `Repeat` as a fallback.
- **[ASSUMPTION]** `GET /api/v1/trading/strategies` (existing endpoint) returns strategies with at least `{ id, name }` fields suitable for a form dropdown.
