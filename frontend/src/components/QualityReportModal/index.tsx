import React, { useState, useEffect } from 'react';
import { RefreshCw, Loader2, AlertTriangle, Wand2 } from 'lucide-react';
import Modal from '../ui/Modal';
import Button from '../ui/Button';
import { useQualityReport } from '../../hooks/useQualityReport';
import type { StockUniverse, QualityTickerResult } from '../../api/universe';
import type { QualityGateAssessment } from '../../api/scanner';
import NormalizationProgressPanel from './NormalizationProgressPanel';
import TickerRow from './TickerRow';
import DeleteConfirmDialog from './DeleteConfirmDialog';
import QualityOverviewCard from './QualityOverviewCard';
import QualityFiltersBar from './QualityFiltersBar';
import TrustGateSummary from './TrustGateSummary';

type SortKey = 'ticker' | 'grade' | 'coverage_pct' | 'gap_count' | 'actual_bars';

interface SortThProps {
  label: string;
  k: SortKey;
  sortKey: SortKey;
  sortAsc: boolean;
  onSort: (k: SortKey) => void;
}
const SortTh = ({ label, k, sortKey, sortAsc, onSort }: SortThProps) => (
  <th
    className="px-3 py-2 text-left text-xs text-gray-400 font-medium cursor-pointer select-none hover:text-gray-200"
    onClick={() => onSort(k)}
  >
    {label}{sortKey === k ? (sortAsc ? ' ↑' : ' ↓') : ''}
  </th>
);

interface QualityReportModalProps {
  isOpen: boolean;
  onClose: () => void;
  universe: StockUniverse | null;
  gate?: QualityGateAssessment;
}

const QualityReportModal: React.FC<QualityReportModalProps> = ({ isOpen, onClose, universe, gate }) => {
  const [sortKey, setSortKey] = useState<SortKey>('grade');
  const [sortAsc, setSortAsc] = useState(true);
  const [gradeFilter, setGradeFilter] = useState<string>('all');
  const [timespanFilter, setTimespanFilter] = useState<string>('all');
  const [minScore, setMinScore] = useState<number>(0);
  const [pendingDelete, setPendingDelete] = useState<QualityTickerResult | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  const {
    report,
    isLoading,
    removedTickers,
    normalizationTriggered,
    isAnalyzing,
    isNormalizing,
    isBusy,
    deleteMutation,
    analyzeMutation,
    normalizeMutation,
  } = useQualityReport(universe, isOpen);

  const tickers = report?.report_data?.tickers ?? [];

  const sorted = [...tickers]
    .filter((t) => gradeFilter === 'all' || t.grade === gradeFilter)
    .filter((t) => timespanFilter === 'all' || (t.multiplier === 1 ? t.timespan : `${t.multiplier}${t.timespan}`) === timespanFilter)
    .filter((t) => t.coverage_pct >= minScore)
    .filter((t) => !removedTickers.has(t.ticker))
    .sort((a, b) => {
      let av: QualityTickerResult[SortKey] | number = a[sortKey];
      let bv: QualityTickerResult[SortKey] | number = b[sortKey];
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

  // Reset transient UI state when modal closes
  useEffect(() => {
    if (!isOpen) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setPendingDelete(null);
      setDeleteError(null);
      setGradeFilter('all');
      setTimespanFilter('all');
      setMinScore(0);
      setSortKey('grade');
      setSortAsc(true);
    }
  }, [isOpen]);

  const rd = report?.report_data;

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
              onClick={() => analyzeMutation.mutate(undefined, {
                onSuccess: () => setGradeFilter('all'),
              })}
              disabled={isBusy}
            >
              {isAnalyzing ? 'Analysing…' : (report ? 'Re-analyse' : 'Run Analysis')}
            </Button>
            {rd && (
              <Button
                variant="primary"
                icon={isNormalizing ? Loader2 : Wand2}
                onClick={() => normalizeMutation.mutate(sorted.map(t => t.ticker), {
                  onSuccess: () => { setGradeFilter('all'); setTimespanFilter('all'); setMinScore(0); },
                })}
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
            <TrustGateSummary gate={gate} />

            <QualityOverviewCard
              rd={rd}
              gradeFilter={gradeFilter}
              onGradeFilterChange={setGradeFilter}
            />

            <QualityFiltersBar
              timespanFilter={timespanFilter}
              onTimespanChange={setTimespanFilter}
              minScore={minScore}
              onMinScoreChange={setMinScore}
              availableTimespans={rd.timespans_analyzed}
              totalCount={tickers.length}
              activeCount={sorted.length}
            />

            <div className="overflow-auto max-h-96 rounded border border-gray-700">
              <table className="w-full text-sm border-collapse">
                <thead className="bg-gray-800 sticky top-0">
                  <tr>
                    <SortTh label="Ticker" k="ticker" sortKey={sortKey} sortAsc={sortAsc} onSort={handleSort} />
                    <th className="px-3 py-2 text-left text-xs text-gray-400 font-medium">Timespan</th>
                    <SortTh label="Grade" k="grade" sortKey={sortKey} sortAsc={sortAsc} onSort={handleSort} />
                    <SortTh label="Coverage" k="coverage_pct" sortKey={sortKey} sortAsc={sortAsc} onSort={handleSort} />
                    <SortTh label="Gaps" k="gap_count" sortKey={sortKey} sortAsc={sortAsc} onSort={handleSort} />
                    <th className="px-3 py-2 text-right text-xs text-gray-400 font-medium">Bad bars</th>
                    <SortTh label="Bars" k="actual_bars" sortKey={sortKey} sortAsc={sortAsc} onSort={handleSort} />
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
                        No results match the current filters
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </>
        )}

        {pendingDelete && (
          <DeleteConfirmDialog
            pendingDelete={pendingDelete}
            deleteError={deleteError}
            isPending={deleteMutation.isPending}
            onConfirm={() => deleteMutation.mutate(pendingDelete, {
              onSuccess: () => { setPendingDelete(null); setDeleteError(null); },
              onError: (err: unknown) => {
                const e = err as { response?: { data?: { detail?: string } }; message?: string };
                const msg = e?.response?.data?.detail ?? e?.message ?? 'Delete failed';
                setDeleteError(typeof msg === 'string' ? msg : JSON.stringify(msg));
              },
            })}
            onCancel={() => { setPendingDelete(null); setDeleteError(null); }}
          />
        )}
      </div>
    </Modal>
  );
};

export default QualityReportModal;
