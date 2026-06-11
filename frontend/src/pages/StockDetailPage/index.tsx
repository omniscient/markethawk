import React from 'react';
import { useParams, Link, useSearchParams } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { ArrowLeft, TrendingUp, TrendingDown, Info } from 'lucide-react';
import { format } from 'date-fns';
import { fetchStockDetails, refreshStockData, syncMissingStockAggregates } from '../../api/stocks';
import { fetchScannerResults, fetchHistoricalData, fetchUniversesForTicker, clearScannerEvents, runScannerRange } from '../../api/scanner';
import { getSystemInfo } from '../../api/system';
import { useLiveStockData } from '../../hooks/useLiveStockData';
import { useScanTask } from '../../hooks/useScanTask';
import { ChartPanel } from './ChartPanel';
import { MetadataPanel } from './MetadataPanel';
import { ScannerHistoryPanel } from './ScannerHistoryPanel';

const StockDetailPage: React.FC = () => {
  const { ticker } = useParams<{ ticker: string }>();
  const symbol = ticker?.toUpperCase() || '';
  const [searchParams] = useSearchParams();
  const [period, setPeriod] = React.useState(localStorage.getItem('stock_detail_period') || '1y');
  const [timespan, setTimespan] = React.useState(localStorage.getItem('stock_detail_timespan') || 'day');
  const [wsResolution, setWsResolution] = React.useState<'minute' | 'second'>(
    (localStorage.getItem('stock_detail_ws_res') as 'minute' | 'second') || 'minute'
  );
  const [highlightDate, setHighlightDate] = React.useState<string | undefined>(
    searchParams.get('date') ?? undefined
  );
  const [catchingUp, setCatchingUp] = React.useState(false);
  const [showST, setShowST] = React.useState(localStorage.getItem('show_double_st') === 'true');
  const [scanDialogOpen, setScanDialogOpen] = React.useState(false);
  const [scanTaskId, setScanTaskId] = React.useState<string | null>(null);
  const [scanSubmitting, setScanSubmitting] = React.useState(false);
  const [scanDoneMsg, setScanDoneMsg] = React.useState<string | null>(null);
  const [clearConfirmOpen, setClearConfirmOpen] = React.useState(false);
  const queryClient = useQueryClient();

  const refreshMutation = useMutation({
    mutationFn: (v: { sym: string; timespan: string; period: string }) =>
      refreshStockData(v.sym, v.timespan, v.period),
    onSuccess: (_, v) => {
      queryClient.invalidateQueries({ queryKey: ['historicalData', v.sym, v.period, v.timespan] });
      queryClient.invalidateQueries({ queryKey: ['stockDetails', v.sym] });
    }
  });

  const catchUpMutation = useMutation({
    mutationFn: (sym: string) => syncMissingStockAggregates(sym),
    onSuccess: () => {
      setCatchingUp(true);
      queryClient.invalidateQueries({ queryKey: ['historicalData', symbol] });
    },
    onError: () => setCatchingUp(false),
  });

  const clearEventsMutation = useMutation({
    mutationFn: () => clearScannerEvents(symbol),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['scannerResults', { ticker: symbol }] });
      setClearConfirmOpen(false);
    },
  });

  React.useEffect(() => {
    localStorage.setItem('stock_detail_period', period);
    localStorage.setItem('stock_detail_timespan', timespan);
    localStorage.setItem('stock_detail_ws_res', wsResolution);
    localStorage.setItem('show_double_st', String(showST));
  }, [period, timespan, wsResolution, showST]);

  const didRefreshRef = React.useRef<string | null>(null);
  React.useEffect(() => {
    if (symbol && didRefreshRef.current !== symbol) {
      didRefreshRef.current = symbol;
      refreshMutation.mutate({ sym: symbol, timespan, period });
    }
  }, [symbol, period, timespan, refreshMutation]);

  const { data: details, isLoading: loadingDetails } = useQuery({
    queryKey: ['stockDetails', symbol],
    queryFn: () => fetchStockDetails(symbol),
    enabled: !!symbol,
    staleTime: 60_000,
  });

  const { data: historicalResponse, isLoading: loadingHistorical, isFetching: fetchingHistorical } = useQuery({
    queryKey: ['historicalData', symbol, period, timespan],
    queryFn: () => fetchHistoricalData(symbol, period, timespan),
    enabled: !!symbol,
    staleTime: 30_000,
  });

  const historicalData = historicalResponse?.data || [];

  React.useEffect(() => {
    if (catchingUp && !fetchingHistorical) setCatchingUp(false);
  }, [fetchingHistorical, catchingUp]);

  const autoRefreshAttempts = React.useRef<Set<string>>(new Set());
  React.useEffect(() => {
    if (!symbol || loadingHistorical || fetchingHistorical || historicalData.length > 0 || refreshMutation.isPending) return;
    const attemptKey = `${symbol}-${period}-${timespan}`;
    if (autoRefreshAttempts.current.has(attemptKey)) return;
    autoRefreshAttempts.current.add(attemptKey);
    if (period !== '30d') {
      setPeriod('30d');
      autoRefreshAttempts.current.add(`${symbol}-30d-${timespan}`);
    }
    refreshMutation.mutate({ sym: symbol, timespan, period: '30d' });
  }, [symbol, period, timespan, historicalData.length, loadingHistorical, fetchingHistorical, refreshMutation.isPending, refreshMutation]);

  const { data: scannerResults } = useQuery({
    queryKey: ['scannerResults', { ticker: symbol }],
    queryFn: () => fetchScannerResults({ ticker: symbol, limit: 10 }),
    enabled: !!symbol,
    staleTime: 120_000,
  });

  const { liveData, isConnected } = useLiveStockData(symbol, wsResolution);
  const { data: systemInfo } = useQuery({ queryKey: ['systemInfo'], queryFn: getSystemInfo });
  const { data: tickerUniverses = [] } = useQuery({
    queryKey: ['tickerUniverses', symbol],
    queryFn: () => fetchUniversesForTicker(symbol),
    enabled: !!symbol,
    staleTime: 300_000,
  });

  const scanTaskRef = React.useRef<ReturnType<typeof useScanTask> | null>(null);
  const scanTask = useScanTask(scanTaskId, () => {
    queryClient.invalidateQueries({ queryKey: ['scannerResults', { ticker: symbol }] });
    const count = scanTaskRef.current?.eventsDetected ?? 0;
    setScanTaskId(null);
    setScanDoneMsg(`Done — ${count} event${count !== 1 ? 's' : ''} found`);
    setTimeout(() => setScanDoneMsg(null), 5000);
  });
  scanTaskRef.current = scanTask;

  const onTimespanChange = (ts: string) => {
    let nextPeriod = period;
    if (ts === 'minute' && (period === '1y' || period === '2y' || period === '90d')) nextPeriod = '30d';
    else if (ts === 'hour' && (period === '1y' || period === '2y')) nextPeriod = '90d';
    else if (ts === 'day' && period === '30d') nextPeriod = '1y';
    setTimespan(ts);
    if (nextPeriod !== period) setPeriod(nextPeriod);
    queryClient.invalidateQueries({ queryKey: ['historicalData', symbol, nextPeriod, ts] });
  };

  const onPeriodChange = (p: string) => {
    setPeriod(p);
    queryClient.invalidateQueries({ queryKey: ['historicalData', symbol, p, timespan] });
  };

  const handleScanSubmit = async (types: string[], startDate: string, endDate: string, fetchData: boolean) => {
    setScanSubmitting(true);
    try {
      const res = await runScannerRange({ ticker: symbol, scanner_types: types, start_date: startDate, end_date: endDate, fetch_missing_data: fetchData });
      setScanTaskId(res.task_id);
      setScanDialogOpen(false);
    } catch (err) {
      console.error('Failed to queue scan:', err);
    } finally {
      setScanSubmitting(false);
    }
  };

  if (loadingDetails) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-financial-blue"></div>
      </div>
    );
  }

  if (!details) {
    return (
      <div className="p-8 text-center bg-gray-900 rounded-xl border border-gray-800">
        <h2 className="text-2xl font-bold text-financial-light mb-4">Stock Not Found</h2>
        <p className="text-gray-400 mb-6">We couldn't find any data for {symbol}.</p>
        <Link to="/" className="inline-flex items-center px-4 py-2 bg-financial-blue text-white rounded-lg hover:bg-blue-600 transition-colors">
          <ArrowLeft className="h-4 w-4 mr-2" />
          Back to Dashboard
        </Link>
      </div>
    );
  }

  const events = Array.isArray(scannerResults) ? scannerResults : [];

  const currentPrice = liveData ? liveData.c : (details.latest_price || (historicalData.length > 0 ? historicalData[historicalData.length - 1].Close : 0));
  const prevClose = historicalData.length > 1 ? historicalData[historicalData.length - 2].Close : currentPrice;
  const change = currentPrice - prevClose;
  const changePct = (change / prevClose) * 100;
  const lastUpdatedTime = liveData ? new Date(liveData.e) : details?.last_updated ? new Date(details.last_updated) : null;
  const recentSplits = details.recent_splits || [];
  const splitPending = details.split_adjustment_pending === true;

  return (
    <div className="space-y-6 animate-fade-in pb-12">
      <div className="flex flex-col md:flex-row md:items-end justify-between gap-4">
        <div>
          <Link to="/" className="inline-flex items-center text-financial-blue hover:text-blue-400 mb-2 transition-colors">
            <ArrowLeft className="h-4 w-4 mr-1" />
            Back to Dashboard
          </Link>
          <div className="flex items-center space-x-3">
            <h1 className="text-4xl font-black text-financial-light tracking-tight">{symbol}</h1>
            <div className="px-2 py-0.5 bg-gray-800 rounded text-xs font-bold text-gray-400 uppercase">
              {details.info.sector || 'Unknown Sector'}
            </div>
            {tickerUniverses.map((u) => (
              <div key={u.id} className="px-2 py-0.5 bg-purple-900/50 border border-purple-700/50 rounded text-xs font-bold text-purple-300 uppercase">
                {u.name}
              </div>
            ))}
          </div>
          <p className="text-xl text-gray-400 font-medium">{details.info.longName}</p>
        </div>
        <div className="text-right">
          <div className="flex items-baseline justify-end space-x-2">
            {systemInfo?.data_mode === 'delayed' && (
              <span className="text-[10px] font-black bg-warning/20 text-warning px-1.5 py-0.5 rounded border border-warning/30 mr-1 uppercase tracking-tighter">
                15M Delayed
              </span>
            )}
            <span className="text-4xl font-bold text-financial-light">${currentPrice?.toFixed(2)}</span>
            <span className={`text-xl font-semibold flex items-center ${change >= 0 ? 'text-positive' : 'text-negative'}`}>
              {change >= 0 ? <TrendingUp className="h-5 w-5 mr-1" /> : <TrendingDown className="h-5 w-5 mr-1" />}
              {Math.abs(change).toFixed(2)} ({Math.abs(changePct).toFixed(2)}%)
            </span>
          </div>
          <p className="text-sm text-gray-500 mt-1 flex items-center justify-end">
            {isConnected && <span className="flex h-2 w-2 rounded-full bg-positive mr-2 animate-pulse" title="Live connection active"></span>}
            {systemInfo?.data_mode === 'delayed' ? 'Delayed Feed' : 'Live Feed'}: {lastUpdatedTime ? format(lastUpdatedTime, 'h:mm:ss a') : '—'}
          </p>
        </div>
      </div>

      {recentSplits.length > 0 && (
        <div className={`flex items-start gap-3 p-4 rounded-lg border ${splitPending ? 'bg-amber-500/10 border-amber-500/30' : 'bg-blue-500/10 border-blue-500/30'}`}>
          <Info className={`h-5 w-5 mt-0.5 flex-shrink-0 ${splitPending ? 'text-amber-400' : 'text-blue-400'}`} />
          <div className="text-sm">
            <p className={`font-semibold ${splitPending ? 'text-amber-300' : 'text-blue-300'}`}>
              {splitPending ? 'Split Adjustment Pending' : 'Recent Stock Split'}
            </p>
            <p className="text-gray-400 mt-1">
              {recentSplits.map((s) => (
                <span key={s.execution_date} className="mr-4">
                  {s.split_to}:{s.split_from} split on {format(new Date(s.execution_date + 'T00:00:00'), 'MMM d, yyyy')}
                  {s.adjusted ? <span className="text-positive ml-1">(adjusted)</span> : <span className="text-amber-400 ml-1">(pending adjustment)</span>}
                </span>
              ))}
            </p>
            {splitPending && <p className="text-amber-400/80 text-xs mt-1">Scanner event prices may be inconsistent until the split adjustment runs.</p>}
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2 space-y-6">
          <ChartPanel
            symbol={symbol} historicalData={historicalData} liveData={liveData} events={events}
            loadingHistorical={loadingHistorical} fetchingHistorical={fetchingHistorical}
            highlightDate={highlightDate}
            period={period} onPeriodChange={onPeriodChange}
            timespan={timespan} onTimespanChange={onTimespanChange}
            wsResolution={wsResolution} onWsResolution={setWsResolution}
            showST={showST} onShowST={setShowST}
            catchingUp={catchingUp} catchUpPending={catchUpMutation.isPending}
            onCatchUp={() => catchUpMutation.mutate(symbol)}
            details={details}
          />
          <ScannerHistoryPanel
            symbol={symbol} events={events}
            clearConfirmOpen={clearConfirmOpen} onClearConfirmOpen={setClearConfirmOpen}
            onClearHistory={() => clearEventsMutation.mutate()} clearHistoryPending={clearEventsMutation.isPending}
            scanDialogOpen={scanDialogOpen} onScanDialogOpen={setScanDialogOpen}
            scanTask={{ status: scanTask.status, done: scanTask.done, total: scanTask.total, error: scanTask.error }}
            scanDoneMsg={scanDoneMsg} onScanSubmit={handleScanSubmit} scanSubmitting={scanSubmitting}
            onHighlightDate={(date) => { setHighlightDate(date); window.scrollTo({ top: 0, behavior: 'smooth' }); }}
          />
        </div>
        <MetadataPanel
          symbol={symbol}
          details={details}
          scannerResults={scannerResults}
          events={events}
        />
      </div>
    </div>
  );
};

export default StockDetailPage;
