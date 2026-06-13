import { apiClient } from '../client';
import type { OHLCVRow, StorageStats, DataProvider } from './types';

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

  // Handle the new globally-defaulted High Performance 'columnar_compact' format.
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

  // Backward compatibility for the legacy 'columnar' format.
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

export const fetchStorageStats = async (): Promise<StorageStats> => {
  const response = await apiClient.get('/system/storage');
  return response.data;
};

export const fetchProviders = async (): Promise<{ available: DataProvider[] }> => {
  const response = await apiClient.get('/futures/providers');
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
