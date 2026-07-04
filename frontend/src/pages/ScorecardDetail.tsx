import React, { useState, useMemo } from 'react';
import { useParams, Link } from 'react-router-dom';
import { ArrowLeft, AlertTriangle } from 'lucide-react';
import { useScorecard, useEdgeDecay, useIntervals, useDistribution, useExplanationTraits, useExplanationArchetypes } from '../hooks/useScorecard';
import type { ExplanationArchetype, ExplanationTrait } from '../api/outcomes';
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

const fmtPct = (value: number | null | undefined): string => (
  value === null || value === undefined ? '—' : `${value.toFixed(1)}%`
);

const traitOutcomeScore = (trait: ExplanationTrait): number => (
  (trait.win_rate_pct ?? 0) + (trait.avg_mfe_pct ?? 0) - Math.abs(trait.avg_mae_pct ?? 0)
);

const compactTraitType = (type: string): string => type.replace(/_/g, ' ');

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
  const { data: traits, isLoading: loadingTraits } = useExplanationTraits(scannerType, scorecardParams);
  const { data: archetypes, isLoading: loadingArchetypes } = useExplanationArchetypes(scannerType, scorecardParams);

  const displayName = scannerType?.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase()) ?? '';
  const rankedTraits = traits?.traits ?? [];
  const positiveTraits = rankedTraits
    .filter((trait) => (trait.win_rate_pct ?? 0) >= 50)
    .sort((a, b) => traitOutcomeScore(b) - traitOutcomeScore(a))
    .slice(0, 4);
  const negativeTraits = rankedTraits
    .filter((trait) => (trait.win_rate_pct ?? 0) < 50)
    .sort((a, b) => traitOutcomeScore(a) - traitOutcomeScore(b))
    .slice(0, 4);
  const hasTraitData = rankedTraits.length > 0;
  const archetypeRows = archetypes?.archetypes ?? [];

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
                aria-pressed={period === p.value}
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

      {/* Explanation Intelligence */}
      <div className="grid grid-cols-1 xl:grid-cols-3 gap-6">
        <section className="xl:col-span-2 bg-financial-gray rounded-lg border border-gray-700 p-5">
          <div className="flex items-center justify-between gap-3 mb-4">
            <div>
              <h2 className="text-sm font-bold text-financial-light uppercase tracking-wider">Explanation Traits</h2>
              <p className="text-xs text-gray-500 mt-1">{traits?.event_count ?? 0} complete signals in scope</p>
            </div>
            {rankedTraits.some((trait) => trait.warnings.length > 0) && (
              <div className="flex items-center gap-1 text-amber-300 text-xs font-semibold">
                <AlertTriangle className="h-4 w-4" />
                Low sample
              </div>
            )}
          </div>

          {loadingTraits && (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              {[1, 2, 3, 4].map((i) => (
                <div key={i} className="h-16 bg-gray-800 rounded animate-pulse" />
              ))}
            </div>
          )}

          {!loadingTraits && !hasTraitData && (
            <div className="border border-dashed border-gray-700 rounded-lg p-5 text-sm text-gray-400">
              No explanation trait performance yet.
            </div>
          )}

          {!loadingTraits && hasTraitData && (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
              <TraitList title="Top Positive Traits" traits={positiveTraits} />
              <TraitList title="Top Negative Traits" traits={negativeTraits} />
            </div>
          )}
        </section>

        <section className="bg-financial-gray rounded-lg border border-gray-700 p-5">
          <div className="mb-4">
            <h2 className="text-sm font-bold text-financial-light uppercase tracking-wider">Archetypes</h2>
            <p className="text-xs text-gray-500 mt-1">{archetypes?.event_count ?? 0} assigned signals</p>
          </div>

          {loadingArchetypes && <div className="h-24 bg-gray-800 rounded animate-pulse" />}

          {!loadingArchetypes && archetypeRows.length === 0 && (
            <div className="border border-dashed border-gray-700 rounded-lg p-5 text-sm text-gray-400">
              No explanation archetypes yet.
            </div>
          )}

          {!loadingArchetypes && archetypeRows.length > 0 && (
            <div className="space-y-3">
              {archetypeRows.slice(0, 4).map((archetype) => (
                <ArchetypeRow key={archetype.cluster_id} archetype={archetype} />
              ))}
            </div>
          )}
        </section>
      </div>

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

const TraitList: React.FC<{ title: string; traits: ExplanationTrait[] }> = ({ title, traits }) => (
  <div>
    <h3 className="text-xs font-bold text-gray-400 uppercase tracking-wider mb-3">{title}</h3>
    <div className="space-y-2">
      {traits.length === 0 && (
        <div className="border border-dashed border-gray-800 rounded-lg p-3 text-sm text-gray-500">
          No traits in this group.
        </div>
      )}
      {traits.map((trait) => (
        <div key={`${title}-${trait.trait_type}-${trait.trait_key}`} className="border border-gray-800 rounded-lg p-3">
          <div className="flex items-start justify-between gap-3">
            <div>
              <div className="text-sm font-semibold text-financial-light">{trait.trait_label}</div>
              <div className="text-xs text-gray-500 capitalize">{compactTraitType(trait.trait_type)} • n={trait.sample_size}</div>
            </div>
            <div className="text-right">
              <div className="text-sm font-bold text-financial-light">{fmtPct(trait.win_rate_pct)}</div>
              <div className="text-xs text-gray-500">MFE {fmtPct(trait.avg_mfe_pct)}</div>
            </div>
          </div>
          {trait.warnings.length > 0 && (
            <div className="mt-2 text-xs text-amber-300">{trait.warnings[0].message}</div>
          )}
        </div>
      ))}
    </div>
  </div>
);

const ArchetypeRow: React.FC<{ archetype: ExplanationArchetype }> = ({ archetype }) => (
  <div className="border border-gray-800 rounded-lg p-3">
    <div className="text-sm font-semibold text-financial-light">{archetype.label}</div>
    <div className="mt-2 grid grid-cols-3 gap-2 text-xs">
      <div>
        <div className="text-gray-500">Sample</div>
        <div className="text-financial-light font-semibold">{archetype.sample_size}</div>
      </div>
      <div>
        <div className="text-gray-500">Win</div>
        <div className="text-financial-light font-semibold">{fmtPct(archetype.return_profile.win_rate_pct)}</div>
      </div>
      <div>
        <div className="text-gray-500">MFE</div>
        <div className="text-financial-light font-semibold">{fmtPct(archetype.return_profile.avg_mfe_pct)}</div>
      </div>
    </div>
    {archetype.warnings.length > 0 && (
      <div className="mt-2 text-xs text-amber-300">{archetype.warnings[0].message}</div>
    )}
  </div>
);

export default ScorecardDetail;
