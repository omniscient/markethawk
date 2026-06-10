import { vi, describe, it, expect } from 'vitest';
import { screen } from '@testing-library/react';
import { renderWithQuery } from '../test-utils/renderWithQuery';
import ScorecardDetail from './ScorecardDetail';

vi.mock('react-router-dom', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react-router-dom')>();
  return {
    ...actual,
    useParams: () => ({ scannerType: 'pre_market_volume_spike' }),
  };
});

vi.mock('../hooks/useScorecard', () => ({
  useScorecard: () => ({ data: null, isLoading: false, isError: false }),
  useEdgeDecay: () => ({ data: [], isLoading: false }),
  useIntervals: () => ({ data: {}, isLoading: false }),
  useDistribution: () => ({ data: [], isLoading: false }),
  useBackfillMutation: () => ({
    mutate: vi.fn(),
    isPending: false,
    isSuccess: false,
    isError: false,
    data: null,
    error: null,
  }),
  useSignals: () => ({ data: { items: [], total: 0, page: 1, pages: 1 }, isLoading: false }),
}));

vi.mock('../components/scorecard/EdgeDecayChart', () => ({ default: () => null }));
vi.mock('../components/scorecard/DistributionChart', () => ({ default: () => null }));

describe('ScorecardDetail', () => {
  const renderDetail = () => renderWithQuery(<ScorecardDetail />);

  it('renders without crashing', () => {
    renderDetail();
  });

  it('shows period selector buttons', () => {
    renderDetail();
    expect(screen.getByRole('button', { name: /7D/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /30D/i })).toBeInTheDocument();
  });

  it('shows severity selector', () => {
    renderDetail();
    expect(screen.getByRole('combobox')).toBeInTheDocument();
    expect(screen.getByText(/All Severities/i)).toBeInTheDocument();
  });

  it('shows "No outcome data yet" message when scorecard is null and not loading', () => {
    renderDetail();
    expect(screen.getByText(/No outcome data yet/i)).toBeInTheDocument();
  });

  it('shows "Signal quality analysis" subtitle', () => {
    renderDetail();
    expect(screen.getByText(/Signal quality analysis/i)).toBeInTheDocument();
  });

  it('shows backfill panel toggle', () => {
    renderDetail();
    expect(screen.getByRole('button', { name: /Backfill Outcomes/i })).toBeInTheDocument();
  });

  it('shows back arrow link', () => {
    renderDetail();
    const link = screen.getByRole('link');
    expect(link).toBeInTheDocument();
  });
});
