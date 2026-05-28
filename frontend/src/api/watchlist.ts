import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { apiClient } from './client';

export interface WatchlistItem {
  id: number;
  symbol: string;
  security_type: string;   // "STK" | "FUT"
  exchange: string | null;
  notes: string | null;
  added_at: string;
}

export interface AddToWatchlistPayload {
  symbol: string;
  security_type?: string;
  exchange?: string;
  notes?: string;
}

// ── API calls ──────────────────────────────────────────────────────────────

const fetchWatchlist = (): Promise<WatchlistItem[]> =>
  apiClient.get('/watchlist/').then((r) => r.data);

const addToWatchlist = (payload: AddToWatchlistPayload): Promise<WatchlistItem> =>
  apiClient.post('/watchlist/', payload).then((r) => r.data);

const removeFromWatchlist = (symbol: string): Promise<void> =>
  apiClient.delete(`/watchlist/${symbol}`).then((): void => undefined);

const updateWatchlistNotes = (symbol: string, notes: string | null): Promise<WatchlistItem> =>
  apiClient.patch(`/watchlist/${symbol}`, { notes }).then((r) => r.data);

// ── React Query hooks ──────────────────────────────────────────────────────

export const WATCHLIST_KEY = ['watchlist'] as const;

export function useWatchlist() {
  return useQuery({
    queryKey: WATCHLIST_KEY,
    queryFn: fetchWatchlist,
    staleTime: 30_000,
  });
}

export function useAddToWatchlist() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: addToWatchlist,
    onSuccess: () => qc.invalidateQueries({ queryKey: WATCHLIST_KEY }),
  });
}

export function useRemoveFromWatchlist() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: removeFromWatchlist,
    onSuccess: () => qc.invalidateQueries({ queryKey: WATCHLIST_KEY }),
  });
}

export function useUpdateWatchlistNotes() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ symbol, notes }: { symbol: string; notes: string | null }) =>
      updateWatchlistNotes(symbol, notes),
    onSuccess: () => qc.invalidateQueries({ queryKey: WATCHLIST_KEY }),
  });
}
