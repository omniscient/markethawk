import { vi, describe, it, expect } from 'vitest';
import { screen, fireEvent } from '@testing-library/react';
import { renderWithQuery } from '../test-utils/renderWithQuery';
import ScannerResults from './ScannerResults';
import type { ScannerEvent, QualityGateAssessment } from '../api/scanner';

vi.mock('../api/scanner', () => ({
  submitReview: vi.fn().mockResolvedValue({}),
}));

const makeEvent = (overrides: Partial<ScannerEvent> = {}): ScannerEvent => ({
  id: 1,
  uuid: 'test-uuid-1',
  ticker: 'AAPL',
  event_date: '2026-06-06',
  scanner_type: 'pre_market_volume_spike',
  severity: 'high',
  summary: 'Volume spike detected',
  indicators: { relative_volume: 4.2 },
  criteria_met: {},
  metadata: {},
  created_at: '2026-06-06T09:00:00Z',
  updated_at: '2026-06-06T09:00:00Z',
  latest_review: null,
  ...overrides,
});

const emptyResults = {
  scan_id: 'test-scan',
  status: 'completed',
  stocks_scanned: 100,
  events_detected: 0,
  execution_time_ms: 500,
  events: [],
};

const resultsWithEvents = {
  ...emptyResults,
  events_detected: 2,
  events: [
    makeEvent({ id: 1, ticker: 'AAPL', severity: 'high' }),
    makeEvent({ id: 2, ticker: 'TSLA', severity: 'medium', uuid: 'test-uuid-2' }),
  ],
};

describe('ScannerResults', () => {
  it('renders without crashing with empty results', () => {
    renderWithQuery(<ScannerResults results={emptyResults} />);
  });

  it('shows the empty-state placeholder when no events match filters', () => {
    renderWithQuery(<ScannerResults results={emptyResults} />);
    expect(screen.getByText(/no scanner results match your filters/i)).toBeInTheDocument();
  });

  it('renders event rows for each event in results', () => {
    renderWithQuery(<ScannerResults results={resultsWithEvents} />);
    expect(screen.getByText('AAPL')).toBeInTheDocument();
    expect(screen.getByText('TSLA')).toBeInTheDocument();
  });

  it('filters rows by ticker when filter input changes', () => {
    renderWithQuery(<ScannerResults results={resultsWithEvents} />);
    const filterInput = screen.getByPlaceholderText(/enter ticker/i);
    fireEvent.change(filterInput, { target: { value: 'AAPL' } });
    expect(screen.getByText('AAPL')).toBeInTheDocument();
    expect(screen.queryByText('TSLA')).not.toBeInTheDocument();
  });

  it('calls onSort when a sortable column header is clicked', () => {
    const onSort = vi.fn();
    renderWithQuery(
      <ScannerResults results={resultsWithEvents} onSort={onSort} sortBy="event_date" sortOrder="desc" />
    );
    fireEvent.click(screen.getByText(/^date$/i));
    expect(onSort).toHaveBeenCalledWith('event_date');
  });
});

const makeGate = (overrides: Partial<QualityGateAssessment> = {}): QualityGateAssessment => ({
  verdict: 'trusted',
  policy: 'advisory',
  consumer: 'scanner',
  scanner_type: null,
  universe_id: null,
  generated_at: '2026-06-20T00:00:00Z',
  assessment_id: 'test-gate-1',
  verdict_reason: '',
  summary: { blocker_count: 0, warning_count: 0, info_count: 0, affected_ticker_count: 0, total_tickers_evaluated: 0, most_affected_tickers: [], issue_code_counts: {} },
  issues: [],
  ...overrides,
});

describe('ScannerResults — TrustGateBanner', () => {
  it('does not render banner when qualityGate is absent', () => {
    renderWithQuery(<ScannerResults results={emptyResults} />);
    expect(screen.queryByText(/trusted/i)).not.toBeInTheDocument();
  });

  it('renders trusted banner when qualityGate verdict is trusted', () => {
    renderWithQuery(
      <ScannerResults results={emptyResults} qualityGate={makeGate({ verdict: 'trusted' })} />
    );
    expect(screen.getByText(/trusted/i)).toBeInTheDocument();
    expect(screen.getByText('Data quality checks passed')).toBeInTheDocument();
  });

  it('renders warning banner with warning count', () => {
    renderWithQuery(
      <ScannerResults
        results={emptyResults}
        qualityGate={makeGate({
          verdict: 'warning',
          summary: { blocker_count: 0, warning_count: 2, info_count: 0, affected_ticker_count: 0, total_tickers_evaluated: 0, most_affected_tickers: [], issue_code_counts: {} },
        })}
      />
    );
    expect(screen.getByText('warning')).toBeInTheDocument();
    expect(screen.getByText(/2 warnings/i)).toBeInTheDocument();
  });

  it('renders blocked banner with blocker count', () => {
    renderWithQuery(
      <ScannerResults
        results={emptyResults}
        qualityGate={makeGate({
          verdict: 'blocked',
          summary: { blocker_count: 1, warning_count: 0, info_count: 0, affected_ticker_count: 0, total_tickers_evaluated: 0, most_affected_tickers: [], issue_code_counts: {} },
        })}
      />
    );
    expect(screen.getByText(/blocked/i)).toBeInTheDocument();
    expect(screen.getByText(/1 blocker/i)).toBeInTheDocument();
  });
});

describe('ScannerResults — QualityWarningBadge', () => {
  it('renders warning badge for events with quality_warnings in metadata', () => {
    const eventWithWarnings = makeEvent({
      id: 3,
      ticker: 'NVDA',
      uuid: 'test-uuid-3',
      metadata: { quality_warnings: ['missing_bars', 'stale_quote_risk'] },
    });
    const results = { ...emptyResults, events_detected: 1, events: [eventWithWarnings] };
    renderWithQuery(<ScannerResults results={results} />);
    expect(screen.getByTitle(/2 data quality warning/i)).toBeInTheDocument();
  });

  it('does not render warning badge when quality_warnings is absent', () => {
    renderWithQuery(<ScannerResults results={resultsWithEvents} />);
    expect(screen.queryByTitle(/data quality warning/i)).not.toBeInTheDocument();
  });
});
