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

export const getSystemConfig = async (): Promise<Record<string, string>> => {
  const response = await apiClient.get('/system/config');
  return response.data;
};

export const updateSystemConfig = async (patch: Record<string, string | number>): Promise<Record<string, string>> => {
  const response = await apiClient.patch('/system/config', patch);
  return response.data;
};
