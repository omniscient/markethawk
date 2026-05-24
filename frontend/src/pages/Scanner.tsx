import React, { useEffect, useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { formatDistanceToNow, format } from 'date-fns';
import {
  Play,
  X,
  Settings,
  Download,
  Eye,
  Clock,
  Zap
} from 'lucide-react';

// Components
import Card from '../components/ui/Card';
import Button from '../components/ui/Button';
import ScannerConfig from '../components/ScannerConfig';
import ScannerResults from '../components/ScannerResults';
import SignalReviewStats from '../components/SignalReviewStats';

// API functions
import {
  runScanner,
  fetchScannerConfigs,
  fetchStockUniverses,
  fetchScannerResults,
  fetchScannerHistory,
  handleApiError,
  fetchScanStatus,
  cancelScan,
  createScanRunWebSocket,
  fetchScanStatusBlock,
} from '../api/scanner';

const ACTIVE_SCAN_LS_KEY = 'markethawk.activeScan';
const SELECTION_LS_KEY = 'markethawk.scanner.selection';

interface PersistedSelection {
  scanner_type?: string;
  universe_id?: number | null;
}

const loadPersistedSelection = (): PersistedSelection => {
  try {
    const raw = localStorage.getItem(SELECTION_LS_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === 'object' ? parsed : {};
  } catch {
    return {};
  }
};

interface ActiveScanRef {
  scan_id: string;
  task_id: string;
  scanner_type: string;
  universe_id: number;
  start_date: string;
  end_date: string;
  started_at: string;
}

interface LiveProgress {
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

const EMPTY_PROGRESS: LiveProgress = {
  day_index: 0, total_days: 0, total_tickers: 0, estimated_pairs: 0,
  evaluated: 0, no_data: 0, no_prior_close: 0, no_baseline: 0,
  fired_pre: 0, fired_post: 0, errors: 0, events_detected: 0,
};

// Returns the ISO date for the previous completed weekday in the user's local timezone.
const lastCompletedWeekday = (): string => {
  const d = new Date();
  d.setDate(d.getDate() - 1);
  while (d.getDay() === 0 || d.getDay() === 6) {
    d.setDate(d.getDate() - 1);
  }
  return d.toISOString().slice(0, 10);
};

const todayIso = (): string => new Date().toISOString().slice(0, 10);

const Scanner: React.FC = () => {
  const [isScanning, setIsScanning] = useState(false);
  const persisted = useRef<PersistedSelection>(loadPersistedSelection()).current;
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

  // Fetch scanner configurations
  const { data: configs, isLoading: loadingConfigs } = useQuery({
    queryKey: ['scannerConfigs'],
    queryFn: fetchScannerConfigs,
  });

  // Fetch stock universes
  const { data: universes, isLoading: loadingUniverses } = useQuery({
    queryKey: ['stockUniverses'],
    queryFn: () => fetchStockUniverses(),
  });

  // Fetch scanner history
  const { data: scanHistory, isLoading: loadingHistory } = useQuery({
    queryKey: ['scannerHistory'],
    queryFn: () => fetchScannerHistory(10),
  });

  // Fetch rich status block (last run, next run, metrics, sparkline)
  const { data: statusBlock } = useQuery({
    queryKey: ['scanStatusBlock', selectedConfig, selectedUniverse],
    queryFn: () => fetchScanStatusBlock(selectedConfig, selectedUniverse),
    refetchInterval: isScanning ? 5000 : false,
  });

  const queryClient = useQueryClient();

  // Auto-load existing results
  const { data: existingResults } = useQuery({
    queryKey: ['scannerResults', selectedUniverse, selectedConfig, sortBy, sortOrder],
    queryFn: () => fetchScannerResults({
      universe_id: selectedUniverse,
      scanner_type: selectedConfig,
      sort_by: sortBy,
      sort_order: sortOrder,
      limit: 100
    }),
    enabled: !!selectedUniverse && !!selectedConfig,
  });

  // Auto-load existing results when the user changes universe/scanner. Don't clobber a fresh
  // manual scan — only overwrite if scanResults is empty or itself a 'historical' placeholder.
  React.useEffect(() => {
    if (!existingResults) return;
    setScanResults((prev: any) => {
      if (prev && prev.scan_id !== 'historical') return prev;
      return {
        scan_id: 'historical',
        status: 'completed',
        stocks_scanned: 0,
        events_detected: existingResults.length,
        execution_time_ms: 0,
        events: existingResults,
      };
    });
  }, [existingResults]);

  // ---- Live scan tracking -------------------------------------------------
  const [activeScan, setActiveScan] = useState<ActiveScanRef | null>(null);
  const [liveProgress, setLiveProgress] = useState<LiveProgress>(EMPTY_PROGRESS);
  const wsRef = useRef<WebSocket | null>(null);

  const finishScan = (
    finalStatus: 'completed' | 'failed' | 'cancelled',
    errorMsg?: string,
  ) => {
    setIsScanning(false);
    setActiveScan(null);
    localStorage.removeItem(ACTIVE_SCAN_LS_KEY);
    if (wsRef.current) {
      try { wsRef.current.close(); } catch { /* ignore */ }
      wsRef.current = null;
    }
    if (finalStatus === 'failed' && errorMsg) {
      setScanError(errorMsg);
    } else if (finalStatus === 'cancelled') {
      setScanError('Scan cancelled');
    }
    queryClient.invalidateQueries({ queryKey: ['scannerHistory'] });
    queryClient.invalidateQueries({ queryKey: ['scannerConfigs'] });
    queryClient.invalidateQueries({ queryKey: ['scannerResults'] });
    queryClient.invalidateQueries({ queryKey: ['scanStatusBlock'] });
  };

  const handleWsMessage = (msg: any) => {
    if (!msg || typeof msg !== 'object') return;
    setLiveProgress((prev) => {
      const next = { ...prev };
      if (msg.type === 'snapshot' || msg.type === 'started') {
        next.total_days = msg.total_days ?? next.total_days;
        next.total_tickers = msg.total_tickers ?? msg.tickers ?? next.total_tickers;
        next.estimated_pairs = msg.estimated_pairs
          ?? (next.total_days * next.total_tickers);
      }
      if (msg.type === 'snapshot') {
        // Replay carries cumulative counters under the same keys.
        for (const k of [
          'day_index', 'total_days', 'evaluated', 'no_data', 'no_prior_close',
          'no_baseline', 'fired_pre', 'fired_post', 'errors', 'events_detected',
        ] as (keyof LiveProgress)[]) {
          if (msg[k] != null) (next[k] as any) = msg[k];
        }
      }
      if (msg.type === 'day_started') {
        next.day_index = msg.day_index ?? next.day_index;
        next.total_days = msg.total_days ?? next.total_days;
        next.last_day = msg.date ?? next.last_day;
      }
      if (msg.type === 'day_completed') {
        next.day_index = msg.day_index ?? next.day_index;
        next.last_day = msg.date ?? next.last_day;
        for (const k of [
          'evaluated', 'no_data', 'no_prior_close', 'no_baseline',
          'fired_pre', 'fired_post', 'errors', 'events_detected',
        ] as (keyof LiveProgress)[]) {
          if (msg[k] != null) (next[k] as any) = msg[k];
        }
      }
      return next;
    });

    if (msg.type === 'completed') {
      finishScan('completed');
    } else if (msg.type === 'failed') {
      finishScan('failed', msg.error || 'Scan failed');
    } else if (msg.type === 'cancelled') {
      finishScan('cancelled');
    }
  };

  const attachWebSocket = (taskId: string) => {
    if (wsRef.current) {
      try { wsRef.current.close(); } catch { /* ignore */ }
    }
    const ws = createScanRunWebSocket(taskId);
    if (!ws) return;
    wsRef.current = ws;
    ws.onmessage = (ev) => {
      try {
        handleWsMessage(JSON.parse(ev.data));
      } catch (e) {
        console.error('[scanner WS] invalid payload', e);
      }
    };
    ws.onclose = () => {
      // Closure is normal once a terminal message arrives — finishScan already
      // ran via the message handler. If the socket closes while we still think
      // a scan is running, fall back to the status endpoint.
      if (wsRef.current === ws) {
        wsRef.current = null;
      }
    };
    ws.onerror = (e) => {
      console.error('[scanner WS] error', e);
    };
  };

  // Submit-the-scan mutation (HTTP only — progress arrives via WS).
  const scannerMutation = useMutation({
    mutationFn: runScanner,
    onSuccess: (data) => {
      const ref: ActiveScanRef = {
        scan_id: data.scan_id,
        task_id: data.task_id,
        scanner_type: data.scanner_type,
        universe_id: data.universe_id ?? selectedUniverse ?? 0,
        start_date: data.scan_start_date ?? scanStartDate,
        end_date: data.scan_end_date ?? scanEndDate,
        started_at: data.started_at,
      };
      setActiveScan(ref);
      setLiveProgress(EMPTY_PROGRESS);
      setIsScanning(true);
      setScanError(null);
      localStorage.setItem(ACTIVE_SCAN_LS_KEY, JSON.stringify(ref));
      attachWebSocket(data.task_id);
    },
    onError: (error: any) => {
      // 409 = a scan for the same (universe, scanner_type) is already running.
      // Reattach to the existing one instead of erroring out.
      const status = error?.response?.status;
      const detail = error?.response?.data?.detail;
      if (status === 409 && detail && typeof detail === 'object' && detail.task_id) {
        const ref: ActiveScanRef = {
          scan_id: detail.scan_id,
          task_id: detail.task_id,
          scanner_type: selectedConfig,
          universe_id: selectedUniverse || 0,
          start_date: scanStartDate,
          end_date: scanEndDate,
          started_at: detail.started_at,
        };
        setActiveScan(ref);
        setIsScanning(true);
        setScanError(null);
        localStorage.setItem(ACTIVE_SCAN_LS_KEY, JSON.stringify(ref));
        attachWebSocket(detail.task_id);
        return;
      }
      console.error('Scanner error:', error);
      setScanError(handleApiError(error));
      setIsScanning(false);
    },
  });

  const handleRunScanner = async () => {
    if (!selectedUniverse || !selectedConfig) {
      setScanError('Please select a universe and a scanner type');
      return;
    }
    if (scanStartDate && scanEndDate && scanEndDate < scanStartDate) {
      setScanError('End date must be on or after start date');
      return;
    }

    setScanError(null);
    scannerMutation.mutate({
      scanner_type: selectedConfig,
      universe_id: selectedUniverse,
      tickers: [],
      dry_run: false,
      start_date: scanStartDate || undefined,
      end_date: scanEndDate || scanStartDate || undefined,
    });
  };

  const handleCancelScanner = async () => {
    if (!activeScan) return;
    try {
      await cancelScan(activeScan.scan_id);
    } catch (e) {
      console.error('cancel failed', e);
      setScanError(handleApiError(e));
    }
  };

  // Reattach to an in-flight scan after page reload.
  useEffect(() => {
    const raw = localStorage.getItem(ACTIVE_SCAN_LS_KEY);
    if (!raw) return;
    let ref: ActiveScanRef;
    try { ref = JSON.parse(raw); } catch { localStorage.removeItem(ACTIVE_SCAN_LS_KEY); return; }

    fetchScanStatus(ref.scan_id)
      .then((status) => {
        if (status.status === 'queued' || status.status === 'running') {
          setActiveScan(ref);
          setIsScanning(true);
          if (status.progress) {
            setLiveProgress((p) => ({ ...p, ...status.progress } as LiveProgress));
          }
          attachWebSocket(ref.task_id);
        } else {
          localStorage.removeItem(ACTIVE_SCAN_LS_KEY);
          // Refresh results to pick up whatever the previous run left.
          queryClient.invalidateQueries({ queryKey: ['scannerResults'] });
          queryClient.invalidateQueries({ queryKey: ['scannerHistory'] });
        }
      })
      .catch(() => {
        localStorage.removeItem(ACTIVE_SCAN_LS_KEY);
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Remember the user's last universe + scanner type across page navigations.
  useEffect(() => {
    try {
      localStorage.setItem(
        SELECTION_LS_KEY,
        JSON.stringify({ scanner_type: selectedConfig, universe_id: selectedUniverse }),
      );
    } catch { /* ignore quota errors */ }
  }, [selectedConfig, selectedUniverse]);

  // Tear down WS on unmount.
  useEffect(() => {
    return () => {
      if (wsRef.current) {
        try { wsRef.current.close(); } catch { /* ignore */ }
        wsRef.current = null;
      }
    };
  }, []);

  return (
    <div className="space-y-6 animate-fade-in">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-financial-light">Scanner</h1>
          <p className="text-gray-400 mt-1">Configure and run stock scanning algorithms</p>
        </div>
        <div className="flex items-end space-x-3">
          <div className="flex flex-col">
            <label htmlFor="scan-start" className="text-[10px] font-bold uppercase tracking-wider text-gray-500 mb-1">
              From
            </label>
            <input
              id="scan-start"
              type="date"
              value={scanStartDate}
              max={scanEndDate || todayIso()}
              onChange={(e) => {
                const v = e.target.value;
                setScanStartDate(v);
                if (scanEndDate && v && v > scanEndDate) setScanEndDate(v);
              }}
              disabled={isScanning}
              className="px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-financial-light text-sm focus:outline-none focus:ring-1 focus:ring-financial-blue disabled:opacity-50"
            />
          </div>
          <div className="flex flex-col">
            <label htmlFor="scan-end" className="text-[10px] font-bold uppercase tracking-wider text-gray-500 mb-1">
              To
            </label>
            <input
              id="scan-end"
              type="date"
              value={scanEndDate}
              min={scanStartDate || undefined}
              max={todayIso()}
              onChange={(e) => setScanEndDate(e.target.value)}
              disabled={isScanning}
              className="px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-financial-light text-sm focus:outline-none focus:ring-1 focus:ring-financial-blue disabled:opacity-50"
            />
          </div>
          <DateRangePresets
            disabled={isScanning}
            onSelect={(start, end) => {
              setScanStartDate(start);
              setScanEndDate(end);
            }}
          />
          {isScanning ? (
            <Button
              variant="danger"
              onClick={handleCancelScanner}
              icon={X as any}
            >
              Cancel Scan
            </Button>
          ) : (
            <Button
              variant="primary"
              onClick={handleRunScanner}
              icon={Play as any}
              loading={scannerMutation.isPending}
              disabled={loadingConfigs}
            >
              Run Scanner
            </Button>
          )}
        </div>
      </div>

      {/* Live progress */}
      {isScanning && activeScan && (
        <LiveProgressCard scan={activeScan} progress={liveProgress} />
      )}

      {scanError && !isScanning && (
        <Card className="bg-red-900/20 border-red-500/30">
          <div className="flex items-start justify-between space-x-3">
            <div>
              <h3 className="text-red-300 font-semibold">Scanner failed</h3>
              <p className="text-red-200 text-sm mt-1">{scanError}</p>
            </div>
            <button
              onClick={() => setScanError(null)}
              className="text-red-300 hover:text-red-100 text-sm"
              aria-label="Dismiss error"
            >
              Dismiss
            </button>
          </div>
        </Card>
      )}

      {/* Configuration */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2">
          <Card title="Scanner Configuration" icon={Settings as any}>
            <ScannerConfig
              configs={configs || []}
              universes={universes || []}
              selectedConfig={selectedConfig}
              selectedUniverse={selectedUniverse}
              onConfigChange={setSelectedConfig}
              onUniverseChange={setSelectedUniverse}
              loading={loadingConfigs || loadingUniverses}
            />
          </Card>
        </div>

        {/* Quick Stats */}
        <div className="space-y-4">
          <Card title="Scan Status" icon={Eye as any}>
            <div className="space-y-3">
              {/* Status badge */}
              <div className="flex justify-between items-center">
                <span className="text-gray-400">Status</span>
                <span className={`px-2 py-1 rounded text-xs font-medium ${isScanning
                  ? 'bg-blue-500/20 text-blue-400'
                  : statusBlock?.next_run
                    ? 'bg-purple-500/20 text-purple-400'
                    : 'bg-green-500/20 text-green-400'
                  }`}>
                  {isScanning ? 'Running' : statusBlock?.next_run ? 'Scheduled' : 'Ready'}
                </span>
              </div>

              {/* Last Run */}
              <div className="flex justify-between items-center">
                <span className="text-gray-400">Last Run</span>
                <span className="text-financial-light text-right">
                  {statusBlock?.last_run?.timestamp
                    ? (
                      <span>
                        {formatDistanceToNow(new Date(statusBlock.last_run.timestamp), { addSuffix: true })}
                        <span className="ml-1 text-xs text-gray-500">
                          · {statusBlock.last_run.events_detected} events
                        </span>
                      </span>
                    )
                    : 'Never'}
                </span>
              </div>

              {/* Next Run */}
              <div className="flex justify-between items-center">
                <span className="text-gray-400">Next Run</span>
                <span className="text-financial-light">
                  {statusBlock === undefined
                    ? '—'
                    : statusBlock?.next_run
                      ? formatDistanceToNow(new Date(statusBlock.next_run), { addSuffix: true })
                      : 'Manual only'}
                </span>
              </div>

              {/* Stocks in Universe */}
              <div className="flex justify-between items-center">
                <span className="text-gray-400">Stocks in Universe</span>
                <span className="text-financial-light">
                  {universes?.find(u => u.id === selectedUniverse)?.ticker_count || universes?.find(u => u.id === selectedUniverse)?.aggregate_count || 0}
                </span>
              </div>

              {/* Total Events */}
              <div className="flex justify-between items-center">
                <span className="text-gray-400">Total Events</span>
                <span className="text-financial-light">
                  {statusBlock !== undefined ? statusBlock.total_events.toLocaleString() : '—'}
                </span>
              </div>

              {/* Last Run Duration */}
              {statusBlock?.last_run?.duration_ms != null && statusBlock.last_run.duration_ms > 0 && (
                <div className="flex justify-between items-center">
                  <span className="text-gray-400">Last Duration</span>
                  <span className="text-financial-light">
                    {statusBlock.last_run.duration_ms < 1000
                      ? `${statusBlock.last_run.duration_ms}ms`
                      : `${(statusBlock.last_run.duration_ms / 1000).toFixed(1)}s`}
                  </span>
                </div>
              )}

              {/* Success Rate */}
              {statusBlock?.success_rate != null && (
                <div className="flex justify-between items-center">
                  <span className="text-gray-400">Success Rate</span>
                  <span className={`text-financial-light ${statusBlock.success_rate < 80 ? 'text-red-400' : statusBlock.success_rate < 95 ? 'text-yellow-400' : 'text-green-400'}`}>
                    {statusBlock.success_rate}%
                    <span className="ml-1 text-xs text-gray-500">last 20</span>
                  </span>
                </div>
              )}

              {/* Avg events per scan */}
              {statusBlock?.avg_events_per_scan != null && (
                <div className="flex justify-between items-center">
                  <span className="text-gray-400">Avg Events/Scan</span>
                  <span className="text-financial-light">{statusBlock.avg_events_per_scan}</span>
                </div>
              )}

              {/* Sparkline — events per run over last 10 scans */}
              {statusBlock?.sparkline && statusBlock.sparkline.length > 1 && (() => {
                const pts = statusBlock.sparkline;
                const maxVal = Math.max(...pts.map(p => p.events_detected), 1);
                const w = 100, h = 28, barW = Math.floor(w / pts.length) - 1;
                return (
                  <div className="pt-1">
                    <span className="text-xs text-gray-500 mb-1 block">Events/run (last {pts.length})</span>
                    <svg width={w} height={h} className="w-full" viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none">
                      {pts.map((p, i) => {
                        const barH = Math.max(2, Math.round((p.events_detected / maxVal) * (h - 2)));
                        const x = i * (barW + 1);
                        const fill = p.status === 'completed' ? '#60a5fa' : p.status === 'failed' ? '#f87171' : '#6b7280';
                        return (
                          <rect key={i} x={x} y={h - barH} width={barW} height={barH} fill={fill} rx={1} />
                        );
                      })}
                    </svg>
                  </div>
                );
              })()}
            </div>
          </Card>

          <Card title="Quick Actions" icon={Zap as any}>
            <div className="space-y-2">
              <Button
                variant="secondary"
                size="sm"
                fullWidth
                icon={Clock as any}
              >
                Schedule Scan
              </Button>
              <Button
                variant="secondary"
                size="sm"
                fullWidth
                icon={Download as any}
              >
                Export Results
              </Button>
            </div>
          </Card>
        </div>
      </div>

      {/* Results */}
      {scanResults && (
        <div className="animate-slide-up">
          <ScannerResults 
            results={scanResults} 
            sortBy={sortBy}
            sortOrder={sortOrder}
            onSort={(column) => {
              if (column === sortBy) {
                setSortOrder(sortOrder === 'asc' ? 'desc' : 'asc');
              } else {
                setSortBy(column);
                setSortOrder('desc');
              }
            }}
          />
        </div>
      )}

      {/* Historical Results */}
      <Card title="Recent Scan History" icon={Clock as any}>
        <div className="space-y-4">
          {loadingHistory ? (
            <div className="text-center py-4 text-gray-400">Loading history...</div>
          ) : scanHistory && scanHistory.length > 0 ? (
            scanHistory.map((scan, index) => (
              <div key={index} className="flex items-center justify-between p-4 bg-gray-800 rounded-lg">
                <div className="flex-1">
                  <div className="flex items-center space-x-2">
                    <div className="text-financial-light font-medium">
                      {scan.created_at ? format(new Date(scan.created_at), 'yyyy-MM-dd HH:mm:ss') : 'Unknown Date'}
                    </div>
                    <span className="text-xs text-gray-500 uppercase">({scan.scanner_type.replace(/_/g, ' ')})</span>
                  </div>
                  <div className="flex items-center space-x-3 mt-1">
                    <div className="text-gray-400 text-sm">{scan.stocks_scanned} stocks analyzed</div>
                    <div className="text-financial-blue text-sm font-semibold">{scan.events_detected} events found</div>
                  </div>
                  {scan.status === 'failed' && scan.error_message && (
                    <div className="text-red-400 text-xs mt-1 italic">Error: {scan.error_message}</div>
                  )}
                </div>
                <div className="flex items-center space-x-3">
                  <span className="text-gray-400 text-sm">{(scan.execution_time_ms / 1000).toFixed(1)}s</span>
                  <span className={`px-2 py-1 rounded text-xs font-medium ${scan.status === 'completed'
                    ? 'bg-green-500/20 text-green-400'
                    : scan.status === 'running'
                      ? 'bg-blue-500/20 text-blue-400'
                      : 'bg-red-500/20 text-red-400'
                    }`}>
                    {scan.status}
                  </span>
                </div>
              </div>
            ))
          ) : (
            <div className="text-center py-8 text-gray-500">No scan history found</div>
          )}
        </div>
      </Card>

      <SignalReviewStats />
    </div>
  );
};

// Live progress card shown while a scan is running. Counters come from the
// Celery worker via /api/scanner/ws/runs/{task_id}; the events table reloads
// from the DB once the scan reaches 'completed'.
const LiveProgressCard: React.FC<{
  scan: ActiveScanRef;
  progress: LiveProgress;
}> = ({ scan, progress }) => {
  const total = progress.estimated_pairs || (progress.total_days * progress.total_tickers) || 0;
  const done = progress.evaluated + progress.no_data + progress.no_prior_close + progress.no_baseline;
  const pct = total > 0 ? Math.min(100, Math.round((done / total) * 100)) : 0;

  return (
    <Card className="bg-blue-900/20 border-blue-500/30">
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center space-x-3">
            <div className="animate-spin rounded-full h-5 w-5 border-b-2 border-financial-blue"></div>
            <div>
              <h3 className="text-financial-light font-semibold">
                Scanning <span className="font-mono text-sm text-blue-300">{scan.scanner_type}</span>
              </h3>
              <p className="text-gray-400 text-xs">
                {scan.start_date}{scan.end_date && scan.end_date !== scan.start_date ? ` → ${scan.end_date}` : ''}
                {progress.total_days > 0 && (
                  <> · day {progress.day_index || 0}/{progress.total_days}{progress.last_day ? ` (${progress.last_day})` : ''}</>
                )}
              </p>
            </div>
          </div>
          <div className="text-right">
            <div className="text-2xl font-bold text-financial-light tabular-nums">{progress.events_detected}</div>
            <div className="text-[10px] uppercase tracking-wider text-gray-500">events so far</div>
          </div>
        </div>

        <div className="w-full bg-gray-800 rounded-full h-2 overflow-hidden">
          <div
            className="h-2 bg-financial-blue transition-all duration-300"
            style={{ width: `${pct}%` }}
          />
        </div>
        <div className="flex justify-between text-[11px] text-gray-400 font-mono tabular-nums">
          <span>{done.toLocaleString()} / {total.toLocaleString() || '—'} pairs</span>
          <span>{pct}%</span>
        </div>

        <div className="grid grid-cols-3 md:grid-cols-6 gap-2 pt-1 text-[11px] font-mono tabular-nums">
          <ProgressChip label="evaluated" value={progress.evaluated} tone="ok" />
          <ProgressChip label="fired pre" value={progress.fired_pre} tone="ok" />
          <ProgressChip label="fired post" value={progress.fired_post} tone="ok" />
          <ProgressChip label="no data" value={progress.no_data} tone="warn" />
          <ProgressChip label="no baseline" value={progress.no_baseline} tone="warn" />
          <ProgressChip label="errors" value={progress.errors} tone="err" />
        </div>
      </div>
    </Card>
  );
};

const ProgressChip: React.FC<{ label: string; value: number; tone: 'ok' | 'warn' | 'err' }> = ({
  label, value, tone,
}) => {
  const colour =
    tone === 'err' && value > 0 ? 'text-red-400'
      : tone === 'warn' && value > 0 ? 'text-yellow-400'
      : tone === 'ok' && value > 0 ? 'text-green-400'
      : 'text-gray-500';
  return (
    <div className="flex justify-between border-b border-gray-800/60 pb-0.5">
      <span className="text-[9px] uppercase tracking-wider text-gray-500">{label}</span>
      <span className={`font-semibold ${colour}`}>{value.toLocaleString()}</span>
    </div>
  );
};

// Quick range buttons. All ranges end at the most recent completed weekday so
// they don't include today before the regular session has closed.
const DateRangePresets: React.FC<{
  onSelect: (_start: string, _end: string) => void;
  disabled?: boolean;
}> = ({ onSelect, disabled }) => {
  const apply = (calendarDays: number) => {
    const end = new Date();
    end.setDate(end.getDate() - 1);
    while (end.getDay() === 0 || end.getDay() === 6) {
      end.setDate(end.getDate() - 1);
    }
    const start = new Date(end);
    start.setDate(start.getDate() - (calendarDays - 1));
    onSelect(start.toISOString().slice(0, 10), end.toISOString().slice(0, 10));
  };

  const presets: [string, number][] = [
    ['1D', 1],
    ['7D', 7],
    ['30D', 30],
    ['90D', 90],
  ];

  return (
    <div className="flex space-x-1">
      {presets.map(([label, days]) => (
        <button
          key={label}
          type="button"
          disabled={disabled}
          onClick={() => apply(days)}
          className="px-2 py-1 text-[10px] font-bold uppercase tracking-wider bg-gray-800 hover:bg-gray-700 border border-gray-700 rounded text-gray-300 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
        >
          {label}
        </button>
      ))}
    </div>
  );
};

export default Scanner;