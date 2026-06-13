import { vi, describe, it, expect, beforeEach, afterEach } from 'vitest';
import { screen, fireEvent } from '@testing-library/react';
import { renderWithQuery } from '../test-utils/renderWithQuery';
import ScorecardOverview, { periodToDates } from './ScorecardOverview';

const mockUseScannerConfigs = vi.fn(() => ({ data: [], isLoading: false }));
const mockUseScorecard = vi.fn(() => ({ data: null, isLoading: false }));

vi.mock('../hooks/useScorecard', () => ({
  useScannerConfigs: () => mockUseScannerConfigs(),
  useScorecard: (...args: unknown[]) => mockUseScorecard(...args),
}));

vi.mock('../components/scorecard/ScannerSummaryCard', () => ({
  default: ({ scannerName, isLoading }: { scannerName: string; isLoading?: boolean }) => (
    <div data-testid="summary-card" data-loading={String(isLoading)}>{scannerName}</div>
  ),
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

  it('shows empty state when all configs are inactive', () => {
    mockUseScannerConfigs.mockReturnValueOnce({
      data: [
        { id: 1, name: 'Scanner A', scanner_type: 'pre_market_volume_spike', is_active: false },
        { id: 2, name: 'Scanner B', scanner_type: 'trend_pullback', is_active: false },
      ],
      isLoading: false,
    });
    renderWithQuery(<ScorecardOverview />);
    expect(screen.getByText(/No scanner configurations found/i)).toBeInTheDocument();
  });

  it('renders scanner summary cards when configs are present', () => {
    mockUseScannerConfigs.mockReturnValueOnce({
      data: [
        { id: 1, name: 'Pre-Market Spike', scanner_type: 'pre_market_volume_spike', is_active: true },
        { id: 2, name: 'Inactive Scanner', scanner_type: 'trend_pullback', is_active: false },
      ],
      isLoading: false,
    });
    renderWithQuery(<ScorecardOverview />);
    expect(screen.getAllByTestId('summary-card')).toHaveLength(1);
  });

  it('shows loading skeleton cards with isLoading=true', () => {
    mockUseScannerConfigs.mockReturnValueOnce({ data: undefined, isLoading: true });
    renderWithQuery(<ScorecardOverview />);
    const cards = screen.getAllByTestId('summary-card');
    expect(cards).toHaveLength(2);
    cards.forEach((card) => expect(card).toHaveAttribute('data-loading', 'true'));
  });

  it('changes active period button styling when clicked', () => {
    renderWithQuery(<ScorecardOverview />);
    fireEvent.click(screen.getByRole('button', { name: /7D/i }));
    const sevenDayBtn = screen.getByRole('button', { name: /7D/i });
    expect(sevenDayBtn.className).toContain('bg-financial-blue');
  });
});

describe('ScorecardOverview — period → useScorecard call args', () => {
  const FIXED_DATE = new Date('2026-06-12T00:00:00.000Z');

  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(FIXED_DATE);
    mockUseScorecard.mockClear();
  });

  afterEach(() => {
    vi.useRealTimers();
    mockUseScannerConfigs.mockImplementation(() => ({ data: [], isLoading: false }));
  });

  it('passes 7D date window to useScorecard on period click', () => {
    mockUseScannerConfigs.mockReturnValue({
      data: [{ id: 1, name: 'Pre-Market Spike', scanner_type: 'pre_market_volume_spike', is_active: true }],
      isLoading: false,
    });
    renderWithQuery(<ScorecardOverview />);
    mockUseScorecard.mockClear();
    fireEvent.click(screen.getByRole('button', { name: /7D/i }));
    expect(mockUseScorecard).toHaveBeenCalledWith(
      'pre_market_volume_spike',
      { start_date: '2026-06-05', end_date: '2026-06-12' },
    );
  });
});

describe('periodToDates', () => {
  const FIXED_DATE = new Date('2026-06-12T00:00:00.000Z');

  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(FIXED_DATE);
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("returns {} for 'all'", () => {
    expect(periodToDates('all')).toEqual({});
  });

  it("returns 7-day window for '7d'", () => {
    expect(periodToDates('7d')).toEqual({
      start_date: '2026-06-05',
      end_date: '2026-06-12',
    });
  });

  it("returns 30-day window for '30d'", () => {
    expect(periodToDates('30d')).toEqual({
      start_date: '2026-05-13',
      end_date: '2026-06-12',
    });
  });

  it("returns 90-day window for '90d'", () => {
    expect(periodToDates('90d')).toEqual({
      start_date: '2026-03-14',
      end_date: '2026-06-12',
    });
  });
});
