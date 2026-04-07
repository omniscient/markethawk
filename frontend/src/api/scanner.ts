import { apiClient } from './client';

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
  
  indicators: Record<string, any>;
  criteria_met: Record<string, any>;
  metadata: Record<string, any>;
  
  created_at: string;
  updated_at: string;
}

// Backward compatibility alias during transition
export type VolumeEvent = ScannerEvent;

export interface ScannerConfig {
  id: number;
  uuid: string;
  name: string;
  description: string;
  scanner_type: string;
  parameters: Record<string, any>;
  criteria: Record<string, any>[];
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
  criteria: Record<string, any>;
  created_at: string;
  is_active: boolean;
  ticker_count?: number;
  aggregate_count?: number;
  min_aggregate_date?: string;
  max_aggregate_date?: string;
  available_timespans?: string[];
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

export const runScanner = async (request: ScannerRunRequest): Promise<ScannerRunResponse> => {
  const response = await apiClient.post('/scanner/run', request);
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

export const fetchStockUniverses = async (): Promise<StockUniverse[]> => {
  const response = await apiClient.get('/universe/list');
  return response.data;
};

export const createStockUniverse = async (universe: {
  name: string;
  description?: string;
  criteria: Record<string, any>;
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
    criteria?: Record<string, any>;
    is_active?: boolean;
  },
): Promise<StockUniverse> => {
  const response = await apiClient.put(`/universe/${id}`, universe);
  return response.data;
};

export const syncFundamentals = async (delay: number = 15.0): Promise<any> => {
  const response = await apiClient.post('/universe/sync/fundamentals', null, { params: { delay } });
  return response.data;
};

export const syncMetrics = async (): Promise<any> => {
  const response = await apiClient.post('/universe/sync/metrics');
  return response.data;
};

export const syncTickerDetails = async (delay: number = 15.0): Promise<any> => {
  const response = await apiClient.post('/universe/sync/details', null, { params: { delay } });
  return response.data;
};

export const stopSync = async (): Promise<any> => {
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

// ---- Stocks --------------------------------------------------------------- //

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
  data: any[];
}> => {
  const response = await apiClient.get(`/stocks/historical/${ticker}`, {
    params: { period, timespan, multiplier },
  });
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
    const wsBase = import.meta.env.VITE_WS_URL ?? 'ws://localhost:8000';
    const ws = new WebSocket(`${wsBase}/ws/scanner`);
    ws.onopen = () => console.log('[WS] Scanner connected');
    ws.onclose = () => console.log('[WS] Scanner disconnected');
    ws.onerror = (e) => console.error('[WS] Scanner error', e);
    return ws;
  } catch (e) {
    console.error('[WS] Failed to create connection', e);
    return null;
  }
};

// ---- Error Helpers -------------------------------------------------------- //

/**
 * Extract a human-readable message from an Axios error.
 * Callers can still use this for local inline error display.
 */
export const handleApiError = (error: any): string => {
  if (error.response) {
    return error.response.data?.detail ?? error.response.statusText;
  }
  if (error.request) {
    return 'Unable to connect to server';
  }
  return error.message ?? 'An unexpected error occurred';
};