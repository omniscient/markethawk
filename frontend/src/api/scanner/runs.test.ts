import { describe, expect, it, vi, beforeEach } from 'vitest';
import { fetchScannerHistory } from './runs';

const mocks = vi.hoisted(() => ({ get: vi.fn() }));

vi.mock('../client', () => ({
  apiClient: { get: (...args: unknown[]) => mocks.get(...args) },
}));

describe('fetchScannerHistory', () => {
  beforeEach(() => vi.clearAllMocks());

  it('keeps the limit-only call shape', async () => {
    mocks.get.mockResolvedValueOnce({ data: [] });
    await fetchScannerHistory(10);
    expect(mocks.get).toHaveBeenCalledWith('/scanner/history', { params: { limit: 10 } });
  });

  it('passes degraded-run filters (#388)', async () => {
    mocks.get.mockResolvedValueOnce({ data: [] });
    await fetchScannerHistory(1, { universe_id: 6, scanner_type: 'pre_market_volume_spike', data_degraded: true });
    expect(mocks.get).toHaveBeenCalledWith('/scanner/history', {
      params: { limit: 1, universe_id: 6, scanner_type: 'pre_market_volume_spike', data_degraded: true },
    });
  });
});
