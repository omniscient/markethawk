import { useState, useRef, useEffect } from 'react';

export const ACTIVE_SCAN_LS_KEY = 'markethawk.activeScan';
export const SELECTION_LS_KEY = 'markethawk.scanner.selection';

export interface PersistedSelection {
  scanner_type?: string;
  universe_id?: number | null;
}

export interface ActiveScanRef {
  scan_id: string;
  task_id: string;
  scanner_type: string;
  universe_id: number;
  start_date: string;
  end_date: string;
  started_at: string;
}

export interface LiveProgress {
  day_index: number;
  total_days: number;
  total_tickers: number;
  estimated_pairs: number;
  evaluated: number;
  no_data: number;
  no_prior_close: number;
  no_baseline: number;
  fired_pre: number;
  fired_post: number;
  errors: number;
  events_detected: number;
  last_day?: string;
}

export const EMPTY_PROGRESS: LiveProgress = {
  day_index: 0, total_days: 0, total_tickers: 0, estimated_pairs: 0,
  evaluated: 0, no_data: 0, no_prior_close: 0, no_baseline: 0,
  fired_pre: 0, fired_post: 0, errors: 0, events_detected: 0,
};

export const lastCompletedWeekday = (): string => {
  const d = new Date();
  d.setDate(d.getDate() - 1);
  while (d.getDay() === 0 || d.getDay() === 6) {
    d.setDate(d.getDate() - 1);
  }
  return d.toISOString().slice(0, 10);
};

export const todayIso = (): string => new Date().toISOString().slice(0, 10);

export const loadPersistedSelection = (): PersistedSelection => {
  try {
    const raw = localStorage.getItem(SELECTION_LS_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === 'object' ? parsed : {};
  } catch {
    return {};
  }
};

export function useScannerState() {
  const persisted = useRef<PersistedSelection>(loadPersistedSelection()).current;

  const [isScanning, setIsScanning] = useState(false);
  const [selectedConfig, setSelectedConfig] = useState<string>(
    persisted.scanner_type || 'pre_market_volume_spike',
  );
  const [selectedUniverse, setSelectedUniverse] = useState<number | null>(
    typeof persisted.universe_id === 'number' ? persisted.universe_id : null,
  );
  const [scanStartDate, setScanStartDate] = useState<string>(lastCompletedWeekday());
  const [scanEndDate, setScanEndDate] = useState<string>(lastCompletedWeekday());
  const [scanResults, setScanResults] = useState<any>(null);
  const [scanError, setScanError] = useState<string | null>(null);
  const [sortBy, setSortBy] = useState<string>('signal_quality_score');
  const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('desc');
  const [activeScan, setActiveScan] = useState<ActiveScanRef | null>(null);
  const [liveProgress, setLiveProgress] = useState<LiveProgress>(EMPTY_PROGRESS);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    try {
      localStorage.setItem(
        SELECTION_LS_KEY,
        JSON.stringify({ scanner_type: selectedConfig, universe_id: selectedUniverse }),
      );
    } catch { /* ignore quota errors */ }
  }, [selectedConfig, selectedUniverse]);

  return {
    isScanning, setIsScanning,
    selectedConfig, setSelectedConfig,
    selectedUniverse, setSelectedUniverse,
    scanStartDate, setScanStartDate,
    scanEndDate, setScanEndDate,
    scanResults, setScanResults,
    scanError, setScanError,
    sortBy, setSortBy,
    sortOrder, setSortOrder,
    activeScan, setActiveScan,
    liveProgress, setLiveProgress,
    wsRef,
  };
}
