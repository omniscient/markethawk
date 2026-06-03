import { describe, it, expect, vi } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import React, { createElement } from 'react';
import { useScorecard } from './useScorecard';

vi.mock('../api/outcomes', () => ({
  fetchScorecard: vi.fn(),
}));

vi.mock('../api/scanner', () => ({
  fetchScannerConfigs: vi.fn(),
}));

import { fetchScorecard } from '../api/outcomes';

function makeWrapper() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return {
    wrapper: ({ children }: { children: React.ReactNode }) =>
      createElement(QueryClientProvider, { client: qc }, children),
    qc,
  };
}

describe('useScorecard', () => {
  it('is loading initially when scannerType is provided', () => {
    vi.mocked(fetchScorecard).mockResolvedValue({} as any);
    const { wrapper } = makeWrapper();
    const { result } = renderHook(() => useScorecard('pre_market'), { wrapper });
    expect(result.current.isLoading).toBe(true);
  });

  it('is not enabled (not fetching) when scannerType is undefined', () => {
    const { wrapper } = makeWrapper();
    const { result } = renderHook(() => useScorecard(undefined), { wrapper });
    expect(result.current.isPending).toBe(true);
    expect(result.current.fetchStatus).toBe('idle');
  });

  it('returns data on success', async () => {
    const mockScorecard = { win_rate: 0.6, avg_mfe: 2.5, sample_size: 100 };
    vi.mocked(fetchScorecard).mockResolvedValue(mockScorecard as any);
    const { wrapper } = makeWrapper();
    const { result } = renderHook(() => useScorecard('pre_market'), { wrapper });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(result.current.data).toMatchObject({ win_rate: 0.6, sample_size: 100 });
  });

  it('returns error state on fetch failure', async () => {
    vi.mocked(fetchScorecard).mockRejectedValue(new Error('network error'));
    const { wrapper } = makeWrapper();
    const { result } = renderHook(() => useScorecard('pre_market'), { wrapper });

    await waitFor(() => expect(result.current.isError).toBe(true));

    expect(result.current.error).toBeInstanceOf(Error);
  });
});
