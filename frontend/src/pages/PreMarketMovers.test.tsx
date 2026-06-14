import { vi, describe, it, expect, beforeEach } from 'vitest';
import { screen, waitFor, fireEvent } from '@testing-library/react';
import { renderWithQuery } from '../test-utils/renderWithQuery';
import type { PreMarketMover } from '../api/scanner';
import PreMarketMovers from './PreMarketMovers';

const mockFetchPreMarketMovers = vi.hoisted(() => vi.fn());

vi.mock('../api/scanner', () => ({
  fetchPreMarketMovers: mockFetchPreMarketMovers,
}));

vi.mock('../components/Ticker', () => ({ default: () => null }));

// Omits market_cap intentionally — keeps name-text assertions clean
function makeMover(overrides: Partial<PreMarketMover> = {}): PreMarketMover {
  return {
    ticker: 'AAPL',
    name: null,
    price: 150,
    change_percent: 2.5,
    change_value: 3.75,
    volume: 100000,
    prev_close: 146.25,
    ...overrides,
  };
}

const EMPTY_RESPONSE = { status: 'ok', movers: [], timestamp: '2026-01-01T04:00:00.000Z' };

describe('PreMarketMovers page', () => {
  beforeEach(() => {
    mockFetchPreMarketMovers.mockReset();
    mockFetchPreMarketMovers.mockResolvedValue(EMPTY_RESPONSE);
  });

  it('shows loading spinner initially', () => {
    renderWithQuery(<PreMarketMovers />);
    expect(screen.getByText(/Loading/i)).toBeInTheDocument();
  });

  it('shows error message and Retry button when fetch fails', async () => {
    mockFetchPreMarketMovers.mockRejectedValueOnce(new Error('Network error'));
    renderWithQuery(<PreMarketMovers />);
    await waitFor(() => {
      expect(screen.getByText(/Network error/i)).toBeInTheDocument();
    });
    expect(screen.getByRole('button', { name: /Retry/i })).toBeInTheDocument();
  });

  it('shows empty state message after fetch returns no movers', async () => {
    renderWithQuery(<PreMarketMovers />);
    await waitFor(() => {
      expect(screen.getByText(/No movers found/i)).toBeInTheDocument();
    });
  });

  it('filters table rows by ticker text input', async () => {
    mockFetchPreMarketMovers.mockResolvedValueOnce({
      status: 'ok',
      timestamp: '2026-01-01T04:00:00.000Z',
      movers: [
        makeMover({ ticker: 'AAPL', name: 'Apple', change_percent: 2.5 }),
        makeMover({ ticker: 'NVDA', name: 'Nvidia', change_percent: 5.0 }),
      ],
    });
    renderWithQuery(<PreMarketMovers />);
    await waitFor(() => {
      expect(screen.getByText('Apple')).toBeInTheDocument();
    });

    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'AAPL' } });

    expect(screen.queryByText('Nvidia')).not.toBeInTheDocument();
    expect(screen.getByText('Apple')).toBeInTheDocument();
  });
});
