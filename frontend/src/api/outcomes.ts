import { apiClient } from './client';

// ---- Types ---------------------------------------------------------------- //

export interface OutcomeSnapshot {
  id: number;
  scanner_event_id: number;
  interval_key: string;
  reference_price: number;
  snapshot_price: number | null;
  pct_change: number | null;
  high_since_signal: number | null;
  low_since_signal: number | null;
  volume_since_signal: number | null;
  captured_at: string | null;
  status: string;
}

export interface OutcomeSummary {
  id: number;
  scanner_event_id: number;
  reference_price: number;
  mfe_pct: number | null;
  mfe_time_minutes: number | null;
  mae_pct: number | null;
  mae_time_minutes: number | null;
  mfe_mae_ratio: number | null;
  r_multiple: number | null;
  eod_pct_change: number | null;
  follow_through: boolean | null;
  gap_filled: boolean | null;
  is_complete: boolean;
  completed_at: string | null;
}

export interface EventOutcome {
  summary: OutcomeSummary | null;
  snapshots: OutcomeSnapshot[];
}

export interface IntervalBreakdown {
  avg_pct: number;
  median_pct: number;
  stddev_pct: number;
  win_rate: number;
  sample_size: number;
}

export interface EdgeDecayPoint {
  period: string;
  win_rate: number;
  avg_mfe: number;
  avg_mae: number;
  sample_size: number;
}

export interface RejectReasonCount {
  reason: string;
  count: number;
}

export interface Scorecard {
  scanner_type: string;
  period: string;
  total_signals: number;
  complete_signals: number;
  win_rate_pct: number | null;
  avg_mfe_pct: number | null;
  avg_mae_pct: number | null;
  mfe_mae_ratio: number | null;
  avg_r_multiple: number | null;
  expectancy: number | null;
  profit_factor: number | null;
  follow_through_rate_pct: number | null;
  edge_decay: EdgeDecayPoint[];
  interval_breakdown: Record<string, IntervalBreakdown>;
  // Review-side fields (issue #303)
  precision_pct?: number | null;
  review_coverage_pct?: number | null;
  verdict_counts?: Record<string, number> | null;
  top_reject_reasons?: RejectReasonCount[];
  review_sample_n?: number;
}

export interface ReadinessCoverage {
  timespan: string;
  multiplier: number;
  required_from: string;
  required_to: string;
  available_from: string | null;
  available_to: string | null;
  is_ready: boolean;
}

export interface ReadinessReport {
  ticker: string;
  scanner_type: string;
  coverages: ReadinessCoverage[];
  is_ready: boolean;
  missing_summary: string;
}

export interface DistributionPoint {
  ticker: string;
  event_date: string;
  value: number;
  scanner_type: string;
  severity: string | null;
}

export interface BackfillRequest {
  scanner_type: string;
  start_date: string;
  end_date: string;
}

export interface BackfillResponse {
  snapshots_created: number;
  events_processed: number;
  scanner_type: string;
}

export interface SignalListItem {
  id: number;
  ticker: string;
  event_date: string;
  severity: string | null;
  summary: string | null;
  opening_price: number | null;
  previous_close: number | null;
  closing_price: number | null;
  reference_price: number | null;
  mfe_pct: number | null;
  mae_pct: number | null;
  eod_pct_change: number | null;
  follow_through: boolean | null;
  mfe_mae_ratio: number | null;
  is_complete: boolean | null;
}

export interface SignalListResponse {
  signals: SignalListItem[];
  total: number;
  limit: number;
  offset: number;
}

export interface ExplanationWarning {
  code: string;
  message: string;
}

export interface ExplanationTrait {
  trait_type: string;
  trait_key: string;
  trait_label: string;
  sample_size: number;
  event_ids: number[];
  win_rate_pct: number | null;
  follow_through_rate_pct: number | null;
  avg_mfe_pct: number | null;
  avg_mae_pct: number | null;
  win_rate_ci_95_pct: { lower: number | null; upper: number | null };
  warnings: ExplanationWarning[];
}

export interface ExplanationTraitPerformance {
  event_count: number;
  filters: {
    scanner_type: string | null;
    start_date: string | null;
    end_date: string | null;
    severity: string | null;
    min_sample_size: number;
  };
  traits: ExplanationTrait[];
}

export interface ExplanationArchetype {
  cluster_id: number;
  cluster_index: number;
  label: string;
  sample_size: number;
  event_ids: number[];
  centroid: Record<string, unknown>;
  return_profile: {
    sample_size?: number;
    win_rate_pct?: number | null;
    follow_through_rate_pct?: number | null;
    avg_mfe_pct?: number | null;
    avg_mae_pct?: number | null;
    avg_eod_pct_change?: number | null;
  };
  warnings: ExplanationWarning[];
}

export interface ExplanationArchetypeResponse {
  analysis_run_id: number | null;
  scanner_type: string;
  event_count: number;
  filters: {
    scanner_type: string;
    start_date: string | null;
    end_date: string | null;
    severity: string | null;
    min_sample_size: number;
  };
  warnings: ExplanationWarning[];
  archetypes: ExplanationArchetype[];
}

// ---- API Functions -------------------------------------------------------- //

export const fetchScorecard = async (params: {
  scanner_type: string;
  start_date?: string;
  end_date?: string;
  severity?: string;
}): Promise<Scorecard> => {
  const response = await apiClient.get(`/outcomes/scorecard/${params.scanner_type}`, {
    params: {
      start_date: params.start_date,
      end_date: params.end_date,
      severity: params.severity,
    },
  });
  return response.data;
};

export const fetchIntervals = async (
  scannerType: string,
  intervalKey?: string,
): Promise<Record<string, IntervalBreakdown>> => {
  const response = await apiClient.get(`/outcomes/intervals/${scannerType}`, {
    params: { interval_key: intervalKey },
  });
  return response.data;
};

export const fetchDistribution = async (
  scannerType: string,
  metric: string = 'mfe_pct',
): Promise<DistributionPoint[]> => {
  const response = await apiClient.get(`/outcomes/distribution/${scannerType}`, {
    params: { metric },
  });
  return response.data;
};

export const fetchEdgeDecay = async (
  scannerType: string,
  params?: { start_date?: string; end_date?: string; period?: string },
): Promise<EdgeDecayPoint[]> => {
  const response = await apiClient.get(`/outcomes/edge-decay/${scannerType}`, { params });
  return response.data;
};

export const fetchEventOutcome = async (eventId: number): Promise<EventOutcome> => {
  const response = await apiClient.get(`/outcomes/event/${eventId}`);
  return response.data;
};

export const fetchReadiness = async (
  ticker: string,
  scannerType: string,
): Promise<ReadinessReport> => {
  const response = await apiClient.get(`/outcomes/readiness/${ticker}`, {
    params: { scanner_type: scannerType },
  });
  return response.data;
};

export const fetchSignals = async (params: {
  scanner_type: string;
  start_date?: string;
  end_date?: string;
  severity?: string;
  sort_by?: string;
  sort_order?: string;
  limit?: number;
  offset?: number;
}): Promise<SignalListResponse> => {
  const { scanner_type, ...rest } = params;
  const response = await apiClient.get(`/outcomes/signals/${scanner_type}`, { params: rest });
  return response.data;
};

export const fetchExplanationTraits = async (params: {
  scanner_type: string;
  start_date?: string;
  end_date?: string;
  severity?: string;
}): Promise<ExplanationTraitPerformance> => {
  const response = await apiClient.get(`/outcomes/traits/${params.scanner_type}`, {
    params: {
      start_date: params.start_date,
      end_date: params.end_date,
      severity: params.severity,
    },
  });
  return response.data;
};

export const fetchExplanationArchetypes = async (params: {
  scanner_type: string;
  start_date?: string;
  end_date?: string;
  severity?: string;
}): Promise<ExplanationArchetypeResponse> => {
  const response = await apiClient.get(`/outcomes/archetypes/${params.scanner_type}`, {
    params: {
      start_date: params.start_date,
      end_date: params.end_date,
      severity: params.severity,
    },
  });
  return response.data;
};

export const triggerBackfill = async (request: BackfillRequest): Promise<BackfillResponse> => {
  const response = await apiClient.post('/outcomes/backfill', request);
  return response.data;
};
