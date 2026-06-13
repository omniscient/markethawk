import { apiClient } from '../client';
import type {
  ScannerRunRequest,
  ScannerRunAsyncResponse,
  ScannerRunStatus,
  ScannerRangeRequest,
  ScannerRangeResponse,
  ScannerRunResponse,
  ScannerStatusBlock,
} from './types';

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

export const runScannerRange = async (
  request: ScannerRangeRequest
): Promise<ScannerRangeResponse> => {
  const response = await apiClient.post('/scanner/run-range', request);
  return response.data;
};

export const fetchScannerHistory = async (limit: number = 20): Promise<ScannerRunResponse[]> => {
  const response = await apiClient.get('/scanner/history', { params: { limit } });
  return response.data;
};

export const fetchScanStatusBlock = async (
  scannerType: string,
  universeId?: number | null,
): Promise<ScannerStatusBlock> => {
  const params: Record<string, unknown> = { scanner_type: scannerType };
  if (universeId != null) params.universe_id = universeId;
  const response = await apiClient.get('/scanner/scan-status-block', { params });
  return response.data;
};
