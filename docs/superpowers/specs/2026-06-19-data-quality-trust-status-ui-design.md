# Data Quality Trust Status UI Design

**Date:** 2026-06-19  
**Issue:** #495  
**Parent Epic:** #491 (Data Quality Trust Gate)  
**Status:** Spec — pending review  
**Blocked by:** #493 (preflight API), #494 (scanner run gate persistence)

---

## Overview

Issue #495 delivers the UI surfaces that display data quality trust gate status in two existing surfaces: the scanner results page and the quality report modal. Users should be able to see — at a glance — whether scanner data carries a **trusted**, **warning**, **blocked**, or **skipped** trust verdict, with grouped issue details and practical remediation actions.

The implementation ships UI components that are "present but dark" where the backing API (#493) or run-level persistence (#494) is not yet available, allowing UI development to proceed in parallel and become visible when those blockers land.

---

## Requirements

From the issue acceptance criteria:

1. UI renders all four gate verdict states (trusted, warning, blocked, skipped) with clear labels.
2. Issues are grouped by their stable issue code (7 defined in epic #491).
3. Each issue displays: severity, affected ticker or scope, affected inputs when available, and a remediation action.
4. The quality modal includes a trust-gate summary section with blocker count, warning count, and most-affected tickers.
5. Scanner UI surfaces advisory warnings without implying the result is clean.
6. Frontend tests cover all verdict states and issue grouping behaviour.

---

## Architecture

### New TypeScript Types

Add to `frontend/src/api/scanner/types.ts` (alongside existing `ScannerRunResponse`):

```typescript
// The 7 stable issue codes from epic #491
export type QualityIssueCode =
  | 'missing_bars'
  | 'split_dividend_anomaly'
  | 'stale_quote_risk'
  | 'provider_gaps'
  | 'timezone_session_mismatch'
  | 'survivorship_bias_risk'
  | 'stale_reference_data';

export interface QualityGateIssue {
  issue_code: QualityIssueCode;
  severity: 'blocker' | 'warning' | 'info';
  title: string;
  scope: 'ticker' | 'universe' | 'session' | 'provider';
  ticker: string | null;
  asset_class: string | null;
  affected_inputs: {
    timespans?: string[];
    date_range?: { start: string; end: string };
    session?: string;
    fields?: string[];
  } | null;
  detail: Record<string, unknown>;
  remediation: {
    action: string;
    label: string;
    description: string;
    automated: boolean;
  };
}

export interface QualityGateSummary {
  blocker_count: number;
  warning_count: number;
  info_count: number;
  affected_ticker_count: number;
  total_tickers_evaluated: number;
  most_affected_tickers: Array<{
    ticker: string;
    issue_count: number;
    max_severity: 'blocker' | 'warning' | 'info';
  }>;
  issue_code_counts: Partial<Record<QualityIssueCode, number>>;
}

export interface QualityGateAssessment {
  verdict: 'trusted' | 'warning' | 'blocked' | 'skipped';
  policy: 'advisory' | 'strict';
  consumer: string;
  scanner_type: string | null;
  universe_id: number | null;
  generated_at: string;
  assessment_id: string;
  verdict_reason: string;
  summary: QualityGateSummary;
  issues: QualityGateIssue[];
}
```

### Scanner Run Response Extension

Extend `ScannerRunResponse` in `frontend/src/api/scanner/types.ts`:

```typescript
export interface ScannerRunResponse {
  // ... existing fields unchanged ...
  quality_gate?: QualityGateAssessment;  // added by #494 run persistence
}
```

Event-level warnings arrive via `ScannerEvent.metadata_["quality_warnings"]` (array of `QualityGateIssue`), persisted by #494. The existing `metadata: Record<string, unknown>` field on `ScannerEvent` already carries this without schema changes.

### New Components

#### `TrustGateSummary` (`frontend/src/components/TrustGateSummary.tsx`)

Prop-driven component. Renders null when `gate` is absent (safe to mount in both surfaces).

```typescript
interface TrustGateSummaryProps {
  gate: QualityGateAssessment;
}
```

Renders:
- **Verdict badge** — colour-coded pill using the four-state palette below.
- **Count chips** — blocker count (red), warning count (amber), info count (blue).
- **Most-affected tickers** — up to 5 ticker chips with their max severity colour.
- **Issue list** — grouped by `issue_code`; each group shows a heading (human title) with severity icon, then each issue's scope/ticker, affected inputs, and a remediation CTA (link or button for automated actions).
- **Expand/collapse** — the issue list is collapsed by default when verdict is `trusted` or `warning`; expanded by default when `blocked`.

**Verdict badge palette:**

| Verdict  | Background + text                                              |
|----------|----------------------------------------------------------------|
| trusted  | `bg-green-500/20 text-green-400 border-green-500/30`          |
| warning  | `bg-yellow-500/20 text-yellow-400 border-yellow-500/30`       |
| blocked  | `bg-red-500/20 text-red-400 border-red-500/30`                |
| skipped  | `bg-gray-500/20 text-gray-400 border-gray-500/30`             |

Matches the existing severity/regime badge palette already used in `ScannerResults.tsx`.

#### `TrustGateBanner` (`frontend/src/components/TrustGateBanner.tsx`)

Compact run-level advisory banner for the scanner results page. Renders null when `gate` is absent.

```typescript
interface TrustGateBannerProps {
  gate: QualityGateAssessment;
}
```

Renders: verdict badge + one-sentence summary (`verdict_reason`) + blocker/warning count summary + link to expand into the full `TrustGateSummary` in a popover or inline collapsible panel.

Uses the same amber advisory banner style as `QualityReportModal`'s removed-tickers notice (`bg-yellow-500/10 border border-yellow-500/30`), but with the verdict-specific colour applied to the border and icon.

#### `QualityWarningBadge` (inline within `ScannerResults.tsx` event rows)

Small badge rendered inside the ticker cell when `event.metadata?.quality_warnings?.length > 0`. Shows the count of warnings and the max severity colour. On click, opens a popover listing each warning's `title`, `severity`, and `remediation.label`.

```
[AAPL] ⚠ 2   ← amber badge with count; click → popover
```

Keeps the ticker cell layout consistent with the existing `<Ticker>` component (no new column, no row expansion).

### Modified Components

#### `QualityReportModal/index.tsx`

Add optional `gate?: QualityGateAssessment` prop to `QualityReportModalProps`. Render `<TrustGateSummary gate={gate} />` **above** `<QualityOverviewCard>` (before line 180 in current file). When `gate` is undefined the render is a no-op.

```typescript
interface QualityReportModalProps {
  isOpen: boolean;
  onClose: () => void;
  universe: StockUniverse | null;
  gate?: QualityGateAssessment;  // optional; absent until wiring follow-up lands
}
```

`Universes.tsx` does not need to change — it passes no `gate` and the section stays hidden until a follow-up ticket wires the preflight API call.

#### `ScannerResults.tsx`

Add optional `qualityGate?: QualityGateAssessment` prop to `ScannerResultsProps`. Render `<TrustGateBanner gate={qualityGate} />` above the filter controls when present. Add `<QualityWarningBadge>` inline in the ticker cell for events with `metadata?.quality_warnings?.length > 0`.

`ResultsPanel.tsx` passes `scanResults.quality_gate` down to `ScannerResults`. `Scanner/index.tsx` already holds `scanResults` in state, so no additional fetch is needed.

---

## Approaches Considered

### Approach A — Component-driven with optional gate prop (Selected)

Ship `TrustGateSummary` and `TrustGateBanner` as prop-driven components that render null when `gate` is absent. Add to the quality modal with an optional prop (present but dark), and to scanner results with the embedded `quality_gate` from the run response (lit up when #494 ships).

**Pros:** Simple, fully testable with mock data immediately, no blocking dependency on #493 for UI development. The scanner results surface becomes live the moment #494 merges. Modal surface stays dark until a follow-up wires the preflight fetch, which is explicitly flagged.

**Cons:** Quality modal section is invisible until the follow-up ships. Requires a follow-up issue.

### Approach B — Modal calls preflight API (#493) inline

`QualityReportModal` calls `POST /api/v1/data-quality/gate` with `universe_id`.

**Pros:** Fully live modal experience when both #493 and #495 merge.

**Cons:** Couples #495 implementation to #493 landing first. Adds a new React Query call and loading state to the modal. This is simpler as a follow-up ticket once #493 is confirmed stable.

### Approach C — Standalone trust dashboard

New route or separate modal for data trust status.

**Rejected** explicitly by the issue body: "instead of creating a separate standalone dashboard."

---

## Open Questions (non-blocking)

1. Should `TrustGateBanner` in scanner results be dismissible (×) or always visible while gate data is present? — Recommend always visible for transparency; can be revisited.
2. Should a `blocked` verdict visually dim the events table, or only surface the banner? — Recommend banner only; results are still valid observations even under advisory block.

---

## Assumptions (flagged)

- **[A1]** The `QualityGateAssessment` JSON shape produced by #493 matches the TypeScript types defined here. If #493 deviates (e.g. uses different field names or severity values), the frontend types will need a corresponding update in the same PR.
- **[A2]** Issue #494 persists the gate assessment on `ScannerRun` and exposes it as `quality_gate` in `ScannerRunResponse`. The frontend type addition in `ScannerRunResponse` in this spec is a forward declaration; it becomes active once #494 ships.
- **[A3]** Event-level warnings are in `ScannerEvent.metadata_["quality_warnings"]` as an array of objects with at minimum `issue_code`, `severity`, `title`, and `remediation`. The existing `metadata: Record<string, unknown>` type on `ScannerEvent` already accommodates this.
- **[A4]** A follow-up issue must be filed after #493 ships to wire the `POST /api/v1/data-quality/gate` fetch into `QualityReportModal` (or `useQualityReport`), passing the result as the `gate` prop. Until that lands the modal trust-gate section is present but renders nothing.

---

## File Touch List

| File | Change |
|------|--------|
| `frontend/src/api/scanner/types.ts` | Add `QualityIssueCode`, `QualityGateIssue`, `QualityGateSummary`, `QualityGateAssessment` types; extend `ScannerRunResponse` with optional `quality_gate` |
| `frontend/src/components/TrustGateSummary.tsx` | New component — verdict badge, counts, affected tickers, grouped issue list |
| `frontend/src/components/TrustGateBanner.tsx` | New component — compact run-level banner for scanner results |
| `frontend/src/components/QualityReportModal/index.tsx` | Add optional `gate` prop; render `<TrustGateSummary>` above `<QualityOverviewCard>` |
| `frontend/src/components/ScannerResults.tsx` | Add optional `qualityGate` prop; render `<TrustGateBanner>` above filters; add `QualityWarningBadge` in ticker cells |
| `frontend/src/pages/Scanner/ResultsPanel.tsx` | Pass `scanResults.quality_gate` to `ScannerResults` |
| `frontend/src/components/QualityReportModal/panels.test.tsx` | Add trust gate verdict state and issue grouping tests |
| `frontend/src/components/ScannerResults.test.tsx` | Add banner render tests for each verdict state; per-event badge tests |

---

*Spec generated by MarketHawk Refinement Pipeline — issue #495*
