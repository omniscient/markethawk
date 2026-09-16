import { vi, describe, it, expect } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithQuery } from '../../test-utils/renderWithQuery';
import Scanner from './index';

const mocks = vi.hoisted(() => ({
  fetchScannerCoverage: vi.fn(),
  runScanner: vi.fn(),
}));

vi.mock('../../api/scanner', () => ({
  fetchScannerConfigs: vi.fn().mockResolvedValue([
    {
      id: 1,
      uuid: 'cfg-1',
      name: 'Liquidity Hunt',
      description: '',
      scanner_type: 'liquidity_hunt',
      parameters: {},
      criteria: [],
      is_active: true,
      run_frequency: 'manual',
      last_run: null,
      next_run: null,
    },
  ]),
  fetchStockUniverses: vi.fn().mockResolvedValue([
    { id: 6, name: 'Small Cap', ticker_count: 10, aggregate_count: 10 },
  ]),
  fetchScannerHistory: vi.fn().mockResolvedValue([]),
  fetchScanStatusBlock: vi.fn().mockResolvedValue({
    scanner_type: 'pre_market_volume_spike',
    universe_id: 6,
    last_run: null,
    next_run: null,
    total_events: 0,
    success_rate: null,
    avg_events_per_scan: null,
    sparkline: [],
  }),
  fetchScannerCoverage: mocks.fetchScannerCoverage,
  fetchScannerResults: vi.fn().mockResolvedValue([]),
  fetchScanStatus: vi.fn().mockResolvedValue({ status: 'completed' }),
  handleApiError: vi.fn().mockReturnValue('error'),
  runScanner: mocks.runScanner,
  submitReview: vi.fn().mockResolvedValue({}),
}));

vi.mock('../../hooks/useScannerWs', () => ({
  useScannerWs: () => ({ attachWebSocket: vi.fn() }),
}));

describe('Scanner page', () => {
  beforeEach(() => {
    localStorage.clear();
    localStorage.setItem(
      'markethawk.scanner.selection',
      JSON.stringify({ scanner_type: 'pre_market_volume_spike', universe_id: 6 }),
    );
    mocks.fetchScannerCoverage.mockResolvedValue({
      scanner_type: 'pre_market_volume_spike',
      universe_id: 6,
      latest_covered: '2026-07-08',
      latest_trading_day: '2026-07-09',
      covered: [{ start: '2026-07-08', end: '2026-07-08', runs: 1, events: 6 }],
      gaps: [{ start: '2026-07-09', end: '2026-07-09', weekdays: 1 }],
    });
    mocks.runScanner.mockResolvedValue({
      scan_id: '1',
      task_id: 't1',
      scanner_type: 'liquidity_hunt',
      universe_id: 6,
      scan_start_date: '2026-07-09',
      scan_end_date: '2026-07-09',
      started_at: '2026-07-09T20:00:00Z',
      status: 'queued',
    });
  });

  it('renders without crashing', () => {
    renderWithQuery(<Scanner />);
  });

  it('mounts the ScanConfigPanel with a Run Scanner button', () => {
    renderWithQuery(<Scanner />);
    expect(screen.getByRole('button', { name: /run scanner/i })).toBeInTheDocument();
  });

  it('fetches coverage for the selected scanner and universe', async () => {
    renderWithQuery(<Scanner />);

    await waitFor(() => {
      expect(mocks.fetchScannerCoverage).toHaveBeenCalledWith('pre_market_volume_spike', 6);
    });
  });

  it('runs an exact gap range from the coverage panel', async () => {
    const user = userEvent.setup();
    renderWithQuery(<Scanner />);

    await user.click(await screen.findByRole('button', { name: /scan this gap/i }));

    expect(mocks.runScanner).toHaveBeenCalledWith(
      {
        scanner_type: 'pre_market_volume_spike',
        universe_id: 6,
        tickers: [],
        dry_run: false,
        start_date: '2026-07-09',
        end_date: '2026-07-09',
      },
      expect.anything(),
    );
  });
});
