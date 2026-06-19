# Regime Performance Panel — Scorecard / Edge Explorer Design

**Date:** 2026-06-19
**Issue:** #526
**Status:** Pending review

## Overview

Issue #106 introduced HMM-based market regime detection and stamps a `regime` column on every `ScannerEvent` at write time. The resulting data — per-regime win rates, average MFE, and average MAE — is already aggregated by `GET /api/v1/outcomes/regime-breakdown/{scanner_type}` but is not yet exposed in the UI.

This spec adds a **Regime Performance Panel** to the `ScorecardDetail` page. The panel presents per-regime outcome evidence (sample size, win rate, avg MFE, avg MAE) with a simple advisory interpretation label for each regime. The first version is explicitly read-only and advisory; it does not influence scanner filtering, alert routing, or any automation behavior.

## Requirements

### Functional

- Fetch regime breakdown data from `GET /api/v1/outcomes/regime-breakdown/{scanner_type}` with the same `start_date`/`end_date` that the page-level period selector (7D/30D/90D/ALL) supplies to every other panel.
- Display one row per regime in the breakdown response. Each row shows:
  - Regime label (`risk_on`, `risk_off`, `high_volatility`, `low_vol_drift`, `transition`)
  - Sample size (count of events with a non-null, complete outcome summary in that regime)
  - Win rate (%)
  - Average MFE (%)
  - Average MAE (%)
  - An advisory interpretation badge
- Show a loading skeleton while the request is in-flight.
- Show an empty state ("No regime data for this scanner yet") when the endpoint returns an empty `breakdown` dict or `total_events: 0`.
- Mark regimes with `sample_size < 20` as **Insufficient Evidence**; show the sample count but suppress win rate, MFE, and MAE values (render `—`) to avoid implying a directional edge.
- For regimes with `sample_size ≥ 20`, apply advisory interpretation tiers:
  - `win_rate_pct ≥ 60` → **Candidate Favorable**
  - `win_rate_pct ≤ 40` → **Candidate Hostile**
  - `40 < win_rate_pct < 60` → **Neutral / Mixed**
- Display a persistent disclaimer on the panel ("Regime interpretation is advisory evidence, not a trading rule.").
- The panel's denominators (sample sizes, total_events) come from the endpoint response, not from the page-level scorecard totals; older events pre-dating #106 carry a null `regime` and are excluded from the breakdown.

### Non-functional

- The panel is purely additive: no backend model changes, no new migration, no change to scanner logic, alert routing, or backtest behavior.
- Threshold constants (`REGIME_MIN_SAMPLE`, `REGIME_FAVORABLE_WIN_PCT`, `REGIME_HOSTILE_WIN_PCT`) are local to the panel module; do not extend `colorByThreshold` or `StatsService.gate_status` for this purpose.

### Tests

Three test units:

1. **`interpretRegime()` pure function** — unit-tests all tier boundaries: `sample_size < 20`, `win_rate ≥ 60`, `win_rate ≤ 40`, and the 40–60 neutral band. Boundary conditions (exactly 20, exactly 40%, exactly 60%) must be covered explicitly.
2. **`fetchRegimeBreakdown` API client function** — in a new `outcomes.test.ts` (no equivalent exists yet). Tests URL construction and response passthrough.
3. **`RegimePerformancePanel.test.tsx` component test** — covers four render states: loading skeleton, empty (no breakdown data), low-sample (insufficient-evidence badge shown, metric cells suppressed), and full multi-regime data (all five metric columns rendered with correct advisory labels).

## Architecture / Approach

### Backend (no changes required)

The endpoint `GET /api/v1/outcomes/regime-breakdown/{scanner_type}` already exists in `backend/app/routers/outcomes.py` and is implemented in `backend/app/services/stats.py:get_regime_breakdown()`. The Pydantic schema in `backend/app/schemas/regime.py` defines:

```python
class RegimeSliceSchema(BaseModel):
    sample_size: int
    win_rate_pct: Optional[float] = None
    avg_mfe_pct: Optional[float] = None
    avg_mae_pct: Optional[float] = None

class RegimeBreakdownResponse(BaseModel):
    scanner_type: str
    total_events: int
    breakdown: Dict[str, RegimeSliceSchema]
```

No backend changes are needed.

### Frontend

#### 1. API client — `frontend/src/api/outcomes.ts`

Add TypeScript interfaces and a fetch function alongside the existing `fetch*` functions:

```typescript
export interface RegimeSlice {
  sample_size: number;
  win_rate_pct: number | null;
  avg_mfe_pct: number | null;
  avg_mae_pct: number | null;
}

export interface RegimeBreakdownResponse {
  scanner_type: string;
  total_events: number;
  breakdown: Record<string, RegimeSlice>;
}

export const fetchRegimeBreakdown = async (
  scannerType: string,
  params?: { start_date?: string; end_date?: string },
): Promise<RegimeBreakdownResponse> => {
  const response = await apiClient.get(`/outcomes/regime-breakdown/${scannerType}`, { params });
  return response.data;
};
```

#### 2. React Query hook — `frontend/src/hooks/useScorecard.ts`

Add `useRegimeBreakdown` matching the `useEdgeDecay` / `useIntervals` pattern (the page owns all queries; panels receive props only):

```typescript
export const useRegimeBreakdown = (
  scannerType: string | undefined,
  params?: { start_date?: string; end_date?: string },
) => {
  return useQuery<RegimeBreakdownResponse>({
    queryKey: ['regimeBreakdown', scannerType, params],
    queryFn: () => fetchRegimeBreakdown(scannerType!, params),
    enabled: !!scannerType,
  });
};
```

#### 3. Interpretation logic — co-located in panel module

```typescript
// Threshold constants — local, do not export
const REGIME_MIN_SAMPLE = 20;
const REGIME_FAVORABLE_WIN_PCT = 60;
const REGIME_HOSTILE_WIN_PCT = 40;

type RegimeInterpretation =
  | 'insufficient_evidence'
  | 'candidate_favorable'
  | 'candidate_hostile'
  | 'neutral_mixed';

export function interpretRegime(slice: RegimeSlice): RegimeInterpretation {
  if (slice.sample_size < REGIME_MIN_SAMPLE || slice.win_rate_pct === null) {
    return 'insufficient_evidence';
  }
  if (slice.win_rate_pct >= REGIME_FAVORABLE_WIN_PCT) return 'candidate_favorable';
  if (slice.win_rate_pct <= REGIME_HOSTILE_WIN_PCT) return 'candidate_hostile';
  return 'neutral_mixed';
}
```

Export `interpretRegime` so the unit test can import it without rendering the component.

#### 4. Component — `frontend/src/components/scorecard/RegimePerformancePanel.tsx`

```
Props:
  data: RegimeBreakdownResponse | undefined
  isLoading: boolean
```

Layout — follows `IntervalTable.tsx` as the closest structural analog:

- Container: `bg-financial-gray rounded-lg border border-gray-700 p-4`
- Section heading: "Regime Performance" (same `text-sm font-semibold text-financial-light` style)
- Loading state: pulse skeleton rows (matches `IntervalTable` skeleton)
- Empty state: centred `text-gray-500 text-sm` message in a `h-40` container
- Data state: `<table>` with columns: **Regime** | **Samples** | **Win Rate** | **Avg MFE** | **Avg MAE** | **Interpretation**
  - Regime label: human-readable (`risk_on` → "Risk On", etc.) in `text-financial-light`
  - Sample size: always shown
  - Win Rate / Avg MFE / Avg MAE: `—` when `< REGIME_MIN_SAMPLE`; otherwise formatted with `%` and sign
  - Interpretation: badge chip with colour coding:
    - `insufficient_evidence` → gray (`bg-gray-700 text-gray-400`)
    - `candidate_favorable` → green (`bg-green-900/40 text-green-400`)
    - `candidate_hostile` → red (`bg-red-900/40 text-red-400`)
    - `neutral_mixed` → yellow (`bg-yellow-900/40 text-yellow-400`)
- Footer disclaimer: `text-[10px] text-gray-500 italic` — "Regime interpretation is advisory evidence, not a trading rule."

#### 5. `ScorecardDetail.tsx` — wiring

Insert the panel between the `SignalTable` block and the `BackfillPanel` block (after line 148 in the current file):

```tsx
// Add hook call alongside others at top of component
const { data: regimeBreakdown, isLoading: loadingRegime } = useRegimeBreakdown(
  scannerType,
  dates,  // same object passed to useScorecard / useEdgeDecay
);

// Insert panel in JSX after </SignalTable> block
{scannerType && (
  <RegimePerformancePanel data={regimeBreakdown} isLoading={loadingRegime} />
)}
```

No new query cache keys need invalidation from `BackfillPanel`'s mutation (backfill does not create `ScannerEvent.regime` stamps retroactively; that would require re-running the HMM for historical events, which is out of scope).

### File inventory

| File | Change |
|------|--------|
| `frontend/src/api/outcomes.ts` | Add `RegimeSlice`, `RegimeBreakdownResponse` interfaces; add `fetchRegimeBreakdown()` |
| `frontend/src/hooks/useScorecard.ts` | Add `useRegimeBreakdown()` hook |
| `frontend/src/components/scorecard/RegimePerformancePanel.tsx` | New component |
| `frontend/src/components/scorecard/RegimePerformancePanel.test.tsx` | New component test |
| `frontend/src/pages/ScorecardDetail.tsx` | Wire `useRegimeBreakdown` + render `RegimePerformancePanel` |
| `frontend/src/api/outcomes.test.ts` | New API client test (`fetchRegimeBreakdown`) |

No backend files change.

## Alternatives Considered

### A. Panel in the charts row (replacing DistributionChart position)
Rejected. The existing charts row is a fixed two-column grid (`grid-cols-1 lg:grid-cols-2`). Inserting regime here would either evict `DistributionChart` (out of scope) or break the layout. Regime performance is supplementary analytical context, not a headline metric.

### B. Panel between IntervalTable and SignalTable
Considered. Regime context is thematically adjacent to interval breakdown, so placing it here (option A in brainstorming) would read naturally. Rejected in favour of post-SignalTable placement because the primary drill-down flow (HeroMetrics → charts → IntervalTable → SignalTable) should complete before advisory context is introduced. Users who want regime context can scroll past the detailed signal list.

### C. Separate `/regime` route or tab
Rejected as over-engineering for a v1 advisory panel. The issue explicitly scopes this as a single panel on the existing scorecard surface.

### D. All-time-only data (ignore period selector)
Considered. All-time data maximises per-regime sample counts, which aids statistical reliability. Rejected because the rest of the page is period-contextualized; a panel that silently disagrees with the period selector would confuse users. The `< 20` sample gate handles small-window degradation gracefully by surfacing "insufficient evidence" rather than showing misleading numbers.

## Open Questions (non-blocking)

1. **Regime label sort order**: Should regimes be displayed in a fixed order (e.g., `risk_on` first, `high_volatility` last) or sorted by sample size descending? Not specified by the issue; implementation can default to sample-size descending.
2. **Backfill integration**: `BackfillPanel` triggers `ScannerOutcomeSnapshot` creation for historical events. It does not retroactively stamp `ScannerEvent.regime` for pre-#106 events. If a future issue adds historical regime re-labeling, the panel's query will automatically reflect it without changes.
3. **`neutral` vs `mixed evidence`** as separate tiers: The issue groups them as "neutral / mixed evidence" with a slash, implying a single combined tier. This spec treats them as one tier. If the product later wants to distinguish "flat neutral" (win rate ~50%, MFE ≈ MAE) from "mixed evidence" (decent win rate but adverse MFE/MAE ratio), an MFE-vs-MAE rule would need to be added to `interpretRegime()`.

## Assumptions

- **[Assumption]** The HMM regime labels in use are the five defined in `RegimeService`: `risk_on`, `risk_off`, `high_volatility`, `low_vol_drift`, `transition`. The panel renders whatever labels the endpoint returns, so this assumption holds even if a future model adds states.
- **[Assumption]** No migration is needed. `ScannerEvent.regime` and `RegimeModel` already exist; the regime-breakdown endpoint already exists; only the frontend wiring is missing.
- **[Assumption]** The page-level severity filter (`All Severities` / `high` / `medium` / `low`) is not threaded into the regime-breakdown call. The endpoint does not currently accept a `severity` param, and adding one is out of scope for this issue.
- **[Assumption]** `BackfillPanel`'s `onSuccess` invalidation does not need to include `regimeBreakdown` in its query key list, since backfill creates outcome snapshots/summaries for existing events but does not add or change `regime` labels on those events.
