import axios from 'axios';

const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

export interface SystemInfo {
  name: string;
  version: string;
  data_mode: 'live' | 'delayed';
  log_level: string;
}

export const getSystemInfo = async (): Promise<SystemInfo> => {
  const response = await axios.get(`${API_BASE_URL}/api/system/info`);
  return response.data;
};

export const getStorageStats = async () => {
  const response = await axios.get(`${API_BASE_URL}/api/system/storage`);
  return response.data;
};
