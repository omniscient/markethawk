import { vi, describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MetadataPanel } from './MetadataPanel';

vi.mock('../../components/NewsFeed', () => ({ default: () => null }));

const baseProps = {
  symbol: 'AAPL',
  details: {
    pre_market: {
      pre_market_volume: 200000,
      pre_market_high: 155.75,
    },
  },
  scannerResults: [{ metadata: { catalyst_summary: 'Earnings beat' } }],
  events: [{ id: 1 }],
};

describe('MetadataPanel', () => {
  it('renders without crashing', () => {
    render(<MetadataPanel {...baseProps} />);
  });

  it('passes symbol to NewsFeed (section heading visible)', () => {
    render(<MetadataPanel {...baseProps} />);
    expect(screen.getByText(/Stock Specific News/i)).toBeInTheDocument();
  });

  it('shows PM High formatted to 2 decimal places when available', () => {
    render(<MetadataPanel {...baseProps} />);
    expect(screen.getByText(/155\.75/)).toBeInTheDocument();
  });

  it('shows N/A when pre_market_high is null', () => {
    const props = {
      ...baseProps,
      details: { pre_market: { pre_market_volume: 200000, pre_market_high: null } },
    };
    render(<MetadataPanel {...props} />);
    expect(screen.getByText(/N\/A/)).toBeInTheDocument();
  });

  it('shows N/A when details is null', () => {
    render(<MetadataPanel {...baseProps} details={null} />);
    expect(screen.getByText(/N\/A/)).toBeInTheDocument();
  });

  it('renders all 4 checklist items', () => {
    render(<MetadataPanel {...baseProps} />);
    expect(screen.getByText(/Scanner Alert Detected/i)).toBeInTheDocument();
    expect(screen.getByText(/Check Extended Hours Volume/i)).toBeInTheDocument();
    expect(screen.getByText(/Confirm Sector Strength/i)).toBeInTheDocument();
    expect(screen.getByText(/Review Catalyst Summary/i)).toBeInTheDocument();
  });

  it('renders Pro Tip with the symbol name', () => {
    render(<MetadataPanel {...baseProps} />);
    expect(screen.getByText(/Pro Tip/i)).toBeInTheDocument();
    expect(screen.getByText(/AAPL/)).toBeInTheDocument();
  });

  it('renders Trader Plan Checklist card heading', () => {
    render(<MetadataPanel {...baseProps} />);
    expect(screen.getByText(/Trader Plan Checklist/i)).toBeInTheDocument();
  });
});
