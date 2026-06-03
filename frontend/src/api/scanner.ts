import { apiClient, wsUrl } from './client';

// ---- Types ---------------------------------------------------------------- //

export interface ScannerEvent {
  id: number;
  uuid: string;
  ticker: string;
  event_date: string;
  scanner_type: string;
  
  summary?: string;
  severity: 'low' | 'medium' | 'high';
  
  previous_close?: number;
  opening_price?: number;
  closing_price?: number;

  signal_quality_score?: number | null;

  indicators: Record<string, unknown>;
  criteria_met: Record<string, unknown>;
  metadata: Record<string, unknown>;
  
  created_at: string;
  updated_at: string;
  latest_review?: SignalReview | null;
}

export interface SignalReview {
  id: number;
  scanner_event_id: number;
  verdict: 'confirmed' | 'rejected' | 'enhanced' | 'uncertain';
  reject_reason: string | null;
  notes: string | null;
  enhance_suggestion: Record<string, unknown> | null;
  reviewed_at: string;
  reviewed_by: string | null;
}

export type RejectionReason = 'too_late' | 'noise' | 'stale_data' | 'split_artifact';

export interface SignalReviewStats {
  total_events: number;
  reviewed_count: number;
  acceptance_rate: number;
  by_scanner_type: Array<{
    scanner_type: string;
    total: number;
    confirmed: number;
    rejected: number;
    uncertain: number;
    enhanced: number;
  }>;
  top_rejection_reasons: Array<{ reason: string; count: number }>;
}

// Backward compatibility alias during transition
export type VolumeEvent = ScannerEvent;

export interface ScannerConfig {
  id: number;
  uuid: string;
  name: string;
  description: string;
  scanner_type: string;
  parameters: Record<string, unknown>;
  criteria: Record<string, unknown>[];
  is_active: boolean;
  run_frequency: string;
  last_run: string | null;
  next_run: string | null;
}

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

export interface ScannerRunRequest {
  universe_id?: number;
  tickers?: string[];
  scanner_type: string;
  dry_run?: boolean;
  start_date?: string; // ISO date "YYYY-MM-DD"
  end_date?: string;
}

export interface ScannerDiagnostics {
  tickers?: number;
  days?: number;
  start_date?: string;
  end_date?: string;
  no_data?: number;
  no_prior_close?: number;
  no_baseline?: number;
  evaluated?: number;
  fired_pre?: number;
  fired_post?: number;
  errors?: number;
}

export interface ScannerRunResponse {
  scan_id: string;
  status: string;
  stocks_scanned: number;
  events_detected: number;
  execution_time_ms: number;
  scanner_type: string;
  events?: ScannerEvent[];
  error_message?: string;
  created_at?: string;
  scan_start_date?: string;
  scan_end_date?: string;
  diagnostics?: ScannerDiagnostics;
}

export interface MarketStats {
  activeAlerts: number;
  avgVolumeSpike: number;
  totalEvents: number;
  todayEvents: number;
}

export interface PreMarketMover {
  ticker: string;
  name: string | null;
  price: number;
  change_percent: number;
  change_value: number;
  volume: number;
  prev_close: number;
  sector?: string;
  market_cap?: number;
}

export interface PreMarketMoversResponse {
  status: string;
  movers: PreMarketMover[];
  timestamp: string;
}

export interface StorageStats {
  scanner: { bytes: number; formatted: string };
  historical: { bytes: number; formatted: string };
  settings: { bytes: number; formatted: string };
  total: { bytes: number; formatted: string };
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

// ---- Scanner -------------------------------------------------------------- //

export const fetchScannerResults = async (params?: {
  ticker?: string;
  scanner_type?: string;
  event_type?: string; // Kept for backward compatibility with existing component states
  universe_id?: number | null;
  sort_by?: string;
  sort_order?: 'asc' | 'desc';
  limit?: number;
  offset?: number;
}): Promise<ScannerEvent[]> => {
  const response = await apiClient.get('/scanner/results', { params });
  return response.data;
};

export interface ScannerRunAsyncResponse {
  scan_id: string;
  task_id: string;
  started_at: string;
  scanner_type: string;
  universe_id?: number;
  scan_start_date?: string;
  scan_end_date?: string;
  status: 'queued';
}

export interface ScannerRunStatus {
  scan_id: string;
  task_id?: string;
  status: 'queued' | 'running' | 'completed' | 'failed' | 'cancelled';
  scanner_type: string;
  universe_id?: number;
  scan_start_date?: string;
  scan_end_date?: string;
  stocks_scanned: number;
  events_detected: number;
  execution_time_ms: number;
  error_message?: string | null;
  started_at?: string;
  progress?: ScannerDiagnostics & {
    day_index?: number;
    total_days?: number;
    tickers?: number;
    events_detected?: number;
    [k: string]: unknown;
  } | null;
}

/** Enqueue a scan. Returns immediately with task/scan IDs; progress arrives via WS. */
export const runScanner = async (request: ScannerRunRequest): Promise<ScannerRunAsyncResponse> => {
  const response = await apiClient.post('/scanner/run', request);
  return response.data;
};

export const fetchScanStatus = async (scanId: string): Promise<ScannerRunStatus> => {
  const response = await apiClient.get(`/scanner/runs/${scanId}/status`);
  return response.data;
};

export const cancelScan = async (scanId: string): Promise<{ status: string; scan_id: string }> => {
  const response = await apiClient.post(`/scanner/runs/${scanId}/cancel`);
  return response.data;
};

/** Open a WebSocket that streams progress for one running scan task. */
export const createScanRunWebSocket = (taskId: string): WebSocket | null => {
  try {
    return new WebSocket(wsUrl(`/scanner/ws/runs/${taskId}`));
  } catch (e) {
    console.error('[WS] Failed to open scanner run WS', e);
    return null;
  }
};

export interface ScannerRangeRequest {
  ticker: string;
  scanner_types: string[];
  start_date: string;   // ISO date string, e.g. "2025-01-01"
  end_date: string;
  fetch_missing_data: boolean;
}

export interface ScannerRangeResponse {
  task_id: string;
  status: 'queued';
}

export const runScannerRange = async (
  request: ScannerRangeRequest
): Promise<ScannerRangeResponse> => {
  const response = await apiClient.post('/scanner/run-range', request);
  return response.data;
};

export interface ScannerLastRunInfo {
  timestamp: string | null;
  status: string;
  events_detected: number;
  duration_ms: number;
}

export interface ScannerSparklinePoint {
  created_at: string | null;
  events_detected: number;
  status: string;
}

export interface ScannerStatusBlock {
  scanner_type: string;
  universe_id: number | null;
  last_run: ScannerLastRunInfo | null;
  next_run: string | null;
  total_events: number;
  success_rate: number | null;
  avg_events_per_scan: number | null;
  sparkline: ScannerSparklinePoint[];
}

export const fetchScanStatusBlock = async (
  scannerType: string,
  universeId?: number | null,
): Promise<ScannerStatusBlock> => {
  const params: Record<string, unknown> = { scanner_type: scannerType };
  if (universeId != null) params.universe_id = universeId;
  const response = await apiClient.get('/scanner/scan-status-block', { params });
  return response.data;
};

export const fetchScannerConfigs = async (): Promise<ScannerConfig[]> => {
  const response = await apiClient.get('/scanner/configs');
  return response.data;
};

export const fetchScannerHistory = async (limit: number = 20): Promise<ScannerRunResponse[]> => {
  const response = await apiClient.get('/scanner/history', { params: { limit } });
  return response.data;
};

export const submitReview = async (
  eventUuid: string,
  payload: { verdict: string; reject_reason?: string | null; notes?: string | null },
): Promise<SignalReview> => {
  const response = await apiClient.post(`/scanner/events/${eventUuid}/review`, payload);
  return response.data;
};

export const fetchReviewStats = async (params?: {
  scanner_type?: string;
  start_date?: string;
  end_date?: string;
}): Promise<SignalReviewStats> => {
  const response = await apiClient.get('/scanner/reviews/stats', { params });
  return response.data;
};

export const fetchMarketStats = async (): Promise<MarketStats> => {
  const response = await apiClient.get('/scanner/stats');
  return response.data;
};

export const fetchPreMarketMovers = async (params?: {
  min_volume?: number;
  limit?: number;
}): Promise<PreMarketMoversResponse> => {
  const response = await apiClient.get('/scanner/movers/pre-market', { params });
  return response.data;
};

// ---- Universe ------------------------------------------------------------- //

export interface UniverseSummary {
  id: number;
  name: string;
}

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

export interface TaskEnqueueResponse {
  status: string;
  message?: string;
  task_id?: string;
}

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

export interface ExportAggregatesOptions {
  tickers: string[];
  timespan: string;
  multiplier: number;
  from_date?: string;
  to_date?: string;
  zip_format: 'per_ticker' | 'single_csv';
}

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

// ---- Stocks --------------------------------------------------------------- //

export interface OHLCVRow {
  Date: string;
  Open: number;
  High: number;
  Low: number;
  Close: number;
  Volume?: number;
  vwap?: number;
  vwap_intraday?: number;
  marker_type?: string;
  contract_month?: string;
  transactions?: number;
}

export const fetchHistoricalData = async (
  ticker: string,
  period: string = '30d',
  timespan: string = 'day',
  multiplier: number = 1,
): Promise<{
  ticker: string;
  period: string;
  timespan: string;
  multiplier: number;
  data_points: number;
  data: OHLCVRow[];
  format?: 'row' | 'columnar';
}> => {
  const response = await apiClient.get(`/stocks/historical/${ticker}`, {
    params: { period, timespan, multiplier },
  });

  const { data, format } = response.data;
  
  // 1. Handle the new globally-defaulted High Performance 'columnar_compact' format.
  // Reconstructs the row-oriented array and restores full key names so components don't break.
  if (format === 'columnar_compact' && !Array.isArray(data)) {
    const mapping: Record<string, string> = {
      t: 'Date', o: 'Open', h: 'High', l: 'Low', c: 'Close',
      v: 'Volume', w: 'vwap', n: 'transactions', wi: 'vwap_intraday',
      mt: 'marker_type', cm: 'contract_month'
    };

    const keys = Object.keys(data);
    const rowCount = data[keys[0]]?.length || 0;
    const records = new Array(rowCount);

    for (let i = 0; i < rowCount; i++) {
      const row: Record<string, string | number | null> = {};
      for (const key of keys) {
        const fullKey = mapping[key] || key;
        let value = data[key][i];
        
        // Convert Unix timestamp (seconds) back to ISO string if it's the Date field
        if (key === 't') {
          value = new Date(value * 1000).toISOString();
        }
        
        row[fullKey] = value;
      }
      records[i] = row;
    }
    
    return { ...response.data, data: records };
  }

  // 2. Backward compatibility for the legacy 'columnar' format.
  if (format === 'columnar' && !Array.isArray(data)) {
    const keys = Object.keys(data);
    const rowCount = data[keys[0]]?.length || 0;
    const records = new Array(rowCount);
    
    for (let i = 0; i < rowCount; i++) {
       const row: Record<string, string | number | null> = {};
       for (const key of keys) {
         row[key] = data[key][i];
       }
       records[i] = row;
    }
    
    return { ...response.data, data: records };
  }

  return response.data;
};

// ---- Providers ------------------------------------------------------------ //

export interface DataProvider {
  name: string;
  classes: string[];
  available: boolean;
  status_message?: string;
}

export const fetchProviders = async (): Promise<{ available: DataProvider[] }> => {
  const response = await apiClient.get('/futures/providers');
  return response.data;
};

// ---- System --------------------------------------------------------------- //

export const fetchStorageStats = async (): Promise<StorageStats> => {
  const response = await apiClient.get('/system/storage');
  return response.data;
};

// ---- WebSocket (non-Axios) ------------------------------------------------ //

/** Create a raw WebSocket for real-time scanner updates. */
export const createScannerWebSocket = (): WebSocket | null => {
  try {
    const ws = new WebSocket(wsUrl('/ws/scanner'));
    ws.onopen = () => console.log('[WS] Scanner connected');
    ws.onclose = () => console.log('[WS] Scanner disconnected');
    ws.onerror = (e) => console.error('[WS] Scanner error', e);
    return ws;
  } catch (e) {
    console.error('[WS] Failed to create connection', e);
    return null;
  }
};

// ---- Event History -------------------------------------------------------- //

export interface ClearEventsResponse {
  ticker: string;
  deleted_count: number;
}

export const clearScannerEvents = async (ticker: string): Promise<ClearEventsResponse> => {
  const response = await apiClient.delete(`/scanner/events/${encodeURIComponent(ticker)}`);
  return response.data;
};

// ---- Error Helpers -------------------------------------------------------- //

/**
 * Extract a human-readable message from an Axios error.
 * Callers can still use this for local inline error display.
 */
export interface SignalQualityDecile {
  decile: string;
  count: number;
  avg_eod_pct: number | null;
  follow_through_rate: number | null;
}

export interface SignalQualityDistributionResponse {
  deciles: SignalQualityDecile[];
  signal_ranker_version: string;
}

export const getSignalQualityDistribution = async (params: {
  scanner_type?: string;
  start_date?: string;
  end_date?: string;
} = {}): Promise<SignalQualityDistributionResponse> => {
  const query = new URLSearchParams();
  if (params.scanner_type) query.append('scanner_type', params.scanner_type);
  if (params.start_date) query.append('start_date', params.start_date);
  if (params.end_date) query.append('end_date', params.end_date);
  const response = await apiClient.get<SignalQualityDistributionResponse>(
    `/scanner/signal-quality-distribution?${query.toString()}`
  );
  return response.data;
};

export const handleApiError = (error: unknown): string => {
  if (error && typeof error === 'object' && 'response' in error) {
    const e = error as { response: { data?: { detail?: string }; statusText: string } };
    return e.response.data?.detail ?? e.response.statusText;
  }
  if (error && typeof error === 'object' && 'request' in error) {
    return 'Unable to connect to server';
  }
  if (error instanceof Error) {
    return error.message;
  }
  return 'An unexpected error occurred';
};