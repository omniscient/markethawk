import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { ScannerCoverage } from '../../api/scanner';
import { CoveragePanel } from './CoveragePanel';

const coverage: ScannerCoverage = {
  scanner_type: 'liquidity_hunt',
  universe_id: 6,
  latest_covered: '2026-07-08',
  latest_trading_day: '2026-07-09',
  covered: [
    { start: '2026-03-26', end: '2026-05-22', runs: 2, events: 194 },
    { start: '2026-07-08', end: '2026-07-08', runs: 1, events: 6 },
  ],
  gaps: [
    { start: '2026-05-23', end: '2026-07-07', weekdays: 32 },
    { start: '2026-07-09', end: '2026-07-09', weekdays: 1 },
  ],
};

describe('CoveragePanel', () => {
  it('renders coverage timeline segments and explicit gaps', () => {
    render(
      <CoveragePanel
        coverage={coverage}
        isLoading={false}
        isScanning={false}
        onScanGap={vi.fn()}
        onFillAllGaps={vi.fn()}
      />,
    );

    expect(screen.getByText('2026-05-23 - 2026-07-07')).toBeInTheDocument();
    expect(screen.getByText('32 weekdays')).toBeInTheDocument();
    expect(screen.getByTitle('Covered: 2026-03-26 - 2026-05-22, 194 events')).toBeInTheDocument();
    expect(screen.getByTitle('Gap: 2026-05-23 - 2026-07-07, 32 weekdays')).toBeInTheDocument();
  });

  it('wires gap scan actions to exact gap ranges', async () => {
    const user = userEvent.setup();
    const onScanGap = vi.fn();
    const onFillAllGaps = vi.fn();

    render(
      <CoveragePanel
        coverage={coverage}
        isLoading={false}
        isScanning={false}
        onScanGap={onScanGap}
        onFillAllGaps={onFillAllGaps}
      />,
    );

    await user.click(screen.getAllByRole('button', { name: /scan this gap/i })[0]);
    await user.click(screen.getByRole('button', { name: /fill all gaps/i }));

    expect(onScanGap).toHaveBeenCalledWith({ start: '2026-05-23', end: '2026-07-07', weekdays: 32 });
    expect(onFillAllGaps).toHaveBeenCalledWith(coverage.gaps);
  });

  it('disables rescan buttons while a scan is running', () => {
    render(
      <CoveragePanel
        coverage={coverage}
        isLoading={false}
        isScanning={true}
        onScanGap={vi.fn()}
        onFillAllGaps={vi.fn()}
      />,
    );

    expect(screen.getAllByRole('button', { name: /scan this gap/i })[0]).toBeDisabled();
    expect(screen.getByRole('button', { name: /fill all gaps/i })).toBeDisabled();
    expect(screen.getByText(/scan running/i)).toBeInTheDocument();
  });
});
