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
  Newspaper
} from 'lucide-react';
import { format } from 'date-fns';

// Components
import Card from '../components/ui/Card';
import MetricCard from '../components/ui/MetricCard';
import Chart from '../components/ui/Chart';
import RecentEvents from '../components/RecentEvents';
import NewsFeed from '../components/NewsFeed';

// API
import { fetchStockDetails, refreshStockData } from '../api/stocks';
import { fetchScannerResults, fetchHistoricalData } from '../api/scanner';
import { fetchRecentNews } from '../api/news';

const StockDetailPage: React.FC = () => {
  const { ticker } = useParams<{ ticker: string }>();
  const symbol = ticker?.toUpperCase() || '';
  const [period, setPeriod] = React.useState('1y');
  const [timespan, setTimespan] = React.useState('day');
  const queryClient = useQueryClient();

  // 0. Refresh Data on Mount
  const refreshMutation = useMutation({
    mutationFn: (sym: string) => refreshStockData(sym, timespan),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['historicalData', symbol] });
    }
  });

  React.useEffect(() => {
    if (symbol) {
      refreshMutation.mutate(symbol);
    }
  }, [symbol, timespan]);

  // 1. Consolidated Details (Fundamentals, Pre-market)
  const { data: details, isLoading: loadingDetails } = useQuery({
    queryKey: ['stockDetails', symbol],
    queryFn: () => fetchStockDetails(symbol),
    enabled: !!symbol,
  });

  // 2. Historical Data (Variable Period)
  const { data: historicalResponse, isLoading: loadingHistorical, isFetching: fetchingHistorical } = useQuery({
    queryKey: ['historicalData', symbol, period, timespan],
    queryFn: () => fetchHistoricalData(symbol, period, timespan),
    enabled: !!symbol,
  });

  // 3. Scanner History
  const { data: scannerResults, isLoading: loadingScanner } = useQuery({
    queryKey: ['scannerResults', { ticker: symbol }],
    queryFn: () => fetchScannerResults({ ticker: symbol, limit: 10 }),
    enabled: !!symbol,
  });

  if (loadingDetails || loadingHistorical || loadingScanner) {
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

  const historicalData = historicalResponse?.data || [];
  const latestPrice = details.latest_price || (historicalData.length > 0 ? historicalData[historicalData.length - 1].Close : 0);
  const prevClose = historicalData.length > 1 ? historicalData[historicalData.length - 2].Close : latestPrice;
  const change = latestPrice - prevClose;
  const changePct = (change / prevClose) * 100;

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
          </div>
          <p className="text-xl text-gray-400 font-medium">{details.info.longName}</p>
        </div>

        <div className="text-right">
          <div className="flex items-baseline justify-end space-x-2">
            <span className="text-4xl font-bold text-financial-light">${latestPrice?.toFixed(2)}</span>
            <span className={`text-xl font-semibold flex items-center ${change >= 0 ? 'text-positive' : 'text-negative'}`}>
              {change >= 0 ? <TrendingUp className="h-5 w-5 mr-1" /> : <TrendingDown className="h-5 w-5 mr-1" />}
              {Math.abs(change).toFixed(2)} ({Math.abs(changePct).toFixed(2)}%)
            </span>
          </div>
          <p className="text-sm text-gray-500 mt-1">Last updated: {format(new Date(details.last_updated), 'h:mm:ss a')}</p>
        </div>
      </div>

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
              <div className="flex space-x-2">
                <div className="flex space-x-1 p-1 bg-gray-900 rounded-lg">
                  {['minute', 'hour', 'day'].map((t) => (
                    <button
                      key={t}
                      onClick={() => setTimespan(t)}
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
                  {['30d', '90d', '1y', '2y'].map((p) => (
                    <button
                      key={p}
                      onClick={() => setPeriod(p)}
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
                height={500}
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
          <Card title="Scanner Event History" icon={Zap as any}>
            <RecentEvents 
              events={(scannerResults || []).map(e => ({
                id: String(e.id),
                ticker: e.ticker,
                event_date: e.event_date,
                event_type: e.event_type,
                relative_volume: e.relative_volume,
                volume_spike_ratio: e.volume_spike_ratio,
                price_gap_pct: e.price_gap_pct,
                criteria_met: e.criteria_met
              }))} 
              maxItems={10} 
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
                { label: 'Verify Liquidity Hunt Event', status: scannerResults && scannerResults.some(e => e.event_type === 'liquidity_hunt') },
                { label: 'Check Extended Hours Volume', status: (details.pre_market.pre_market_volume || 0) > 100000 },
                { label: 'Confirm Sector Strength', status: true },
                { label: 'Identify Key Levels', status: !!details.pre_market.pre_market_high },
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
    </div>
  );
};

export default StockDetailPage;
