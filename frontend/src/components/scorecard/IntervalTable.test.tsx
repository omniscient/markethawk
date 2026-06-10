import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import IntervalTable from './IntervalTable';
import type { IntervalBreakdown } from '../../api/outcomes';

const makeRow = (overrides: Partial<IntervalBreakdown> = {}): IntervalBreakdown => ({
  avg_pct: 1.5,
  median_pct: 1.2,
  stddev_pct: 0.8,
  win_rate: 60,
  sample_size: 45,
  ...overrides,
});

const baseData: Record<string, IntervalBreakdown> = {
  '1h': makeRow({ avg_pct: 2.1, win_rate: 65 }),
  '4h': makeRow({ avg_pct: -0.5, win_rate: 40 }),
  'eod': makeRow({ avg_pct: 0.0, win_rate: 50 }),
};

describe('IntervalTable — loading state', () => {
  it('renders loading skeleton when isLoading is true', () => {
    const { container } = render(<IntervalTable data={{}} isLoading={true} />);
    expect(container.querySelectorAll('.animate-pulse').length).toBeGreaterThan(0);
  });

  it('shows Interval Breakdown heading in loading state', () => {
    render(<IntervalTable data={{}} isLoading={true} />);
    expect(screen.getByText(/Interval Breakdown/i)).toBeInTheDocument();
  });
});

describe('IntervalTable — empty state', () => {
  it('shows "No interval data available" when data is empty', () => {
    render(<IntervalTable data={{}} isLoading={false} />);
    expect(screen.getByText(/No interval data available/i)).toBeInTheDocument();
  });

  it('shows Interval Breakdown heading in empty state', () => {
    render(<IntervalTable data={{}} isLoading={false} />);
    expect(screen.getByText(/Interval Breakdown/i)).toBeInTheDocument();
  });
});

describe('IntervalTable — data rendering', () => {
  it('renders without crashing with data', () => {
    render(<IntervalTable data={baseData} isLoading={false} />);
  });

  it('shows interval keys as uppercase table rows', () => {
    render(<IntervalTable data={baseData} isLoading={false} />);
    expect(screen.getByText('1h')).toBeInTheDocument();
    expect(screen.getByText('4h')).toBeInTheDocument();
    expect(screen.getByText('eod')).toBeInTheDocument();
  });

  it('shows column headers', () => {
    render(<IntervalTable data={baseData} isLoading={false} />);
    expect(screen.getAllByText(/Interval/i).length).toBeGreaterThan(0);
    expect(screen.getByText(/Avg %/i)).toBeInTheDocument();
    expect(screen.getByText(/Win Rate/i)).toBeInTheDocument();
    expect(screen.getByText(/Samples/i)).toBeInTheDocument();
  });

  it('applies green color to positive avg_pct', () => {
    render(<IntervalTable data={baseData} isLoading={false} />);
    const positiveCell = screen.getByText('+2.1%');
    expect(positiveCell.className).toContain('text-green-400');
  });

  it('applies red color to negative avg_pct', () => {
    render(<IntervalTable data={baseData} isLoading={false} />);
    const negativeCell = screen.getByText('-0.5%');
    expect(negativeCell.className).toContain('text-red-400');
  });

  it('applies green color to win rate >= 50', () => {
    render(<IntervalTable data={baseData} isLoading={false} />);
    const winRateCell = screen.getByText('65%');
    expect(winRateCell.className).toContain('text-green-400');
  });

  it('applies red color to win rate < 50', () => {
    render(<IntervalTable data={baseData} isLoading={false} />);
    const winRateCell = screen.getByText('40%');
    expect(winRateCell.className).toContain('text-red-400');
  });

  it('shows sample size', () => {
    const data = { '1h': makeRow({ sample_size: 88 }) };
    render(<IntervalTable data={data} isLoading={false} />);
    expect(screen.getByText('88')).toBeInTheDocument();
  });

  it('renders extra keys not in INTERVAL_ORDER', () => {
    const data = { ...baseData, 'custom': makeRow() };
    render(<IntervalTable data={data} isLoading={false} />);
    expect(screen.getByText('custom')).toBeInTheDocument();
  });
});
