
import { RefreshCw, Eye, EyeOff, BarChart2 } from 'lucide-react';
import Card from '../../components/ui/Card';
import Chart from '../../components/ui/Chart';
import { Activity, Info } from 'lucide-react';

export interface ChartPanelProps {
  symbol: string;
  historicalData: any[];
  loadingHistorical: boolean;
  fetchingHistorical: boolean;
  liveData: any;
  events: any[];
  highlightDate: string | undefined;
  period: string;
  onPeriodChange: (p: string) => void;
  timespan: string;
  onTimespanChange: (t: string) => void;
  wsResolution: 'minute' | 'second';
  onWsResolution: (r: 'minute' | 'second') => void;
  showST: boolean;
  onShowST: (v: boolean) => void;
  catchingUp: boolean;
  catchUpPending: boolean;
  onCatchUp: () => void;
  details: any;
}

export function ChartPanel({
  symbol, historicalData, loadingHistorical, fetchingHistorical, liveData,
  events, highlightDate, period, onPeriodChange, timespan, onTimespanChange,
  wsResolution, onWsResolution, showST, onShowST,
  catchingUp, catchUpPending, onCatchUp, details,
}: ChartPanelProps) {
  return (
    <>
      <Card
        title={`Performance History (${period})`}
        subtitle={`${timespan === 'day' ? 'Daily' : 'Intraday'} candlestick chart`}
        icon={BarChart2 as any}
        actions={
          <div className="flex flex-col md:flex-row space-y-2 md:space-y-0 md:space-x-3">
            <div className="flex items-center space-x-1 p-1 bg-gray-900 rounded-lg border border-gray-800">
              <span className="text-[10px] uppercase font-black text-gray-500 px-2">Live Update:</span>
              {(['minute', 'second'] as const).map((res) => (
                <button
                  key={res}
                  onClick={() => onWsResolution(res)}
                  className={`px-3 py-1 text-xs font-bold rounded-md transition-all ${
                    wsResolution === res ? 'bg-emerald-600 text-white shadow-lg' : 'text-gray-500 hover:text-white'
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
                      timespan === t ? 'bg-financial-blue text-white shadow-lg' : 'text-gray-400 hover:text-white hover:bg-gray-800'
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
                      period === p ? 'bg-financial-blue text-white shadow-lg' : 'text-gray-400 hover:text-white hover:bg-gray-800'
                    }`}
                  >
                    {p.toUpperCase()}
                  </button>
                ))}
              </div>
              <button
                onClick={onCatchUp}
                disabled={catchingUp || catchUpPending || historicalData.length === 0}
                className={`flex items-center space-x-2 px-3 py-1 text-xs font-bold rounded-md border transition-all ${
                  historicalData.length > 0
                    ? 'bg-financial-blue/10 border-financial-blue/30 text-financial-blue hover:bg-financial-blue hover:text-white'
                    : 'bg-gray-800 border-gray-700 text-gray-600 cursor-not-allowed'
                }`}
                title={historicalData.length === 0 ? "No data to catch up" : "Fetch missing history since last stored bar"}
              >
                <RefreshCw className={`h-3 w-3 ${catchingUp || catchUpPending ? 'animate-spin' : ''}`} />
                <span>{catchingUp ? 'Syncing…' : 'Catch Up'}</span>
              </button>
              <button
                onClick={() => onShowST(!showST)}
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

      {details && (
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
                <span className="text-financial-light font-semibold">{details.info.sector || 'N/A'}</span>
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
      )}
    </>
  );
}
