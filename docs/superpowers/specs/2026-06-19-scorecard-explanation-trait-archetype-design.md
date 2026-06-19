# Scorecard Upgrade: Explanation Trait and Archetype Performance

**Date:** 2026-06-19
**Issue:** #468
**Parent epic:** #449 (Explanation-Aware Edge Intelligence)
**Status:** Spec — pending review

---

## Overview

Scanner signals already receive a `signal_quality_score` and MFE/MAE outcomes. Epic 2 (#449) adds
explanation data — `criteria_passed`, `criteria_failed`, `confidence_inputs`, and
`data_quality_warnings` — to every scanner event. Issue #468 surfaces that explanation data on the
existing Scorecard Detail page so users can answer: *which traits produced edge, which destroyed it,
and which signal archetypes perform best?*

No new page or route is added. The existing `ScorecardDetail.tsx` (at `/scorecard/:scannerType`)
gains two new sections rendered from two new backend endpoints delivered by #465 and #466.

---

## Requirements

1. `ScorecardDetail` shows **top-5 positive explanation traits** (highest win rate / avg MFE) and
   **top-5 negative explanation traits** (lowest win rate / worst avg MFE) for the selected scanner
   type, date range, and severity.

2. `ScorecardDetail` shows a **archetype performance table** listing all archetypes for the scanner
   type with sample size, win rate, avg MFE, avg MAE, and a tooltip showing user-readable trait
   drivers.

3. Both new sections respect the existing page-level filters: period buttons (7D / 30D / 90D / ALL)
   and severity dropdown — the same `start_date`, `end_date`, and `severity` params passed to
   existing scorecard queries.

4. Rows where `sample_size < 30` display an inline **orange "Low sample" badge** and are visually
   de-emphasised (`text-gray-500` on numeric cells).

5. All four UI states must be handled: **loading** (skeleton rows), **empty** (no data message),
   **low-sample** (badge + de-emphasis), and **populated** (normal rendering).

6. Frontend tests cover all four states for both sections.

---

## Architecture / Approach

### Page changes

The insertion order in `ScorecardDetail.tsx` becomes:

```
Header (filters)
HeroMetrics
Charts Row (EdgeDecayChart + DistributionChart)
IntervalTable
──────────────── NEW ──────────────────────────
TraitPerformanceTable      ← new component
ArchetypePerformanceTable  ← new component
───────────────────────────────────────────────
SignalTable
BackfillPanel
```

Both new sections are co-located in a `frontend/src/components/scorecard/` sub-directory, matching
the established component-per-section pattern.

### API contract — trait performance

Issue #465 delivers:

```
GET /api/v1/outcomes/trait-performance/{scanner_type}
    ?start_date=YYYY-MM-DD&end_date=YYYY-MM-DD&severity=<low|medium|high>
```

New TypeScript interfaces (added to `frontend/src/api/outcomes.ts`):

```typescript
export type TraitType =
  | 'criteria_passed'
  | 'criteria_failed'
  | 'confidence_input'
  | 'data_quality_warning';

export interface TraitPerformance {
  trait_type: TraitType;
  trait_key: string;             // e.g. "premarket.relative_volume"
  label: string;                 // user-readable label from explanation.criteria_passed[key].label
  sample_size: number;
  win_rate: number;              // 0–100 (percentage)
  follow_through_rate: number;   // 0–100 (percentage)
  avg_mfe_pct: number;
  avg_mae_pct: number;
  ci_low: number | null;         // confidence bound; null when sample < 30
  ci_high: number | null;
  low_sample: boolean;           // true when sample_size < 30
}

export interface TraitPerformanceResponse {
  scanner_type: string;
  top_positive: TraitPerformance[];   // up to 5, sorted by win_rate desc
  top_negative: TraitPerformance[];   // up to 5, sorted by win_rate asc
}

export const fetchTraitPerformance = async (params: {
  scanner_type: string;
  start_date?: string;
  end_date?: string;
  severity?: string;
}): Promise<TraitPerformanceResponse> => {
  const { scanner_type, ...rest } = params;
  const response = await apiClient.get(
    `/outcomes/trait-performance/${scanner_type}`,
    { params: rest },
  );
  return response.data;
};
```

### API contract — archetype performance

Issue #466 delivers:

```
GET /api/v1/outcomes/archetypes/{scanner_type}
    ?start_date=YYYY-MM-DD&end_date=YYYY-MM-DD&severity=<low|medium|high>
```

New TypeScript interfaces (added to `frontend/src/api/outcomes.ts`):

```typescript
export interface ArchetypeTraitDriver {
  trait_key: string;
  label: string;        // user-readable, e.g. "High relative volume"
  weight: number;       // centroid component weight 0–1
}

export interface ArchetypeReturnInterval {
  median_pct: number;
  win_rate: number;
  sharpe: number;
  n: number;
}

export interface ArchetypePerformance {
  id: number;
  label: string;
  event_count: number;
  trait_drivers: ArchetypeTraitDriver[];
  return_profile: Record<string, ArchetypeReturnInterval>;
  low_sample: boolean;   // true when event_count < 30
}

export interface ArchetypePerformanceResponse {
  scanner_type: string;
  archetypes: ArchetypePerformance[];
}

export const fetchArchetypePerformance = async (params: {
  scanner_type: string;
  start_date?: string;
  end_date?: string;
  severity?: string;
}): Promise<ArchetypePerformanceResponse> => {
  const { scanner_type, ...rest } = params;
  const response = await apiClient.get(
    `/outcomes/archetypes/${scanner_type}`,
    { params: rest },
  );
  return response.data;
};
```

### React Query hooks

Two hooks added to `frontend/src/hooks/useScorecard.ts`:

```typescript
export const useTraitPerformance = (
  scannerType: string | undefined,
  params?: { start_date?: string; end_date?: string; severity?: string },
) =>
  useQuery<TraitPerformanceResponse>({
    queryKey: ['traitPerformance', scannerType, params],
    queryFn: () => fetchTraitPerformance({ scanner_type: scannerType!, ...params }),
    enabled: !!scannerType,
  });

export const useArchetypePerformance = (
  scannerType: string | undefined,
  params?: { start_date?: string; end_date?: string; severity?: string },
) =>
  useQuery<ArchetypePerformanceResponse>({
    queryKey: ['archetypePerformance', scannerType, params],
    queryFn: () => fetchArchetypePerformance({ scanner_type: scannerType!, ...params }),
    enabled: !!scannerType,
  });
```

### Component design

#### `TraitPerformanceTable`

`frontend/src/components/scorecard/TraitPerformanceTable.tsx`

Props: `{ topPositive: TraitPerformance[]; topNegative: TraitPerformance[]; isLoading: boolean }`

Layout: two sub-sections in a 2-col grid (matching the Charts Row pattern). Each sub-section is a
card with a header ("Top Positive Traits" / "Top Negative Traits") and a table:

| Trait | Samples | Win Rate | Follow-Through | Avg MFE | Avg MAE |
|-------|---------|----------|---------------|---------|---------|

Reuse `colorForWinRate` and `colorForPct` from `IntervalTable`. The `low_sample` flag renders an
inline badge:
```tsx
{row.low_sample && (
  <span
    className="ml-1.5 inline-block px-1.5 text-[10px] font-bold bg-orange-400/10
                text-orange-400 border border-orange-400/30 rounded"
    title="Fewer than 30 samples — treat with caution"
  >
    Low sample
  </span>
)}
```
Numeric cells on low-sample rows use `text-gray-500` instead of the color helper.

Loading state: 5 skeleton rows in each sub-section. Empty state: "No trait data available." message.

#### `ArchetypePerformanceTable`

`frontend/src/components/scorecard/ArchetypePerformanceTable.tsx`

Props: `{ archetypes: ArchetypePerformance[]; isLoading: boolean }`

Single card, table format:

| Archetype | Samples | Win Rate | Avg MFE | Avg MAE |
|-----------|---------|----------|---------|---------|

The archetype `label` cell includes a `title` attribute with the top-3 trait drivers, space-joined
as human-readable strings, e.g. `"High relative volume · Above VWAP · Clean data"`. This satisfies
#466's "centroid/trait drivers in user-readable terms" AC without requiring a separate tooltip
library.

The `return_profile` JSONB typically contains `1h`, `eod`, `1d` keys; render win_rate from the
`eod` key by default (matching how IntervalTable defaults to the "end of day" slot for the primary
metric). If no `eod` key exists, use the first available key.

Low-sample badge and de-emphasis: identical to `TraitPerformanceTable`.

#### Shared constant

```typescript
// frontend/src/components/scorecard/scorecardConstants.ts
export const LOW_SAMPLE_THRESHOLD = 30;
```

Import in both table components to keep the threshold consistent.

---

## Alternatives Considered

### A: Bar chart for trait performance instead of table

A horizontal bar chart (Recharts `BarChart`) would visually rank traits, but five columns of
metrics (win rate, follow-through, MFE, MAE, samples) do not map well to a single bar chart without
losing data. A grouped-bar approach would be cluttered. The table pattern mirrors `IntervalTable`
and is the established idiom for multi-metric breakdowns on this page. Rejected.

### B: Cards per archetype (HeroMetrics pattern)

Cards work for a fixed small set (HeroMetrics has exactly 4). Archetypes are unbounded (K-means
yields a variable K). A card grid would overflow awkwardly when K > 4. Table chosen for
scalability.

### C: Combine trait and archetype into a single API call

A combined endpoint would reduce round-trips but couples two independently deliverable blocking
tickets (#465 and #466). Keeping them separate lets each issue ship independently, and React Query's
parallel useQuery calls mean both requests fire simultaneously with no added latency.

---

## Open Questions

1. **Exact `return_profile` key names from #466.** The spec assumes `eod` as the default display
   key for archetype win_rate. If #466 uses different interval key names, the frontend default
   selection logic needs updating. Non-blocking: the component falls back to the first available key.

2. **Sorting for archetype rows.** The spec does not prescribe an archetype sort order (by label,
   by event_count, by eod win_rate). Backend can return any order; the frontend renders as received.
   A future sort-header interaction is possible but out of scope for this issue.

3. **Top-N trait cap.** The spec assumes the backend returns at most 5 entries per list
   (`top_positive`, `top_negative`) and the frontend renders all returned rows. If the product
   decision is to allow a user-adjustable limit, that is a separate enhancement.

---

## Assumptions

- **[ASSUMED]** Issues #465 and #466 will implement the exact endpoint paths and response shapes
  defined in this spec. If either issue changes field names, this spec's TypeScript interfaces must
  be updated before implementation begins.

- **[ASSUMED]** The `explanation` JSONB column on `scanner_events` is populated for sufficient
  historical events to produce meaningful trait data. If coverage is sparse, the empty state will
  appear; no special handling is needed.

- **[ASSUMED]** The `LOW_SAMPLE_THRESHOLD = 30` matches the threshold that #465's backend uses to
  set the `low_sample: boolean` flag. This avoids the frontend having to re-implement the logic.

- **[ASSUMED]** No changes to `ScorecardOverview.tsx` are in scope. The overview page shows
  summary cards per scanner type; per-trait and per-archetype breakdowns belong on the detail page.
