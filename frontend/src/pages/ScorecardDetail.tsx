import React, { useState, useMemo } from 'react';
import { useParams, Link } from 'react-router-dom';
import { ArrowLeft } from 'lucide-react';
import { useScorecard, useEdgeDecay, useIntervals, useDistribution } from '../hooks/useScorecard';
import HeroMetrics from '../components/scorecard/HeroMetrics';
import EdgeDecayChart from '../components/scorecard/EdgeDecayChart';
import DistributionChart from '../components/scorecard/DistributionChart';
import IntervalTable from '../components/scorecard/IntervalTable';
import BackfillPanel from '../components/scorecard/BackfillPanel';
import SignalTable from '../components/scorecard/SignalTable';

type Period = '7d' | '30d' | '90d' | 'all';

const periodToDates = (period: Period): { start_date?: string; end_date?: string } => {
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

const SEVERITIES = ['All Severities', 'high', 'medium', 'low'] as const;

const ScorecardDetail: React.FC = () => {
  const { scannerType } = useParams<{ scannerType: string }>();
  const [period, setPeriod] = useState<Period>('30d');
  const [severity, setSeverity] = useState<string>('');
  const dates = useMemo(() => periodToDates(period), [period]);

  const scorecardParams = useMemo(
    () => ({ ...dates, ...(severity ? { severity } : {}) }),
    [dates, severity],
  );

  const { data: scorecard, isLoading: loadingScorecard, isError: scorecardError } = useScorecard(scannerType, scorecardParams);
  const { data: edgeDecay, isLoading: loadingEdge } = useEdgeDecay(scannerType, dates);
  const { data: intervals, isLoading: loadingIntervals } = useIntervals(scannerType);
  const { data: distribution, isLoading: loadingDist } = useDistribution(scannerType);

  const displayName = scannerType?.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase()) ?? '';

  return (
    <div className="space-y-6 animate-fade-in">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <Link to="/scorecard" className="text-gray-400 hover:text-financial-light transition-colors">
            <ArrowLeft className="h-5 w-5" />
          </Link>
          <div>
            <h1 className="text-3xl font-black text-financial-light tracking-tight">{displayName.toUpperCase()}</h1>
            <p className="text-gray-400 mt-0.5 text-sm font-medium">Signal quality analysis</p>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <div className="flex items-center gap-1 bg-gray-800/50 p-1 rounded-lg border border-gray-700/50">
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

          <select
            value={severity}
            onChange={(e) => setSeverity(e.target.value)}
            className="bg-gray-900 border border-gray-700 text-financial-light rounded-lg px-3 py-1.5 text-xs font-bold focus:outline-none focus:ring-1 focus:ring-financial-blue"
          >
            {SEVERITIES.map((s) => (
              <option key={s} value={s === 'All Severities' ? '' : s}>
                {s === 'All Severities' ? s : s.charAt(0).toUpperCase() + s.slice(1)}
              </option>
            ))}
          </select>
        </div>
      </div>

      {/* Error state */}
      {scorecardError && (
        <div className="bg-red-900/20 border border-red-500/30 rounded-lg p-4 text-red-400 text-sm">
          Failed to load scorecard data. The backend may not have outcome data for this scanner type yet.
        </div>
      )}

      {/* Loading state for hero metrics */}
      {loadingScorecard && (
        <div className="space-y-4">
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
            {[1, 2, 3, 4].map((i) => (
              <div key={i} className="bg-financial-gray rounded-lg border border-gray-700 p-5 animate-pulse">
                <div className="h-3 bg-gray-700 rounded w-1/2 mb-2" />
                <div className="h-8 bg-gray-700 rounded w-2/3" />
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Hero Metrics */}
      {scorecard && <HeroMetrics scorecard={scorecard} />}

      {/* No data state */}
      {!loadingScorecard && !scorecardError && !scorecard && (
        <div className="flex flex-col items-center justify-center h-48 bg-gray-900/50 rounded-2xl border-2 border-dashed border-gray-800">
          <p className="text-gray-400 text-sm">No outcome data yet for this scanner type.</p>
          <p className="text-gray-500 text-xs mt-1">Run a backfill below to populate historical metrics.</p>
        </div>
      )}

      {/* Charts Row */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <EdgeDecayChart data={edgeDecay ?? []} isLoading={loadingEdge} />
        <DistributionChart data={distribution ?? []} isLoading={loadingDist} />
      </div>

      {/* Interval Breakdown */}
      <IntervalTable data={intervals ?? {}} isLoading={loadingIntervals} />

      {/* Signal Drill-Down */}
      {scannerType && (
        <SignalTable
          scannerType={scannerType}
          startDate={dates.start_date}
          endDate={dates.end_date}
          severity={severity || undefined}
        />
      )}

      {/* Backfill Panel */}
      {scannerType && <BackfillPanel scannerType={scannerType} />}
    </div>
  );
};

export default ScorecardDetail;
