// Scanner-domain types — shared across scanner sub-modules

export interface ScannerEvent {
  id: number;
  uuid: string;
  ticker: string;
  event_date: string;
  scanner_type: string;

  summary?: string;
  severity: 'low' | 'medium' | 'high';

  previous_close?: number;
  opening_price?: number;
  closing_price?: number;

  signal_quality_score?: number | null;
  regime?: string | null;

  indicators: Record<string, unknown>;
  criteria_met: Record<string, unknown>;
  metadata: Record<string, unknown>;
  explanation?: ScannerExplanation | null;

  created_at: string;
  updated_at: string;
  latest_review?: SignalReview | null;
}

export interface ScannerCriterionExplanation {
  label: string;
  observed?: unknown;
  threshold?: unknown;
  operator: '>' | '>=' | '<' | '<=' | '==' | '!=' | 'exists';
  unit?: string | null;
  source?: string | null;
  lookback?: string | null;
  importance?: number | null;
}

export interface ScannerDataQualityWarning {
  code: string;
  severity: 'low' | 'medium' | 'high';
  message: string;
  affected_inputs: string[];
}

export interface ScannerExplanationEvidence {
  reconstructed: boolean;
  reconstruction_quality?: 'best_effort' | 'partial' | null;
  generated_at?: string | null;
  generator_version?: string | null;
  market_data_asof?: string | null;
  provider?: string | null;
}

export interface ScannerExplanation {
  schema_version: 'scanner_explanation.v1';
  why: string[];
  criteria_passed: Record<string, ScannerCriterionExplanation>;
  criteria_failed: Record<string, ScannerCriterionExplanation>;
  confidence_inputs: Record<string, unknown>;
  data_quality_warnings: ScannerDataQualityWarning[];
  evidence: ScannerExplanationEvidence;
}

export interface SignalReview {
  id: number;
  scanner_event_id: number;
  verdict: 'confirmed' | 'rejected' | 'enhanced' | 'uncertain';
  reject_reason: string | null;
  notes: string | null;
  enhance_suggestion: Record<string, unknown> | null;
  reviewed_at: string;
  reviewed_by: string | null;
}

export type RejectionReason = 'too_late' | 'noise' | 'stale_data' | 'split_artifact';

export interface SignalReviewStats {
  total_events: number;
  reviewed_count: number;
  acceptance_rate: number;
  by_scanner_type: Array<{
    scanner_type: string;
    total: number;
    confirmed: number;
    rejected: number;
    uncertain: number;
    enhanced: number;
  }>;
  top_rejection_reasons: Array<{ reason: string; count: number }>;
}

// Backward compatibility alias during transition
export type VolumeEvent = ScannerEvent;

export interface ScannerConfig {
  id: number;
  uuid: string;
  name: string;
  description: string;
  scanner_type: string;
  parameters: Record<string, unknown>;
  criteria: Record<string, unknown>[];
  is_active: boolean;
  run_frequency: string;
  last_run: string | null;
  next_run: string | null;
}

export interface ScannerRunRequest {
  universe_id?: number;
  tickers?: string[];
  scanner_type: string;
  dry_run?: boolean;
  start_date?: string;
  end_date?: string;
}

export interface ScannerDiagnostics {
  tickers?: number;
  days?: number;
  start_date?: string;
  end_date?: string;
  no_data?: number;
  no_prior_close?: number;
  no_baseline?: number;
  evaluated?: number;
  fired_pre?: number;
  fired_post?: number;
  errors?: number;
}

export type QualityIssueCode =
  | 'missing_bars'
  | 'split_dividend_anomaly'
  | 'stale_quote_risk'
  | 'provider_gaps'
  | 'timezone_session_mismatch'
  | 'survivorship_bias_risk'
  | 'stale_reference_data';

export type QualityGateVerdict = 'trusted' | 'warning' | 'blocked' | 'skipped';

export interface QualityGateIssue {
  issue_code: QualityIssueCode;
  severity: 'blocker' | 'warning' | 'info';
  title: string;
  scope: 'ticker' | 'universe' | 'session' | 'provider';
  ticker: string | null;
  asset_class: string | null;
  affected_inputs: {
    timespans?: string[];
    date_range?: { start: string; end: string };
    session?: string;
    fields?: string[];
  } | null;
  detail: Record<string, unknown>;
  remediation: {
    action: string;
    label: string;
    description: string;
    automated: boolean;
  };
}

export interface QualityGateSummary {
  blocker_count: number;
  warning_count: number;
  info_count: number;
  affected_ticker_count: number;
  total_tickers_evaluated: number;
  most_affected_tickers: Array<{
    ticker: string;
    issue_count: number;
    max_severity: 'blocker' | 'warning' | 'info';
  }>;
  issue_code_counts: Partial<Record<QualityIssueCode, number>>;
}

export interface QualityGateAssessment {
  verdict: QualityGateVerdict;
  policy: 'advisory' | 'strict';
  consumer: string;
  scanner_type: string | null;
  universe_id: number | null;
  generated_at: string;
  assessment_id: string;
  verdict_reason: string;
  summary: QualityGateSummary;
  issues: QualityGateIssue[];
}

export interface ScannerRunResponse {
  scan_id: string;
  status: string;
  stocks_scanned: number;
  events_detected: number;
  execution_time_ms: number;
  scanner_type: string;
  events?: ScannerEvent[];
  error_message?: string;
  created_at?: string;
  scan_start_date?: string;
  scan_end_date?: string;
  diagnostics?: ScannerDiagnostics;
  quality_gate?: QualityGateAssessment;
}

export interface ScannerRunAsyncResponse {
  scan_id: string;
  task_id: string;
  started_at: string;
  scanner_type: string;
  universe_id?: number;
  scan_start_date?: string;
  scan_end_date?: string;
  status: 'queued';
}

export interface ScannerRunStatus {
  scan_id: string;
  task_id?: string;
  status: 'queued' | 'running' | 'completed' | 'failed' | 'cancelled';
  scanner_type: string;
  universe_id?: number;
  scan_start_date?: string;
  scan_end_date?: string;
  stocks_scanned: number;
  events_detected: number;
  execution_time_ms: number;
  error_message?: string | null;
  started_at?: string;
  progress?: ScannerDiagnostics & {
    day_index?: number;
    total_days?: number;
    tickers?: number;
    events_detected?: number;
    [k: string]: unknown;
  } | null;
}

export interface ScannerRangeRequest {
  ticker: string;
  scanner_types: string[];
  start_date: string;
  end_date: string;
  fetch_missing_data: boolean;
}

export interface ScannerRangeResponse {
  task_id: string;
  status: 'queued';
}

export interface ScannerLastRunInfo {
  timestamp: string | null;
  status: string;
  events_detected: number;
  duration_ms: number;
}

export interface ScannerSparklinePoint {
  created_at: string | null;
  events_detected: number;
  status: string;
}

export interface ScannerStatusBlock {
  scanner_type: string;
  universe_id: number | null;
  last_run: ScannerLastRunInfo | null;
  next_run: string | null;
  total_events: number;
  success_rate: number | null;
  avg_events_per_scan: number | null;
  sparkline: ScannerSparklinePoint[];
}

export interface MarketStats {
  activeAlerts: number;
  avgVolumeSpike: number;
  totalEvents: number;
  todayEvents: number;
}

export interface PreMarketMover {
  ticker: string;
  name: string | null;
  price: number;
  change_percent: number;
  change_value: number;
  volume: number;
  prev_close: number;
  sector?: string;
  market_cap?: number;
}

export interface PreMarketMoversResponse {
  status: string;
  movers: PreMarketMover[];
  timestamp: string;
}

export interface StorageStats {
  scanner: { bytes: number; formatted: string };
  historical: { bytes: number; formatted: string };
  settings: { bytes: number; formatted: string };
  total: { bytes: number; formatted: string };
}

export interface DataProvider {
  name: string;
  classes: string[];
  available: boolean;
  status_message?: string;
}

export interface OHLCVRow {
  Date: string;
  Open: number;
  High: number;
  Low: number;
  Close: number;
  Volume?: number;
  vwap?: number;
  vwap_intraday?: number;
  marker_type?: string;
  contract_month?: string;
  transactions?: number;
}

export interface ClearEventsResponse {
  ticker: string;
  deleted_count: number;
}

export interface EdgeDistributionEvent {
  ticker: string;
  event_date: string;
  gap_pct: number;
  fade_pct: number;
  day_range_pct: number;
}

export interface EdgeDistributionResponse {
  events: EdgeDistributionEvent[];
}

export interface EdgeStatEntry {
  label: string;
  event_count: number;
  avg_gap_pct: number;
  avg_fade_pct: number;
  avg_day_range_pct: number;
  avg_rel_vol: number;
}

export interface SignalQualityDecile {
  decile: string;
  count: number;
  avg_eod_pct: number | null;
  follow_through_rate: number | null;
}

export interface SignalQualityDistributionResponse {
  deciles: SignalQualityDecile[];
  signal_ranker_version: string;
}
