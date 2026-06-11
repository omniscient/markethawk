import { vi, describe, it, expect } from 'vitest';
import { screen, fireEvent } from '@testing-library/react';
import { renderWithQuery } from '../test-utils/renderWithQuery';
import ScorecardOverview from './ScorecardOverview';

const mockUseScannerConfigs = vi.fn(() => ({ data: [], isLoading: false }));
const mockUseScorecard = vi.fn(() => ({ data: null, isLoading: false }));

vi.mock('../hooks/useScorecard', () => ({
  useScannerConfigs: () => mockUseScannerConfigs(),
  useScorecard: () => mockUseScorecard(),
}));

vi.mock('../components/scorecard/ScannerSummaryCard', () => ({
  default: ({ scannerName }: { scannerName: string }) => <div data-testid="summary-card">{scannerName}</div>,
}));

describe('ScorecardOverview', () => {
  it('renders without crashing', () => {
    renderWithQuery(<ScorecardOverview />);
  });

  it('shows SCANNER SCORECARD heading', () => {
    renderWithQuery(<ScorecardOverview />);
    expect(screen.getByText(/Scanner Scorecard/i)).toBeInTheDocument();
  });

  it('shows period selector buttons', () => {
    renderWithQuery(<ScorecardOverview />);
    expect(screen.getByRole('button', { name: /7D/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /30D/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /90D/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /ALL/i })).toBeInTheDocument();
  });

  it('shows "No scanner configurations found" when configs is empty', () => {
    renderWithQuery(<ScorecardOverview />);
    expect(screen.getByText(/No scanner configurations found/i)).toBeInTheDocument();
  });

  it('renders scanner summary cards when configs are present', () => {
    mockUseScannerConfigs.mockReturnValueOnce({
      data: [{ id: 1, name: 'Pre-Market Spike', scanner_type: 'pre_market_volume_spike', is_active: true }],
      isLoading: false,
    });
    renderWithQuery(<ScorecardOverview />);
    expect(screen.getAllByTestId('summary-card').length).toBeGreaterThan(0);
  });

  it('shows loading skeleton cards when loadingConfigs is true', () => {
    mockUseScannerConfigs.mockReturnValueOnce({ data: undefined, isLoading: true });
    renderWithQuery(<ScorecardOverview />);
    expect(screen.getAllByTestId('summary-card').length).toBeGreaterThan(0);
  });

  it('changes active period button styling when clicked', () => {
    renderWithQuery(<ScorecardOverview />);
    fireEvent.click(screen.getByRole('button', { name: /7D/i }));
    const sevenDayBtn = screen.getByRole('button', { name: /7D/i });
    expect(sevenDayBtn.className).toContain('bg-financial-blue');
  });
});
