# Scanner Explanation UI — Design

**Date:** 2026-06-19
**Status:** Spec generated
**Issue:** #457 (parent: #448 Epic: Explainability Foundation)
**Blocked by:** #456 (Expose scanner explanations through API contracts)

## Overview

Scanner events already capture `criteria_met`, `indicators`, and `signal_quality_score`.
Issue #456 adds a structured `explanation` JSONB field (`scanner_explanation.v1`) to every
event's API response. This issue (#457) builds the React UI that surfaces that explanation
without requiring users to read raw JSON — as inline "why" bullets in the collapsed row and
a full criteria/confidence/warnings breakdown in an expandable accordion.

Two surfaces are in scope:

1. **ScannerResults** (`frontend/src/components/ScannerResults.tsx`) — main scanner results
   table: collapsed bullets + expand-to-detail accordion.
2. **RecentEvents** (`frontend/src/components/RecentEvents.tsx`) — compact list in
   `StockDetailPage/ScannerHistoryPanel`: collapsed bullets only.

## Requirements

1. Collapsed row in ScannerResults shows top 2 `explanation.why` bullets in the Summary cell
   (fallback: `event.summary` text, unchanged behavior for rows without explanation).
2. A data-quality warning chip (count or icon) is visible in the collapsed Summary cell
   whenever `explanation.data_quality_warnings` is non-empty.
3. Clicking the expand chevron in the Summary cell toggles an in-row accordion (colSpan
   sub-row) beneath the event row, showing: passed criteria, failed/caveat criteria,
   confidence inputs, and the full data-quality warnings list.
4. A reconstructed-explanation indicator is shown when `explanation.evidence.reconstructed`
   is `true` — both in the collapsed chip area and inside the accordion.
5. Events with no explanation (`explanation` is `null` or `undefined`) render exactly as
   they do today: `event.summary` text, no chevron, no accordion.
6. RecentEvents shows the top 2 `why` bullets + warning chip in the existing col-span-4
   Summary area; no accordion expansion (the row click is already claimed for chart
   highlight in ScannerHistoryPanel).
7. Frontend tests cover four states: **explained**, **warning**, **missing-explanation**,
   **reconstructed**.

## Architecture

### Type contract (from #456, not re-declared here)

This issue consumes `ScannerExplanation` as an optional field on `ScannerEvent`:

```ts
// Defined and owned by issue #456 in frontend/src/api/scanner/types.ts
ScannerEvent.explanation?: ScannerExplanation | null
```

The full `ScannerExplanation` interface (`why`, `criteria_passed`, `criteria_failed`,
`confidence_inputs`, `data_quality_warnings`, `evidence`) is the upstream contract from #456.
If the type is incomplete when #457 lands, that is a #456 fix — do not redeclare the shape here.

### New components

#### `ExplanationSummary` — shared collapsed view

**File:** `frontend/src/components/ExplanationSummary.tsx`

**Props:**
```ts
interface ExplanationSummaryProps {
  explanation?: ScannerExplanation | null;
  fallbackSummary?: string;
  onExpandToggle?: () => void;
  expanded?: boolean;
}
```

**Renders (when `explanation?.why` is present):**
- An expand chevron (`ChevronRight`→`ChevronDown`) as the cell's leading element, bound to
  `onExpandToggle`. Only rendered when `onExpandToggle` is provided (so RecentEvents can
  pass `undefined` to suppress it).
- Top 2 `explanation.why` bullets as compact text lines.
- A warning chip (amber, e.g. "⚠ 2 warnings") when `data_quality_warnings.length > 0`.
- A reconstructed badge ("reconstructed") when `evidence.reconstructed === true`.

**Renders (when explanation is absent):**
- `fallbackSummary` text, identical to current behavior. No chevron, no chip.

This component is used by both ScannerResults (with `onExpandToggle`/`expanded` wired) and
RecentEvents (with `onExpandToggle={undefined}`, expand suppressed).

#### `ExplanationDetail` — full accordion content

**File:** `frontend/src/components/ExplanationDetail.tsx`

**Props:**
```ts
interface ExplanationDetailProps {
  explanation: ScannerExplanation;
}
```

**Renders in four sections:**

1. **Why it fired** — all `explanation.why` bullets (not just top 2).
2. **Passed criteria** — for each entry in `criteria_passed`: label, observed value
   (formatted with unit), threshold, importance bar or percentage.
3. **Failed / caveat criteria** — for each entry in `criteria_failed`: label, observed
   value, threshold, failure reason if present.
4. **Confidence inputs** — overall score, positive and negative contributors as a
   horizontal breakdown; any `missing` inputs listed as gaps.
5. **Data-quality warnings** — each `{ code, severity, message, affected_inputs }` as a
   collapsible alert row; severity drives color (high=red, medium=amber, low=blue).
6. **Evidence footer** — `generated_at`, `provider`, and a `reconstructed` flag row when
   `evidence.reconstructed === true`.

This component is used **only** inside the ScannerResults accordion sub-row. It is not
imported by RecentEvents.

### Changes to ScannerResults

**`frontend/src/components/ScannerResults.tsx`**

Extract the current inline `<tr>` JSX into a named `EventRow` subcomponent that owns its
own `const [expanded, setExpanded] = useState(false)`. This mirrors
`frontend/src/components/QualityReportModal/TickerRow.tsx`, the canonical pattern for
row-level expand state.

Each `EventRow` renders two `<tr>` elements when expanded:

```tsx
// collapsed row (always rendered)
<tr key={event.id} ...>
  <td>...</td>  {/* Date */}
  <td>...</td>  {/* Ticker */}
  <td>...</td>  {/* Scanner */}
  <td onClick={() => event.explanation && setExpanded(e => !e)}>
    <ExplanationSummary
      explanation={event.explanation}
      fallbackSummary={event.summary}
      onExpandToggle={event.explanation ? () => setExpanded(e => !e) : undefined}
      expanded={expanded}
    />
  </td>
  <td>...</td>  {/* Key Indicators */}
  <td>...</td>  {/* Severity */}
  <td>...</td>  {/* Score */}
  <td>...</td>  {/* Review — ReviewControls, stopPropagation not needed since click is on Summary td only */}
</tr>

// expanded sub-row (conditional)
{expanded && event.explanation && (
  <tr>
    <td colSpan={8} className="bg-gray-900/60 border-b border-gray-800 px-6 py-4">
      <ExplanationDetail explanation={event.explanation} />
    </td>
  </tr>
)}
```

The `onClick` is attached to the Summary `<td>` only (not the whole `<tr>`), preserving
the existing interactive cells: `ReviewControls` in the Review cell and the tweet link in
the Scanner cell.

Column count stays at 8; `colSpan={8}` fits the sub-row to the full width.

### Changes to RecentEvents

**`frontend/src/components/RecentEvents.tsx`**

Replace the existing col-span-4 Summary `<div>` (currently `lines 85-89`) with
`<ExplanationSummary>` with `onExpandToggle={undefined}`:

```tsx
<div className="col-span-4">
  <ExplanationSummary
    explanation={event.explanation}
    fallbackSummary={event.summary}
    {/* no onExpandToggle — suppress chevron */}
  />
</div>
```

No other structural changes. The row click (`onEventClick` → `onHighlightDate`) is
untouched.

## Graceful handling of missing/reconstructed explanations

| State | `explanation` field | Collapsed rendering |
|---|---|---|
| **Explained** | present, `why` populated | bullets + expand chevron |
| **Warning** | present, `data_quality_warnings` non-empty | bullets + amber warning chip |
| **Reconstructed** | present, `evidence.reconstructed: true` | bullets + "reconstructed" badge |
| **Missing** | `null` or `undefined` | `event.summary` text, no chevron |

All four states must render without throwing for both `ScannerResults` and `RecentEvents`.

## Alternatives considered

### A. New "Explanation" column

Add a dedicated "Why" column to the table. Rejected: the table is already 8 columns wide
(`max-w-xs` Summary is tight). Reusing the Summary cell avoids column count growth.

### B. Modal/drawer for expanded view

Open a dialog when the user clicks "Explain". Rejected: the existing modal pattern in this
app is reserved for forms and create/edit actions (`UniverseFormModal`, `AlertRuleModal`).
For read-only row drill-down, `QualityReportModal/TickerRow.tsx` uses in-row accordion —
this issue follows the same convention.

### C. Full accordion in RecentEvents

Mirror ScannerResults and add accordion expansion to RecentEvents. Rejected: the row's
`onClick` is already claimed by `onHighlightDate` (chart scroll), and the "Details"
col-span-1 column already renders criteria-met count. Adding a second click action would
require stopPropagation fighting across a panel used primarily for quick-glance history
review.

## Testing

### New test files

**`frontend/src/components/ExplanationSummary.test.tsx`**

Four states per the AC:
- **Explained:** renders `explanation.why[0]` and `explanation.why[1]` bullets; chevron
  rendered when `onExpandToggle` provided; chevron not rendered when omitted.
- **Warning:** `data_quality_warnings.length > 0` renders warning chip; chip absent when
  empty.
- **Missing:** `explanation` absent → renders `fallbackSummary` text; no chevron, no chip.
- **Reconstructed:** `evidence.reconstructed: true` renders reconstruction badge.

**`frontend/src/components/ExplanationDetail.test.tsx`**

- Renders criterion label, observed value, and threshold for a passed criterion.
- Renders failed criterion row.
- Renders data-quality warning with correct severity color class.
- Renders reconstructed evidence footer when `evidence.reconstructed: true`.
- Renders `confidence_inputs.score` and positive contributors.

### Integration assertion in existing test file

**`frontend/src/components/ScannerResults.test.tsx`**

Add one integration test:
- When an event has `explanation.why = ["Volume was 4x average", "Above VWAP"]`,
  the accordion is initially closed (explanation detail not in document); clicking
  the Summary cell opens it (passes a criterion label from criteria_passed into
  the document).

### Mock shape

All test fixtures must derive from the actual `ScannerExplanation` interface (once defined
by #456), not ad-hoc field names.

## Open questions (non-blocking)

1. **Criterion importance visualization.** The spec shows `importance: 0.31` per criterion.
   A small bar or percentage makes this scannable; a raw number is fine for v1. Implementation
   can choose.
2. **`criteria_failed` labeling.** The parent spec calls these "failed/caveat criteria." If
   criteria that didn't fire but weren't required have a different `label` convention in the
   actual scanner output, the component should use that label verbatim.
3. **Confidence-input chart.** A horizontal bar breakdown (`positive` vs. `negative` inputs)
   is a natural fit but adds Recharts dependency inside a lightweight subcomponent. Plain text
   rows are acceptable for v1.

## Assumptions

- **[A1]** `ScannerEvent.explanation?: ScannerExplanation | null` is delivered by #456 before
  this issue ships. If the type is missing or has a different shape, unblock via #456, not by
  local redefinition.
- **[A2]** The explanation column on the API response will return `null` for events that
  pre-date the explanation system, and the backend never returns a partial shape — either
  the full `scanner_explanation.v1` object or `null`.
- **[A3]** `colSpan={8}` is correct at time of implementation. If column count changes after
  this issue is specced, adjust the colSpan value.
- **[A4]** `QualityReportModal/TickerRow.tsx` remains the canonical per-row accordion pattern
  and its styling classes (`bg-gray-900/60 border-b border-gray-800`) are safe to mirror.
