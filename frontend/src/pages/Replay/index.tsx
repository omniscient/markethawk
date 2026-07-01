import React, { useEffect, useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { BarChart3, GitCompare, History, RefreshCw } from 'lucide-react';
import Card from '../../components/ui/Card';
import Button from '../../components/ui/Button';
import Modal from '../../components/ui/Modal';
import StockChart from '../../components/ui/StockChart';
import { fetchScannerConfigs } from '../../api/scanner';
import { fetchStockUniverses } from '../../api/universe';
import { fetchHistoricalData } from '../../api/scanner';
import { useStrategies } from '../../api/trading';
import {
  useCompareReplayRuns,
  useReplayAnalytics,
  useReplayRun,
  useReplayRuns,
  useReplayTrades,
} from '../../api/replay';
import type { ReplayRunSummary, ReplayTrade } from '../../api/replay';
import RunCreateForm from './RunCreateForm';
import RunSummaryPanel from './RunSummaryPanel';
import AnalyticsPanel from './AnalyticsPanel';
import { buildReplayMarkers, buildReplayPriceLines } from '../../utils/replayChartOverlays';

const formatMetric = (value: number | null | undefined, suffix = ''): string =>
  value == null ? '-' : `${value.toFixed(2)}${suffix}`;

const statusClass = (status: ReplayRunSummary['status']): string => {
  if (status === 'completed') return 'text-green-400';
  if (status === 'failed') return 'text-red-400';
  if (status === 'running') return 'text-blue-400';
  return 'text-yellow-400';
};

const ReplayPage: React.FC = () => {
  const [selectedRunUuid, setSelectedRunUuid] = useState<string | null>(null);
  const [selectedTrade, setSelectedTrade] = useState<ReplayTrade | null>(null);
  const [compareIds, setCompareIds] = useState<string[]>([]);

  const { data: scannerConfigs = [] } = useQuery({
    queryKey: ['scannerConfigs'],
    queryFn: fetchScannerConfigs,
  });
  const { data: universes = [] } = useQuery({
    queryKey: ['universes', 'replay'],
    queryFn: () => fetchStockUniverses({ include_stats: true }),
  });
  const { data: strategies = [] } = useStrategies(true);
  const runsQuery = useReplayRuns({ limit: 50 });
  const runs = runsQuery.data ?? [];
  const selectedRunQuery = useReplayRun(selectedRunUuid);
  const selectedRun = selectedRunQuery.data ?? runs.find((run) => run.uuid === selectedRunUuid) ?? null;
  const tradesQuery = useReplayTrades(selectedRunUuid);
  const analyticsQuery = useReplayAnalytics(selectedRunUuid);
  const compareRuns = useCompareReplayRuns();

  useEffect(() => {
    if (!selectedRunUuid && runs.length > 0) {
      setSelectedRunUuid(runs[0].uuid);
    }
  }, [runs, selectedRunUuid]);

  const selectedTradeChart = useQuery({
    queryKey: ['replay', 'trade-chart', selectedTrade?.ticker],
    queryFn: () => fetchHistoricalData(selectedTrade!.ticker, '6mo', 'day'),
    enabled: Boolean(selectedTrade),
  });

  const compareSummary = useMemo(() => {
    const comparisons = compareRuns.data?.comparisons ?? [];
    if (comparisons.length === 0) return null;
    const mismatches = comparisons.filter((comparison) => !comparison.data_hash_match).length;
    return `${comparisons.length - mismatches}/${comparisons.length} hash pairs match`;
  }, [compareRuns.data]);

  const toggleCompare = (uuid: string) => {
    setCompareIds((current) => {
      if (current.includes(uuid)) return current.filter((id) => id !== uuid);
      if (current.length >= 5) return current;
      return [...current, uuid];
    });
  };

  const runComparison = () => {
    if (compareIds.length >= 2) {
      compareRuns.mutate(compareIds);
    }
  };

  return (
    <div className="space-y-6 animate-fade-in">
      <div className="flex flex-col xl:flex-row xl:items-center justify-between gap-4">
        <div>
          <h1 className="text-3xl font-black text-financial-light tracking-tight">SIGNAL REPLAY</h1>
          <p className="text-gray-400 mt-1 font-medium">Canonical replay runs with reproducible manifests and trade-level audit trails</p>
        </div>
        <Button icon={RefreshCw} variant="secondary" onClick={() => runsQuery.refetch()}>
          Refresh
        </Button>
      </div>

      <Card title="Create Replay Run" icon={History}>
        <RunCreateForm
          scannerConfigs={scannerConfigs}
          strategies={strategies}
          universes={universes}
          onCreated={(run) => setSelectedRunUuid(run.uuid)}
        />
      </Card>

      <div className="grid grid-cols-1 2xl:grid-cols-[minmax(26rem,34rem)_1fr] gap-6">
        <Card
          title="Runs"
          icon={BarChart3}
          actions={
            <Button
              icon={GitCompare}
              size="sm"
              variant="secondary"
              disabled={compareIds.length < 2}
              loading={compareRuns.isPending}
              onClick={runComparison}
            >
              Compare
            </Button>
          }
          noPadding
        >
          <div className="divide-y divide-gray-800">
            {runs.map((run) => {
              const active = selectedRunUuid === run.uuid;
              return (
                <div
                  key={run.uuid}
                  className={`p-4 cursor-pointer transition-colors ${active ? 'bg-financial-blue/10' : 'hover:bg-gray-800/50'}`}
                  onClick={() => setSelectedRunUuid(run.uuid)}
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="flex items-center gap-2">
                        <input
                          type="checkbox"
                          checked={compareIds.includes(run.uuid)}
                          onChange={(event) => {
                            event.stopPropagation();
                            toggleCompare(run.uuid);
                          }}
                          onClick={(event) => event.stopPropagation()}
                          className="h-4 w-4 rounded border-gray-700 bg-gray-900"
                        />
                        <p className="font-bold text-financial-light truncate">{run.scanner_type}</p>
                      </div>
                      <p className="text-xs text-gray-500 mt-1">
                        {run.start_date} to {run.end_date} · {run.total_trades} trades
                      </p>
                      <p className="font-mono text-[10px] text-gray-500 mt-2 truncate">{run.data_hash ?? 'hash pending'}</p>
                    </div>
                    <div className="text-right shrink-0">
                      <p className={`text-xs font-bold uppercase ${statusClass(run.status)}`}>{run.status}</p>
                      <p className="text-sm text-gray-300 mt-1">{formatMetric(run.expectancy_r)}R</p>
                    </div>
                  </div>
                </div>
              );
            })}
            {runs.length === 0 && (
              <div className="px-4 py-16 text-center text-sm text-gray-500">No replay runs yet.</div>
            )}
          </div>
          {compareSummary && (
            <div className="border-t border-gray-800 bg-gray-900/70 px-4 py-3 text-sm text-gray-300">
              {compareSummary}
            </div>
          )}
        </Card>

        <Card title="Run Summary" icon={History}>
          <RunSummaryPanel run={selectedRun} />
        </Card>
      </div>

      <AnalyticsPanel metrics={analyticsQuery.data} />

      <Card title="Trades" noPadding>
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-gray-800">
            <thead className="bg-gray-900/80">
              <tr>
                {['Ticker', 'Signal', 'Direction', 'Entry', 'Exit', 'Reason', 'Return', 'R', 'Regime'].map((header) => (
                  <th key={header} className="px-4 py-3 text-left text-[10px] font-bold uppercase tracking-widest text-gray-500">
                    {header}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-800">
              {(tradesQuery.data?.trades ?? []).map((trade) => (
                <tr
                  key={trade.id}
                  onClick={() => setSelectedTrade(trade)}
                  className="hover:bg-gray-800/50 cursor-pointer"
                >
                  <td className="px-4 py-3 font-bold text-financial-light">{trade.ticker}</td>
                  <td className="px-4 py-3 text-sm text-gray-300">{trade.signal_date.slice(0, 10)}</td>
                  <td className="px-4 py-3 text-sm text-gray-300 uppercase">{trade.direction}</td>
                  <td className="px-4 py-3 text-sm text-gray-300">{formatMetric(trade.entry_price, '')}</td>
                  <td className="px-4 py-3 text-sm text-gray-300">{formatMetric(trade.exit_price, '')}</td>
                  <td className="px-4 py-3 text-sm text-gray-300">{trade.exit_reason ?? '-'}</td>
                  <td className={`px-4 py-3 text-sm font-bold ${(trade.return_pct ?? 0) >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                    {formatMetric(trade.return_pct, '%')}
                  </td>
                  <td className={`px-4 py-3 text-sm font-bold ${(trade.return_r ?? 0) >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                    {formatMetric(trade.return_r, 'R')}
                  </td>
                  <td className="px-4 py-3 text-sm text-gray-300">
                    {[trade.regime_trend, trade.regime_vol].filter(Boolean).join(' / ') || '-'}
                  </td>
                </tr>
              ))}
              {(tradesQuery.data?.trades ?? []).length === 0 && (
                <tr>
                  <td colSpan={9} className="px-4 py-16 text-center text-sm text-gray-500">No replay trades for this run.</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </Card>

      <Modal
        isOpen={Boolean(selectedTrade)}
        onClose={() => setSelectedTrade(null)}
        title={selectedTrade ? `${selectedTrade.ticker} Trade Drill-Down` : 'Trade Drill-Down'}
        size="xl"
      >
        {selectedTrade && (
          <div className="space-y-4">
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
              {[
                ['Signal', selectedTrade.signal_date.slice(0, 10)],
                ['Return', formatMetric(selectedTrade.return_r, 'R')],
                ['MFE', formatMetric(selectedTrade.mfe_pct, '%')],
                ['MAE', formatMetric(selectedTrade.mae_pct, '%')],
              ].map(([label, value]) => (
                <div key={label} className="bg-gray-950 border border-gray-800 rounded-lg px-4 py-3">
                  <p className="text-[10px] uppercase tracking-widest text-gray-500 font-bold">{label}</p>
                  <p className="text-lg font-bold text-financial-light mt-1">{value}</p>
                </div>
              ))}
            </div>

            <div className="border border-gray-800 rounded-lg overflow-hidden bg-gray-950">
              <StockChart
                data={selectedTradeChart.data?.data ?? []}
                type="candlestick"
                timespan="day"
                height={420}
                symbol={selectedTrade.ticker}
                highlightDate={selectedTrade.signal_date}
                replayMarkers={buildReplayMarkers(selectedTrade)}
                priceLines={buildReplayPriceLines(selectedTrade)}
              />
            </div>
          </div>
        )}
      </Modal>
    </div>
  );
};

export default ReplayPage;
