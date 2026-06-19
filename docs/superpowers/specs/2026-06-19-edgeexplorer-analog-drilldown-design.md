# EdgeExplorer Historical Analog Drill-Down — Design (issue #470)

**Date**: 2026-06-19
**Issue**: [#470](https://github.com/omniscient/markethawk/issues/470) — Add EdgeExplorer historical analog drill-down
**Parent epic**: [#449](https://github.com/omniscient/markethawk/issues/449) — Explanation-Aware Edge Intelligence
**Blocked by**: #464 (deterministic historical analog service), #469 (EdgeExplorer explanation trait filters and archetype charts)

## Problem

EdgeExplorer currently shows aggregate edge statistics — gap/fade distributions, lifecycle trends, signal quality deciles — but offers no way to inspect what actual historical events form an archetype or analog group. After #469 adds archetype charts and trait filters, users can see that "archetype X has a 65% follow-through rate" but cannot examine which events it is built from, why each event fired (its explanation), what data quality concerns affected it, or how each event ultimately resolved. This gap makes the archetype surface descriptive rather than investigable.

Issue #470 closes that gap by adding a drill-down modal that renders the constituent events of a selected archetype/analog group, with their explanations and realized outcomes, and links each event to its stock detail page.

## Requirements

Derived from the AC in #470 and Q&A:

1. **Entry point**: clicking an archetype/analog group element in #469's charts/results opens the drill-down modal for that group.
2. **Modal overlay**: the drill-down is a modal (not an inline expand), consistent with the existing `Modal.tsx` + `UniverseDetailsModal` patterns. EdgeExplorer's dense multi-card layout makes an inline expand disruptive.
3. **Cluster summary header**: the modal shows the selected cluster's label, event count (sample size), and return profile (win rates, median return per interval) sourced from `SignalCluster.return_profile`.
4. **Per-event data**: each event row shows:
   - Event metadata: ticker, event date, scanner type, signal quality score.
   - Explanation bullets: `explanation.why` string array (defaults to `[]` if the event predates Epic 1).
   - Key criteria: top 2–3 criteria from `explanation.criteria_passed`, ranked by their weight in `explanation.confidence_inputs.positive`; fall back to insertion order if `confidence_inputs` is absent. Display label, observed value, threshold, operator, unit. Show "+N more" if criteria were truncated.
   - Warnings: `explanation.data_quality_warnings` array (`code`, `severity`, `message`); styled by severity.
   - Outcome metrics (nullable): `mfe_pct`, `mae_pct`, `mfe_mae_ratio`, `eod_pct_change`, `follow_through`, `r_multiple`, `gap_filled`, `is_complete` from `ScannerOutcomeSummary`. Whole block is optional — dim/omit when the outcome row does not exist yet.
5. **Event-level navigation**: each event row links to `/stock/{ticker}` (existing route). No per-event route exists yet; #471 will add one. Once available, upgrade the link to the event route without a data-contract change (the API already returns `event_id`).
6. **Empty state**: when a cluster has no events (`event_count = 0` or empty events list), render an empty-state message inside the modal (e.g. "No analog events available for this group.") — no crash, no empty table.
7. **Warning-heavy state**: when events carry `data_quality_warnings`, they render visibly with severity indicators.
8. **Tests**: Vitest + React Testing Library; colocated `AnalogDrilldownModal.test.tsx`; three required cases: populated, no-analog, warning-heavy.

## Architecture

### Chosen approach: cluster-scoped events endpoint + AnalogDrilldownModal

The drill-down is scoped to the archetype cluster that #469 surfaces. It adds:
- One new backend route: `GET /api/v1/outcomes/analysis/clusters/{cluster_id}/events`
- One new frontend component: `AnalogDrilldownModal`

This cleanly separates responsibilities:

| Concern | Owner |
|---------|-------|
| Finding similar events for a target event | #464's analog service |
| Showing archetype group members | #470 (this issue) |
| Event-level UI (explanation + analogs on a per-event page) | #471 |

The #464 per-event similarity endpoint is **not** consumed by this modal. The modal is about researching a group, not about diagnosing a single signal.

### Backend

**New endpoint: `GET /api/v1/outcomes/analysis/clusters/{cluster_id}/events`**

Location: `backend/app/routers/outcomes.py` (existing outcomes router, prefix `/api/v1/outcomes`).

Query params:
- `limit: int = 50` — max events to return (default 50).
- `offset: int = 0` — pagination offset.

Response schema (`AnalogDrilldownResponse`):

```python
class CriterionDetail(BaseModel):
    criterion_id: str
    label: str
    observed: float | None
    threshold: float | None
    operator: str | None
    unit: str | None
    importance: float | None  # from confidence_inputs.positive; None if absent

class DataQualityWarning(BaseModel):
    code: str
    severity: str  # "low" | "medium" | "high"
    message: str

class AnalogEventItem(BaseModel):
    event_id: int
    ticker: str
    event_date: date
    scanner_type: str
    signal_quality_score: float | None
    explanation_why: list[str]           # explanation.why; [] if absent
    key_criteria: list[CriterionDetail]  # top 2-3, ranked by importance
    total_criteria_count: int            # total criteria_passed count for "+N more"
    warnings: list[DataQualityWarning]
    outcome: OutcomeSummaryResponse | None  # reuse existing schema from app/schemas/outcome.py

class AnalogDrilldownResponse(BaseModel):
    cluster: ClusterSummary             # existing schema from app/schemas/analysis.py
    events: list[AnalogEventItem]
    total: int                          # for pagination
```

The handler:
1. Looks up `SignalCluster` by `cluster_id`; returns 404 if not found.
2. Queries `ScannerEvent` filtered by `signal_cluster_id = cluster_id`, ordered by `event_date DESC`, with `limit`/`offset` applied.
3. For each event, extracts `explanation` JSONB fields defensively (null-safe); ranks criteria by `confidence_inputs.positive` weights; left-joins `ScannerOutcomeSummary` on `scanner_event_id`.
4. Returns `AnalogDrilldownResponse`.

All of these models and the join pattern are already established in the codebase; no new tables or migrations are required.

### Frontend

**New component: `AnalogDrilldownModal`**

File: `frontend/src/components/AnalogDrilldownModal.tsx`
Test file: `frontend/src/components/AnalogDrilldownModal.test.tsx`

Props:
```typescript
interface AnalogDrilldownModalProps {
  clusterId: number | null;  // null = closed
  clusterLabel: string;
  onClose: () => void;
}
```

The modal is open when `clusterId !== null`. It uses the existing `Modal` component (`frontend/src/components/ui/Modal.tsx`).

Data fetching:
```typescript
const { data, isLoading } = useQuery({
  queryKey: ['analogDrilldown', clusterId],
  queryFn: () => fetchAnalogDrilldown(clusterId!),
  enabled: clusterId !== null,
});
```

`fetchAnalogDrilldown` goes in `frontend/src/api/analysis.ts` (where other cluster/analysis functions live):
```typescript
export const fetchAnalogDrilldown = (clusterId: number): Promise<AnalogDrilldownResponse> =>
  apiClient.get(`/outcomes/analysis/clusters/${clusterId}/events`).then(r => r.data);
```

Layout inside the modal:
1. **Header**: cluster label + event count + return profile summary (win rate at closest interval from `return_profile`).
2. **Event list**: scrollable, one card/row per event.
   - Primary row: ticker (link to `/stock/{ticker}` via react-router `<Link>`), date, scanner type, signal quality score badge.
   - Explanation bullets: `explanation_why` as a `<ul>`.
   - Key criteria: compact table/list (label, observed vs threshold, operator, unit). "+N more" badge if truncated.
   - Warnings: severity-styled chips/badges per warning.
   - Outcome block: `mfe_pct`, `mae_pct`, `eod_pct_change`, `follow_through` (bool → "Yes"/"No"), `is_complete` flag. Entire block absent if `outcome === null`.
3. **Empty state**: when `data.events.length === 0`, render centered "No analog events available for this group." with no table.

**Integration with #469**: The component that renders archetype charts/cards (added by #469) needs to:
- Hold state: `const [selectedClusterId, setSelectedClusterId] = useState<number | null>(null);`
- Pass `onClick={id => setSelectedClusterId(id)}` to the archetype chart elements.
- Render `<AnalogDrilldownModal clusterId={selectedClusterId} clusterLabel="..." onClose={() => setSelectedClusterId(null)} />`.

Since #469 hasn't landed yet, the exact integration point in `EdgeExplorer.tsx` will be determined when #469's PR merges. The `AnalogDrilldownModal` component is self-contained and can be authored and tested independently of that integration point.

### Testing

Three test cases in `AnalogDrilldownModal.test.tsx`:

**Case 1 — Populated**: mock returns a cluster summary + 2 events, each with `explanation_why`, `key_criteria`, and an `outcome` block. Assert: cluster label renders, both event rows render with ticker, explanation bullets show, criterion labels show, outcome `mfe_pct` renders, `<Link>` href is `/stock/{ticker}`.

**Case 2 — No-analog**: mock returns `{ cluster: {..., event_count: 0}, events: [], total: 0 }`. Assert: "No analog events available" message renders; no event rows; no crash.

**Case 3 — Warning-heavy**: mock returns events where each has a non-empty `warnings` array with `severity: "high"`. Assert: warning messages render for each event (e.g. `screen.getAllByText(/missing_intraday_bars/i).length > 0`).

Use `renderWithQuery` from `frontend/src/test-utils/renderWithQuery.tsx` (provides `QueryClientProvider` + `MemoryRouter`). Mock `frontend/src/api/analysis.ts` with `vi.mock`. Test the closed state: when `clusterId={null}`, modal renders nothing (`container.firstChild` is null — the shared `Modal` returns null when `!isOpen`).

Backend tests:
- `backend/tests/routers/test_outcomes.py` (or a new `test_analog_drilldown.py`).
- Three cases: populated cluster with events + outcome rows, empty cluster (`event_count = 0`, empty query result), events with warning-filled `explanation` JSONB.
- Use the existing `db_session` / `TestClient` fixture pattern from `backend/tests/conftest.py`.

## Alternatives Considered

**Approach B: Dual entry points (cluster drill-down + per-event analog similarity)**

Also expose #464's per-event similarity as a second trigger inside the modal — e.g. selecting an event row launches a nested "similar to this event" view. Rejected: this duplicates what #471 ("Upgrade event-level intelligence UI") is planned to handle. Two entry points also creates surface ambiguity. YAGNI.

**Approach C: Inline expandable rows instead of a modal**

Expand archetype chart rows in-place, showing events below the chart bar. Rejected: EdgeExplorer is already a dense multi-card page; an inline expand disrupts the layout and moves chart rows. The existing codebase uses modals for this pattern (`UniverseDetailsModal`, `QualityReportModal`).

## Open Questions

1. **Pagination in the modal**: the spec defaults to `limit=50`. If a cluster has 200+ events, users may need pagination or a "load more" button inside the modal. This is non-blocking — start with a hard 50-event cap with a note ("Showing top 50 events by date") and revisit if product feedback calls for it.
2. **Sort order**: events are returned `ORDER BY event_date DESC` (newest first). An ascending sort or "by signal quality" sort may be useful; defer to implementation.
3. **#469 integration point**: the exact component/element in #469's archetype charts that accepts an `onClick` handler is unknown until #469's PR merges. The `AnalogDrilldownModal` can be built and tested without it; integration is a one-line wire-up.

## Assumptions

- **[A1]** `ScannerEvent.signal_cluster_id` FK exists by the time #470 ships (added during archetype clustering work upstream of #469). If the column doesn't exist yet, the backend endpoint returns an empty events list rather than erroring.
- **[A2]** `explanation` JSONB may be null for events scanned before Epic 1 completes. All extraction is null-safe; `explanation_why` defaults to `[]`, `key_criteria` to `[]`, `warnings` to `[]`.
- **[A3]** No database migration is needed for this issue — it joins existing tables (`signal_clusters`, `scanner_events`, `scanner_outcome_summaries`) without new columns.
- **[A4]** The #469 component will expose a `clusterId` (integer) when a user clicks an archetype group. The precise component API of #469 is not known yet; the integration point will be confirmed when #469's PR is reviewed.
- **[A5]** The event-level navigation target is `/stock/{ticker}` until #471 adds a dedicated event route. When #471 lands, the link can be updated from `to={/stock/${ticker}}` to `to={/scanner/events/${event_id}}` (or whatever route #471 defines) without changing the API contract.
