import { vi, describe, it, expect } from 'vitest';
import { screen } from '@testing-library/react';
import { renderWithQuery } from '../test-utils/renderWithQuery';
import PreMarketMovers from './PreMarketMovers';

vi.mock('../api/scanner', () => ({
  fetchPreMarketMovers: vi.fn().mockResolvedValue({
    movers: [],
    timestamp: new Date().toISOString(),
  }),
  fetchStorageStats: vi.fn().mockResolvedValue({}),
}));

vi.mock('../components/Ticker', () => ({ default: () => null }));

describe('PreMarketMovers page', () => {
  it('renders without crashing', () => {
    renderWithQuery(<PreMarketMovers />);
  });

  it('shows loading spinner initially', () => {
    renderWithQuery(<PreMarketMovers />);
    expect(screen.getByText(/Loading/i)).toBeInTheDocument();
  });
});
