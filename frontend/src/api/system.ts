import { apiClient } from './client';

// ---- Types ---------------------------------------------------------------- //

export interface SystemInfo {
  name: string;
  version: string;
  data_mode: 'live' | 'delayed';
  log_level: string;
}

export interface StorageStats {
  scanner: { bytes: number; formatted: string };
  historical: { bytes: number; formatted: string };
  settings: { bytes: number; formatted: string };
  total: { bytes: number; formatted: string };
}

// ---- API calls ------------------------------------------------------------ //

export const getSystemInfo = async (): Promise<SystemInfo> => {
  const response = await apiClient.get('/system/info');
  return response.data;
};

export const getStorageStats = async (): Promise<StorageStats> => {
  const response = await apiClient.get('/system/storage');
  return response.data;
};
