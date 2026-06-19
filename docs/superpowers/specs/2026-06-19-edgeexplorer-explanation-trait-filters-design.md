# EdgeExplorer Explanation Trait Filters and Archetype Charts — Design

**Date:** 2026-06-19
**Status:** Spec generated — pending review
**Issue:** #469
**Parent epic:** #449 (Explanation-Aware Edge Intelligence)
**Blocked by:** #464 (Historical Analog Service), #465 (Explanation Trait Performance Aggregation), #466 (Signal Archetypes from Explanation Traits)

---

## Overview

EdgeExplorer today surfaces gap/fade statistics and raw-indicator correlations. It cannot answer: "Which explanation criteria are associated with better or worse outcomes?" or "What archetypes do my signals cluster into based on why they fired?"

This issue adds three explanation-aware sections to EdgeExplorer by consuming the three new API endpoints introduced by issues #464–#466:

1. **Explanation Trait Performance** — a sortable table with inline mini-bars showing win_rate and follow_through_rate per trait (criteria_passed, criteria_failed, warning, confidence_input), with sample-quality badges.
2. **Signal Archetypes** — a card grid of up to 6 explanation-based clusters, each showing its human-readable label, event count, return profile, and a low-sample warning.
3. **Edge Decay** — the existing `EdgeDecayChart` component, mounted on EdgeExplorer for the first time (reusing `fetchEdgeDecay` from `api/outcomes.ts` and the existing component from `components/scorecard/EdgeDecayChart.tsx`).

---

## Requirements

1. A `trait_type` dropdown is added to the existing top-bar filter (values: All / criteria\_passed / criteria\_failed / warning / confidence\_input). Selecting a value re-fires the trait-performance query with that filter.

2. The **Explanation Trait Performance** section renders a table inside a `<Card>` component:
   - Each row corresponds to one trait returned by `GET /scanner/trait-performance`.
   - Columns: Trait Label, Sample, Complete, Win Rate (inline bar + %, max 100%), Follow-Through (inline bar + %, max 100%), Avg MFE %, Avg MAE %, Quality.
   - The Quality column shows a badge: green `TRUSTED` (≥30 events), yellow `CAUTION` (10–29), gray `BLOCKED` (<10).
   - Rows are ordered as returned by the API (by sample_size descending).
   - Inline bars are CSS `<div>` elements whose `width` is set as `${value}%`; no external library needed.

3. The **Signal Archetypes** section renders a responsive grid inside a `<Card>` component:
   - Grid: 1 column on small, 2 on medium, 3 on large screens (Tailwind: `grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4`).
   - Each archetype cluster renders as an individual card showing: label (human-readable), event\_count, win\_rate (as `%`), avg\_mfe (as `%`), avg\_mae (as `%`), and a `LOW SAMPLE` warning badge when `return_profile.low_sample === true`.
   - When the archetypes response is empty or the run hasn't been completed yet, show an empty-state message: "No archetype run available yet. The archetype task runs at 11:30 UTC weekdays. Run it manually via the API or wait for the next scheduled run."

4. The **Edge Decay** section mounts `<EdgeDecayChart>` using data from `fetchEdgeDecay` keyed to the current `scannerType`. When `scannerType` is empty, call with `"all"`. Shows the existing component's loading and empty states (no custom empty state needed — `EdgeDecayChart` handles it).

5. All three sections appear below the existing content in this order: Edge Decay → Explanation Trait Performance → Signal Archetypes.

6. All three queries are always enabled; they are not gated by data from other queries. Empty and loading states are handled per section, not globally.

7. New TypeScript types are added to `frontend/src/api/scanner/types.ts`:
   ```ts
   export interface TraitPerformanceRow {
     trait_type: string;
     trait_id: string;
     label: string;
     sample_size: number;
     complete_count: number;
     win_rate_pct: number | null;
     follow_through_rate_pct: number | null;
     avg_mfe_pct: number | null;
     avg_mae_pct: number | null;
     sample_warning: 'trusted' | 'warning' | 'blocked';
   }

   export interface TraitPerformanceResponse {
     traits: TraitPerformanceRow[];
     filters_applied: Record<string, string | null>;
   }
   ```

8. A `fetchTraitPerformance` function is added to `frontend/src/api/scanner/misc.ts`:
   ```ts
   export const fetchTraitPerformance = async (params: {
     scanner_type?: string;
     date_from?: string;
     date_to?: string;
     trait_type?: string;
   }): Promise<TraitPerformanceResponse>
   ```
   Calls `GET /scanner/trait-performance` via `apiClient`.

9. New TypeScript types are added to `frontend/src/api/analysis.ts`:
   ```ts
   export interface ArchetypeReturnProfile {
     win_rate: number | null;
     avg_mfe: number | null;
     avg_mae: number | null;
     low_sample: boolean;
   }

   export interface ArchetypeCluster {
     cluster_index: number;
     label: string;
     event_count: number;
     return_profile: ArchetypeReturnProfile;
   }

   export interface ArchetypeLatestResponse {
     run_id: number;
     completed_at: string;
     clusters: ArchetypeCluster[];
   }
   ```

10. A `fetchLatestArchetypes` function is added to `frontend/src/api/analysis.ts`:
    ```ts
    export async function fetchLatestArchetypes(
      scannerType?: string
    ): Promise<ArchetypeLatestResponse>
    ```
    Calls `GET /outcomes/archetypes/latest` with optional `scanner_type` param.

11. `fetchTraitPerformance` and `fetchLatestArchetypes` are exported from their respective module index files so they are importable from `../api/scanner` and `../api/analysis`.

12. Frontend tests (new file `frontend/src/pages/EdgeExplorer.test.tsx`) cover:
    - Selecting a `trait_type` from the dropdown fires a query with the correct `trait_type` param in the query key.
    - The trait table renders rows for mocked `TraitPerformanceRow` data.
    - Sample-warning badges render with the correct tier label per trait (trusted → `TRUSTED`, warning → `CAUTION`, blocked → `BLOCKED`).
    - An archetype card with `return_profile.low_sample = true` renders the `LOW SAMPLE` badge.
    - When `traits` is empty, the Trait Performance section renders its empty-state message.
    - When the archetypes response has no clusters, the Signal Archetypes section renders its empty-state message.

13. `EdgeDecayChart` is stub-mocked in tests (`vi.mock('../components/scorecard/EdgeDecayChart', () => ({ default: () => null }))`) so Recharts/canvas is not exercised in jsdom.

14. `npx tsc --noEmit` must pass before committing.

---

## Architecture / Approach

### Filter state additions (EdgeExplorer.tsx)

Add one new state variable alongside the existing `period`, `ticker`, `scannerType`:

```ts
const [traitType, setTraitType] = useState<string>('');
```

Add the `trait_type` dropdown to the existing filter bar (`<div className="flex flex-wrap items-center gap-3 ...">`) following the same `<select>` pattern as the existing `scannerType` selector.

### Query additions (EdgeExplorer.tsx)

Three new `useQuery` calls:

```ts
const { data: traitPerf, isLoading: loadingTraitPerf } = useQuery({
  queryKey: ['traitPerformance', scannerType, traitType],
  queryFn: () => fetchTraitPerformance({
    scanner_type: scannerType || undefined,
    trait_type: traitType || undefined,
  }),
});

const { data: archetypes, isLoading: loadingArchetypes } = useQuery({
  queryKey: ['archetypes', scannerType],
  queryFn: () => fetchLatestArchetypes(scannerType || undefined),
});

const { data: edgeDecay, isLoading: loadingEdgeDecay } = useQuery({
  queryKey: ['edgeDecay', scannerType],
  queryFn: () => fetchEdgeDecay(scannerType || 'all'),
});
```

All three use `retry: false` (same as the existing `correlations` query) to avoid repeated failures when the backend task hasn't run yet.

### Inline mini-bars (Trait Performance table)

Bar cells use a two-layer div pattern:

```tsx
<div className="w-24 bg-gray-700 rounded overflow-hidden h-1.5 inline-block align-middle mr-2">
  <div
    className="h-full bg-financial-blue rounded"
    style={{ width: `${Math.min(value ?? 0, 100)}%` }}
  />
</div>
<span className="text-xs font-mono">{value?.toFixed(1)}%</span>
```

This mirrors the pattern used in the existing signal quality validation chart without introducing new chart dependencies.

### Sample-warning badge

```tsx
const WARNING_BADGE = {
  trusted: 'bg-positive/20 text-positive',
  warning: 'bg-yellow-500/20 text-yellow-400',
  blocked: 'bg-gray-700 text-gray-500',
} as const;

const WARNING_LABEL = {
  trusted: 'TRUSTED',
  warning: 'CAUTION',
  blocked: 'BLOCKED',
} as const;
```

### Archetype card grid

Reuse the `Card` shell component but use a plain `div` grid inside rather than `MetricCard` (which expects title/value/icon/color props that don't match the archetype shape):

```tsx
<Card title="Signal Archetypes" icon={Layers}>
  <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
    {archetypes?.clusters.map((c) => (
      <div key={c.cluster_index} className="bg-gray-800/60 rounded-xl p-4 space-y-2">
        <div className="text-xs font-black text-financial-light uppercase tracking-wide">{c.label}</div>
        ...
        {c.return_profile.low_sample && (
          <span className="text-[9px] font-black bg-yellow-500/20 text-yellow-400 px-2 py-0.5 rounded uppercase tracking-widest">
            Low Sample
          </span>
        )}
      </div>
    ))}
  </div>
</Card>
```

### Edge Decay mounting

```tsx
import EdgeDecayChart from '../components/scorecard/EdgeDecayChart';
import { fetchEdgeDecay } from '../api/outcomes';
...
<Card title="Edge Decay" icon={TrendingUp}>
  <EdgeDecayChart data={edgeDecay ?? []} isLoading={loadingEdgeDecay} />
</Card>
```

The `EdgeDecayChart` component already handles its own loading spinner and empty state — no additional wrapping needed.

---

## Alternatives Considered

### Tab-based trait navigation (rejected)
Surfacing each trait type on a separate tab (Passed Criteria | Failed Criteria | Warnings | Confidence Inputs) was considered. Rejected because (a) the existing page uses no tabs anywhere — it uses dropdowns for all filter primitives, and (b) the trait-performance API already accepts a `trait_type` param, making a dropdown the direct mapping.

### Multi-select trait IDs as a filter (rejected)
Allowing users to pick specific trait IDs (e.g., "premarket.relative_volume") from a dynamic dropdown was considered. Rejected because the API aggregates by trait type and doesn't support arbitrary trait ID filtering — the table rows themselves provide per-trait granularity.

### Horizontal bar chart for trait performance (rejected)
A Recharts `BarChart` with trait labels on the Y-axis was considered. Rejected because it only surfaces one metric at a time (win_rate or follow_through, not both simultaneously), and the table-with-inline-bars approach carries all six metrics in one view while visually encoding ranking.

### Archetype bar chart (rejected)
A Recharts chart for archetype performance was considered. Rejected because 6 clusters is a small N where a bar chart's ranking advantage is marginal, and the `low_sample` per-cluster flag has no natural place in a bar chart without color-coding hacks. The card grid directly maps one cluster → one card, with a first-class badge slot for `low_sample`.

---

## Open Questions

- **Trait label localization**: The API returns `label` from the criterion's `ExplanationBuilder` metadata. If the backend returns raw criterion IDs as fallback labels (e.g., `"premarket.relative_volume"` instead of `"Relative volume"`), the table still renders them verbatim — no frontend label-mapping is needed.

- **`fetchEdgeDecay` signature for `"all"` scanner type**: The existing function signature is `fetchEdgeDecay(scanner_type: string, ...)` with `scanner_type` matching a specific scanner. Passing `"all"` may return an error if the backend does not accept it. Implementation should use `scannerType || undefined` (omit the path param for empty string) or follow whatever convention `ScorecardDetail.tsx` uses. This is a minor integration detail to resolve during implementation.

---

## Assumptions

- [**Assumed**] Issues #464, #465, and #466 are fully merged and their endpoints are available before this issue is implemented.
- [**Assumed**] The `/outcomes/archetypes/latest` route is on the backend `outcomes` router (per spec for #466) and follows the same API prefix convention as existing routes.
- [**Assumed**] `EdgeDecayChart` accepts `data: EdgeDecayPoint[]` and `isLoading: boolean` props matching the interface already in use in `ScorecardDetail.tsx:133`.
- [**Assumed**] The archetype `return_profile` JSONB shape at runtime matches the spec-defined structure `{win_rate, avg_mfe, avg_mae, low_sample}` — the TypeScript type is written against this contract.
- [**Assumed**] No new backend routes are needed for this issue — all three endpoints are introduced by the blocking issues.
