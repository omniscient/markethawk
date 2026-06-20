# Data Quality Trust Status UI

**Date:** 2026-06-20  
**Issue:** #495  
**Spec:** `docs/superpowers/specs/2026-06-19-data-quality-trust-status-ui-design.md`  
**Branch:** `refine/issue-495-show-data-quality-trust-status-in-scanne`

---

## Goal

Ship three new frontend components and wire them into three existing files, surfacing data quality trust gate status in the scanner results page and quality report modal. Components are prop-driven and render nothing when gate data is absent ("present but dark"), so this lands in production without waiting for backend dependencies #493 and #494.

## Architecture

- **Types layer**: new `QualityIssueCode`, `QualityGateIssue`, `QualityGateSummary`, `QualityGateAssessment` exported from `frontend/src/api/scanner/types.ts`; `ScannerRunResponse` extended with optional `quality_gate`
- **`TrustGateSummary`**: prop-driven, shows verdict badge + count chips + most-affected tickers + grouped issue list (collapse/expand)
- **`TrustGateBanner`**: compact run-level advisory banner that embeds `TrustGateSummary` in an expandable panel
- **`QualityWarningBadge`**: local sub-component within `ScannerResults.tsx`; inline amber badge in the ticker cell opening a popover
- **Wiring**: `QualityReportModal` gets an optional `gate?` prop; `ScannerResults` gets `qualityGate?`; `ResultsPanel` passes `scanResults.quality_gate` down

No backend changes. No new routes. No new React Query hooks.

## Tech Stack

React 18 + TypeScript (strict) · Tailwind CSS (utility classes only — no custom CSS) · Vitest + React Testing Library

## File Structure

| File | Change |
|------|--------|
| `frontend/src/api/scanner/types.ts` | Add 4 new exported types; extend `ScannerRunResponse.quality_gate?` |
| `frontend/src/components/TrustGateSummary.tsx` | New component |
| `frontend/src/components/TrustGateBanner.tsx` | New component |
| `frontend/src/components/ScannerResults.tsx` | Add `qualityGate?` prop; render `<TrustGateBanner>` above filters; add `QualityWarningBadge` in ticker cell |
| `frontend/src/pages/Scanner/ResultsPanel.tsx` | Pass `scanResults.quality_gate` to `<ScannerResults>` |
| `frontend/src/components/QualityReportModal/index.tsx` | Add `gate?` prop; render `<TrustGateSummary>` above `<QualityOverviewCard>` |
| `frontend/src/components/QualityReportModal/panels.test.tsx` | Add `TrustGateSummary` verdict + grouping tests; add `QualityReportModal` gate-wiring tests |
| `frontend/src/components/ScannerResults.test.tsx` | Add banner verdict tests; add `QualityWarningBadge` badge tests |

---

## Task 1 — TypeScript types

**Files:** `frontend/src/api/scanner/types.ts`

No failing-test step (pure type definitions; verified by `tsc --noEmit`).

### Steps

**1.1** Open `frontend/src/api/scanner/types.ts`. After the last `export interface` block (currently `SignalQualityDistributionResponse`, ~line 272), append:

```typescript
// Data Quality Trust Gate — types matching the QualityGateAssessment shape from #493
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

**1.2** In the existing `ScannerRunResponse` interface, add `quality_gate` as the last field:

```typescript
export interface ScannerRunResponse {
  scan_id: string;
  status: string;
  stocks_scanned: number;
  events_detected: number;
  execution_time_ms: number;
  scanner_type: string;
  events?: ScannerEvent[];
  error_message?: string;
  created_at?: string;
  scan_start_date?: string;
  scan_end_date?: string;
  diagnostics?: ScannerDiagnostics;
  quality_gate?: QualityGateAssessment;
}
```

**1.3** Verify:
```bash
cd frontend && npx tsc --noEmit
```
Expected: exit 0, no errors.

**1.4** Commit:
```
feat(types): add QualityGateAssessment types and extend ScannerRunResponse (#495)
```

---

## Task 2 — `TrustGateSummary` component (TDD)

**Files:** `frontend/src/components/QualityReportModal/panels.test.tsx` (tests first), `frontend/src/components/TrustGateSummary.tsx` (component)

### Steps

**2.1** At the top of `frontend/src/components/QualityReportModal/panels.test.tsx`, add these imports after the existing import block:

```typescript
import type { QualityGateAssessment, QualityGateIssue } from '../../api/scanner/types';
import TrustGateSummary from '../TrustGateSummary';
```

**2.2** Add these two factory helpers after the existing `mockReportData` declaration in `panels.test.tsx`:

```typescript
// Minimal gate — no counts, no issues. Only the verdict badge renders.
const makeMinimalGate = (verdict: QualityGateAssessment['verdict']): QualityGateAssessment => ({
  verdict,
  policy: 'advisory',
  consumer: 'scanner',
  scanner_type: null,
  universe_id: null,
  generated_at: '2026-06-20T00:00:00Z',
  assessment_id: 'test-1',
  verdict_reason: 'Test reason',
  summary: {
    blocker_count: 0,
    warning_count: 0,
    info_count: 0,
    affected_ticker_count: 0,
    total_tickers_evaluated: 0,
    most_affected_tickers: [],
    issue_code_counts: {},
  },
  issues: [],
});

const makeIssue = (overrides: Partial<QualityGateIssue> = {}): QualityGateIssue => ({
  issue_code: 'missing_bars',
  severity: 'warning',
  title: 'Missing Bars',
  scope: 'ticker',
  ticker: 'AAPL',
  asset_class: 'us_equity',
  affected_inputs: { timespans: ['minute'] },
  detail: {},
  remediation: {
    action: 'backfill',
    label: 'Backfill missing bars',
    description: 'Run backfill job',
    automated: true,
  },
  ...overrides,
});

// Full gate with one warning issue.
const makeGate = (overrides: Partial<QualityGateAssessment> = {}): QualityGateAssessment => ({
  ...makeMinimalGate('warning'),
  summary: {
    blocker_count: 0,
    warning_count: 1,
    info_count: 0,
    affected_ticker_count: 1,
    total_tickers_evaluated: 100,
    most_affected_tickers: [{ ticker: 'AAPL', issue_count: 1, max_severity: 'warning' }],
    issue_code_counts: { missing_bars: 1 },
  },
  issues: [makeIssue()],
  ...overrides,
});
```

**2.3** Append the `TrustGateSummary` describe block at the end of `panels.test.tsx`:

```typescript
// ── TrustGateSummary ──────────────────────────────────────────────────────────

describe('TrustGateSummary', () => {
  it('renders trusted verdict badge', () => {
    renderWithQuery(<TrustGateSummary gate={makeMinimalGate('trusted')} />);
    expect(screen.getByText('trusted')).toBeInTheDocument();
  });

  it('renders warning verdict badge', () => {
    renderWithQuery(<TrustGateSummary gate={makeMinimalGate('warning')} />);
    expect(screen.getByText('warning')).toBeInTheDocument();
  });

  it('renders blocked verdict badge', () => {
    renderWithQuery(<TrustGateSummary gate={makeMinimalGate('blocked')} />);
    expect(screen.getByText('blocked')).toBeInTheDocument();
  });

  it('renders skipped verdict badge', () => {
    renderWithQuery(<TrustGateSummary gate={makeMinimalGate('skipped')} />);
    expect(screen.getByText('skipped')).toBeInTheDocument();
  });

  it('shows blocker count chip when summary.blocker_count > 0', () => {
    const gate = makeGate({
      verdict: 'blocked',
      summary: { ...makeGate().summary, blocker_count: 2, warning_count: 0 },
    });
    renderWithQuery(<TrustGateSummary gate={gate} />);
    expect(screen.getByText(/2 blocker/i)).toBeInTheDocument();
  });

  it('shows warning count chip when summary.warning_count > 0', () => {
    renderWithQuery(<TrustGateSummary gate={makeGate()} />);
    expect(screen.getByText(/1 warning/i)).toBeInTheDocument();
  });

  it('shows most-affected ticker chips', () => {
    renderWithQuery(<TrustGateSummary gate={makeGate()} />);
    expect(screen.getByText('AAPL')).toBeInTheDocument();
  });

  it('collapses issue list by default for warning verdict', () => {
    renderWithQuery(<TrustGateSummary gate={makeGate({ verdict: 'warning' })} />);
    expect(screen.queryByText('Missing Bars')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /show issues/i })).toBeInTheDocument();
  });

  it('expands issue list by default for blocked verdict', () => {
    const gate = makeGate({
      verdict: 'blocked',
      summary: { ...makeGate().summary, blocker_count: 1, warning_count: 0 },
    });
    renderWithQuery(<TrustGateSummary gate={gate} />);
    expect(screen.getByText('Missing Bars')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /hide issues/i })).toBeInTheDocument();
  });

  it('toggles issue list on show/hide button click', () => {
    renderWithQuery(<TrustGateSummary gate={makeGate({ verdict: 'warning' })} />);
    expect(screen.queryByText('Missing Bars')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /show issues/i }));
    expect(screen.getByText('Missing Bars')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /hide issues/i }));
    expect(screen.queryByText('Missing Bars')).not.toBeInTheDocument();
  });

  it('groups multiple issues with the same issue_code under one heading', () => {
    const gate = makeGate({
      verdict: 'blocked',
      issues: [
        makeIssue({ ticker: 'AAPL' }),
        makeIssue({ ticker: 'MSFT' }),
      ],
      summary: {
        ...makeGate().summary,
        blocker_count: 1,
        most_affected_tickers: [],
      },
    });
    renderWithQuery(<TrustGateSummary gate={gate} />);
    // Both issues share 'Missing Bars' title — must appear exactly once as the group heading
    expect(screen.getAllByText('Missing Bars')).toHaveLength(1);
    // Both tickers appear as individual rows
    expect(screen.getByText(/AAPL/)).toBeInTheDocument();
    expect(screen.getByText(/MSFT/)).toBeInTheDocument();
  });

  it('shows remediation label for each issue', () => {
    const gate = makeGate({ verdict: 'blocked', summary: { ...makeGate().summary, blocker_count: 1 } });
    renderWithQuery(<TrustGateSummary gate={gate} />);
    expect(screen.getByText('Backfill missing bars')).toBeInTheDocument();
  });
});
```

**2.4** Run tests — expect FAIL (module not found):
```bash
cd frontend && npx vitest run --reporter=verbose src/components/QualityReportModal/panels.test.tsx 2>&1 | tail -20
```
Expected output contains: `Error: Cannot find module '../TrustGateSummary'`

**2.5** Create `frontend/src/components/TrustGateSummary.tsx`:

```tsx
import React, { useState } from 'react';
import {
  ChevronDown,
  ChevronRight,
  AlertTriangle,
  Info,
  CheckCircle,
  XCircle,
  SkipForward,
} from 'lucide-react';
import type { QualityGateAssessment, QualityGateIssue, QualityIssueCode } from '../api/scanner/types';

const VERDICT_STYLES: Record<QualityGateAssessment['verdict'], string> = {
  trusted: 'bg-green-500/20 text-green-400 border-green-500/30',
  warning: 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30',
  blocked: 'bg-red-500/20 text-red-400 border-red-500/30',
  skipped: 'bg-gray-500/20 text-gray-400 border-gray-500/30',
};

const VERDICT_ICONS: Record<
  QualityGateAssessment['verdict'],
  React.FC<{ className?: string }>
> = {
  trusted: CheckCircle,
  warning: AlertTriangle,
  blocked: XCircle,
  skipped: SkipForward,
};

const SEVERITY_TEXT: Record<QualityGateIssue['severity'], string> = {
  blocker: 'text-red-400',
  warning: 'text-yellow-400',
  info: 'text-blue-400',
};

const TICKER_SEVERITY_STYLES: Record<'blocker' | 'warning' | 'info', string> = {
  blocker: 'bg-red-500/15 text-red-400 border-red-500/30',
  warning: 'bg-yellow-500/15 text-yellow-400 border-yellow-500/30',
  info: 'bg-blue-500/15 text-blue-400 border-blue-500/30',
};

const SeverityIcon: React.FC<{ severity: QualityGateIssue['severity'] }> = ({
  severity,
}) => {
  if (severity === 'blocker')
    return <XCircle className="h-3.5 w-3.5 text-red-400 flex-shrink-0" />;
  if (severity === 'warning')
    return <AlertTriangle className="h-3.5 w-3.5 text-yellow-400 flex-shrink-0" />;
  return <Info className="h-3.5 w-3.5 text-blue-400 flex-shrink-0" />;
};

interface TrustGateSummaryProps {
  gate: QualityGateAssessment;
}

const TrustGateSummary: React.FC<TrustGateSummaryProps> = ({ gate }) => {
  const [expanded, setExpanded] = useState(gate.verdict === 'blocked');

  const groupedIssues = gate.issues.reduce<
    Partial<Record<QualityIssueCode, QualityGateIssue[]>>
  >((acc, issue) => {
    const key = issue.issue_code;
    if (!acc[key]) acc[key] = [];
    acc[key]!.push(issue);
    return acc;
  }, {});

  const VerdictIcon = VERDICT_ICONS[gate.verdict];
  const verdictStyle = VERDICT_STYLES[gate.verdict];

  return (
    <div className="border border-gray-700 rounded-lg overflow-hidden">
      <div className="p-3 bg-gray-800/60 flex items-center justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-2 flex-wrap">
          <span
            className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded text-xs font-bold uppercase border ${verdictStyle}`}
          >
            <VerdictIcon className="h-3.5 w-3.5" />
            {gate.verdict}
          </span>

          <div className="flex items-center gap-1.5">
            {gate.summary.blocker_count > 0 && (
              <span className="bg-red-500/20 text-red-400 border border-red-500/30 px-2 py-0.5 rounded text-xs font-semibold">
                {gate.summary.blocker_count} blocker
                {gate.summary.blocker_count !== 1 ? 's' : ''}
              </span>
            )}
            {gate.summary.warning_count > 0 && (
              <span className="bg-yellow-500/20 text-yellow-400 border border-yellow-500/30 px-2 py-0.5 rounded text-xs font-semibold">
                {gate.summary.warning_count} warning
                {gate.summary.warning_count !== 1 ? 's' : ''}
              </span>
            )}
            {gate.summary.info_count > 0 && (
              <span className="bg-blue-500/20 text-blue-400 border border-blue-500/30 px-2 py-0.5 rounded text-xs font-semibold">
                {gate.summary.info_count} info
              </span>
            )}
          </div>

          {gate.summary.most_affected_tickers.length > 0 && (
            <div className="flex items-center gap-1 flex-wrap">
              {gate.summary.most_affected_tickers.slice(0, 5).map((t) => (
                <span
                  key={t.ticker}
                  className={`text-[10px] font-mono font-bold px-1.5 py-0.5 rounded border ${
                    TICKER_SEVERITY_STYLES[t.max_severity]
                  }`}
                >
                  {t.ticker}
                </span>
              ))}
            </div>
          )}
        </div>

        {gate.issues.length > 0 && (
          <button
            onClick={() => setExpanded((v) => !v)}
            className="flex items-center gap-1 text-xs text-gray-400 hover:text-gray-200 flex-shrink-0"
            aria-expanded={expanded}
          >
            {expanded ? (
              <>
                <ChevronDown className="h-3.5 w-3.5" /> Hide issues
              </>
            ) : (
              <>
                <ChevronRight className="h-3.5 w-3.5" /> Show issues
              </>
            )}
          </button>
        )}
      </div>

      {expanded && gate.issues.length > 0 && (
        <div className="divide-y divide-gray-800">
          {(
            Object.entries(groupedIssues) as [QualityIssueCode, QualityGateIssue[]][]
          ).map(([code, issues]) => {
            const first = issues[0];
            return (
              <div key={code} className="p-3">
                <div className="flex items-center gap-2 mb-2">
                  <SeverityIcon severity={first.severity} />
                  <span
                    className={`text-xs font-semibold ${SEVERITY_TEXT[first.severity]}`}
                  >
                    {first.title}
                  </span>
                  <span className="text-[10px] font-mono text-gray-500">{code}</span>
                </div>
                <div className="space-y-1 pl-5">
                  {issues.map((issue, idx) => (
                    <div
                      key={idx}
                      className="flex items-start justify-between gap-2 text-xs text-gray-400"
                    >
                      <span>
                        {issue.ticker && (
                          <span className="font-mono font-bold text-gray-300">
                            {issue.ticker} ·{' '}
                          </span>
                        )}
                        {issue.scope}
                        {issue.affected_inputs?.fields && (
                          <span className="text-gray-500 ml-1">
                            ({issue.affected_inputs.fields.join(', ')})
                          </span>
                        )}
                      </span>
                      <span className="text-[10px] text-gray-500 shrink-0">
                        {issue.remediation.label}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
};

export default TrustGateSummary;
```

**2.6** Run tests — expect all TrustGateSummary tests PASS:
```bash
cd frontend && npx vitest run --reporter=verbose src/components/QualityReportModal/panels.test.tsx 2>&1 | tail -30
```
Expected: all describe('TrustGateSummary', ...) tests show ✓

**2.7** Verify TypeScript:
```bash
cd frontend && npx tsc --noEmit
```
Expected: exit 0.

**2.8** Commit:
```
feat(ui): TrustGateSummary component with verdict badge and issue grouping (#495)
```

---

## Task 3 — `TrustGateBanner` + wire `ScannerResults` (TDD)

**Files:** `frontend/src/components/ScannerResults.test.tsx` (tests first), `frontend/src/components/TrustGateBanner.tsx` (new), `frontend/src/components/ScannerResults.tsx` (modified)

### Steps

**3.1** Add a `makeGate` factory and two new `describe` blocks to `frontend/src/components/ScannerResults.test.tsx` (after the existing `describe('ScannerResults', ...)` block):

```typescript
import type { QualityGateAssessment, QualityGateIssue } from '../api/scanner/types';

const makeGate = (
  verdict: QualityGateAssessment['verdict'] = 'warning',
): QualityGateAssessment => ({
  verdict,
  policy: 'advisory',
  consumer: 'scanner',
  scanner_type: null,
  universe_id: null,
  generated_at: '2026-06-20T00:00:00Z',
  assessment_id: 'test-1',
  verdict_reason: 'Test reason',
  summary: {
    blocker_count: verdict === 'blocked' ? 1 : 0,
    warning_count: verdict === 'warning' ? 1 : 0,
    info_count: 0,
    affected_ticker_count: 0,
    total_tickers_evaluated: 0,
    most_affected_tickers: [],
    issue_code_counts: {},
  },
  issues: [],
});

const makeWarning = (overrides: Partial<QualityGateIssue> = {}): QualityGateIssue => ({
  issue_code: 'missing_bars',
  severity: 'warning',
  title: 'Missing Bars',
  scope: 'ticker',
  ticker: 'AAPL',
  asset_class: 'us_equity',
  affected_inputs: null,
  detail: {},
  remediation: {
    action: 'backfill',
    label: 'Backfill',
    description: 'Run backfill',
    automated: true,
  },
  ...overrides,
});

describe('ScannerResults — TrustGateBanner', () => {
  it('does not render trust gate banner when qualityGate prop is absent', () => {
    renderWithQuery(<ScannerResults results={emptyResults} />);
    // None of the four verdict words should appear
    expect(screen.queryByText(/^trusted$|^warning$|^blocked$|^skipped$/)).not.toBeInTheDocument();
  });

  it.each(['trusted', 'warning', 'blocked', 'skipped'] as const)(
    'renders banner showing %s verdict when qualityGate is provided',
    (verdict) => {
      renderWithQuery(
        <ScannerResults results={emptyResults} qualityGate={makeGate(verdict)} />,
      );
      expect(screen.getByText(verdict)).toBeInTheDocument();
    },
  );
});

describe('ScannerResults — QualityWarningBadge', () => {
  it('renders quality warning badge in ticker cell when event has quality_warnings', () => {
    const event = makeEvent({
      metadata: { quality_warnings: [makeWarning()] },
    });
    renderWithQuery(
      <ScannerResults
        results={{ ...emptyResults, events_detected: 1, events: [event] }}
      />,
    );
    expect(
      screen.getByRole('button', { name: /1 quality warning/i }),
    ).toBeInTheDocument();
  });

  it('does not render quality warning badge when event has no quality_warnings', () => {
    renderWithQuery(<ScannerResults results={resultsWithEvents} />);
    expect(
      screen.queryByRole('button', { name: /quality warning/i }),
    ).not.toBeInTheDocument();
  });

  it('opens popover with warning details on badge click', () => {
    const event = makeEvent({
      metadata: { quality_warnings: [makeWarning()] },
    });
    renderWithQuery(
      <ScannerResults
        results={{ ...emptyResults, events_detected: 1, events: [event] }}
      />,
    );
    fireEvent.click(screen.getByRole('button', { name: /1 quality warning/i }));
    expect(screen.getByText('Missing Bars')).toBeInTheDocument();
    expect(screen.getByText('Backfill')).toBeInTheDocument();
  });
});
```

**3.2** Run tests — expect FAIL (qualityGate prop not accepted):
```bash
cd frontend && npx vitest run --reporter=verbose src/components/ScannerResults.test.tsx 2>&1 | tail -20
```
Expected: TypeScript error or test failures on the new describe blocks.

**3.3** Create `frontend/src/components/TrustGateBanner.tsx`:

```tsx
import React, { useState } from 'react';
import {
  ChevronDown,
  ChevronRight,
  AlertTriangle,
  CheckCircle,
  XCircle,
  SkipForward,
} from 'lucide-react';
import type { QualityGateAssessment } from '../api/scanner/types';
import TrustGateSummary from './TrustGateSummary';

type VerdictStyle = {
  container: string;
  iconClass: string;
  textClass: string;
  Icon: React.FC<{ className?: string }>;
};

const VERDICT_STYLES: Record<QualityGateAssessment['verdict'], VerdictStyle> = {
  trusted: {
    container: 'border-green-500/30 bg-green-500/5',
    iconClass: 'text-green-400',
    textClass: 'text-green-400',
    Icon: CheckCircle,
  },
  warning: {
    container: 'border-yellow-500/30 bg-yellow-500/10',
    iconClass: 'text-yellow-400',
    textClass: 'text-yellow-400',
    Icon: AlertTriangle,
  },
  blocked: {
    container: 'border-red-500/30 bg-red-500/10',
    iconClass: 'text-red-400',
    textClass: 'text-red-400',
    Icon: XCircle,
  },
  skipped: {
    container: 'border-gray-500/30 bg-gray-500/5',
    iconClass: 'text-gray-400',
    textClass: 'text-gray-400',
    Icon: SkipForward,
  },
};

interface TrustGateBannerProps {
  gate: QualityGateAssessment;
}

const TrustGateBanner: React.FC<TrustGateBannerProps> = ({ gate }) => {
  const [expanded, setExpanded] = useState(false);
  const { container, iconClass, textClass, Icon } = VERDICT_STYLES[gate.verdict];

  return (
    <div className={`mb-4 border rounded-lg ${container}`}>
      <div className="flex items-start gap-2 p-3">
        <Icon className={`h-4 w-4 flex-shrink-0 mt-0.5 ${iconClass}`} />
        <div className="flex-1 min-w-0">
          <div className="flex items-baseline gap-2 flex-wrap">
            <span className={`text-sm font-semibold ${textClass}`}>
              {gate.verdict}
            </span>
            <span className="text-xs text-gray-400 truncate">{gate.verdict_reason}</span>
          </div>
          {(gate.summary.blocker_count > 0 || gate.summary.warning_count > 0) && (
            <div className="mt-0.5 text-[11px] text-gray-500">
              {gate.summary.blocker_count > 0 &&
                `${gate.summary.blocker_count} blocker(s)`}
              {gate.summary.blocker_count > 0 && gate.summary.warning_count > 0 && ' · '}
              {gate.summary.warning_count > 0 &&
                `${gate.summary.warning_count} warning(s)`}
            </div>
          )}
        </div>
        {gate.issues.length > 0 && (
          <button
            onClick={() => setExpanded((v) => !v)}
            className="flex items-center gap-1 text-xs text-gray-400 hover:text-gray-200 shrink-0"
            aria-expanded={expanded}
            aria-label={expanded ? 'Collapse gate details' : 'Expand gate details'}
          >
            {expanded ? (
              <ChevronDown className="h-3.5 w-3.5" />
            ) : (
              <ChevronRight className="h-3.5 w-3.5" />
            )}{' '}
            Details
          </button>
        )}
      </div>
      {expanded && (
        <div className="px-3 pb-3">
          <TrustGateSummary gate={gate} />
        </div>
      )}
    </div>
  );
};

export default TrustGateBanner;
```

**3.4** Update `frontend/src/components/ScannerResults.tsx`:

**a)** Add imports at the top (alongside existing imports):
```tsx
import TrustGateBanner from './TrustGateBanner';
import type { QualityGateAssessment, QualityGateIssue } from '../api/scanner';
```

**b)** Extend `ScannerResultsProps` with the new optional prop:
```tsx
interface ScannerResultsProps {
  results: {
    scan_id: string;
    status: string;
    stocks_scanned: number;
    events_detected: number;
    execution_time_ms: number;
    events?: ScannerEvent[];
    scan_start_date?: string;
    scan_end_date?: string;
    diagnostics?: ScannerDiagnostics;
  };
  onSort?: (column: string) => void;
  sortBy?: string;
  sortOrder?: 'asc' | 'desc';
  qualityGate?: QualityGateAssessment;
}
```

**c)** Destructure `qualityGate` in the component function signature:
```tsx
const ScannerResults: React.FC<ScannerResultsProps> = ({
  results,
  onSort,
  sortBy,
  sortOrder,
  qualityGate,
}) => {
```

**d)** Add `<TrustGateBanner>` immediately inside the `<Card>` body, before the Results Summary grid (currently first child in the return). Place it ABOVE the diagnostics block and filter controls:
```tsx
return (
  <Card title="Scanner Results" icon={Eye}>
    {/* Trust gate advisory banner — only shown when quality gate data is available */}
    {qualityGate && <TrustGateBanner gate={qualityGate} />}

    {/* Results Summary */}
    <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
      ...
    </div>
    ...
```

**e)** Add `QualityWarningBadge` local component (below the existing `ScoreQualityBadge` component, before `export default ScannerResults`):

```tsx
const SEVERITY_ORDER: Record<QualityGateIssue['severity'], number> = {
  blocker: 0,
  warning: 1,
  info: 2,
};

const BADGE_STYLES: Record<QualityGateIssue['severity'], string> = {
  blocker: 'bg-red-500/20 text-red-400 border-red-500/30',
  warning: 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30',
  info: 'bg-blue-500/20 text-blue-400 border-blue-500/30',
};

interface QualityWarningBadgeProps {
  warnings: QualityGateIssue[];
}

const QualityWarningBadge: React.FC<QualityWarningBadgeProps> = ({ warnings }) => {
  const [open, setOpen] = useState(false);

  const maxSeverity = warnings.reduce<QualityGateIssue['severity']>((max, w) => {
    return SEVERITY_ORDER[w.severity] < SEVERITY_ORDER[max] ? w.severity : max;
  }, 'info');

  return (
    <div className="relative inline-block ml-1">
      <button
        onClick={() => setOpen((v) => !v)}
        className={`inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[9px] font-bold border ${BADGE_STYLES[maxSeverity]}`}
        aria-label={`${warnings.length} quality warning${warnings.length !== 1 ? 's' : ''}`}
      >
        ⚠ {warnings.length}
      </button>
      {open && (
        <div className="absolute z-10 left-0 top-full mt-1 min-w-[220px] bg-gray-900 border border-gray-700 rounded-lg shadow-lg p-2 text-xs">
          {warnings.map((w, i) => (
            <div key={i} className="py-1.5 border-b border-gray-800 last:border-0">
              <div className="font-semibold text-gray-200">{w.title}</div>
              <div className="text-gray-400">{w.remediation.label}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};
```

**f)** In the event row ticker cell (currently `<td className="py-4 px-4 bg-gray-800">`), add `QualityWarningBadge` after `<Ticker>`:
```tsx
<td className="py-4 px-4 bg-gray-800">
  <div className="flex items-center">
    <Ticker
      ticker={event.ticker}
      size="lg"
      showIcon={true}
    />
    {Array.isArray(event.metadata?.quality_warnings) &&
      (event.metadata.quality_warnings as QualityGateIssue[]).length > 0 && (
        <QualityWarningBadge
          warnings={event.metadata.quality_warnings as QualityGateIssue[]}
        />
      )}
  </div>
</td>
```

**3.5** Run tests — expect all new describe blocks PASS:
```bash
cd frontend && npx vitest run --reporter=verbose src/components/ScannerResults.test.tsx 2>&1 | tail -30
```
Expected: all tests in `describe('ScannerResults — TrustGateBanner', ...)` and `describe('ScannerResults — QualityWarningBadge', ...)` show ✓

**3.6** Verify TypeScript:
```bash
cd frontend && npx tsc --noEmit
```
Expected: exit 0.

**3.7** Commit:
```
feat(ui): TrustGateBanner component and ScannerResults trust gate wiring (#495)
```

---

## Task 4 — Wire `QualityReportModal` (TDD)

**Files:** `frontend/src/components/QualityReportModal/panels.test.tsx` (tests first), `frontend/src/components/QualityReportModal/index.tsx` (modified)

### Steps

**4.1** Add two new `vi.mock` calls at the top of `panels.test.tsx` (after existing `vi.mock` calls; `vi.mock` is hoisted, so placement within the file does not matter, but grouping them is conventional):

```typescript
vi.mock('../../hooks/useQualityReport', () => ({
  useQualityReport: () => ({
    report: null,
    isLoading: false,
    removedTickers: new Set<string>(),
    normalizationTriggered: false,
    isAnalyzing: false,
    isNormalizing: false,
    isBusy: false,
    deleteMutation: { isPending: false },
    analyzeMutation: { mutate: vi.fn() },
    normalizeMutation: { mutate: vi.fn() },
  }),
}));
```

**4.2** Add the following import and declare `mockUniverse` after the `makeGate` helpers block:

```typescript
import QualityReportModal from '../QualityReportModal';
import type { StockUniverse } from '../../api/universe';

const mockUniverse: StockUniverse = {
  id: 1,
  uuid: 'test-universe-uuid',
  name: 'Test Universe',
  description: 'Test description',
  criteria: {},
  is_active: true,
  created_at: '2026-06-20T00:00:00Z',
};
```

**4.3** Append the `QualityReportModal` trust gate integration describe block at the end of `panels.test.tsx`:

```typescript
// ── QualityReportModal — trust gate wiring ────────────────────────────────────

describe('QualityReportModal — trust gate wiring', () => {
  it('renders TrustGateSummary verdict when gate prop is provided', () => {
    renderWithQuery(
      <QualityReportModal
        isOpen={true}
        onClose={vi.fn()}
        universe={mockUniverse}
        gate={makeMinimalGate('blocked')}
      />,
    );
    expect(screen.getByText('blocked')).toBeInTheDocument();
  });

  it('does not render trust gate section when gate prop is absent', () => {
    renderWithQuery(
      <QualityReportModal
        isOpen={true}
        onClose={vi.fn()}
        universe={mockUniverse}
      />,
    );
    expect(
      screen.queryByText(/^trusted$|^warning$|^blocked$|^skipped$/),
    ).not.toBeInTheDocument();
  });
});
```

**4.4** Run tests — expect FAIL (gate prop not accepted by QualityReportModal):
```bash
cd frontend && npx vitest run --reporter=verbose src/components/QualityReportModal/panels.test.tsx 2>&1 | tail -20
```
Expected: TypeScript or runtime error on `gate={makeMinimalGate('blocked')}`.

**4.5** Update `frontend/src/components/QualityReportModal/index.tsx`:

**a)** Add import for `TrustGateSummary` and the gate type after the existing import block:
```tsx
import TrustGateSummary from '../TrustGateSummary';
import type { QualityGateAssessment } from '../../api/scanner/types';
```

**b)** Extend `QualityReportModalProps` with the optional `gate` field:
```tsx
interface QualityReportModalProps {
  isOpen: boolean;
  onClose: () => void;
  universe: StockUniverse | null;
  gate?: QualityGateAssessment;
}
```

**c)** Destructure `gate` in the component signature:
```tsx
const QualityReportModal: React.FC<QualityReportModalProps> = ({
  isOpen,
  onClose,
  universe,
  gate,
}) => {
```

**d)** Inside `<div className="relative space-y-4 min-h-[300px]">`, add the `TrustGateSummary` render as the **first** child (before the loading spinner block, so it always shows when gate is present):
```tsx
<div className="relative space-y-4 min-h-[300px]">
  {gate && <TrustGateSummary gate={gate} />}

  {(isLoading || isAnalyzing) && (
    ...
```

**4.6** Run tests — expect all `QualityReportModal — trust gate wiring` tests PASS:
```bash
cd frontend && npx vitest run --reporter=verbose src/components/QualityReportModal/panels.test.tsx 2>&1 | tail -30
```
Expected: all tests show ✓.

**4.7** Verify TypeScript:
```bash
cd frontend && npx tsc --noEmit
```
Expected: exit 0.

**4.8** Commit:
```
feat(ui): wire QualityReportModal with optional trust gate section (#495)
```

---

## Task 5 — Wire `ResultsPanel`

**Files:** `frontend/src/pages/Scanner/ResultsPanel.tsx`

No failing-test step (change is a one-line prop addition; verified by `tsc --noEmit`).

### Steps

**5.1** In `frontend/src/pages/Scanner/ResultsPanel.tsx`, pass `scanResults.quality_gate` down to `ScannerResults`:

Full updated file (only the `<ScannerResults>` call changes):

```tsx
import ScannerResults from '../../components/ScannerResults';
import SignalReviewStats from '../../components/SignalReviewStats';
import type { ScannerRunResponse } from '../../api/scanner';

export interface ResultsPanelProps {
  scanResults: ScannerRunResponse | null;
  sortBy: string;
  sortOrder: 'asc' | 'desc';
  onSort: (column: string) => void;
}

export function ResultsPanel({ scanResults, sortBy, sortOrder, onSort }: ResultsPanelProps) {
  return (
    <>
      {scanResults && (
        <div className="animate-slide-up">
          <ScannerResults
            results={scanResults}
            sortBy={sortBy}
            sortOrder={sortOrder}
            onSort={onSort}
            qualityGate={scanResults.quality_gate}
          />
        </div>
      )}
      <SignalReviewStats />
    </>
  );
}
```

**5.2** Verify TypeScript:
```bash
cd frontend && npx tsc --noEmit
```
Expected: exit 0.

**5.3** Run all tests to confirm no regressions:
```bash
cd frontend && npx vitest run 2>&1 | tail -20
```
Expected: all tests pass.

**5.4** Commit:
```
feat(ui): wire ResultsPanel to pass quality_gate to ScannerResults (#495)
```

---

## Memory: Key Patterns Applied

The following memory lessons from `.archon/memory/frontend-patterns.md` are baked into the tasks above:

- **[AVOID] `any` in TypeScript** — all new code uses proper types: `QualityGateAssessment`, `QualityGateIssue`, `QualityIssueCode`. The only cast is `event.metadata.quality_warnings as QualityGateIssue[]` with a `Array.isArray()` guard.
- **[PATTERN] API types from `frontend/src/api/*.ts`** — new components import types from `'../api/scanner/types'` (or `'../api/scanner'` which re-exports from `types.ts` via `export * from './types'`).
- **[AVOID] `screen.getAllByRole('button')[0]`** — all test assertions use `getByRole('button', { name: /label/i })`.
- **[AVOID] ad-hoc mock shapes** — `makeMinimalGate`, `makeGate`, `makeIssue`, `makeWarning` factories are derived from the actual `QualityGateAssessment` and `QualityGateIssue` interfaces.
- **[PATTERN] Tailwind CSS utilities only** — no custom CSS files or inline `style` objects; all new components use Tailwind class strings matching the existing `bg-*/20 text-*/400 border-*/30` badge palette used in `ScannerResults.tsx`.
