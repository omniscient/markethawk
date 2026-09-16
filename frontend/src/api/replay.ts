import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiClient } from './client';

export type ReplayRunStatus = 'queued' | 'running' | 'completed' | 'failed';
export type ReplayExitFidelity = 'intraday' | 'daily';

export interface ReplayRunCreateRequest {
  scanner_type: string;
  universe_id: number;
  start_date: string;
  end_date: string;
  trading_strategy_id?: number | null;
  max_hold_days?: number;
  exit_fidelity?: ReplayExitFidelity;
  benchmark_symbol?: string;
}

export interface ReplayRunSummary {
  id: number;
  uuid: string;
  status: ReplayRunStatus;
  celery_task_id: string | null;
  scanner_type: string;
  trading_strategy_id: number | null;
  universe_id: number;
  start_date: string;
  end_date: string;
  max_hold_days: number;
  exit_fidelity: ReplayExitFidelity;
  benchmark_symbol: string;
  data_hash: string | null;
  metrics: ReplayMetrics | null;
  skipped_count: number;
  error_message: string | null;
  total_trades: number;
  hit_rate: number | null;
  expectancy_r: number | null;
  profit_factor: number | null;
  max_drawdown_r: number | null;
  avg_bars_held: number | null;
  median_bars_held: number | null;
  avg_mfe_pct: number | null;
  avg_mae_pct: number | null;
  mfe_mae_ratio: number | null;
  created_at: string;
  completed_at: string | null;
}

export interface ReplayTrade {
  id: number;
  ticker: string;
  signal_date: string;
  entry_date: string | null;
  entry_price: number | null;
  direction: 'long' | 'short';
  stop_price: number | null;
  target_price: number | null;
  exit_date: string | null;
  exit_price: number | null;
  exit_reason: string | null;
  return_pct: number | null;
  return_r: number | null;
  mfe_pct: number | null;
  mae_pct: number | null;
  bars_held: number | null;
  regime_trend: string | null;
  regime_vol: string | null;
  fill_source: string | null;
}

export interface ReplayTradesResponse {
  trades: ReplayTrade[];
  total: number;
  limit: number;
  offset: number;
}

export interface ReplayMetrics {
  equity_curve?: Array<{ trade_index: number; equity_r: number }>;
  calendar_decay?: Array<{ bucket: string; trades: number; expectancy_r: number | null }>;
  holding_period_decay?: Array<{ bars_held: number; trades: number; expectancy_r: number | null }>;
  regime_breakdown?: Array<{
    trend: string;
    volatility: string;
    trades: number;
    expectancy_r: number | null;
    hit_rate: number | null;
  }>;
  [key: string]: unknown;
}

export interface ReplayCompareResponse {
  runs: ReplayRunSummary[];
  comparisons: Array<{
    a: string;
    b: string;
    data_hash_match: boolean;
  }>;
}

export interface ReplayRunListParams {
  scanner_type?: string;
  status?: ReplayRunStatus;
  universe_id?: number;
  limit?: number;
  offset?: number;
}

export const fetchReplayRuns = async (params?: ReplayRunListParams): Promise<ReplayRunSummary[]> => {
  const response = await apiClient.get('/replay/runs', { params });
  return response.data;
};

export const fetchReplayRun = async (uuid: string): Promise<ReplayRunSummary> => {
  const response = await apiClient.get(`/replay/runs/${uuid}`);
  return response.data;
};

export const createReplayRun = async (payload: ReplayRunCreateRequest): Promise<ReplayRunSummary> => {
  const response = await apiClient.post('/replay/runs', payload);
  return response.data;
};

export const fetchReplayTrades = async (
  runUuid: string,
  params?: { limit?: number; offset?: number; sort?: string; direction?: 'asc' | 'desc' },
): Promise<ReplayTradesResponse> => {
  const response = await apiClient.get(`/replay/runs/${runUuid}/trades`, { params });
  return response.data;
};

export const fetchReplayAnalytics = async (runUuid: string): Promise<ReplayMetrics> => {
  const response = await apiClient.get(`/replay/runs/${runUuid}/analytics`);
  return response.data;
};

export const compareReplayRuns = async (ids: string[]): Promise<ReplayCompareResponse> => {
  const response = await apiClient.get('/replay/runs/compare', { params: { ids: ids.join(',') } });
  return response.data;
};

export const useReplayRuns = (params?: ReplayRunListParams) =>
  useQuery({
    queryKey: ['replay', 'runs', params],
    queryFn: () => fetchReplayRuns(params),
    refetchInterval: 15_000,
  });

export const useReplayRun = (uuid?: string | null) =>
  useQuery({
    queryKey: ['replay', 'run', uuid],
    queryFn: () => fetchReplayRun(uuid as string),
    enabled: Boolean(uuid),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === 'queued' || status === 'running' ? 5_000 : false;
    },
  });

export const useReplayTrades = (runUuid?: string | null, sort = 'signal_date', direction: 'asc' | 'desc' = 'desc') =>
  useQuery({
    queryKey: ['replay', 'trades', runUuid, sort, direction],
    queryFn: () => fetchReplayTrades(runUuid as string, { limit: 250, sort, direction }),
    enabled: Boolean(runUuid),
  });

export const useReplayAnalytics = (runUuid?: string | null) =>
  useQuery({
    queryKey: ['replay', 'analytics', runUuid],
    queryFn: () => fetchReplayAnalytics(runUuid as string),
    enabled: Boolean(runUuid),
  });

export const useCreateReplayRun = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: createReplayRun,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['replay', 'runs'] });
    },
  });
};

export const useCompareReplayRuns = () =>
  useMutation({
    mutationFn: compareReplayRuns,
  });
