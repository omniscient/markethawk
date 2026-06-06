import { vi, describe, it, expect } from 'vitest';
import { screen } from '@testing-library/react';
import { renderWithQuery } from '../test-utils/renderWithQuery';
import Dashboard from './Dashboard';

vi.mock('../api/scanner', () => ({
  fetchScannerResults: vi.fn().mockResolvedValue([]),
  fetchMarketStats: vi.fn().mockResolvedValue({
    activeAlerts: 0,
    avgVolumeSpike: 0,
    totalEvents: 0,
    todayEvents: 0,
  }),
  fetchStockUniverses: vi.fn().mockResolvedValue([]),
  submitReview: vi.fn().mockResolvedValue({}),
}));

vi.mock('../api/news', () => ({
  fetchNewsPreferences: vi.fn().mockResolvedValue({ tickers: [], topics: [] }),
  updateNewsPreferences: vi.fn().mockResolvedValue({}),
}));

vi.mock('../components/NewsFeed', () => ({ default: () => null }));
vi.mock('../components/TweetFeed', () => ({ default: () => null }));
vi.mock('../components/ui/StockChart', () => ({ default: () => null }));

describe('Dashboard page', () => {
  it('renders without crashing', () => {
    renderWithQuery(<Dashboard />);
  });

  it('shows the Dashboard heading', async () => {
    renderWithQuery(<Dashboard />);
    expect(await screen.findByRole('heading', { name: /dashboard/i })).toBeInTheDocument();
  });
});
