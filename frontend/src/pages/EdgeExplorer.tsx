import React, { useState } from 'react';
import { useQuery, useMutation } from '@tanstack/react-query';
import {
  BarChart2,
  TrendingUp,
  Calendar,
  Layers,
  Search,
  Target,
  AlertTriangle,
} from 'lucide-react';

// Per spec Req 7: library cast, does not count against @ts-expect-error budget.
// strictFunctionTypes: (value: number, name: string) not assignable to Formatter<ValueType, NameType>
// because ValueType includes string and array; runtime behavior is correct.
type TooltipFormatterFn = NonNullable<React.ComponentProps<typeof Tooltip>['formatter']>;

// Components
import Card from '../components/ui/Card';
import MetricCard from '../components/ui/MetricCard';
import {
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  ScatterChart,
  Scatter,
  ZAxis,
  Cell,
  Legend,
  AreaChart,
  Area,
  ComposedChart,
  Bar,
  Line,
} from 'recharts';

// API functions
import { fetchScannerConfigs, getSignalQualityDistribution } from '../api/scanner';
import type { EdgeDistributionEvent, EdgeStatEntry } from '../api/scanner';
import { apiClient } from '../api/client';
import CorrelationHeatmap from '../components/CorrelationHeatmap';
import { fetchCorrelations, triggerAnalysis } from '../api/analysis';
import {
  fetchEdgeDecay,
  fetchExplanationArchetypes,
  fetchExplanationTraits,
} from '../api/outcomes';
import type {
  EdgeDecayPoint,
  ExplanationArchetype,
  ExplanationTrait,
} from '../api/outcomes';

const fmtPct = (value: number | null | undefined): string => (
  value === null || value === undefined ? 'N/A' : `${value.toFixed(1)}%`
);

const traitValue = (trait: ExplanationTrait): string => `${trait.trait_type}:${trait.trait_key}`;

const traitTypeLabel = (type: string): string => {
  const labels: Record<string, string> = {
    criterion_passed: 'Criterion',
    criterion_failed: 'Failed Criterion',
    warning: 'Warning',
    confidence_input: 'Confidence',
  };
  return labels[type] ?? type.replace(/_/g, ' ');
};

const traitOptionLabel = (trait: ExplanationTrait): string => (
  `${traitTypeLabel(trait.trait_type)}: ${trait.trait_label}`
);

const traitChartLabel = (trait: ExplanationTrait): string => (
  trait.trait_label.length > 22 ? `${trait.trait_label.slice(0, 19)}...` : trait.trait_label
);

const EdgeExplorer: React.FC = () => {
  const [period, setPeriod] = useState<'weekly' | 'monthly' | 'quarterly'>('monthly');
  const [ticker, setTicker] = useState<string>('');
  const [scannerType, setScannerType] = useState<string>('');
  const [traitFilter, setTraitFilter] = useState<string>('');
  const [archetypeFilter, setArchetypeFilter] = useState<string>('');

  // Fetch scanner configurations for the dropdown
  const { data: configs } = useQuery({
    queryKey: ['scannerConfigs'],
    queryFn: fetchScannerConfigs,
  });

  // Fetch edge stats
  const { data: stats, isLoading: loadingStats } = useQuery<EdgeStatEntry[]>({
    queryKey: ['edgeStats', period, ticker, scannerType],
    queryFn: async () => {
      const params = new URLSearchParams({ period });
      if (ticker) params.append('ticker', ticker);
      if (scannerType) params.append('scanner_type', scannerType);

      const response = await apiClient.get<EdgeStatEntry[]>(`/scanner/edge-stats?${params.toString()}`);
      return response.data;
    }
  });

  // Fetch distribution data
  const { data: distribution, isLoading: loadingDist } = useQuery<{ events: EdgeDistributionEvent[] }>({
    queryKey: ['edgeDistribution', ticker, scannerType],
    queryFn: async () => {
      const params = new URLSearchParams();
      if (ticker) params.append('ticker', ticker);
      if (scannerType) params.append('scanner_type', scannerType);

      const response = await apiClient.get<{ events: EdgeDistributionEvent[] }>(`/scanner/edge-distribution?${params.toString()}`);
      return response.data;
    }
  });

  const { data: correlations, isLoading: loadingCorr, refetch: refetchCorr } = useQuery({
    queryKey: ['correlations', scannerType],
    queryFn: () => fetchCorrelations(scannerType || undefined),
    retry: false,
  });

  const { data: explanationTraits, isLoading: loadingTraits } = useQuery({
    queryKey: ['edgeExplanationTraits', scannerType],
    queryFn: () => fetchExplanationTraits({ scanner_type: scannerType }),
    enabled: !!scannerType,
  });

  const { data: explanationArchetypes, isLoading: loadingArchetypes } = useQuery({
    queryKey: ['edgeExplanationArchetypes', scannerType],
    queryFn: () => fetchExplanationArchetypes({ scanner_type: scannerType }),
    enabled: !!scannerType,
  });

  const { data: edgeDecay, isLoading: loadingEdgeDecay } = useQuery<EdgeDecayPoint[]>({
    queryKey: ['edgeExplanationDecay', scannerType, period],
    queryFn: () => fetchEdgeDecay(scannerType, { period }),
    enabled: !!scannerType,
  });

  const triggerMutation = useMutation({
    mutationFn: () => triggerAnalysis(scannerType || undefined),
    onSuccess: (data) => {
      alert(`Analysis triggered. Task ID: ${data.task_id}`);
      refetchCorr();
    },
  });

  const { data: qualityDist, isLoading: loadingQualityDist } = useQuery({
    queryKey: ['signalQualityDistribution', scannerType],
    queryFn: () => getSignalQualityDistribution({
      scanner_type: scannerType || undefined,
    }),
  });

  const isLoading = loadingStats || loadingDist;

  const events = distribution?.events || [];
  const traitRows = explanationTraits?.traits ?? [];
  const archetypeRows = explanationArchetypes?.archetypes ?? [];
  const selectedTraits = traitFilter
    ? traitRows.filter((trait) => traitValue(trait) === traitFilter)
    : traitRows.slice(0, 8);
  const selectedArchetypes = archetypeFilter
    ? archetypeRows.filter((archetype) => String(archetype.cluster_id) === archetypeFilter)
    : archetypeRows.slice(0, 6);
  const traitChartData = selectedTraits.map((trait) => ({
    name: traitChartLabel(trait),
    label: trait.trait_label,
    sample_size: trait.sample_size,
    win_rate_pct: trait.win_rate_pct ?? 0,
    avg_mfe_pct: trait.avg_mfe_pct ?? 0,
    avg_mae_pct: trait.avg_mae_pct ?? 0,
  }));
  const archetypeChartData = selectedArchetypes.map((archetype) => ({
    name: archetype.label.length > 26 ? `${archetype.label.slice(0, 23)}...` : archetype.label,
    label: archetype.label,
    sample_size: archetype.sample_size,
    win_rate_pct: archetype.return_profile.win_rate_pct ?? 0,
    avg_mfe_pct: archetype.return_profile.avg_mfe_pct ?? 0,
  }));
  
  // Calculate aggregate metrics
  const avgGap = events.length > 0 ? events.reduce((acc, e) => acc + (e.gap_pct || 0), 0) / events.length : 0;
  const avgFade = events.length > 0 ? events.reduce((acc, e) => acc + (e.fade_pct || 0), 0) / events.length : 0;
  const avgRange = events.length > 0 ? events.reduce((acc, e) => acc + (e.day_range_pct || 0), 0) / events.length : 0;

  return (
    <div className="space-y-6 animate-fade-in">
      {/* Header */}
      <div className="flex flex-col xl:flex-row xl:items-center justify-between gap-4">
        <div>
          <h1 className="text-3xl font-black text-financial-light tracking-tight">STATEDGE EXPLORER</h1>
          <p className="text-gray-400 mt-1 font-medium">Quantify your scanning strategy performance across market cycles</p>
        </div>
        
        <div className="flex flex-wrap items-center gap-3 bg-gray-800/50 p-2 rounded-xl border border-gray-700/50 backdrop-blur-sm">
          {/* Scanner Type Selector */}
          <div className="relative min-w-[200px]">
            <Target className="absolute left-3 top-1/2 transform -translate-y-1/2 h-4 w-4 text-financial-blue" />
            <select 
              aria-label="Strategy filter"
              className="pl-9 pr-4 py-2 w-full bg-gray-900 border border-gray-700 rounded-lg text-xs font-bold focus:outline-none focus:ring-1 focus:ring-financial-blue text-white uppercase tracking-wider"
              value={scannerType}
              onChange={(e) => {
                setScannerType(e.target.value);
                setTraitFilter('');
                setArchetypeFilter('');
              }}
            >
              <option value="">All Strategies</option>
              {configs?.map(c => (
                <option key={c.scanner_type} value={c.scanner_type}>{c.name}</option>
              ))}
            </select>
          </div>

          {/* Ticker Filter */}
          <div className="relative">
            <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 h-4 w-4 text-gray-500" />
            <input 
              type="text" 
              placeholder="FILTER TICKER..." 
              className="pl-9 pr-4 py-2 bg-gray-900 border border-gray-700 rounded-lg text-xs font-bold focus:outline-none focus:ring-1 focus:ring-financial-blue text-white w-32 tracking-wider"
              value={ticker}
              onChange={(e) => setTicker(e.target.value.toUpperCase())}
            />
          </div>
          
          {/* Period Toggle */}
          <div className="flex items-center bg-gray-900 rounded-lg p-1 border border-gray-700">
            {(['weekly', 'monthly', 'quarterly'] as const).map((p) => (
              <button
                key={p}
                onClick={() => setPeriod(p)}
                className={`px-4 py-1.5 text-[10px] font-black uppercase tracking-widest rounded-md transition-all ${
                  period === p ? 'bg-financial-blue text-white shadow-lg' : 'text-gray-500 hover:text-white'
                }`}
              >
                {p}
              </button>
            ))}
          </div>
        </div>
      </div>

      {isLoading ? (
        <div className="flex flex-col items-center justify-center h-96 bg-gray-900/50 rounded-2xl border-2 border-dashed border-gray-800">
           <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-financial-blue mb-4"></div>
           <p className="text-gray-400 font-bold tracking-widest uppercase text-xs">Crunching historical edge data...</p>
        </div>
      ) : (
        <>
          {/* Metrics Row */}
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
            <MetricCard
              title="Frequency/Period"
              value={stats && stats.length > 0 ? (stats.reduce((acc, s) => acc + s.event_count, 0) / stats.length).toFixed(1) : '0'}
              icon={Layers}
              color="blue"
            />
            <MetricCard
              title="Avg Gap Persistence"
              value={`${avgGap.toFixed(2)}%`}
              icon={TrendingUp}
              color="green"
            />
            <MetricCard
              title="Avg Fade Severity"
              value={`${avgFade.toFixed(2)}%`}
              icon={Target}
              color="red"
            />
            <MetricCard
              title="Volatility Window"
              value={`${avgRange.toFixed(2)}%`}
              icon={BarChart2}
              color="purple"
            />
          </div>

          <ExplanationResearchSection
            scannerType={scannerType}
            traitRows={traitRows}
            archetypeRows={archetypeRows}
            traitFilter={traitFilter}
            archetypeFilter={archetypeFilter}
            onTraitFilter={setTraitFilter}
            onArchetypeFilter={setArchetypeFilter}
            selectedTraits={selectedTraits}
            selectedArchetypes={selectedArchetypes}
            traitChartData={traitChartData}
            archetypeChartData={archetypeChartData}
            edgeDecay={edgeDecay ?? []}
            isLoading={loadingTraits || loadingArchetypes || loadingEdgeDecay}
          />

          {/* Distribution Charts */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <Card title="Gapper Retention Correlation" icon={TrendingUp}>
              <div className="h-[400px]">
                <ResponsiveContainer width="100%" height="100%">
                  <ScatterChart margin={{ top: 20, right: 20, bottom: 20, left: 20 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#374151" vertical={false} />
                    <XAxis 
                      type="number" 
                      dataKey="gap_pct" 
                      name="Gap" 
                      unit="%" 
                      stroke="#4B5563"
                      tick={{fontSize: 10, fontWeight: 'bold'}}
                      label={{ value: 'INITIAL GAP %', position: 'bottom', fill: '#9CA3AF', fontSize: 10, fontWeight: 'bold', offset: 0 }}
                    />
                    <YAxis 
                      type="number" 
                      dataKey="fade_pct" 
                      name="Fade" 
                      unit="%" 
                      stroke="#4B5563"
                      tick={{fontSize: 10, fontWeight: 'bold'}}
                      label={{ value: 'FADE FROM HIGH %', angle: -90, position: 'insideLeft', fill: '#9CA3AF', fontSize: 10, fontWeight: 'bold' }}
                    />
                    <ZAxis type="number" range={[60, 400]} />
                    <Tooltip 
                      cursor={{ strokeDasharray: '3 3' }} 
                      contentStyle={{ backgroundColor: '#111827', border: '1px solid #374151', borderRadius: '12px', boxShadow: '0 10px 15px -3px rgba(0, 0, 0, 0.5)' }}
                      itemStyle={{ color: '#F9FAFB', fontSize: '12px' }}
                      labelStyle={{ color: '#9CA3AF', fontSize: '10px', fontWeight: 'bold' }}
                    />
                    <Legend verticalAlign="top" height={36} iconType="circle" wrapperStyle={{fontSize: '10px', fontWeight: 'bold', textTransform: 'uppercase'}}/>
                    <Scatter name="Scanner Events" data={events} fill="#3B82F6">
                      {events.map((entry, index) => (
                        <Cell key={`cell-${index}`} fill={entry.fade_pct > entry.gap_pct ? '#EF4444' : '#10B981'} fillOpacity={0.6} />
                      ))}
                    </Scatter>
                  </ScatterChart>
                </ResponsiveContainer>
              </div>
              <p className="text-[10px] font-bold uppercase tracking-widest text-gray-500 mt-4 text-center">
                <span className="text-positive">Green</span>: Market Held. <span className="text-negative">Red</span>: Significant Distribution Detected.
              </p>
            </Card>

            <Card title="Strategy Lifecycle Trends" icon={Calendar}>
              <div className="h-[400px]">
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={stats || []} margin={{ top: 10, right: 30, left: 0, bottom: 0 }}>
                    <defs>
                      <linearGradient id="colorGap" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor="#10B981" stopOpacity={0.4}/>
                        <stop offset="95%" stopColor="#10B981" stopOpacity={0}/>
                      </linearGradient>
                      <linearGradient id="colorFade" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor="#EF4444" stopOpacity={0.4}/>
                        <stop offset="95%" stopColor="#EF4444" stopOpacity={0}/>
                      </linearGradient>
                    </defs>
                    <XAxis dataKey="label" stroke="#4B5563" tick={{fontSize: 10, fontWeight: 'bold'}} />
                    <YAxis stroke="#4B5563" tick={{fontSize: 10, fontWeight: 'bold'}} />
                    <CartesianGrid strokeDasharray="3 3" stroke="#374151" vertical={false} />
                    <Tooltip 
                      contentStyle={{ backgroundColor: '#111827', border: '1px solid #374151', borderRadius: '12px' }}
                      itemStyle={{ color: '#F9FAFB', fontSize: '12px' }}
                      labelStyle={{ color: '#9CA3AF', fontSize: '12px', fontWeight: 'bold' }}
                    />
                    <Legend verticalAlign="top" height={36} iconType="rect" wrapperStyle={{fontSize: '10px', fontWeight: 'bold', textTransform: 'uppercase'}}/>
                    <Area 
                      type="monotone" 
                      dataKey="avg_gap_pct" 
                      name="Retention"
                      stroke="#10B981" 
                      strokeWidth={3}
                      fillOpacity={1} 
                      fill="url(#colorGap)" 
                    />
                    <Area 
                      type="monotone" 
                      dataKey="avg_fade_pct" 
                      name="Degradation"
                      stroke="#EF4444" 
                      strokeWidth={3}
                      fillOpacity={1} 
                      fill="url(#colorFade)" 
                    />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
            </Card>
          </div>

          {/* Aggregate Table */}
          <Card title="Performance Audit Log" icon={BarChart2}>
            <div className="overflow-x-auto">
              <table className="min-w-full border-separate border-spacing-y-2">
                <thead>
                  <tr className="text-left text-[10px] font-black text-gray-500 uppercase tracking-widest">
                    <th className="px-6 py-3">Audit Period</th>
                    <th className="px-6 py-3">Sample Size</th>
                    <th className="px-6 py-3">Avg Gap %</th>
                    <th className="px-6 py-3">Avg Fade %</th>
                    <th className="px-6 py-3">Avg Range %</th>
                    <th className="px-6 py-3">Avg Relative Vol</th>
                  </tr>
                </thead>
                <tbody>
                  {stats?.map((row, i) => (
                    <tr key={i} className="group hover:scale-[1.002] transition-transform duration-200">
                      <td className="px-6 py-4 bg-gray-800/40 rounded-l-xl text-sm font-black text-financial-light">{row.label}</td>
                      <td className="px-6 py-4 bg-gray-800/40 text-sm text-gray-300 font-mono italic">{row.event_count} EVENTS</td>
                      <td className="px-6 py-4 bg-gray-800/40 text-sm font-bold text-positive">+{row.avg_gap_pct}%</td>
                      <td className="px-6 py-4 bg-gray-800/40 text-sm font-bold text-negative">{row.avg_fade_pct}%</td>
                      <td className="px-6 py-4 bg-gray-800/40 text-sm font-bold text-purple-400">{row.avg_day_range_pct}%</td>
                      <td className="px-6 py-4 bg-gray-800/40 rounded-r-xl text-sm font-bold text-financial-blue">{row.avg_rel_vol}x</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>

          {/* Feature Correlations */}
          <Card title="Feature Correlations" icon={BarChart2}>
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <p className="text-gray-400 text-xs">
                  Correlation between signal features and subsequent returns.
                </p>
                <button
                  onClick={() => triggerMutation.mutate()}
                  disabled={triggerMutation.isPending}
                  className="px-3 py-1.5 text-[10px] font-black uppercase tracking-widest rounded-md bg-gray-700 hover:bg-financial-blue text-white transition-all disabled:opacity-50"
                >
                  {triggerMutation.isPending ? 'Queuing...' : 'Run Analysis'}
                </button>
              </div>

              {loadingCorr ? (
                <div className="flex items-center justify-center h-32 text-gray-500 text-xs">
                  Loading correlation data...
                </div>
              ) : correlations ? (
                <CorrelationHeatmap data={correlations} />
              ) : (
                <div className="flex items-center justify-center h-32 text-gray-500 text-xs text-center">
                  No analysis data yet. Run analysis to populate this panel.
                </div>
              )}
            </div>
          </Card>

          <Card title="Signal Quality Validation" icon={TrendingUp}>
            {loadingQualityDist ? (
              <div className="flex items-center justify-center h-48 text-gray-500">Loading…</div>
            ) : !qualityDist?.deciles?.length ? (
              <div className="flex items-center justify-center h-48 text-gray-500 text-sm">
                No outcome data yet — scores will appear here once ScannerOutcomeSummary rows are complete.
              </div>
            ) : (
              <>
                <p className="text-xs text-gray-500 mb-3">
                  Weight set:{' '}
                  <span className="font-mono">{qualityDist.signal_ranker_version}</span>
                </p>
                <ResponsiveContainer width="100%" height={260}>
                  <ComposedChart data={qualityDist.deciles} margin={{ top: 10, right: 30, left: 0, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
                    <XAxis dataKey="decile" tick={{ fill: '#9CA3AF', fontSize: 10 }} />
                    <YAxis
                      yAxisId="left"
                      tickFormatter={(v) => `${v.toFixed(1)}%`}
                      tick={{ fill: '#9CA3AF', fontSize: 10 }}
                      label={{ value: 'Avg EOD %', angle: -90, position: 'insideLeft', fill: '#6B7280', fontSize: 11 }}
                    />
                    <YAxis
                      yAxisId="right"
                      orientation="right"
                      tickFormatter={(v) => `${(v * 100).toFixed(0)}%`}
                      tick={{ fill: '#9CA3AF', fontSize: 10 }}
                      label={{ value: 'Follow-through', angle: 90, position: 'insideRight', fill: '#6B7280', fontSize: 11 }}
                    />
                    <Tooltip
                      contentStyle={{ backgroundColor: '#1F2937', border: '1px solid #374151' }}
                      formatter={((value: number, name: string) => {
                        if (name === 'avg_eod_pct') return [`${value?.toFixed(2)}%`, 'Avg EOD %'];
                        if (name === 'follow_through_rate') return [`${(value * 100).toFixed(1)}%`, 'Follow-through'];
                        return [value, name];
                      }) as unknown as TooltipFormatterFn}
                    />
                    <Legend />
                    <Bar yAxisId="left" dataKey="avg_eod_pct" fill="#3B82F6" name="avg_eod_pct" radius={[2, 2, 0, 0]} />
                    <Line yAxisId="right" type="monotone" dataKey="follow_through_rate" stroke="#10B981" dot={false} name="follow_through_rate" />
                  </ComposedChart>
                </ResponsiveContainer>
              </>
            )}
          </Card>
        </>
      )}
    </div>
  );
};

interface ExplanationResearchSectionProps {
  scannerType: string;
  traitRows: ExplanationTrait[];
  archetypeRows: ExplanationArchetype[];
  traitFilter: string;
  archetypeFilter: string;
  onTraitFilter: (value: string) => void;
  onArchetypeFilter: (value: string) => void;
  selectedTraits: ExplanationTrait[];
  selectedArchetypes: ExplanationArchetype[];
  traitChartData: Array<{
    name: string;
    label: string;
    sample_size: number;
    win_rate_pct: number;
    avg_mfe_pct: number;
    avg_mae_pct: number;
  }>;
  archetypeChartData: Array<{
    name: string;
    label: string;
    sample_size: number;
    win_rate_pct: number;
    avg_mfe_pct: number;
  }>;
  edgeDecay: EdgeDecayPoint[];
  isLoading: boolean;
}

const ExplanationResearchSection: React.FC<ExplanationResearchSectionProps> = ({
  scannerType,
  traitRows,
  archetypeRows,
  traitFilter,
  archetypeFilter,
  onTraitFilter,
  onArchetypeFilter,
  selectedTraits,
  selectedArchetypes,
  traitChartData,
  archetypeChartData,
  edgeDecay,
  isLoading,
}) => (
  <Card title="Explanation Edge Research" icon={Target}>
    {!scannerType ? (
      <div className="flex items-center justify-center h-28 border border-dashed border-gray-800 rounded-lg text-sm text-gray-500">
        Select a strategy to research edge by explanation trait and archetype.
      </div>
    ) : isLoading ? (
      <div className="flex items-center justify-center h-28 text-gray-500 text-xs uppercase tracking-widest">
        Loading explanation analysis...
      </div>
    ) : (
      <div className="space-y-5">
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
          <label className="space-y-1">
            <span className="text-[10px] font-black uppercase tracking-widest text-gray-500">
              Explanation Trait
            </span>
            <select
              aria-label="Explanation trait filter"
              value={traitFilter}
              onChange={(event) => onTraitFilter(event.target.value)}
              className="w-full bg-gray-900 border border-gray-700 rounded-lg px-3 py-2 text-xs font-bold text-white focus:outline-none focus:ring-1 focus:ring-financial-blue"
            >
              <option value="">All explanation traits</option>
              {traitRows.map((trait) => (
                <option key={traitValue(trait)} value={traitValue(trait)}>
                  {traitOptionLabel(trait)}
                </option>
              ))}
            </select>
          </label>

          <label className="space-y-1">
            <span className="text-[10px] font-black uppercase tracking-widest text-gray-500">
              Signal Archetype
            </span>
            <select
              aria-label="Signal archetype filter"
              value={archetypeFilter}
              onChange={(event) => onArchetypeFilter(event.target.value)}
              className="w-full bg-gray-900 border border-gray-700 rounded-lg px-3 py-2 text-xs font-bold text-white focus:outline-none focus:ring-1 focus:ring-financial-blue"
            >
              <option value="">All signal archetypes</option>
              {archetypeRows.map((archetype) => (
                <option key={archetype.cluster_id} value={archetype.cluster_id}>
                  {archetype.label}
                </option>
              ))}
            </select>
          </label>
        </div>

        <div className="grid grid-cols-1 xl:grid-cols-2 gap-5">
          <ExplanationPanel
            title="Trait Performance"
            isEmpty={selectedTraits.length === 0}
            emptyText="No explanation trait performance exists for this strategy yet."
          >
            <ResponsiveContainer width="100%" height={240}>
              <ComposedChart data={traitChartData} margin={{ top: 10, right: 20, left: 0, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#374151" vertical={false} />
                <XAxis dataKey="name" stroke="#6B7280" tick={{ fontSize: 10 }} />
                <YAxis yAxisId="left" stroke="#6B7280" tick={{ fontSize: 10 }} />
                <YAxis yAxisId="right" orientation="right" stroke="#6B7280" tick={{ fontSize: 10 }} />
                <Tooltip contentStyle={{ backgroundColor: '#111827', border: '1px solid #374151' }} />
                <Legend wrapperStyle={{ fontSize: '10px', textTransform: 'uppercase' }} />
                <Bar yAxisId="left" dataKey="sample_size" name="Sample" fill="#3B82F6" radius={[2, 2, 0, 0]} />
                <Bar yAxisId="right" dataKey="avg_mfe_pct" name="Avg MFE %" fill="#10B981" radius={[2, 2, 0, 0]} />
                <Line yAxisId="right" type="monotone" dataKey="win_rate_pct" name="Win %" stroke="#F59E0B" />
              </ComposedChart>
            </ResponsiveContainer>
            <div className="space-y-2">
              {selectedTraits.map((trait) => (
                <ExplanationSummaryRow
                  key={traitValue(trait)}
                  label={trait.trait_label}
                  prefix={traitTypeLabel(trait.trait_type)}
                  sampleSize={trait.sample_size}
                  winRate={trait.win_rate_pct}
                  avgMfe={trait.avg_mfe_pct}
                  warnings={trait.warnings}
                />
              ))}
            </div>
          </ExplanationPanel>

          <ExplanationPanel
            title="Archetype Performance"
            isEmpty={selectedArchetypes.length === 0}
            emptyText="No explanation archetypes exist for this strategy yet."
          >
            <ResponsiveContainer width="100%" height={240}>
              <ComposedChart data={archetypeChartData} margin={{ top: 10, right: 20, left: 0, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#374151" vertical={false} />
                <XAxis dataKey="name" stroke="#6B7280" tick={{ fontSize: 10 }} />
                <YAxis yAxisId="left" stroke="#6B7280" tick={{ fontSize: 10 }} />
                <YAxis yAxisId="right" orientation="right" stroke="#6B7280" tick={{ fontSize: 10 }} />
                <Tooltip contentStyle={{ backgroundColor: '#111827', border: '1px solid #374151' }} />
                <Legend wrapperStyle={{ fontSize: '10px', textTransform: 'uppercase' }} />
                <Bar yAxisId="left" dataKey="sample_size" name="Sample" fill="#8B5CF6" radius={[2, 2, 0, 0]} />
                <Bar yAxisId="right" dataKey="avg_mfe_pct" name="Avg MFE %" fill="#10B981" radius={[2, 2, 0, 0]} />
                <Line yAxisId="right" type="monotone" dataKey="win_rate_pct" name="Win %" stroke="#F59E0B" />
              </ComposedChart>
            </ResponsiveContainer>
            <div className="space-y-2">
              {selectedArchetypes.map((archetype) => (
                <ExplanationSummaryRow
                  key={archetype.cluster_id}
                  label={archetype.label}
                  prefix="Archetype"
                  sampleSize={archetype.sample_size}
                  winRate={archetype.return_profile.win_rate_pct}
                  avgMfe={archetype.return_profile.avg_mfe_pct}
                  warnings={archetype.warnings}
                />
              ))}
            </div>
          </ExplanationPanel>
        </div>

        <ExplanationPanel
          title="Scanner Edge Decay"
          isEmpty={edgeDecay.length === 0}
          emptyText="No edge decay series exists for this strategy yet."
        >
          <ResponsiveContainer width="100%" height={240}>
            <ComposedChart data={edgeDecay} margin={{ top: 10, right: 30, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#374151" vertical={false} />
              <XAxis dataKey="period" stroke="#6B7280" tick={{ fontSize: 10 }} />
              <YAxis yAxisId="left" stroke="#6B7280" tick={{ fontSize: 10 }} />
              <YAxis yAxisId="right" orientation="right" stroke="#6B7280" tick={{ fontSize: 10 }} />
              <Tooltip contentStyle={{ backgroundColor: '#111827', border: '1px solid #374151' }} />
              <Legend wrapperStyle={{ fontSize: '10px', textTransform: 'uppercase' }} />
              <Bar yAxisId="left" dataKey="sample_size" name="Sample" fill="#3B82F6" radius={[2, 2, 0, 0]} />
              <Line yAxisId="right" type="monotone" dataKey="win_rate" name="Win %" stroke="#F59E0B" />
              <Line yAxisId="right" type="monotone" dataKey="avg_mfe" name="Avg MFE" stroke="#10B981" />
              <Line yAxisId="right" type="monotone" dataKey="avg_mae" name="Avg MAE" stroke="#EF4444" />
            </ComposedChart>
          </ResponsiveContainer>
        </ExplanationPanel>
      </div>
    )}
  </Card>
);

const ExplanationPanel: React.FC<{
  title: string;
  isEmpty: boolean;
  emptyText: string;
  children: React.ReactNode;
}> = ({ title, isEmpty, emptyText, children }) => (
  <section className="border border-gray-800 rounded-lg p-4 bg-gray-900/30">
    <h3 className="text-xs font-black uppercase tracking-widest text-financial-light mb-3">
      {title}
    </h3>
    {isEmpty ? (
      <div className="flex items-center justify-center h-32 border border-dashed border-gray-800 rounded-lg text-sm text-gray-500">
        {emptyText}
      </div>
    ) : (
      <div className="space-y-3">{children}</div>
    )}
  </section>
);

const ExplanationSummaryRow: React.FC<{
  label: string;
  prefix: string;
  sampleSize: number;
  winRate: number | null | undefined;
  avgMfe: number | null | undefined;
  warnings: Array<{ code: string; message: string }>;
}> = ({ label, prefix, sampleSize, winRate, avgMfe, warnings }) => (
  <div className="border border-gray-800 rounded-lg p-3 bg-gray-950/30">
    <div className="flex flex-col sm:flex-row sm:items-start justify-between gap-2">
      <div>
        <div className="text-sm font-bold text-financial-light">{label}</div>
        <div className="text-[10px] font-black uppercase tracking-widest text-gray-500">
          {prefix} / n={sampleSize}
        </div>
      </div>
      <div className="grid grid-cols-2 gap-3 text-right text-xs">
        <div>
          <div className="text-gray-500">Win</div>
          <div className="font-bold text-financial-light">{fmtPct(winRate)}</div>
        </div>
        <div>
          <div className="text-gray-500">MFE</div>
          <div className="font-bold text-positive">{fmtPct(avgMfe)}</div>
        </div>
      </div>
    </div>
    {warnings.length > 0 && (
      <div className="mt-2 flex items-start gap-2 text-xs text-amber-300">
        <AlertTriangle className="h-4 w-4 shrink-0" />
        <span>{warnings[0].message}</span>
      </div>
    )}
  </div>
);

export default EdgeExplorer;
