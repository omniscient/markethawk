import React from 'react';
import { Activity, BarChart3, Percent, ShieldCheck, TrendingDown, Trophy } from 'lucide-react';
import MetricCard from '../../components/ui/MetricCard';
import type { ReplayRunSummary } from '../../api/replay';

interface RunSummaryPanelProps {
  run: ReplayRunSummary | null;
}

const formatPct = (value: number | null | undefined): string =>
  value == null ? '-' : `${(value * 100).toFixed(1)}%`;

const formatNumber = (value: number | null | undefined, digits = 2): string =>
  value == null ? '-' : value.toFixed(digits);

const statusClass = (status: ReplayRunSummary['status']): string => {
  if (status === 'completed') return 'bg-green-500/10 text-green-400 border-green-500/30';
  if (status === 'failed') return 'bg-red-500/10 text-red-400 border-red-500/30';
  if (status === 'running') return 'bg-blue-500/10 text-blue-400 border-blue-500/30';
  return 'bg-yellow-500/10 text-yellow-400 border-yellow-500/30';
};

const RunSummaryPanel: React.FC<RunSummaryPanelProps> = ({ run }) => {
  if (!run) {
    return (
      <div className="h-full min-h-64 flex items-center justify-center border border-dashed border-gray-800 rounded-lg bg-gray-900/30">
        <p className="text-sm text-gray-500">Select a replay run.</p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-3">
        <div>
          <div className="flex items-center gap-3">
            <h2 className="text-xl font-black text-financial-light">{run.scanner_type}</h2>
            <span className={`px-2 py-1 rounded border text-[10px] font-bold uppercase tracking-widest ${statusClass(run.status)}`}>
              {run.status}
            </span>
          </div>
          <p className="text-xs text-gray-500 mt-1">
            {run.start_date} to {run.end_date} · universe #{run.universe_id} · {run.exit_fidelity}
          </p>
        </div>
        <div className="bg-gray-900 border border-gray-800 rounded-lg px-3 py-2 min-w-0">
          <p className="text-[10px] uppercase tracking-widest text-gray-500 font-bold">Data hash</p>
          <p className="font-mono text-xs text-gray-300 truncate max-w-[40rem]">{run.data_hash ?? 'pending'}</p>
        </div>
      </div>

      {run.error_message && (
        <div className="border border-red-500/30 bg-red-500/10 text-red-300 rounded-lg px-4 py-3 text-sm">
          {run.error_message}
        </div>
      )}

      <div className="grid grid-cols-1 sm:grid-cols-2 2xl:grid-cols-6 gap-4">
        <MetricCard title="Trades" value={run.total_trades} icon={BarChart3} color="blue" />
        <MetricCard title="Hit Rate" value={formatPct(run.hit_rate)} icon={Percent} color="green" />
        <MetricCard title="Expectancy" value={`${formatNumber(run.expectancy_r)}R`} icon={Trophy} color="purple" />
        <MetricCard title="Profit Factor" value={formatNumber(run.profit_factor)} icon={ShieldCheck} color="yellow" />
        <MetricCard title="Max Drawdown" value={`${formatNumber(run.max_drawdown_r)}R`} icon={TrendingDown} color="red" />
        <MetricCard title="MFE/MAE" value={formatNumber(run.mfe_mae_ratio)} icon={Activity} color="blue" />
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        {[
          ['Avg Bars Held', formatNumber(run.avg_bars_held, 1)],
          ['Median Bars Held', formatNumber(run.median_bars_held, 1)],
          ['Avg MFE', `${formatNumber(run.avg_mfe_pct)}%`],
          ['Avg MAE', `${formatNumber(run.avg_mae_pct)}%`],
        ].map(([label, value]) => (
          <div key={label} className="bg-gray-900/60 border border-gray-800 rounded-lg px-4 py-3">
            <p className="text-[10px] uppercase tracking-widest text-gray-500 font-bold">{label}</p>
            <p className="text-lg font-bold text-financial-light mt-1">{value}</p>
          </div>
        ))}
      </div>
    </div>
  );
};

export default RunSummaryPanel;
