import React from 'react';
import { AlertTriangle, ShieldCheck, TrendingDown, TrendingUp } from 'lucide-react';
import type { RegimeBreakdownResponse, RegimeSlice } from '../../api/outcomes';

type RegimeInterpretation =
  | 'insufficient'
  | 'favorable'
  | 'hostile'
  | 'neutral';

interface RegimeRow {
  key: string;
  label: string;
  sampleSize: number;
  winRatePct: number | null;
  avgMfePct: number | null;
  avgMaePct: number | null;
  interpretation: RegimeInterpretation;
}

interface RegimePerformancePanelProps {
  data: RegimeBreakdownResponse | null | undefined;
  isLoading: boolean;
}

const MIN_SAMPLE_SIZE = 5;

const formatRegimeLabel = (regime: string): string => (
  regime
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (char) => char.toUpperCase())
);

const interpretRegime = (slice: RegimeSlice): RegimeInterpretation => {
  if (slice.sample_size < MIN_SAMPLE_SIZE) return 'insufficient';

  const winRate = slice.win_rate_pct ?? 0;
  const avgMfe = slice.avg_mfe_pct ?? 0;
  const avgMae = slice.avg_mae_pct ?? 0;
  const adverseMove = Math.abs(avgMae);

  if (winRate >= 60 && avgMfe > adverseMove) return 'favorable';
  if (winRate <= 40 || avgMae <= -3) return 'hostile';
  return 'neutral';
};

const regimeRows = (data: RegimeBreakdownResponse | null | undefined): RegimeRow[] => (
  Object.entries(data?.breakdown ?? {})
    .map(([key, slice]) => ({
      key,
      label: formatRegimeLabel(key),
      sampleSize: slice.sample_size,
      winRatePct: slice.win_rate_pct,
      avgMfePct: slice.avg_mfe_pct,
      avgMaePct: slice.avg_mae_pct,
      interpretation: interpretRegime(slice),
    }))
    .sort((a, b) => b.sampleSize - a.sampleSize)
);

const fmtPct = (value: number | null | undefined): string => (
  value === null || value === undefined ? 'N/A' : `${value.toFixed(1)}%`
);

const interpretationCopy: Record<RegimeInterpretation, { label: string; className: string; icon: React.ReactNode }> = {
  insufficient: {
    label: 'Insufficient evidence',
    className: 'text-amber-300 border-amber-700/50 bg-amber-950/20',
    icon: <AlertTriangle className="h-4 w-4" />,
  },
  favorable: {
    label: 'Candidate favorable regime',
    className: 'text-green-300 border-green-700/50 bg-green-950/20',
    icon: <TrendingUp className="h-4 w-4" />,
  },
  hostile: {
    label: 'Candidate hostile regime',
    className: 'text-red-300 border-red-700/50 bg-red-950/20',
    icon: <TrendingDown className="h-4 w-4" />,
  },
  neutral: {
    label: 'Neutral / mixed evidence',
    className: 'text-blue-300 border-blue-700/50 bg-blue-950/20',
    icon: <ShieldCheck className="h-4 w-4" />,
  },
};

const RegimePerformancePanel: React.FC<RegimePerformancePanelProps> = ({ data, isLoading }) => {
  const rows = regimeRows(data);

  return (
    <section className="bg-financial-gray rounded-lg border border-gray-700 p-5">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h2 className="text-sm font-bold text-financial-light uppercase tracking-wider">
            Regime Performance
          </h2>
          <p className="text-xs text-gray-500 mt-1">
            Per-regime scanner evidence. This is advisory evidence, not a trading rule.
          </p>
        </div>
        <div className="text-xs text-gray-500">
          {data?.total_events ?? 0} tagged events
        </div>
      </div>

      {isLoading && (
        <div className="mt-4 h-20 rounded border border-gray-800 bg-gray-900/50 p-4 text-sm text-gray-400">
          Loading regime evidence...
        </div>
      )}

      {!isLoading && rows.length === 0 && (
        <div className="mt-4 rounded border border-dashed border-gray-700 p-5 text-sm text-gray-400">
          No regime outcome evidence yet.
        </div>
      )}

      {!isLoading && rows.length > 0 && (
        <div className="mt-4 grid grid-cols-1 lg:grid-cols-3 gap-3">
          {rows.map((row) => (
            <RegimeCard key={row.key} row={row} />
          ))}
        </div>
      )}
    </section>
  );
};

const RegimeCard: React.FC<{ row: RegimeRow }> = ({ row }) => {
  const interpretation = interpretationCopy[row.interpretation];
  return (
    <div className="rounded border border-gray-800 bg-gray-900/40 p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-sm font-semibold text-financial-light">{row.label}</div>
          <div className="text-xs text-gray-500">n={row.sampleSize}</div>
        </div>
        <div className={`inline-flex items-center gap-1 rounded border px-2 py-1 text-[11px] font-semibold ${interpretation.className}`}>
          {interpretation.icon}
          {interpretation.label}
        </div>
      </div>

      <div className="mt-4 grid grid-cols-3 gap-3 text-xs">
        <Metric label="Win" value={fmtPct(row.winRatePct)} />
        <Metric label="Avg MFE" value={fmtPct(row.avgMfePct)} />
        <Metric label="Avg MAE" value={fmtPct(row.avgMaePct)} />
      </div>
    </div>
  );
};

const Metric: React.FC<{ label: string; value: string }> = ({ label, value }) => (
  <div>
    <div className="text-gray-500">{label}</div>
    <div className="mt-1 font-mono font-semibold text-financial-light">{value}</div>
  </div>
);

export default RegimePerformancePanel;
