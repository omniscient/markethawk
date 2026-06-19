# Event-Level Intelligence UI — Design (issue #471)

**Date**: 2026-06-19
**Issue**: [#471](https://github.com/omniscient/markethawk/issues/471) — Upgrade event-level intelligence UI
**Parent epic**: [#449](https://github.com/omniscient/markethawk/issues/449) — Explanation-Aware Edge Intelligence
**Blocked by**: #464 (analog service), #467 (signal brief endpoint)

---

## Problem

Scanner hits today appear as flat rows: ticker, summary, a few indicator pills, severity badge. A user reviewing a hit cannot see *why* it fired (explanation), how it compares to past signals (analogs), what historical outcomes looked like (expected behavior), or how it fits a repeating pattern (archetype). All these facts are deterministic and will be produced by #464 and #467 — they just have no display surface yet.

---

## Requirements

1. An event detail drawer opens when the user clicks any scanner event row (Scanner page table or Stock Detail scanner history list).
2. The drawer shows: explanation bullets, criteria pass/fail grid, key facts, risks, data quality warnings, historical analogs, expected behavior (outcome distribution), and archetype.
3. All displayed data is deterministic — no AI-generated prose. The section header must make this clear.
4. A named component slot (`<GeneratedNarrative />`) is reserved below the deterministic block for Epic 3 narrative; it renders nothing until Epic 3 fills it.
5. `forbidden_claims[]` from the signal brief is never surfaced to the user.
6. The drawer handles three data states gracefully: **complete** (all brief fields populated), **partial** (some fields null/empty), **no-outcome** (outcome_context null or analogs empty).
7. Frontend tests cover all three data states plus loading and error states.
8. TypeScript: `tsc --noEmit` must pass; no `any` types in new code.

---

## Architecture / Approach

### Data flow

One API call per drawer open: `GET /api/v1/scanner/events/{event_uuid}/signal_brief`  
(introduced by #467). The `ai_signal_brief.v1` response bundles every field the drawer needs:

```typescript
interface AiSignalBrief {
  schema_version: 'ai_signal_brief.v1';
  facts: Record<string, unknown>;
  why: string[];
  risks: string[];
  data_quality_warnings: DataQualityWarning[];
  historical_analogs: HistoricalAnalog[];
  outcome_context: OutcomeContext | null;
  archetype: ArchetypeContext | null;
  forbidden_claims: string[];  // internal only — never rendered
}
```

The drawer does **not** call the standalone `/analogs` endpoint (#464) — the brief already embeds analogs. If a future UX need exceeds the brief's top-N, a "load more" path can fall back to `/analogs`, but that is out of scope for this issue.

React Query cache key: `['signal-brief', event.uuid]`. Stale time: 5 minutes (brief is deterministic, no need to refetch on every open).

### Component structure

```
EventDetailDrawer              (new — slide-over panel)
  ├── DrawerHeader             (ticker, date, scanner type, severity, quality score)
  ├── WhyItFired               (why[] bullets from brief)
  ├── CriteriaGrid             (criteria_passed / criteria_failed from explanation field)
  ├── SignalIntelligencePanel  (facts, risks, data_quality_warnings — labelled "deterministic")
  ├── HistoricalAnalogsPanel   (historical_analogs[] — top-N cards)
  ├── ExpectedBehaviorPanel    (outcome_context — headline stat + sample size)
  ├── ArchetypePanel           (archetype label and traits)
  └── GeneratedNarrative       (stub — renders null; Epic 3 fills this)
```

### Slide-over drawer

A new `EventDetailDrawer` is a **right-side slide-over panel** (not a centered modal) so it overlays the table or list cleanly without disrupting the originating row. It follows the same accessibility conventions as `frontend/src/components/ui/Modal.tsx`:
- Escape key closes
- Backdrop click closes
- `document.body.style.overflow = 'hidden'` while open
- Focus trap inside the panel

Width: `w-[480px] max-w-[90vw]` — wide enough for the analog cards, narrow enough not to cover the table on desktop.

### Wiring into existing surfaces

**`ScannerResults.tsx`**: add `onClick` to each `<tr>` that calls `setSelectedEvent(event)`. The drawer is rendered once outside the table (not per-row). No changes to existing columns or sort behavior.

**`RecentEvents.tsx`**: the `onEventClick` prop already exists but is unused as a detail trigger. Wire it to open the drawer. The Stock Detail page currently uses `onEventClick` to highlight a chart date — preserve that by calling both: `onHighlightDate(event.event_date)` first, then open the drawer. The drawer is rendered at `ScannerHistoryPanel` level, not inside RecentEvents.

### New files

| File | Purpose |
|---|---|
| `frontend/src/components/EventDetailDrawer.tsx` | Drawer + sub-components |
| `frontend/src/components/EventDetailDrawer.test.tsx` | Vitest tests |
| `frontend/src/api/scanner/brief.ts` | `fetchSignalBrief(uuid)` + TypeScript interfaces |

### Modified files

| File | Change |
|---|---|
| `frontend/src/api/scanner/types.ts` | Add `explanation` field to `ScannerEvent` (if not added by #467) |
| `frontend/src/api/scanner/index.ts` | Re-export `fetchSignalBrief`, `AiSignalBrief` |
| `frontend/src/components/ScannerResults.tsx` | Add row click handler + render `<EventDetailDrawer>` |
| `frontend/src/components/RecentEvents.tsx` | Wire `onEventClick` to open drawer |
| `frontend/src/pages/StockDetailPage/ScannerHistoryPanel.tsx` | Render `<EventDetailDrawer>` at panel level |

---

## Drawer section detail

### DrawerHeader
- Left: `<Ticker>` component (existing), event date (font-mono), scanner type chip
- Right: severity badge (reuse `getSeverityStyle()` from ScannerResults), quality score badge (`ScoreQualityBadge`)

### WhyItFired
Renders `brief.why[]` as a bulleted list under the header "Why it fired". If `why` is empty, renders a single muted line: "No explanation available."

### CriteriaGrid
Renders `event.explanation.criteria_passed` / `event.explanation.criteria_failed` as a two-column grid — one row per criterion with label, observed value, threshold, and a pass/fail icon. Falls back to rendering `event.criteria_met` Record if `explanation` is not present (backward compatibility during the period before #467 rolls out to all events).

### SignalIntelligencePanel
Header: **"Signal Intelligence"** with a chip labeled `deterministic` (small, muted). This is the visual boundary the acceptance criteria require — everything in this section and below is computed, not generated.

Sub-sections:
- **Facts**: key-value grid from `brief.facts{}`. Skip rendering if empty.
- **Risks**: `brief.risks[]` as a list with a warning icon. Skip rendering if empty.
- **Data quality warnings**: `brief.data_quality_warnings[]` — each warning shows its `severity` chip, `code`, and `message`. Skip rendering if empty.

### HistoricalAnalogsPanel
Header: "Historical Analogs" with the count (e.g., "3 similar signals").

Renders `brief.historical_analogs[]` as a list of compact cards. Each card shows:
- Prior event: ticker, date, scanner type
- Similarity score (as a percentage or decimal)
- Outcome summary: MFE%, follow-through %, days held (where available)
- If outcome is missing on an analog: "No outcome yet"

If `historical_analogs` is empty: renders "No similar signals found."
If the brief includes a `weak_confidence_warning` on analogs: show it as a yellow callout above the list.

### ExpectedBehaviorPanel
Header: "Expected Behavior" — sourced from `brief.outcome_context`.

Shows headline stat(s): e.g., "73% follow-through >2% (n=12)". Fields consumed:
- `follow_through_rate`, `avg_eod_pct`, `median_mfe_pct`, `sample_size` (exact field names to be confirmed against #467's schema)

Three states:
- **Complete**: show headline stat + sample size + any dispersion metric
- **Partial** (some fields null): show available stats, omit null ones
- **No outcome** (`outcome_context` is null or `sample_size === 0`): show "Outcome data not yet available for this signal type."

### ArchetypePanel
Header: "Signal Archetype" — sourced from `brief.archetype`.

Shows: archetype label/name, key defining traits. If `archetype` is null: renders nothing (collapses entirely).

### GeneratedNarrative (stub)
```tsx
// Reserved slot for Epic 3 (optional LLM narrative). Renders nothing.
const GeneratedNarrative: React.FC<{ narrative?: string | null }> = ({ narrative }) => {
  if (!narrative) return null;
  return (
    <section aria-label="AI Narrative">
      <h4>AI narrative — generated</h4>
      <p>{narrative}</p>
    </section>
  );
};
```

The `narrative` prop will never be passed until Epic 3. The component must exist and be imported so Epic 3 can fill it without structural changes.

---

## Alternatives considered

### A: Centered modal instead of slide-over
Rejected because the existing `Modal.tsx` centers over the page and hides the originating row. A slide-over preserves the row context, which is important when the user wants to reference indicator values while reading the drawer.

### B: Two separate components for ScannerResults vs. RecentEvents
Rejected because both surfaces render the same `ScannerEvent` type and all drawer content is event-keyed by `uuid`. A shared component is simpler and keeps the detail UI consistent. The only difference is the trigger mechanism, which is handled by the parent component.

### C: Fetch analogs and brief separately
Rejected because `ai_signal_brief.v1` (from #467) already embeds `historical_analogs[]` — splitting into two calls adds a second failure mode, a second loading state, and timing divergence for no user benefit in the drawer context.

---

## Testing

Three named fixture datasets for tests (declared in `EventDetailDrawer.test.tsx`):

| Fixture | Description |
|---|---|
| `completeEvent` | All `AiSignalBrief` fields populated: why[], facts, risks, warnings, 3 analogs, outcome_context with follow_through_rate, archetype |
| `partialEvent` | `outcome_context` is null; `historical_analogs` is []; `archetype` is null; `why` has 2 bullets |
| `noOutcomeEvent` | `outcome_context.sample_size === 0`; analogs present but with null outcome fields |

Test coverage:
- Drawer renders closed by default
- Clicking an event row opens the drawer with correct ticker in header
- `completeEvent`: all sections visible, follow_through_rate displayed
- `partialEvent`: "Outcome data not yet available" message shown; Archetype section absent
- `noOutcomeEvent`: "No outcome yet" on each analog card; expected behavior shows "not yet available"
- Loading spinner rendered while brief is fetching
- Error state: error message rendered when fetch fails
- Escape key closes the drawer
- `forbidden_claims` not rendered anywhere in the output

Coverage follows the existing ratchet formula from `frontend/vitest.config.ts`.

---

## Assumptions

- **[A1]** `ai_signal_brief.v1` endpoint is available at `GET /api/v1/scanner/events/{uuid}/signal_brief` (introduced by #467 before this issue is implemented).
- **[A2]** The exact field names inside `outcome_context{}` and `archetype{}` in the brief are confirmed against #467's final schema during implementation — the spec names fields by their semantic intent; implementation adjusts to actual names.
- **[A3]** The `explanation` field is added to `ScannerEvent` (or its API response schema) by an earlier issue in Epic 1. If it is absent from the scanner event at the time of rendering, `CriteriaGrid` falls back to `event.criteria_met`.
- **[A4]** `forbidden_claims[]` is intentionally excluded from every rendered section; its only consumer is future Epic 3 narrative generation.
- **[A5]** The `GeneratedNarrative` stub is never rendered in any test or production path until Epic 3 passes a `narrative` string.

---

## Open questions (non-blocking)

- Should analogs support "load more" (paging beyond the brief's top-N via the `/analogs` endpoint from #464)? Deferred — not needed for the first version; the brief's embedded top-N is sufficient for the drawer.
- Should the drawer be navigable (next/previous event without closing)? Deferred — not in the acceptance criteria.
- Should the `CriteriaGrid` show thresholds and importance weights from `criteria_passed{}`, or just pass/fail? Implementation can decide based on the Epic 1 explanation schema; the drawer should show at minimum label + observed + operator + threshold.
