import React, { useState, useMemo } from 'react';
import { useScannerConfigs, useScorecard } from '../hooks/useScorecard';
import ScannerSummaryCard from '../components/scorecard/ScannerSummaryCard';

type Period = '7d' | '30d' | '90d' | 'all';

export const periodToDates = (period: Period): { start_date?: string; end_date?: string } => {
  if (period === 'all') return {};
  const days = period === '7d' ? 7 : period === '30d' ? 30 : 90;
  const end = new Date();
  const start = new Date();
  start.setDate(end.getDate() - days);
  return {
    start_date: start.toISOString().slice(0, 10),
    end_date: end.toISOString().slice(0, 10),
  };
};

const PERIODS: { label: string; value: Period }[] = [
  { label: '7D', value: '7d' },
  { label: '30D', value: '30d' },
  { label: '90D', value: '90d' },
  { label: 'ALL', value: 'all' },
];

const ScorecardOverview: React.FC = () => {
  const [period, setPeriod] = useState<Period>('30d');
  const dates = useMemo(() => periodToDates(period), [period]);

  const { data: configs, isLoading: loadingConfigs } = useScannerConfigs();
  const activeConfigs = configs?.filter((c) => c.is_active) ?? [];

  return (
    <div className="space-y-6 animate-fade-in">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-3xl font-black text-financial-light tracking-tight">SCANNER SCORECARD</h1>
          <p className="text-gray-400 mt-1 font-medium">Signal quality metrics across all scanner types</p>
        </div>
        <div className="flex items-center gap-2 bg-gray-800/50 p-1 rounded-lg border border-gray-700/50">
          {PERIODS.map((p) => (
            <button
              key={p.value}
              onClick={() => setPeriod(p.value)}
              className={`px-3 py-1.5 text-xs font-bold uppercase tracking-wider rounded transition-all ${
                period === p.value
                  ? 'bg-financial-blue text-white shadow-lg'
                  : 'text-gray-500 hover:text-white'
              }`}
            >
              {p.label}
            </button>
          ))}
        </div>
      </div>

      {/* Scanner Cards */}
      {loadingConfigs ? (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {[1, 2].map((i) => (
            <ScannerSummaryCard
              key={i}
              scannerType=""
              scannerName=""
              scorecard={null}
              isLoading={true}
            />
          ))}
        </div>
      ) : activeConfigs.length === 0 ? (
        <div className="flex flex-col items-center justify-center h-64 bg-gray-900/50 rounded-2xl border-2 border-dashed border-gray-800">
          <p className="text-gray-400 text-sm">No scanner configurations found.</p>
          <p className="text-gray-500 text-xs mt-1">Set up scanners on the Scanner page first.</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {activeConfigs.map((config) => (
            <ScorecardCard key={config.id} config={config} dates={dates} />
          ))}
        </div>
      )}
    </div>
  );
};

const ScorecardCard: React.FC<{
  config: { id: number; name: string; scanner_type: string };
  dates: { start_date?: string; end_date?: string };
}> = ({ config, dates }) => {
  const { data: scorecard, isLoading } = useScorecard(config.scanner_type, dates);

  return (
    <ScannerSummaryCard
      scannerType={config.scanner_type}
      scannerName={config.name}
      scorecard={scorecard ?? null}
      isLoading={isLoading}
    />
  );
};

export default ScorecardOverview;
