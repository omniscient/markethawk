import { apiClient } from '../client';
import type { ScannerConfig, MarketStats, PreMarketMoversResponse } from './types';

export const fetchScannerConfigs = async (): Promise<ScannerConfig[]> => {
  const response = await apiClient.get('/scanner/configs');
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
