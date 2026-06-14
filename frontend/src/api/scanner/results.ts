import { apiClient } from '../client';
import type { ScannerEvent, ClearEventsResponse } from './types';

export const fetchScannerResults = async (params?: {
  ticker?: string;
  scanner_type?: string;
  event_type?: string;
  universe_id?: number | null;
  sort_by?: string;
  sort_order?: 'asc' | 'desc';
  limit?: number;
  offset?: number;
}): Promise<ScannerEvent[]> => {
  const response = await apiClient.get('/scanner/results', { params });
  return response.data;
};

export const clearScannerEvents = async (ticker: string): Promise<ClearEventsResponse> => {
  const response = await apiClient.delete(`/scanner/events/${encodeURIComponent(ticker)}`);
  return response.data;
};
