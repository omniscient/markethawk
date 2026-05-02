import React from 'react';
import { useParams, Link } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { 
  ArrowLeft, 
  Activity, 
  TrendingUp, 
  TrendingDown, 
  Globe, 
  Info, 
  Zap,
  BarChart2,
  Newspaper,
  RefreshCw,
  Eye,
  EyeOff
} from 'lucide-react';
import { format } from 'date-fns';

// Components
import Card from '../components/ui/Card';
import Chart from '../components/ui/Chart';
import RecentEvents from '../components/RecentEvents';
import NewsFeed from '../components/NewsFeed';

// API
import { fetchStockDetails, refreshStockData, syncMissingStockAggregates } from '../api/stocks';
import { fetchScannerResults, fetchHistoricalData, fetchUniversesForTicker } from '../api/scanner';
import { getSystemInfo } from '../api/system';
import { useLiveStockData } from '../hooks/useLiveStockData';
import ForceScanDialog from '../components/ForceScanDialog';
import { useScanTask } from '../hooks/useScanTask';
import { runScannerRange } from '../api/scanner';

const StockDetailPage: React.FC = () => {
  const { ticker } = useParams<{ ticker: string }>();
  const symbol = ticker?.toUpperCase() || '';
  const [period, setPeriod] = React.useState(localStorage.getItem('stock_detail_period') || '1y');
  const [timespan, setTimespan] = React.useState(localStorage.getItem('stock_detail_timespan') || 'day');
  const [wsResolution, setWsResolution] = React.useState<'minute' | 'second'>(
    (localStorage.getItem('stock_detail_ws_res') as 'minute' | 'second') || 'minute'
  );
  const [highlightDate, setHighlightDate] = React.useState<string | undefined>(undefined);
  const [catchingUp, setCatchingUp] = React.useState(false);
  const [showST, setShowST] = React.useState(localStorage.getItem('show_double_st') === 'true');
  const [scanDialogOpen, setScanDialogOpen] = React.useState(false);
  const [scanTaskId, setScanTaskId] = React.useState<string | null>(null);
  const [scanSubmitting, setScanSubmitting] = React.useState(false);
  const [scanDoneMsg, setScanDoneMsg] = React.useState<string | null>(null);
  const queryClient = useQueryClient();

  // 0. Refresh Data Mechanism
  const refreshMutation = useMutation({
    mutationFn: (variables: { sym: string; timespan: string; period: string }) => 
      refreshStockData(variables.sym, variables.timespan, variables.period),
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ 
        queryKey: ['historicalData', variables.sym, variables.period, variables.timespan] 
      });
      queryClient.invalidateQueries({ queryKey: ['stockDetails', variables.sym] });
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

  // Save settings to localStorage
  React.useEffect(() => {
    localStorage.setItem('stock_detail_period', period);
    localStorage.setItem('stock_detail_timespan', timespan);
    localStorage.setItem('stock_detail_ws_res', wsResolution);
    localStorage.setItem('show_double_st', String(showST));
  }, [period, timespan, wsResolution, showST]);

  // Background refresh on mount — fires after the page renders from cache/DB.
  // Uses a ref to avoid re-triggering if the component re-renders before the effect runs.
  const didRefreshRef = React.useRef<string | null>(null);
  React.useEffect(() => {
    if (symbol && didRefreshRef.current !== symbol) {
      didRefreshRef.current = symbol;
      refreshMutation.mutate({ sym: symbol, timespan, period });
    }
  }, [symbol, period, timespan, refreshMutation]);

  // Period synchronization logic now handled in onTimespanChange to reduce re-renders.

  // 1. Consolidated Details (Fundamentals, Pre-market)
  const { data: details, isLoading: loadingDetails } = useQuery({
    queryKey: ['stockDetails', symbol],
    queryFn: () => fetchStockDetails(symbol),
    enabled: !!symbol,
    staleTime: 60_000,        // don't refetch within 1 min of navigating back
  });

  // 2. Historical Data (Variable Period)
  const { data: historicalResponse, isLoading: loadingHistorical, isFetching: fetchingHistorical } = useQuery({
    queryKey: ['historicalData', symbol, period, timespan],
    queryFn: () => fetchHistoricalData(symbol, period, timespan),
    enabled: !!symbol,
    staleTime: 30_000,
  });

  const historicalData = historicalResponse?.data || [];

  // Clear the catch-up indicator once the re-fetch triggered by onSuccess completes
  React.useEffect(() => {
    if (catchingUp && !fetchingHistorical) {
      setCatchingUp(false);
    }
  }, [fetchingHistorical, catchingUp]);

  // AUTO-REFRESH LOGIC: Detect "No Data" and request history from Polygon
  // We use a ref to track which (symbol, period, timespan) combos we've already tried to auto-refresh
  const autoRefreshAttempts = React.useRef<Set<string>>(new Set());
  
  React.useEffect(() => {
    if (!symbol || loadingHistorical || fetchingHistorical || historicalData.length > 0 || refreshMutation.isPending) return;
    
    const attemptKey = `${symbol}-${period}-${timespan}`;
    if (autoRefreshAttempts.current.has(attemptKey)) return;

    // If we reach here, we have no data and haven't tried an auto-refresh for this view yet
    console.log(`[StockDetail] No data found for ${attemptKey}, triggering auto-refresh...`);
    autoRefreshAttempts.current.add(attemptKey);
    
    // Switch UI length to 30D as requested to avoid loading too much
    if (period !== '30d') {
      setPeriod('30d');
      // Pre-emptively block the 30d attempt too
      autoRefreshAttempts.current.add(`${symbol}-30d-${timespan}`);
    }
    
    refreshMutation.mutate({ sym: symbol, timespan, period: '30d' });
  }, [symbol, period, timespan, historicalData.length, loadingHistorical, fetchingHistorical, refreshMutation.isPending, refreshMutation]);

  // 3. Scanner History — does NOT block page render (no loadingScanner in gate below)
  const { data: scannerResults } = useQuery({
    queryKey: ['scannerResults', { ticker: symbol }],
    queryFn: () => fetchScannerResults({ ticker: symbol, limit: 10 }),
    enabled: !!symbol,
    staleTime: 120_000,       // scanner history is slow and rarely changes
  });

  // 4. Live Data Subscription
  const { liveData, isConnected } = useLiveStockData(symbol, wsResolution);

  // 5. System Info (for Plan Detection)
  const { data: systemInfo } = useQuery({
    queryKey: ['systemInfo'],
    queryFn: getSystemInfo
  });

  // 6. Universe Membership Tags
  const { data: tickerUniverses = [] } = useQuery({
    queryKey: ['tickerUniverses', symbol],
    queryFn: () => fetchUniversesForTicker(symbol),
    enabled: !!symbol,
    staleTime: 300_000,
  });

  // 7. Scan Task Polling
  const scanTaskRef = React.useRef<ReturnType<typeof useScanTask> | null>(null);

  const scanTask = useScanTask(scanTaskId, () => {
    queryClient.invalidateQueries({ queryKey: ['scannerResults', { ticker: symbol }] });
    const count = scanTaskRef.current?.eventsDetected ?? 0;
    setScanTaskId(null);
    setScanDoneMsg(`Done — ${count} event${count !== 1 ? 's' : ''} found`);
    setTimeout(() => setScanDoneMsg(null), 5000);
  });
  scanTaskRef.current = scanTask;

  const lastUpdatedTime = liveData
    ? new Date(liveData.e)
    : details?.last_updated
      ? new Date(details.last_updated)
      : null;

  // Only block on details — the header/price paints immediately and is the LCP element.
  // The chart renders an inline skeleton while historicalData is still loading.
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
        <Link
          to="/"
          className="inline-flex items-center px-4 py-2 bg-financial-blue text-white rounded-lg hover:bg-blue-600 transition-colors"
        >
          <ArrowLeft className="h-4 w-4 mr-2" />
          Back to Dashboard
        </Link>
      </div>
    );
  }


  // Safely extract results array if wrapped in an object or from a paginated response
  const resultsArray = Array.isArray(scannerResults)
    ? scannerResults
    : (scannerResults as any)?.data || (scannerResults as any)?.results || [];

  const events = resultsArray.map((e: any) => ({
    id: String(e.id),
    ticker: e.ticker,
    event_date: e.event_date,
    scanner_type: e.scanner_type,
    summary: e.summary,
    severity: e.severity,
    indicators: e.indicators,
    criteria_met: e.criteria_met
  }));

  // Use live data if available, otherwise fallback to details or historical
  const currentPrice = liveData ? liveData.c : (details.latest_price || (historicalData.length > 0 ? historicalData[historicalData.length - 1].Close : 0));
  const latestPrice = currentPrice;
  const prevClose = historicalData.length > 1 ? historicalData[historicalData.length - 2].Close : latestPrice;
  const change = latestPrice - prevClose;
  const changePct = (change / prevClose) * 100;

  const handleEventClick = (event: any) => {
    setHighlightDate(event.event_date);
    // Scroll to top where chart is
    window.scrollTo({ top: 0, behavior: 'smooth' });
  };

  const handleScanSubmit = async (
    types: string[], startDate: string, endDate: string, fetchData: boolean
  ) => {
    setScanSubmitting(true);
    try {
      const res = await runScannerRange({
        ticker: symbol,
        scanner_types: types,
        start_date: startDate,
        end_date: endDate,
        fetch_missing_data: fetchData,
      });
      setScanTaskId(res.task_id);
      setScanDialogOpen(false);
    } catch (err) {
      console.error('Failed to queue scan:', err);
    } finally {
      setScanSubmitting(false);
    }
  };

  const _handleRefreshCheck = (newTimespan?: string, newPeriod?: string) => {
    if (refreshMutation.isPending) return;

    const ts = newTimespan || timespan;
    const p = newPeriod || period;
    
    // Evaluate stale state
    const latestBar = historicalData.length > 0 ? historicalData[historicalData.length - 1] : null;
    const now = new Date();
    let isStale = false;

    if (latestBar) {
      const lastBarTime = new Date(latestBar.Date || latestBar.timestamp);
      const gapMs = now.getTime() - lastBarTime.getTime();
      
      // Determine if stale based on timespan
      if (ts === 'minute' && gapMs > 60 * 1000) isStale = true;
      else if (ts === 'hour' && gapMs > 60 * 60 * 1000) isStale = true;
      else if (ts === 'day' && gapMs > 24 * 60 * 60 * 1000) isStale = true;
    } else {
      isStale = true; // No data for this timeframe in DB
    }

    if (isStale) {
      refreshMutation.mutate({ sym: symbol, timespan: ts, period: p });
    }
  };

  const onTimespanChange = (ts: string) => {
    // 1. Determine next period proactively to avoid multiple renders
    let nextPeriod = period;
    if (ts === 'minute') {
      if (period === '1y' || period === '2y' || period === '90d') {
        nextPeriod = '30d';
      }
    } else if (ts === 'hour') {
      if (period === '1y' || period === '2y') {
        nextPeriod = '90d';
      }
    } else if (ts === 'day') {
      if (period === '30d') {
        nextPeriod = '1y';
      }
    }

    setTimespan(ts);
    if (nextPeriod !== period) {
      setPeriod(nextPeriod);
    }
    
    // Invalidate specific query to trigger fresh fetch from DB if needed
    queryClient.invalidateQueries({ queryKey: ['historicalData', symbol, nextPeriod, ts] });
  };

  const onPeriodChange = (p: string) => {
    setPeriod(p);
    queryClient.invalidateQueries({ queryKey: ['historicalData', symbol, p, timespan] });
  };

  const recentSplits = details.recent_splits || [];
  const splitPending = details.split_adjustment_pending === true;

  return (
    <div className="space-y-6 animate-fade-in pb-12">
      {/* Breadcrumbs & Header */}
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
              <div
                key={u.id}
                className="px-2 py-0.5 bg-purple-900/50 border border-purple-700/50 rounded text-xs font-bold text-purple-300 uppercase"
              >
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
            <span className="text-4xl font-bold text-financial-light">${latestPrice?.toFixed(2)}</span>
            <span className={`text-xl font-semibold flex items-center ${change >= 0 ? 'text-positive' : 'text-negative'}`}>
              {change >= 0 ? <TrendingUp className="h-5 w-5 mr-1" /> : <TrendingDown className="h-5 w-5 mr-1" />}
              {Math.abs(change).toFixed(2)} ({Math.abs(changePct).toFixed(2)}%)
            </span>
          </div>
          <p className="text-sm text-gray-500 mt-1 flex items-center justify-end">
            {isConnected && (
              <span className="flex h-2 w-2 rounded-full bg-positive mr-2 animate-pulse" title="Live connection active"></span>
            )}
            {systemInfo?.data_mode === 'delayed' ? 'Delayed Feed' : 'Live Feed'}: {format(lastUpdatedTime, 'h:mm:ss a')}
          </p>
        </div>
      </div>

      {/* Split Warning Banner */}
      {recentSplits.length > 0 && (
        <div className={`flex items-start gap-3 p-4 rounded-lg border ${
          splitPending
            ? 'bg-amber-500/10 border-amber-500/30'
            : 'bg-blue-500/10 border-blue-500/30'
        }`}>
          <Info className={`h-5 w-5 mt-0.5 flex-shrink-0 ${splitPending ? 'text-amber-400' : 'text-blue-400'}`} />
          <div className="text-sm">
            <p className={`font-semibold ${splitPending ? 'text-amber-300' : 'text-blue-300'}`}>
              {splitPending ? 'Split Adjustment Pending' : 'Recent Stock Split'}
            </p>
            <p className="text-gray-400 mt-1">
              {recentSplits.map((s: any) => (
                <span key={s.execution_date} className="mr-4">
                  {s.split_to}:{s.split_from} split on {format(new Date(s.execution_date + 'T00:00:00'), 'MMM d, yyyy')}
                  {s.adjusted
                    ? <span className="text-positive ml-1">(adjusted)</span>
                    : <span className="text-amber-400 ml-1">(pending adjustment)</span>
                  }
                </span>
              ))}
            </p>
            {splitPending && (
              <p className="text-amber-400/80 text-xs mt-1">
                Scanner event prices may be inconsistent until the split adjustment runs.
              </p>
            )}
          </div>
        </div>
      )}

      {/* Main Content Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Left Column: Charts & Stats */}
        <div className="lg:col-span-2 space-y-6">
          {/* Daily Price Chart */}
          <Card 
            title={`Performance History (${period})`} 
            subtitle={`${timespan === 'day' ? 'Daily' : 'Intraday'} candlestick chart`}
            icon={BarChart2 as any}
            actions={
              <div className="flex flex-col md:flex-row space-y-2 md:space-y-0 md:space-x-3">
                {/* Live Resolution Toggle */}
                <div className="flex items-center space-x-1 p-1 bg-gray-900 rounded-lg border border-gray-800">
                  <span className="text-[10px] uppercase font-black text-gray-500 px-2">Live Update:</span>
                  {(['minute', 'second'] as const).map((res) => (
                    <button
                      key={res}
                      onClick={() => setWsResolution(res)}
                      className={`px-3 py-1 text-xs font-bold rounded-md transition-all ${
                        wsResolution === res 
                          ? 'bg-emerald-600 text-white shadow-lg' 
                          : 'text-gray-500 hover:text-white'
                      }`}
                    >
                      {res === 'minute' ? '1M' : '1S'}
                    </button>
                  ))}
                </div>

                <div className="flex space-x-2">
                  <div className="flex space-x-1 p-1 bg-gray-900 rounded-lg">
                  {['minute', 'hour', 'day'].map((t) => (
                    <button
                      key={t}
                      onClick={() => onTimespanChange(t)}
                      className={`px-3 py-1 text-xs font-bold rounded-md transition-colors ${
                        timespan === t 
                          ? 'bg-financial-blue text-white shadow-lg' 
                          : 'text-gray-400 hover:text-white hover:bg-gray-800'
                      }`}
                    >
                      {t === 'minute' ? '1M' : t === 'hour' ? '1H' : '1D'}
                    </button>
                  ))}

                </div>
                <div className="flex space-x-1 p-1 bg-gray-900 rounded-lg">
                  {['30d', '90d', '1y', '2y', 'all'].map((p) => (
                    <button
                      key={p}
                      onClick={() => onPeriodChange(p)}
                      className={`px-3 py-1 text-xs font-bold rounded-md transition-colors ${
                        period === p 
                          ? 'bg-financial-blue text-white shadow-lg' 
                          : 'text-gray-400 hover:text-white hover:bg-gray-800'
                      }`}
                    >
                      {p.toUpperCase()}
                    </button>
                  ))}
                </div>
                
                <button
                  onClick={() => catchUpMutation.mutate(symbol)}
                  disabled={catchingUp || catchUpMutation.isPending || historicalData.length === 0}
                  className={`flex items-center space-x-2 px-3 py-1 text-xs font-bold rounded-md border transition-all ${
                    historicalData.length > 0
                      ? 'bg-financial-blue/10 border-financial-blue/30 text-financial-blue hover:bg-financial-blue hover:text-white'
                      : 'bg-gray-800 border-gray-700 text-gray-600 cursor-not-allowed'
                  }`}
                  title={historicalData.length === 0 ? "No data to catch up" : "Fetch missing history since last stored bar"}
                >
                  <RefreshCw className={`h-3 w-3 ${catchingUp || catchUpMutation.isPending ? 'animate-spin' : ''}`} />
                  <span>{catchingUp ? 'Syncing…' : 'Catch Up'}</span>
                </button>

                <button
                  onClick={() => setShowST(!showST)}
                  className={`flex items-center space-x-2 px-3 py-1 text-xs font-bold rounded-md border transition-all ${
                    showST
                      ? 'bg-amber-500/10 border-amber-500/30 text-amber-500 hover:bg-amber-500 hover:text-white shadow-[0_0_10px_rgba(245,158,11,0.2)]'
                      : 'bg-gray-800 border-gray-700 text-gray-400 hover:text-white hover:bg-gray-700'
                  }`}
                  title="Toggle Double SuperTrend ATR Indicator"
                >
                  {showST ? <Eye className="h-3 w-3" /> : <EyeOff className="h-3 w-3" />}
                  <span>ST ATR</span>
                </button>
              </div>
            </div>
          }
          >

            {(loadingHistorical || (fetchingHistorical && !historicalData.length)) ? (
              <div className="flex flex-col items-center justify-center h-[500px] bg-gray-900/50 rounded-lg">
                <div className="animate-spin rounded-full h-10 w-10 border-b-2 border-financial-blue mb-4"></div>
                <p className="text-gray-500 font-medium">Fetching historical data...</p>
              </div>
            ) : (
              <Chart
                data={historicalData}
                type="candlestick"
                xKey="Date"
                timespan={timespan}
                height={500}
                events={events}
                highlightDate={highlightDate}
                symbol={symbol}
                liveData={liveData}
                showDoubleSuperTrend={showST}
              />
            )}
          </Card>


          {/* Key Statistics Grid */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <Card title="Market Profile" icon={Info as any}>
              <div className="space-y-4">
                <div className="flex justify-between items-center py-2 border-b border-gray-800">
                  <span className="text-gray-400">Market Cap</span>
                  <span className="text-financial-light font-semibold">
                    ${details.info.marketCap ? (details.info.marketCap / 1e9).toFixed(2) + 'B' : 'N/A'}
                  </span>
                </div>
                <div className="flex justify-between items-center py-2 border-b border-gray-800">
                  <span className="text-gray-400">Industry</span>
                  <span className="text-financial-light font-semibold truncate ml-4 max-w-[200px]">
                    {details.info.industry || 'N/A'}
                  </span>
                </div>
                <div className="flex justify-between items-center py-2">
                  <span className="text-gray-400">Sector</span>
                  <span className="text-financial-light font-semibold">
                    {details.info.sector || 'N/A'}
                  </span>
                </div>
              </div>
            </Card>

            <Card title="Extended Hours" icon={Activity as any}>
              <div className="space-y-4">
                <div className="flex justify-between items-center py-2 border-b border-gray-800">
                  <span className="text-gray-400">PM Volume</span>
                  <span className="text-financial-light font-semibold">
                    {details.pre_market.pre_market_volume?.toLocaleString() || '0'}
                  </span>
                </div>
                <div className="flex justify-between items-center py-2 border-b border-gray-800">
                  <span className="text-gray-400">PM High</span>
                  <span className="text-positive font-semibold">
                    ${details.pre_market.pre_market_high?.toFixed(2) || 'N/A'}
                  </span>
                </div>
                <div className="flex justify-between items-center py-2">
                  <span className="text-gray-400">PM Low</span>
                  <span className="text-negative font-semibold">
                    ${details.pre_market.pre_market_low?.toFixed(2) || 'N/A'}
                  </span>
                </div>
              </div>
            </Card>
          </div>

          {/* Scanner Event History */}
          <Card
            title="Scanner Event History"
            icon={Zap as any}
            actions={
              <div className="flex items-center space-x-2">
                {scanTask.status === 'connecting' && (
                  <span className="text-xs text-gray-400 font-semibold animate-pulse">Queued…</span>
                )}
                {scanTask.status === 'running' && scanTask.total === 0 && (
                  <span className="text-xs text-financial-blue font-semibold animate-pulse">Preparing…</span>
                )}
                {scanTask.status === 'running' && scanTask.total > 0 && (
                  <span className="text-xs text-financial-blue font-semibold animate-pulse">
                    Scanning… {scanTask.done} / {scanTask.total} days
                  </span>
                )}
                {scanDoneMsg && (
                  <span className="text-xs text-positive font-semibold">{scanDoneMsg}</span>
                )}
                {scanTask.status === 'failed' && (
                  <span className="text-xs text-negative font-semibold" title={scanTask.error ?? ''}>
                    Scan failed
                  </span>
                )}
                <button
                  onClick={() => setScanDialogOpen(true)}
                  disabled={scanTask.status === 'connecting' || scanTask.status === 'running'}
                  className={`flex items-center space-x-2 px-3 py-1 text-xs font-bold rounded-md border transition-all ${
                    scanTask.status === 'connecting' || scanTask.status === 'running'
                      ? 'bg-gray-800 border-gray-700 text-gray-500 cursor-not-allowed'
                      : 'bg-financial-blue/10 border-financial-blue/30 text-financial-blue hover:bg-financial-blue hover:text-white'
                  }`}
                >
                  <Zap className={`h-3 w-3 ${scanTask.status === 'running' ? 'animate-pulse' : ''}`} />
                  <span>Run Scanner</span>
                </button>
              </div>
            }
          >
            <RecentEvents
              events={events}
              maxItems={10}
              onEventClick={handleEventClick}
            />
          </Card>
        </div>

        {/* Right Column: News & Insights */}
        <div className="space-y-6">
          <Card title="Stock Specific News" icon={Newspaper as any}>
            <NewsFeed ticker={symbol} limit={10} />
          </Card>
          
          <Card title="Trader Plan Checklist" icon={Globe as any}>
            <div className="space-y-3">
              {[
                { label: 'Scanner Alert Detected', status: events.length > 0 },
                { label: 'Check Extended Hours Volume', status: (details.pre_market.pre_market_volume || 0) > 100000 },
                { label: 'Confirm Sector Strength', status: true },
                { label: 'Review Catalyst Summary', status: scannerResults && scannerResults.some((e: any) => e.metadata?.catalyst_summary) },
              ].map((item, idx) => (
                <div key={idx} className="flex items-center space-x-3 p-3 bg-gray-800/50 rounded-lg">
                  <div className={`h-2 w-2 rounded-full ${item.status ? 'bg-positive' : 'bg-gray-600'}`}></div>
                  <span className={`text-sm ${item.status ? 'text-financial-light' : 'text-gray-500'}`}>{item.label}</span>
                </div>
              ))}
              <div className="mt-4 p-4 bg-financial-blue/10 border border-financial-blue/20 rounded-lg">
                <p className="text-xs text-blue-300 leading-relaxed">
                  <strong>Pro Tip:</strong> Stocks in play often test high/low liquidity before a major move. Watch for wick rejections at {symbol}'s PM High (${details.pre_market.pre_market_high?.toFixed(2) || 'N/A'}).
                </p>
              </div>
            </div>
          </Card>
        </div>
      </div>
      <ForceScanDialog
        isOpen={scanDialogOpen}
        isSubmitting={scanSubmitting}
        onClose={() => setScanDialogOpen(false)}
        onSubmit={handleScanSubmit}
      />
    </div>
  );
};

export default StockDetailPage;
