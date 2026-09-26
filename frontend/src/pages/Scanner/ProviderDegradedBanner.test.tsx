import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { ProviderDegradedBanner } from './ProviderDegradedBanner';
import type { ScannerRunResponse } from '../../api/scanner';

const baseRun: ScannerRunResponse = {
  scan_id: 'abc', status: 'completed', stocks_scanned: 100, events_detected: 0,
  execution_time_ms: 10, scanner_type: 'pre_market_volume_spike',
};

describe('ProviderDegradedBanner', () => {
  it('renders nothing without live provider gaps', () => {
    const { container } = render(<ProviderDegradedBanner run={{ ...baseRun, data_degraded: true, live_provider_gaps: [] }} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('renders nothing when run is null', () => {
    const { container } = render(<ProviderDegradedBanner run={null} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('shows each gap message and coverage ratio', () => {
    render(
      <ProviderDegradedBanner
        run={{
          ...baseRun,
          data_degraded: true,
          live_provider_gaps: [
            {
              code: 'provider_gap', severity: 'warning', message: 'Only 30% of tickers have pre-market data (30/100)',
              detail: { subtype: 'live_degradation', provider: 'polygon', reason: 'partial_coverage', coverage_ratio: 0.3 },
            },
            {
              code: 'provider_gap', severity: 'blocker', message: 'Polygon circuit breaker open (celery:1) — provider unavailable',
              detail: { subtype: 'live_degradation', provider: 'polygon', reason: 'breaker_open' },
            },
          ],
        }}
      />,
    );
    expect(screen.getByText(/Market data degraded during this scan/)).toBeInTheDocument();
    expect(screen.getByText(/Only 30% of tickers/)).toBeInTheDocument();
    expect(screen.getByText(/coverage 30%/)).toBeInTheDocument();
    expect(screen.getByText(/circuit breaker open/)).toBeInTheDocument();
  });
});
