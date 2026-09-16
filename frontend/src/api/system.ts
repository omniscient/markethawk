import { apiClient } from './client';

// ---- Types ---------------------------------------------------------------- //

export interface SystemInfo {
  name: string;
  version: string;
  data_mode: 'live' | 'delayed';
  log_level: string;
}

export type MarketStatus = 'pre_market' | 'open' | 'post_market' | 'closed';

export interface SystemStatus {
  market_status: MarketStatus;
  last_scan_at: string | null;
  ibkr_reachable: boolean;
  ibkr_host: string;
  ibkr_port: number;
}

export interface StorageStats {
  scanner: { bytes: number; formatted: string };
  historical: { bytes: number; formatted: string };
  settings: { bytes: number; formatted: string };
  total: { bytes: number; formatted: string };
}

export interface LLMStatus {
  enabled: boolean;
  provider_state: 'disabled' | 'degraded' | 'available';
  allowed_features: string[];
  limits: {
    timeout_seconds: number;
    max_tokens: number;
    max_cost_usd_per_call: number;
  };
  metrics: Record<string, unknown>;
}

// ---- API calls ------------------------------------------------------------ //

export const getSystemInfo = async (): Promise<SystemInfo> => {
  const response = await apiClient.get('/system/info');
  return response.data;
};

export const getSystemStatus = async (): Promise<SystemStatus> => {
  const response = await apiClient.get('/system/status');
  return response.data;
};

export const getStorageStats = async (): Promise<StorageStats> => {
  const response = await apiClient.get('/system/storage');
  return response.data;
};

export const getLLMStatus = async (): Promise<LLMStatus> => {
  const response = await apiClient.get('/system/llm-status');
  return response.data;
};

export const getSystemConfig = async (): Promise<Record<string, string>> => {
  const response = await apiClient.get('/system/config');
  return response.data;
};

export const updateSystemConfig = async (patch: Record<string, string | number>): Promise<Record<string, string>> => {
  const response = await apiClient.patch('/system/config', patch);
  return response.data;
};
