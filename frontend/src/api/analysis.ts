import { apiClient } from './client';

export interface CorrelationResponse {
  run_id: number;
  scanner_type: string | null;
  event_count: number;
  completed_at: string;
  features: string[];
  intervals: string[];
  pearson: number[][];
  spearman: number[][];
}

export interface FeatureWeight {
  feature: string;
  interval: string;
  shap_importance: number;
  rank: number;
}

export interface ClusterReturnInterval {
  median_pct: number;
  win_rate: number;
  sharpe: number;
  n: number;
}

export interface ClusterSummary {
  id: number;
  label: string;
  event_count: number;
  centroid: Record<string, number>;
  return_profile: Record<string, ClusterReturnInterval>;
}

export interface LatestAnalysisResponse {
  run_id: number;
  completed_at: string;
  feature_weights: FeatureWeight[];
  clusters: ClusterSummary[];
}

export interface AnalysisTriggerResponse {
  task_id: string;
}

export async function fetchCorrelations(scannerType?: string): Promise<CorrelationResponse> {
  const params = scannerType ? `?scanner_type=${encodeURIComponent(scannerType)}` : '';
  const response = await apiClient.get<CorrelationResponse>(`/outcomes/correlations${params}`);
  return response.data;
}

export async function fetchLatestAnalysis(): Promise<LatestAnalysisResponse> {
  const response = await apiClient.get<LatestAnalysisResponse>('/outcomes/analysis/latest');
  return response.data;
}

export async function triggerAnalysis(
  scannerType?: string,
  k?: number,
): Promise<AnalysisTriggerResponse> {
  const params = new URLSearchParams();
  if (scannerType) params.append('scanner_type', scannerType);
  if (k) params.append('k', String(k));
  const query = params.toString() ? `?${params.toString()}` : '';
  const response = await apiClient.post<AnalysisTriggerResponse>(`/outcomes/analyze${query}`);
  return response.data;
}
