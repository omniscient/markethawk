import { vi, describe, it, expect, beforeEach } from 'vitest';
import { screen, fireEvent } from '@testing-library/react';
import { renderWithQuery } from '../../test-utils/renderWithQuery';
import ActiveWatchlist from './index';
import type { WatchlistItem } from '../../api/watchlist';

const mockUseWatchlist = vi.fn(() => ({ data: [], isLoading: false, isError: false }));
const mockAddMutate = vi.hoisted(() => vi.fn());

vi.mock('../../api/watchlist', () => ({
  useWatchlist: () => mockUseWatchlist(),
  useAddToWatchlist: () => ({ mutate: mockAddMutate, isPending: false }),
  useRemoveFromWatchlist: () => ({ mutate: vi.fn(), isPending: false }),
  useUpdateWatchlistNotes: () => ({ mutate: vi.fn(), isPending: false }),
}));

vi.mock('../../hooks/useWatchlistLive', () => ({
  useWatchlistLive: () => ({ liveData: {}, connected: false }),
}));

const fiftyItems: WatchlistItem[] = Array.from({ length: 50 }, (_, i) => ({
  id: i,
  symbol: `SY${String(i).padStart(2, '0')}`,
  security_type: 'STK',
  exchange: null,
  notes: null,
  added_at: new Date().toISOString(),
}));

beforeEach(() => {
  mockAddMutate.mockClear();
});

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

  it('shows loading spinner when isLoading is true', () => {
    mockUseWatchlist.mockReturnValueOnce({ data: [], isLoading: true, isError: false });
    renderWithQuery(<ActiveWatchlist />);
    expect(screen.getByText(/Loading watchlist/i)).toBeInTheDocument();
  });

  it('shows count in red when at limit (50 symbols)', () => {
    mockUseWatchlist.mockReturnValueOnce({ data: fiftyItems, isLoading: false, isError: false });
    renderWithQuery(<ActiveWatchlist />);
    expect(screen.getByText('50').className).toContain('text-red-400');
  });

  it('hides Add Symbol form when at limit', () => {
    mockUseWatchlist.mockReturnValueOnce({ data: fiftyItems, isLoading: false, isError: false });
    renderWithQuery(<ActiveWatchlist />);
    expect(screen.queryByText('Add Symbol')).not.toBeInTheDocument();
  });

  it('shows "Watchlist is full" warning when at limit', () => {
    mockUseWatchlist.mockReturnValueOnce({ data: fiftyItems, isLoading: false, isError: false });
    renderWithQuery(<ActiveWatchlist />);
    expect(screen.getByText(/Watchlist is full/i)).toBeInTheDocument();
  });

  it('submits trimmed uppercased symbol on Add', () => {
    renderWithQuery(<ActiveWatchlist />);
    fireEvent.change(screen.getByPlaceholderText('Symbol (e.g. NVDA)'), { target: { value: 'nvda' } });
    fireEvent.click(screen.getByRole('button', { name: /Add/i }));
    expect(mockAddMutate).toHaveBeenCalledWith(
      expect.objectContaining({ symbol: 'NVDA', security_type: 'STK' }),
      expect.anything()
    );
  });

  it('auto-sets exchange to CME when FUT is selected', () => {
    renderWithQuery(<ActiveWatchlist />);
    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'FUT' } });
    const exchangeInput = screen.getByPlaceholderText('Exchange (e.g. CME)') as HTMLInputElement;
    expect(exchangeInput.value).toBe('CME');
  });

  it('shows API error message when add mutation fails', () => {
    mockAddMutate.mockImplementationOnce(
      (_payload: unknown, { onError }: { onError: (err: unknown) => void }) => {
        onError({ response: { data: { detail: 'Symbol already in watchlist' } } });
      }
    );
    renderWithQuery(<ActiveWatchlist />);
    fireEvent.change(screen.getByPlaceholderText('Symbol (e.g. NVDA)'), { target: { value: 'AAPL' } });
    fireEvent.click(screen.getByRole('button', { name: /Add/i }));
    expect(screen.getByText(/Symbol already in watchlist/i)).toBeInTheDocument();
  });
});
