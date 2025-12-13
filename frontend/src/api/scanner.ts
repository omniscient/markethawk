import axios from 'axios';

const API_BASE_URL = '/api';

// API client instance
const apiClient = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
});

// Interfaces
export interface VolumeEvent {
  id: number;
  uuid: string;
  ticker: string;
  event_date: string;
  event_type: string;
  pre_market_volume: number;
  avg_volume_20d: number;
  relative_volume: number;
  volume_spike_ratio: number;
  price_gap_pct: number;
  criteria_met: Record<string, any>;
  created_at: string;
}

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
}

export interface MarketStats {
  activeAlerts: number;
  avgVolumeSpike: number;
  totalEvents: number;
  todayEvents: number;
}

// API functions

export const fetchScannerResults = async (params?: {
  ticker?: string;
  event_type?: string;
  limit?: number;
  offset?: number;
}): Promise<VolumeEvent[]> => {
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

export const updateStockUniverse = async (id: number, universe: {
  name?: string;
  description?: string;
  criteria?: Record<string, any>;
  is_active?: boolean;
}): Promise<StockUniverse> => {
  const response = await apiClient.put(`/universe/${id}`, universe);
  return response.data;
};

export interface MonitoredStock {
  id: number;
  ticker: string;
  company_name?: string;
  sector?: string;
  market_cap?: number;
  added_date: string;
  is_active: boolean;
}

export interface RefreshUniverseResponse {
  status: string;
  scanned: number;
  added: number;
  message: string;
}

export const refreshUniverseStocks = async (id: number): Promise<RefreshUniverseResponse> => {
  const response = await apiClient.post(`/universe/${id}/refresh`);
  return response.data;
};

export const fetchUniverseStocks = async (id: number): Promise<MonitoredStock[]> => {
  const response = await apiClient.get(`/universe/${id}/stocks`);
  return response.data;
};

export const fetchHistoricalData = async (
  ticker: string,
  period: string = '30d'
): Promise<{
  ticker: string;
  period: string;
  data_points: number;
  data: any[];
}> => {
  const response = await apiClient.get(`/stocks/historical/${ticker}`, {
    params: { period }
  });
  return response.data;
};

export const fetchMarketStats = async (): Promise<MarketStats> => {
  // Mock data for now - will be replaced with real API call
  return {
    activeAlerts: 8,
    avgVolumeSpike: 5.2,
    totalEvents: 156,
    todayEvents: 23
  };
};

// WebSocket connection for real-time updates (future implementation)
export const createScannerWebSocket = (): WebSocket | null => {
  try {
    const ws = new WebSocket(`ws://localhost:8000/ws/scanner`);

    ws.onopen = () => {
      console.log('Scanner WebSocket connected');
    };

    ws.onclose = () => {
      console.log('Scanner WebSocket disconnected');
    };

    ws.onerror = (error) => {
      console.error('Scanner WebSocket error:', error);
    };

    return ws;
  } catch (error) {
    console.error('Failed to create WebSocket connection:', error);
    return null;
  }
};

// Error handling wrapper
export const handleApiError = (error: any): string => {
  if (error.response) {
    // Server responded with error
    return error.response.data?.detail || error.response.statusText;
  } else if (error.request) {
    // Request made but no response
    return 'Unable to connect to server';
  } else {
    // Something else happened
    return error.message || 'An error occurred';
  }
};