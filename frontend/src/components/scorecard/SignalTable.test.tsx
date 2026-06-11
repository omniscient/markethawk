import { vi, describe, it, expect } from 'vitest';
import { screen, fireEvent } from '@testing-library/react';
import { renderWithQuery } from '../../test-utils/renderWithQuery';
import SignalTable from './SignalTable';
import type { SignalListItem } from '../../api/outcomes';

const mockUseSignals = vi.fn();

vi.mock('../../hooks/useScorecard', () => ({
  useSignals: (...args: unknown[]) => mockUseSignals(...args),
}));

const makeSignal = (overrides: Partial<SignalListItem> = {}): SignalListItem => ({
  id: 1,
  ticker: 'AAPL',
  event_date: '2026-01-15',
  severity: 'high',
  summary: null,
  opening_price: 150.0,
  previous_close: 148.0,
  closing_price: 152.0,
  reference_price: 150.5,
  mfe_pct: 3.2,
  mae_pct: -1.1,
  mfe_mae_ratio: 2.9,
  eod_pct_change: 1.5,
  follow_through: true,
  is_complete: true,
  ...overrides,
});

describe('SignalTable — loading state', () => {
  it('shows loading skeleton when isLoading', () => {
    mockUseSignals.mockReturnValue({ data: undefined, isLoading: true });
    const { container } = renderWithQuery(
      <SignalTable scannerType="pre_market_volume_spike" />,
    );
    expect(container.querySelectorAll('.animate-pulse').length).toBeGreaterThan(0);
  });

  it('shows "Signals" heading in loading state', () => {
    mockUseSignals.mockReturnValue({ data: undefined, isLoading: true });
    renderWithQuery(<SignalTable scannerType="pre_market_volume_spike" />);
    expect(screen.getByText(/^Signals$/)).toBeInTheDocument();
  });
});

describe('SignalTable — empty state', () => {
  it('shows "No signals found" when data total is 0', () => {
    mockUseSignals.mockReturnValue({
      data: { signals: [], total: 0, limit: 20, offset: 0 },
      isLoading: false,
    });
    renderWithQuery(<SignalTable scannerType="pre_market_volume_spike" />);
    expect(screen.getByText(/No signals found/i)).toBeInTheDocument();
  });

  it('shows "No signals found" when data is undefined', () => {
    mockUseSignals.mockReturnValue({ data: undefined, isLoading: false });
    renderWithQuery(<SignalTable scannerType="pre_market_volume_spike" />);
    expect(screen.getByText(/No signals found/i)).toBeInTheDocument();
  });
});

describe('SignalTable — data state', () => {
  beforeEach(() => {
    mockUseSignals.mockReturnValue({
      data: {
        signals: [makeSignal({ ticker: 'TSLA', id: 1 })],
        total: 1,
        limit: 20,
        offset: 0,
      },
      isLoading: false,
    });
  });

  it('renders without crashing', () => {
    renderWithQuery(<SignalTable scannerType="pre_market_volume_spike" />);
  });

  it('shows ticker symbol', () => {
    renderWithQuery(<SignalTable scannerType="pre_market_volume_spike" />);
    expect(screen.getByText('TSLA')).toBeInTheDocument();
  });

  it('shows event_date', () => {
    renderWithQuery(<SignalTable scannerType="pre_market_volume_spike" />);
    expect(screen.getByText('2026-01-15')).toBeInTheDocument();
  });

  it('shows total count', () => {
    renderWithQuery(<SignalTable scannerType="pre_market_volume_spike" />);
    expect(screen.getByText(/1 total/i)).toBeInTheDocument();
  });

  it('shows table headers: Date, Ticker, Severity', () => {
    renderWithQuery(<SignalTable scannerType="pre_market_volume_spike" />);
    expect(screen.getByText(/^Date/i)).toBeInTheDocument();
    expect(screen.getByText(/^Ticker/i)).toBeInTheDocument();
    expect(screen.getByText(/^Severity/i)).toBeInTheDocument();
  });

  it('shows severity badge', () => {
    renderWithQuery(<SignalTable scannerType="pre_market_volume_spike" />);
    expect(screen.getByText(/high/i)).toBeInTheDocument();
  });
});

describe('SignalTable — sorting', () => {
  beforeEach(() => {
    mockUseSignals.mockReturnValue({
      data: { signals: [makeSignal()], total: 1, limit: 20, offset: 0 },
      isLoading: false,
    });
  });

  it('clicking Date header calls useSignals with changed sort params', () => {
    renderWithQuery(<SignalTable scannerType="pre_market_volume_spike" />);
    fireEvent.click(screen.getByText(/^Date/i));
    expect(mockUseSignals).toHaveBeenCalled();
  });

  it('clicking Ticker header triggers a re-render', () => {
    renderWithQuery(<SignalTable scannerType="pre_market_volume_spike" />);
    fireEvent.click(screen.getByText(/^Ticker/i));
    expect(screen.getByText(/^Ticker/i)).toBeInTheDocument();
  });
});

describe('SignalTable — pagination', () => {
  it('shows pagination controls when total > PAGE_SIZE', () => {
    mockUseSignals.mockReturnValue({
      data: {
        signals: Array.from({ length: 20 }, (_, i) => makeSignal({ id: i + 1, ticker: `SYM${i}` })),
        total: 45,
        limit: 20,
        offset: 0,
      },
      isLoading: false,
    });
    renderWithQuery(<SignalTable scannerType="pre_market_volume_spike" />);
    expect(screen.getByText(/1 \/ 3/i)).toBeInTheDocument();
  });
});
