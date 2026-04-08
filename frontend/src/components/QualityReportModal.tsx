import React, { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import Modal from './ui/Modal';
import Button from './ui/Button';
import { RefreshCw, Loader2, ChevronDown, ChevronRight, AlertTriangle, Trash2, Wand2 } from 'lucide-react';
import { StockUniverse, QualityReport, QualityTickerResult, CoverageDetail, NormalizationProgress, fetchQualityReport, triggerQualityAnalysis, triggerNormalization, deleteTickerAggregates } from '../api/scanner';

// ── Helpers ──────────────────────────────────────────────────────────────────

const GRADE_STYLES: Record<string, string> = {
  A: 'bg-green-500/20 text-green-400 border-green-500/30',
  B: 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30',
  C: 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30',
  D: 'bg-orange-500/20 text-orange-400 border-orange-500/30',
  F: 'bg-red-500/20 text-red-400 border-red-500/30',
};

const GRADE_LABEL: Record<string, string> = {
  A: 'Production-ready',
  B: 'Minor gaps, usable',
  C: 'Significant gaps — use with caution',
  D: 'Major holes — scanner results unreliable',
  F: 'Severely incomplete',
};

function GradeBadge({ grade, size = 'md' }: { grade: string; size?: 'sm' | 'md' | 'lg' }) {
  const style = GRADE_STYLES[grade] ?? 'bg-gray-500/20 text-gray-400 border-gray-500/30';
  const sz = size === 'lg' ? 'text-3xl px-4 py-1 font-bold' : size === 'md' ? 'text-sm px-2.5 py-0.5 font-semibold' : 'text-xs px-1.5 py-0.5 font-medium';
  return (
    <span className={`inline-flex items-center justify-center rounded border ${style} ${sz} font-mono`}>
      {grade}
    </span>
  );
}

function ScoreBar({ value }: { value: number }) {
  const color = value >= 95 ? 'bg-green-500' : value >= 85 ? 'bg-emerald-500' : value >= 70 ? 'bg-yellow-500' : value >= 50 ? 'bg-orange-500' : 'bg-red-500';
  return (
    <div className="flex items-center gap-2 min-w-0">
      <div className="flex-1 h-1.5 bg-gray-700 rounded-full overflow-hidden">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${value}%` }} />
      </div>
      <span className="text-xs text-gray-400 w-10 text-right">{value.toFixed(1)}%</span>
    </div>
  );
}

// ── Normalization progress panel ──────────────────────────────────────────────

function NormalizationProgressPanel({
  status,
  data,
}: {
  status: string | null;
  data: NormalizationProgress | null;
}) {
  if (!status) return null;

  const processed = data?.processed_combos?.length ?? 0;
  const total     = data?.total_combos ?? 0;
  const pct       = total > 0 ? Math.round((processed / total) * 100) : 0;
  const fixes     = data?.fixes_applied;
  const errors    = data?.errors ?? [];

  const statusColor = status === 'complete' ? 'text-green-400 border-green-500/30 bg-green-500/10'
    : status === 'error'   ? 'text-red-400 border-red-500/30 bg-red-500/10'
    : 'text-purple-400 border-purple-500/30 bg-purple-500/10';

  const label = status === 'complete' ? 'Normalization complete'
    : status === 'error'   ? 'Normalization encountered errors'
    : status === 'pending' ? 'Normalization queued…'
    : `Normalizing… ${processed}/${total} combos`;

  return (
    <div className={`rounded-lg border p-3 text-sm ${statusColor}`}>
      <div className="flex items-center gap-2 mb-2">
        {(status === 'pending' || status === 'running') && (
          <Loader2 className="h-4 w-4 animate-spin flex-shrink-0" />
        )}
        <span className="font-medium">{label}</span>
      </div>

      {/* Progress bar */}
      {total > 0 && (
        <div className="h-1.5 bg-black/30 rounded-full overflow-hidden mb-2">
          <div
            className={`h-full rounded-full transition-all ${
              status === 'complete' ? 'bg-green-500' : status === 'error' ? 'bg-red-500' : 'bg-purple-500'
            }`}
            style={{ width: `${pct}%` }}
          />
        </div>
      )}

      {/* Fix summary */}
      {fixes && (
        <div className="flex flex-wrap gap-x-4 gap-y-0.5 text-xs opacity-80">
          {fixes.gaps_filled  > 0 && <span>{fixes.gaps_filled.toLocaleString()} bars gap-filled</span>}
          {fixes.backfilled   > 0 && <span>{fixes.backfilled.toLocaleString()} bars back-filled</span>}
          {fixes.deduped      > 0 && <span>{fixes.deduped.toLocaleString()} duplicates removed</span>}
        </div>
      )}

      {/* Errors */}
      {errors.length > 0 && (
        <details className="mt-1.5">
          <summary className="text-xs cursor-pointer opacity-70">
            {errors.length} error{errors.length !== 1 ? 's' : ''}
          </summary>
          <ul className="mt-1 space-y-0.5 text-xs opacity-70 max-h-24 overflow-y-auto">
            {errors.map((e, i) => (
              <li key={i} className="font-mono">{e.combo} [{e.fix}]: {e.error}</li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}

// ── Coverage breakdown ────────────────────────────────────────────────────────

function CoverageBreakdown({ detail, coveragePct }: { detail: CoverageDetail; coveragePct: number }) {
  const [showAll, setShowAll] = useState(false);
  const { p90_bars_per_day, full_day_count, stub_day_count, partial_day_count, holiday_day_count, partial_days } = detail;
  const visiblePartials = showAll ? partial_days : partial_days.slice(0, 5);
  const shortfallPct = 100 - coveragePct;

  return (
    <div className="mt-2 space-y-2">
      <p className="text-xs text-gray-400 font-medium">
        Coverage breakdown — {coveragePct.toFixed(1)}%
        <span className="ml-2 text-gray-600 font-normal">
          (baseline: {p90_bars_per_day.toLocaleString()} bars/day P90)
        </span>
      </p>
      <div className="flex flex-wrap gap-x-5 gap-y-1 text-xs">
        <span className="text-green-400">
          ✓ {full_day_count} full day{full_day_count !== 1 ? 's' : ''}
          <span className="text-gray-600 ml-1">(≥ {p90_bars_per_day.toLocaleString()} bars)</span>
        </span>
        {partial_day_count > 0 && (
          <span className="text-yellow-400">
            ◑ {partial_day_count} partial day{partial_day_count !== 1 ? 's' : ''}
            <span className="text-gray-600 ml-1">(unexplained — cause shortfall)</span>
          </span>
        )}
        {stub_day_count > 0 && (
          <span className="text-gray-500">
            ○ {stub_day_count} stub day{stub_day_count !== 1 ? 's' : ''}
            <span className="text-gray-600 ml-1">(Sunday opens / organic short sessions)</span>
          </span>
        )}
        {(holiday_day_count ?? 0) > 0 && (
          <span className="text-blue-400">
            ✦ {holiday_day_count} holiday day{holiday_day_count !== 1 ? 's' : ''}
            <span className="text-gray-600 ml-1">(market calendar — not penalised)</span>
          </span>
        )}
      </div>

      {/* All-clear message when there are no unexplained partials */}
      {partial_day_count === 0 && shortfallPct > 0 && (
        <p className="text-xs text-gray-500 italic">
          All shortened sessions are accounted for
          {stub_day_count > 0 && holiday_day_count > 0
            ? ` (${stub_day_count} stub + ${holiday_day_count} holiday)`
            : stub_day_count > 0 ? ` (${stub_day_count} stub day${stub_day_count !== 1 ? 's' : ''})`
            : ` (${holiday_day_count} holiday day${holiday_day_count !== 1 ? 's' : ''})`}
          . The {shortfallPct.toFixed(1)}% gap is within expected market-calendar variance.
        </p>
      )}

      {/* List unexplained partial days */}
      {partial_days.length > 0 && (
        <div>
          <p className="text-xs text-gray-500 mb-1">
            Unexplained partial days — consider re-syncing these dates (worst first
            {partial_days.length < partial_day_count ? `, showing top ${partial_days.length}` : ''}):
          </p>
          <div className="grid gap-0.5">
            {visiblePartials.map((pd) => (
              <div key={pd.date} className="flex items-center gap-3 text-xs font-mono">
                <span className="text-gray-400 w-24">{pd.date}</span>
                <span className="text-gray-400">{pd.actual_bars.toLocaleString()} bars</span>
                <span className="text-gray-600">of {pd.expected_bars.toLocaleString()} expected</span>
                <span className="text-yellow-500">−{pd.shortfall.toLocaleString()} missing</span>
              </div>
            ))}
          </div>
          {partial_days.length > 5 && !showAll && (
            <button
              className="mt-1 text-xs text-gray-500 hover:text-gray-300 underline"
              onClick={() => setShowAll(true)}
            >
              Show {partial_days.length - 5} more…
            </button>
          )}
        </div>
      )}
    </div>
  );
}

// ── Ticker row ────────────────────────────────────────────────────────────────

function TickerRow({ result, onDelete }: { result: QualityTickerResult; onDelete: (r: QualityTickerResult) => void }) {
  const [expanded, setExpanded] = useState(false);
  const hasGaps = result.gaps.length > 0;
  const hasIssues = result.bad_bar_count > 0 || result.duplicate_count > 0;
  const hasCoverageDetail = result.coverage_pct < 100 && !!result.coverage_detail;

  const isExpandable = hasGaps || hasIssues || hasCoverageDetail;

  return (
    <>
      <tr
        className={`border-b border-gray-800 hover:bg-gray-800/40 ${isExpandable ? 'cursor-pointer' : ''}`}
        onClick={() => isExpandable && setExpanded((v) => !v)}
      >
        <td className="px-3 py-2">
          <div className="flex items-center gap-1.5">
            {isExpandable
              ? (expanded ? <ChevronDown className="h-3.5 w-3.5 text-gray-500 flex-shrink-0" /> : <ChevronRight className="h-3.5 w-3.5 text-gray-500 flex-shrink-0" />)
              : <span className="w-3.5" />}
            <span className="font-mono text-sm text-financial-light">{result.ticker}</span>
            {result.asset_class !== 'stocks' && (
              <span className="px-1 py-0.5 text-[9px] rounded bg-financial-blue/20 text-financial-blue uppercase font-medium">
                {result.asset_class}
              </span>
            )}
          </div>
        </td>
        <td className="px-3 py-2">
          <span className="text-xs text-gray-400 font-mono">
            {result.timespan ? `${result.multiplier !== 1 ? result.multiplier : ''}${result.timespan}` : '—'}
          </span>
        </td>
        <td className="px-3 py-2"><GradeBadge grade={result.grade} size="sm" /></td>
        <td className="px-3 py-2 w-36"><ScoreBar value={result.coverage_pct} /></td>
        <td className="px-3 py-2 text-right">
          <span className={`text-xs font-mono ${result.gap_count > 0 ? 'text-orange-400' : 'text-gray-500'}`}>
            {result.gap_count}
          </span>
        </td>
        <td className="px-3 py-2 text-right">
          <span className={`text-xs font-mono ${result.bad_bar_count > 0 ? 'text-red-400' : 'text-gray-500'}`}>
            {result.bad_bar_count}
          </span>
        </td>
        <td className="px-3 py-2 text-right text-xs text-gray-500 font-mono">
          {result.actual_bars.toLocaleString()}
        </td>
        <td className="px-3 py-2 text-right text-xs text-gray-500 font-mono">
          {result.first_bar ? new Date(result.first_bar).toLocaleDateString() : '—'}
        </td>
        <td className="px-3 py-2 text-right text-xs text-gray-500 font-mono">
          {result.last_bar ? new Date(result.last_bar).toLocaleDateString() : '—'}
        </td>
        <td className="px-3 py-2 text-right">
          <button
            onClick={(e) => { e.stopPropagation(); onDelete(result); }}
            className="p-1 text-gray-600 hover:text-red-400 transition-colors rounded"
            title="Remove ticker from universe"
          >
            <Trash2 className="h-3.5 w-3.5" />
          </button>
        </td>
      </tr>
      {expanded && isExpandable && (
        <tr className="bg-gray-900/60 border-b border-gray-800">
          <td colSpan={10} className="px-6 py-3 space-y-3">
            {hasIssues && (
              <div className="flex gap-4 text-xs">
                {result.bad_bar_count > 0 && (
                  <span className="text-red-400">{result.bad_bar_count} bad bar{result.bad_bar_count !== 1 ? 's' : ''} (OHLCV integrity)</span>
                )}
                {result.duplicate_count > 0 && (
                  <span className="text-orange-400">{result.duplicate_count} duplicate timestamp{result.duplicate_count !== 1 ? 's' : ''}</span>
                )}
              </div>
            )}
            {hasGaps && (
              <div className="space-y-1">
                <p className="text-xs text-gray-500 mb-1">Data gaps ({result.gap_count} total{result.gaps.length < result.gap_count ? `, showing first ${result.gaps.length}` : ''}):</p>
                <div className="grid gap-1">
                  {result.gaps.map((gap, i) => (
                    <div key={i} className="flex items-center gap-3 text-xs font-mono">
                      <span className="text-gray-400">{new Date(gap.from).toLocaleString()}</span>
                      <span className="text-gray-600">→</span>
                      <span className="text-gray-400">{new Date(gap.to).toLocaleString()}</span>
                      <span className="text-orange-400">{gap.duration_hours}h gap</span>
                      <span className="text-gray-500">~{gap.missing_bars} missing bars</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
            {hasCoverageDetail && result.coverage_detail && (
              <CoverageBreakdown detail={result.coverage_detail} coveragePct={result.coverage_pct} />
            )}
          </td>
        </tr>
      )}
    </>
  );
}

// ── Main modal ────────────────────────────────────────────────────────────────

type SortKey = 'ticker' | 'grade' | 'coverage_pct' | 'gap_count' | 'actual_bars';

interface QualityReportModalProps {
  isOpen: boolean;
  onClose: () => void;
  universe: StockUniverse | null;
}

const QualityReportModal: React.FC<QualityReportModalProps> = ({ isOpen, onClose, universe }) => {
  const queryClient = useQueryClient();
  const [sortKey, setSortKey] = useState<SortKey>('grade');
  const [sortAsc, setSortAsc] = useState(true);
  const [gradeFilter, setGradeFilter] = useState<string>('all');
  const [pendingDelete, setPendingDelete] = useState<QualityTickerResult | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  // Optimistically removed tickers (by symbol), cleared when re-analysis completes
  const [removedTickers, setRemovedTickers] = useState<Set<string>>(new Set());
  // True only while normalization was triggered in THIS modal session — resets on close
  const [normalizationTriggered, setNormalizationTriggered] = useState(false);

  const { data: report, isLoading } = useQuery({
    queryKey: ['qualityReport', universe?.id],
    queryFn: () => fetchQualityReport(universe!.id),
    enabled: !!universe && isOpen,
  });

  // Explicit poll — avoids refetchInterval API differences between RQ v4/v5
  // Covers quality analysis, normalization in-progress, AND the automatic re-analysis
  // that runs after normalization completes (status goes pending→running→complete again).
  React.useEffect(() => {
    const qualityActive = report?.status === 'pending' || report?.status === 'running';
    const normActive    = report?.normalization_status === 'pending' || report?.normalization_status === 'running';
    // Also keep polling if normalization just completed this session but quality
    // re-analysis hasn't finished yet (normalization triggers it automatically).
    const postNormPending = normalizationTriggered && report?.normalization_status === 'complete' && report?.status !== 'complete';
    if ((!qualityActive && !normActive && !postNormPending) || !universe || !isOpen) return;
    const timer = setInterval(() => {
      queryClient.invalidateQueries({ queryKey: ['qualityReport', universe.id] });
    }, 2000);
    return () => clearInterval(timer);
  }, [report?.status, report?.normalization_status, normalizationTriggered, universe?.id, isOpen, queryClient]);

  // Once a fresh analysis completes, clear the optimistic removed-tickers set
  React.useEffect(() => {
    if (report?.status === 'complete' && removedTickers.size > 0) {
      setRemovedTickers(new Set());
    }
  }, [report?.status]);

  const deleteMutation = useMutation({
    mutationFn: (row: QualityTickerResult) =>
      deleteTickerAggregates(universe!.id, {
        ticker: row.ticker,
        asset_class: row.asset_class,
        // omit timespan/multiplier so ALL bars are removed
      }),
    onSuccess: (_data, row) => {
      setDeleteError(null);
      setRemovedTickers((prev) => new Set([...prev, row.ticker]));
      setPendingDelete(null);
      queryClient.invalidateQueries({ queryKey: ['stockUniverses'] });
    },
    onError: (err: any) => {
      const msg = err?.response?.data?.detail ?? err?.message ?? 'Delete failed';
      setDeleteError(typeof msg === 'string' ? msg : JSON.stringify(msg));
    },
  });

  const analyzeMutation = useMutation({
    mutationFn: () => triggerQualityAnalysis(universe!.id),
    onSuccess: () => {
      // Immediate refetch so the pending state shows without waiting for the next poll cycle
      queryClient.invalidateQueries({ queryKey: ['qualityReport', universe?.id] });
      queryClient.invalidateQueries({ queryKey: ['stockUniverses'] });
      setGradeFilter('all');
    },
  });

  const normalizeMutation = useMutation({
    mutationFn: () => triggerNormalization(universe!.id),
    onSuccess: () => {
      setNormalizationTriggered(true);
      queryClient.invalidateQueries({ queryKey: ['qualityReport', universe?.id] });
      setGradeFilter('all');
    },
  });

  const isAnalyzing = report?.status === 'pending' || report?.status === 'running' || analyzeMutation.isPending;
  // isNormalizing: only active when triggered this session AND still in progress
  const isNormalizing = normalizeMutation.isPending || (
    normalizationTriggered && (
      report?.normalization_status === 'pending' ||
      report?.normalization_status === 'running'
    )
  );
  // isBusy covers normalization + the subsequent quality re-analysis it triggers
  const isBusy = isAnalyzing || isNormalizing || (
    normalizationTriggered && report?.normalization_status === 'complete' && report?.status !== 'complete'
  );

  const tickers = report?.report_data?.tickers ?? [];

  const sorted = [...tickers]
    .filter((t) => gradeFilter === 'all' || t.grade === gradeFilter)
    .filter((t) => !removedTickers.has(t.ticker))
    .sort((a, b) => {
      let av: any = a[sortKey];
      let bv: any = b[sortKey];
      if (sortKey === 'grade') {
        const order = { A: 0, B: 1, C: 2, D: 3, F: 4 };
        av = order[a.grade as keyof typeof order] ?? 5;
        bv = order[b.grade as keyof typeof order] ?? 5;
      }
      if (av === bv) return 0;
      const cmp = av < bv ? -1 : 1;
      return sortAsc ? cmp : -cmp;
    });

  const handleSort = (key: SortKey) => {
    if (sortKey === key) setSortAsc((v) => !v);
    else { setSortKey(key); setSortAsc(true); }
  };

  const SortTh = ({ label, k }: { label: string; k: SortKey }) => (
    <th
      className="px-3 py-2 text-left text-xs text-gray-400 font-medium cursor-pointer select-none hover:text-gray-200"
      onClick={() => handleSort(k)}
    >
      {label}{sortKey === k ? (sortAsc ? ' ↑' : ' ↓') : ''}
    </th>
  );

  const rd = report?.report_data;

  // Reset transient state when modal closes
  React.useEffect(() => {
    if (!isOpen) {
      setPendingDelete(null);
      setDeleteError(null);
      setGradeFilter('all');
      setSortKey('grade');
      setSortAsc(true);
      // We don't reset removedTickers or normalizationTriggered here
      // so if they reopen the same modal, it retains its optimistic state.
    }
  }, [isOpen]);

  // Reset deep state when universe changes
  React.useEffect(() => {
    setRemovedTickers(new Set());
    setNormalizationTriggered(false);
  }, [universe?.id]);

  if (!universe) return null;

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      size="2xl"
      title={`Data Quality: ${universe.name}`}
      footer={
        <div className="flex items-center justify-between w-full">
          <span className="text-xs text-gray-500">
            {rd ? `Analysed ${new Date(rd.generated_at).toLocaleString()}` : ''}
          </span>
          <div className="flex gap-2">
            <Button variant="secondary" onClick={onClose}>Close</Button>
            <Button
              variant="primary"
              icon={isAnalyzing ? Loader2 : RefreshCw}
              onClick={() => analyzeMutation.mutate()}
              disabled={isBusy}
            >
              {isAnalyzing ? 'Analysing…' : (report ? 'Re-analyse' : 'Run Analysis')}
            </Button>
            {rd && (
              <Button
                variant="primary"
                icon={isNormalizing ? Loader2 : Wand2}
                onClick={() => normalizeMutation.mutate()}
                disabled={isBusy}
                className="bg-purple-600 hover:bg-purple-500 border-purple-500"
              >
                {isNormalizing ? 'Normalizing…' : 'Normalize'}
              </Button>
            )}
          </div>
        </div>
      }
    >
      <div className="relative space-y-4 min-h-[300px]">

        {/* ── Status / loading ── */}
        {(isLoading || isAnalyzing) && (
          <div className={`flex flex-col items-center justify-center gap-3 ${rd ? 'py-4' : 'py-12'} text-gray-400`}>
            <Loader2 className="h-8 w-8 animate-spin text-financial-blue" />
            <p className="text-sm">{isAnalyzing ? 'Analysing data quality…' : 'Loading…'}</p>
          </div>
        )}

        {report?.status === 'error' && (
          <div className="bg-red-500/10 border border-red-500/30 rounded-lg p-3 text-sm text-red-400 flex items-start gap-2">
            <AlertTriangle className="h-4 w-4 flex-shrink-0 mt-0.5" />
            <span>Analysis failed: {report.error_message}</span>
          </div>
        )}

        {/* Normalization progress panel — only shown when triggered this session */}
        {normalizationTriggered && (
          <NormalizationProgressPanel
            status={report?.normalization_status ?? (normalizeMutation.isPending ? 'pending' : null)}
            data={report?.normalization_data ?? null}
          />
        )}

        {removedTickers.size > 0 && !isAnalyzing && !isBusy && (
          <div className="bg-yellow-500/10 border border-yellow-500/30 rounded-lg p-3 text-sm text-yellow-500 flex items-start gap-2">
            <AlertTriangle className="h-4 w-4 flex-shrink-0 mt-0.5" />
            <span>Local changes made (ticker deleted). Re-analyse to update the full report.</span>
          </div>
        )}

        {!report && !isLoading && !isAnalyzing && (
          <div className="flex flex-col items-center justify-center py-12 text-gray-500 gap-3">
            <p className="text-sm">No analysis has been run yet.</p>
          </div>
        )}

        {rd && !isAnalyzing && (
          <>
            {/* ── Overall score ── */}
            <div className="flex items-center gap-6 bg-gray-800/50 rounded-lg p-4">
              <div className="flex flex-col items-center gap-1">
                <GradeBadge grade={rd.overall_grade} size="lg" />
                <span className="text-[10px] text-gray-500 text-center max-w-[90px] leading-tight">
                  {GRADE_LABEL[rd.overall_grade]}
                </span>
              </div>
              <div className="flex-1 grid grid-cols-2 gap-x-8 gap-y-2 text-sm">
                <div className="flex justify-between">
                  <span className="text-gray-400">Overall score</span>
                  <span className="text-financial-light font-mono">{rd.overall_score.toFixed(1)}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-gray-400">Tickers</span>
                  <span className="text-financial-light font-mono">{rd.ticker_count}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-gray-400">Timespans</span>
                  <span className="text-financial-light font-mono">{rd.timespans_analyzed.join(', ') || '—'}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-gray-400">Combinations</span>
                  <span className="text-financial-light font-mono">{rd.analyzed_count}</span>
                </div>
              </div>
              {/* Grade distribution */}
              <div className="flex gap-1.5 flex-wrap justify-end">
                {(['A', 'B', 'C', 'D', 'F'] as const).map((g) => {
                  const count = rd.grade_distribution[g] ?? 0;
                  if (!count) return null;
                  return (
                    <button
                      key={g}
                      onClick={() => setGradeFilter(gradeFilter === g ? 'all' : g)}
                      className={`flex flex-col items-center px-2 py-1 rounded border text-xs transition-all ${
                        GRADE_STYLES[g]
                      } ${gradeFilter === g ? 'opacity-100' : 'opacity-60 hover:opacity-100'}`}
                    >
                      <span className="font-bold font-mono">{g}</span>
                      <span>{count}</span>
                    </button>
                  );
                })}
              </div>
            </div>

            {/* ── Ticker table ── */}
            <div className="overflow-auto max-h-96 rounded border border-gray-700">
              <table className="w-full text-sm border-collapse">
                <thead className="bg-gray-800 sticky top-0">
                  <tr>
                    <SortTh label="Ticker" k="ticker" />
                    <th className="px-3 py-2 text-left text-xs text-gray-400 font-medium">Timespan</th>
                    <SortTh label="Grade" k="grade" />
                    <SortTh label="Coverage" k="coverage_pct" />
                    <SortTh label="Gaps" k="gap_count" />
                    <th className="px-3 py-2 text-right text-xs text-gray-400 font-medium">Bad bars</th>
                    <SortTh label="Bars" k="actual_bars" />
                    <th className="px-3 py-2 text-right text-xs text-gray-400 font-medium">First bar</th>
                    <th className="px-3 py-2 text-right text-xs text-gray-400 font-medium">Last bar</th>
                    <th className="px-3 py-2 w-8" />
                  </tr>
                </thead>
                <tbody>
                  {sorted.map((r, i) => (
                    <TickerRow key={`${r.ticker}-${r.timespan}-${r.multiplier}-${i}`} result={r} onDelete={setPendingDelete} />
                  ))}
                  {sorted.length === 0 && (
                    <tr>
                      <td colSpan={10} className="px-3 py-8 text-center text-gray-500 text-sm">
                        No results for grade filter "{gradeFilter}"
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </>
        )}
        {pendingDelete && (
          <div className="absolute inset-0 z-10 flex items-center justify-center rounded-xl bg-black/60 backdrop-blur-sm">
            <div className="bg-gray-900 border border-gray-700 rounded-xl shadow-2xl p-6 max-w-sm w-full mx-4">
              <div className="flex items-start gap-3 mb-4">
                <AlertTriangle className="h-5 w-5 text-red-400 flex-shrink-0 mt-0.5" />
                <div>
                  <p className="text-financial-light font-semibold">Remove ticker from universe?</p>
                  <p className="text-sm text-gray-400 mt-1">
                    This will permanently delete{' '}
                    <span className="font-mono text-financial-light">{pendingDelete.ticker}</span>'s
                    aggregate data (all timespans) and remove it from this universe.
                    This cannot be undone.
                  </p>
                </div>
              </div>
              {deleteError && (
                <p className="text-xs text-red-400 mb-3">{deleteError}</p>
              )}
              <div className="flex justify-end gap-2">
                <Button variant="secondary" onClick={() => { setPendingDelete(null); setDeleteError(null); }} disabled={deleteMutation.isPending}>
                  Cancel
                </Button>
                <Button
                  variant="ghost"
                  className="text-red-400 hover:text-red-300 border border-red-500/30 hover:border-red-400/50"
                  icon={deleteMutation.isPending ? Loader2 : Trash2}
                  onClick={() => deleteMutation.mutate(pendingDelete)}
                  disabled={deleteMutation.isPending}
                >
                  {deleteMutation.isPending ? 'Deleting…' : 'Delete'}
                </Button>
              </div>
            </div>
          </div>
        )}
      </div>
    </Modal>
  );
};

export default QualityReportModal;
