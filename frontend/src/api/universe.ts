import { apiClient } from './client';

// ---- Types ---------------------------------------------------------------- //

export interface StockUniverse {
  id: number;
  uuid: string;
  name: string;
  description: string;
  criteria: Record<string, unknown>;
  created_at: string;
  is_active: boolean;
  ticker_count?: number;
  aggregate_count?: number;
  min_aggregate_date?: string;
  max_aggregate_date?: string;
  available_timespans?: string[];
  stats_refreshed_at?: string;
}

export interface UniverseSyncStatus {
  is_syncing: boolean;
  total: number;
  pending: number;
  success: number;
  failed: number;
  started_at?: string;
  timespan?: string;
  from_date?: string;
  to_date?: string;
}

export interface MonitoredStock {
  id: number;
  ticker: string;
  company_name?: string;
  sector?: string;
  market_cap?: number;
  added_date: string;
  is_active: boolean;
  asset_class?: string;
}

export interface RefreshUniverseResponse {
  status: string;
  scanned: number;
  added: number;
  message: string;
}

export interface SyncAggregatesOptions {
  from_date: string;
  to_date: string;
  multiplier?: number;
  timespan?: string;
  adjusted?: boolean;
  sort?: string;
  limit?: number;
}

export interface UniverseSummary {
  id: number;
  name: string;
}

export interface TaskEnqueueResponse {
  status: string;
  message?: string;
  task_id?: string;
}

export interface ExportAggregatesOptions {
  tickers: string[];
  timespan: string;
  multiplier: number;
  from_date?: string;
  to_date?: string;
  zip_format: 'per_ticker' | 'single_csv';
}

// ---- Quality Report Types ------------------------------------------------- //

export interface QualityGapEntry {
  from: string;
  to: string;
  duration_hours: number;
  missing_bars: number;
}

export interface CoveragePartialDay {
  date: string;
  actual_bars: number;
  expected_bars: number;
  shortfall: number;
}

export interface CoverageDetail {
  p90_bars_per_day: number;
  full_day_count: number;
  stub_day_count: number;
  partial_day_count: number;
  holiday_day_count: number;
  partial_days: CoveragePartialDay[];
}

export interface QualityTickerResult {
  ticker: string;
  asset_class: string;
  timespan: string | null;
  multiplier: number | null;
  grade: string;
  score: number;
  actual_bars: number;
  expected_bars: number;
  coverage_pct: number;
  integrity_pct: number;
  continuity_score: number;
  gap_count: number;
  bad_bar_count: number;
  duplicate_count: number;
  first_bar: string | null;
  last_bar: string | null;
  gaps: QualityGapEntry[];
  coverage_detail: CoverageDetail | null;
}

export interface NormalizationProgress {
  status: 'pending' | 'running' | 'complete' | 'error';
  total_combos: number;
  processed_combos: string[];
  fixes_applied: {
    deduped: number;
    gaps_filled: number;
    backfilled: number;
    [key: string]: number;
  };
  errors: { combo: string; fix: string; error: string }[];
}

export interface QualityReport {
  universe_id: number;
  status: 'pending' | 'running' | 'complete' | 'error';
  overall_grade: string | null;
  overall_score: number | null;
  ticker_count: number | null;
  started_at: string | null;
  generated_at: string | null;
  error_message: string | null;
  report_data: {
    overall_score: number;
    overall_grade: string;
    generated_at: string;
    ticker_count: number;
    analyzed_count: number;
    timespans_analyzed: string[];
    grade_distribution: Record<string, number>;
    tickers: QualityTickerResult[];
  } | null;
  normalization_status: 'pending' | 'running' | 'complete' | 'error' | null;
  normalization_data: NormalizationProgress | null;
}

// ---- Data Health ---------------------------------------------------------- //

export interface DataHealthResponse {
  degraded: boolean;
  stale_pct: number;
  gapped_pct: number;
  worst_staleness_hours: number;
  grade: string;
}

export const getDataHealth = async (universeId: number): Promise<DataHealthResponse> => {
  const response = await apiClient.get(`/universe/${universeId}/data-health`);
  return response.data;
};

// ---- Universe CRUD -------------------------------------------------------- //

export const fetchUniversesForTicker = async (ticker: string): Promise<UniverseSummary[]> => {
  const response = await apiClient.get(`/universe/by-ticker/${ticker}`);
  return response.data;
};

export const fetchStockUniverses = async (params?: { include_stats?: boolean }): Promise<StockUniverse[]> => {
  const response = await apiClient.get('/universe/list', { params });
  return response.data;
};

export const refreshUniverseStats = async (id: number): Promise<StockUniverse> => {
  const response = await apiClient.post(`/universe/${id}/refresh-stats`);
  return response.data;
};

export const createStockUniverse = async (universe: {
  name: string;
  description?: string;
  criteria: Record<string, unknown>;
}): Promise<StockUniverse> => {
  const response = await apiClient.post('/universe/create', universe);
  return response.data;
};

export const deleteStockUniverse = async (id: number): Promise<void> => {
  await apiClient.delete(`/universe/${id}`);
};

export const updateStockUniverse = async (
  id: number,
  universe: {
    name?: string;
    description?: string;
    criteria?: Record<string, unknown>;
    is_active?: boolean;
  },
): Promise<StockUniverse> => {
  const response = await apiClient.put(`/universe/${id}`, universe);
  return response.data;
};

// ---- Universe Sync -------------------------------------------------------- //

export const syncFundamentals = async (delay: number = 15.0): Promise<TaskEnqueueResponse> => {
  const response = await apiClient.post('/universe/sync/fundamentals', null, { params: { delay } });
  return response.data;
};

export const syncMetrics = async (): Promise<TaskEnqueueResponse> => {
  const response = await apiClient.post('/universe/sync/metrics');
  return response.data;
};

export const syncTickerDetails = async (delay: number = 15.0): Promise<TaskEnqueueResponse> => {
  const response = await apiClient.post('/universe/sync/details', null, { params: { delay } });
  return response.data;
};

export const stopSync = async (): Promise<TaskEnqueueResponse> => {
  const response = await apiClient.post('/universe/sync/stop');
  return response.data;
};

export const refreshUniverse = async (id: number): Promise<RefreshUniverseResponse> => {
  const response = await apiClient.post(`/universe/${id}/refresh`);
  return response.data;
};

export const fetchUniverseStocks = async (id: number): Promise<MonitoredStock[]> => {
  const response = await apiClient.get(`/universe/${id}/stocks`);
  return response.data;
};

export const syncMissingAggregates = async (id: number): Promise<{ status: string; queued?: number; message?: string; summary?: string[] }> => {
  const response = await apiClient.post(`/universe/${id}/sync-missing`);
  return response.data;
};

export const fetchUniverseSyncStatus = async (id: number): Promise<UniverseSyncStatus> => {
  const response = await apiClient.get(`/universe/${id}/sync-status`);
  return response.data;
};

export const syncUniverseAggregates = async (
  id: number,
  options: SyncAggregatesOptions,
): Promise<{ status: string; message: string }> => {
  const response = await apiClient.post(`/universe/${id}/sync-aggregates`, null, {
    params: {
      from_date: options.from_date,
      to_date: options.to_date,
      multiplier: options.multiplier ?? 1,
      timespan: options.timespan ?? 'minute',
      adjusted: options.adjusted ?? true,
      sort: options.sort ?? 'asc',
      limit: options.limit ?? 50000,
    },
  });
  return response.data;
};

export const exportUniverseAggregates = async (
  id: number,
  options: ExportAggregatesOptions,
): Promise<Blob> => {
  const response = await apiClient.post(
    `/universe/${id}/export-aggregates`,
    options,
    { responseType: 'blob' },
  );
  return response.data;
};

// ---- Quality Analysis ----------------------------------------------------- //

export const deleteTickerAggregates = async (
  universeId: number,
  payload: { ticker: string; asset_class: string; timespan?: string | null; multiplier?: number | null },
): Promise<{ deleted_bars: number; removed_from_universe: boolean }> => {
  const response = await apiClient.delete(`/universe/${universeId}/aggregates`, { data: payload });
  return response.data;
};

export const triggerQualityAnalysis = async (id: number): Promise<{ status: string; message: string }> => {
  const response = await apiClient.post(`/universe/${id}/analyze-quality`);
  return response.data;
};

export const triggerNormalization = async (id: number, target_tickers?: string[]): Promise<{ status: string; resume: boolean; message: string }> => {
  const response = await apiClient.post(`/universe/${id}/normalize`, target_tickers ? { target_tickers } : {});
  return response.data;
};

export const fetchQualityReport = async (id: number): Promise<QualityReport | null> => {
  const response = await apiClient.get(`/universe/${id}/quality-report`);
  return response.data;
};
