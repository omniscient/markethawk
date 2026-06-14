import { vi, describe, it, expect, beforeEach } from 'vitest';
import { screen, fireEvent } from '@testing-library/react';
import { renderWithQuery } from '../test-utils/renderWithQuery';
import ScorecardDetail from './ScorecardDetail';
import type { Scorecard } from '../api/outcomes';

const mockUseScorecard = vi.fn();
const mockUseEdgeDecay = vi.fn();
const mockUseIntervals = vi.fn();
const mockUseDistribution = vi.fn();
const mockUseBackfillMutation = vi.fn();
const mockUseSignals = vi.fn();

vi.mock('react-router-dom', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react-router-dom')>();
  return {
    ...actual,
    useParams: () => ({ scannerType: 'pre_market_volume_spike' }),
  };
});

vi.mock('../hooks/useScorecard', () => ({
  useScorecard: (...args: unknown[]) => mockUseScorecard(...args),
  useEdgeDecay: (...args: unknown[]) => mockUseEdgeDecay(...args),
  useIntervals: (...args: unknown[]) => mockUseIntervals(...args),
  useDistribution: (...args: unknown[]) => mockUseDistribution(...args),
  useBackfillMutation: () => mockUseBackfillMutation(),
  useSignals: (...args: unknown[]) => mockUseSignals(...args),
}));

vi.mock('../components/scorecard/EdgeDecayChart', () => ({ default: () => null }));
vi.mock('../components/scorecard/DistributionChart', () => ({ default: () => null }));

const makeScorecard = (overrides: Partial<Scorecard> = {}): Scorecard => ({
  scanner_type: 'pre_market_volume_spike',
  period: '30d',
  total_signals: 42,
  complete_signals: 38,
  win_rate_pct: 65.5,
  avg_mfe_pct: 3.2,
  avg_mae_pct: -1.1,
  mfe_mae_ratio: 2.9,
  avg_r_multiple: 1.8,
  expectancy: 0.9,
  profit_factor: 1.7,
  follow_through_rate_pct: 72.0,
  edge_decay: [],
  interval_breakdown: {},
  ...overrides,
});

const noDataDefaults = () => {
  mockUseScorecard.mockReturnValue({ data: null, isLoading: false, isError: false });
  mockUseEdgeDecay.mockReturnValue({ data: [], isLoading: false });
  mockUseIntervals.mockReturnValue({ data: {}, isLoading: false });
  mockUseDistribution.mockReturnValue({ data: [], isLoading: false });
  mockUseBackfillMutation.mockReturnValue({
    mutate: vi.fn(),
    isPending: false,
    isSuccess: false,
    isError: false,
    data: null,
    error: null,
  });
  mockUseSignals.mockReturnValue({ data: { signals: [], total: 0, limit: 25, offset: 0 }, isLoading: false });
};

describe('ScorecardDetail — shell', () => {
  beforeEach(noDataDefaults);

  it('shows period selector buttons', () => {
    renderWithQuery(<ScorecardDetail />);
    expect(screen.getByRole('button', { name: /7D/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /30D/i })).toBeInTheDocument();
  });

  it('shows severity selector', () => {
    renderWithQuery(<ScorecardDetail />);
    expect(screen.getByRole('combobox')).toBeInTheDocument();
    expect(screen.getByText(/All Severities/i)).toBeInTheDocument();
  });

  it('shows "Signal quality analysis" subtitle', () => {
    renderWithQuery(<ScorecardDetail />);
    expect(screen.getByText(/Signal quality analysis/i)).toBeInTheDocument();
  });

  it('shows backfill panel toggle', () => {
    renderWithQuery(<ScorecardDetail />);
    expect(screen.getByRole('button', { name: /Backfill Outcomes/i })).toBeInTheDocument();
  });

  it('shows back arrow link', () => {
    renderWithQuery(<ScorecardDetail />);
    expect(screen.getByRole('link')).toBeInTheDocument();
  });
});

describe('ScorecardDetail — render branches', () => {
  beforeEach(noDataDefaults);

  it('shows "No outcome data yet" when scorecard is null and not loading', () => {
    renderWithQuery(<ScorecardDetail />);
    expect(screen.getByText(/No outcome data yet/i)).toBeInTheDocument();
  });

  it('shows loading skeleton when isLoading', () => {
    mockUseScorecard.mockReturnValue({ data: null, isLoading: true, isError: false });
    const { container } = renderWithQuery(<ScorecardDetail />);
    expect(container.querySelectorAll('.animate-pulse').length).toBeGreaterThan(0);
  });

  it('shows error message when isError', () => {
    mockUseScorecard.mockReturnValue({ data: null, isLoading: false, isError: true });
    renderWithQuery(<ScorecardDetail />);
    expect(screen.getByText(/Failed to load scorecard data/i)).toBeInTheDocument();
  });

  it('mounts HeroMetrics when scorecard is present', () => {
    mockUseScorecard.mockReturnValue({ data: makeScorecard(), isLoading: false, isError: false });
    renderWithQuery(<ScorecardDetail />);
    expect(screen.getByText(/Win Rate/i)).toBeInTheDocument();
  });
});

describe('ScorecardDetail — period selector', () => {
  beforeEach(noDataDefaults);

  it('marks ALL button aria-pressed=true after clicking it', () => {
    renderWithQuery(<ScorecardDetail />);
    const allButton = screen.getByRole('button', { name: /^ALL$/i });
    fireEvent.click(allButton);
    expect(allButton).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('button', { name: /^30D$/i })).toHaveAttribute('aria-pressed', 'false');
  });
});

describe('ScorecardDetail — derived values', () => {
  beforeEach(noDataDefaults);

  it('renders scanner type as uppercased heading', () => {
    renderWithQuery(<ScorecardDetail />);
    expect(screen.getByRole('heading', { name: 'PRE MARKET VOLUME SPIKE' })).toBeInTheDocument();
  });
});
