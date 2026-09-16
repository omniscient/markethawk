import { describe, expect, it, vi, beforeEach } from 'vitest';
import { fetchRegimeBreakdown } from './outcomes';

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
}));

vi.mock('./client', () => ({
  apiClient: {
    get: (...args: unknown[]) => mocks.get(...args),
  },
}));

describe('outcomes API', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('fetches regime breakdown for a scanner with date filters', async () => {
    mocks.get.mockResolvedValueOnce({
      data: {
        scanner_type: 'pre_market_volume_spike',
        total_events: 2,
        breakdown: {
          risk_on: {
            sample_size: 2,
            win_rate_pct: 50,
            avg_mfe_pct: 3.5,
            avg_mae_pct: -1.2,
          },
        },
      },
    });

    const result = await fetchRegimeBreakdown('pre_market_volume_spike', {
      start_date: '2026-01-01',
      end_date: '2026-01-31',
    });

    expect(mocks.get).toHaveBeenCalledWith('/outcomes/regime-breakdown/pre_market_volume_spike', {
      params: {
        start_date: '2026-01-01',
        end_date: '2026-01-31',
      },
    });
    expect(result.breakdown.risk_on.sample_size).toBe(2);
  });
});
