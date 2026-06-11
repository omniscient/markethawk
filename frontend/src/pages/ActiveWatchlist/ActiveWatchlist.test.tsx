import { vi, describe, it, expect } from 'vitest';
import { screen } from '@testing-library/react';
import { renderWithQuery } from '../../test-utils/renderWithQuery';
import ActiveWatchlist from './index';

const mockUseWatchlist = vi.fn(() => ({ data: [], isLoading: false, isError: false }));

vi.mock('../../api/watchlist', () => ({
  useWatchlist: () => mockUseWatchlist(),
  useAddToWatchlist: () => ({ mutate: vi.fn(), isPending: false }),
  useRemoveFromWatchlist: () => ({ mutate: vi.fn(), isPending: false }),
  useUpdateWatchlistNotes: () => ({ mutate: vi.fn(), isPending: false }),
}));

vi.mock('../../hooks/useWatchlistLive', () => ({
  useWatchlistLive: () => ({ liveData: {}, connected: false }),
}));

describe('ActiveWatchlist', () => {
  it('renders without crashing', () => {
    renderWithQuery(<ActiveWatchlist />);
  });

  it('shows Active Watchlist heading', () => {
    renderWithQuery(<ActiveWatchlist />);
    expect(screen.getByText(/Active Watchlist/i)).toBeInTheDocument();
  });

  it('shows symbol count and limit', () => {
    renderWithQuery(<ActiveWatchlist />);
    expect(screen.getByText(/\/ 50/)).toBeInTheDocument();
  });

  it('shows "Connecting…" when not connected', () => {
    renderWithQuery(<ActiveWatchlist />);
    expect(screen.getByText(/Connecting/i)).toBeInTheDocument();
  });

  it('shows "No symbols in the watchlist yet" when list is empty', () => {
    renderWithQuery(<ActiveWatchlist />);
    expect(screen.getByText(/No symbols in the watchlist yet/i)).toBeInTheDocument();
  });

  it('shows Add Symbol form when list is not full', () => {
    renderWithQuery(<ActiveWatchlist />);
    expect(screen.getByText(/Add Symbol/i)).toBeInTheDocument();
  });

  it('shows error state when useWatchlist returns isError', () => {
    mockUseWatchlist.mockReturnValueOnce({ data: [], isLoading: false, isError: true });
    renderWithQuery(<ActiveWatchlist />);
    expect(screen.getByText(/Failed to load watchlist/i)).toBeInTheDocument();
  });
});
