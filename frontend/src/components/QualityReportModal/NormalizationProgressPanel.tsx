import React from 'react';
import { Loader2 } from 'lucide-react';
import type { NormalizationProgress } from '../../api/universe';

interface NormalizationProgressPanelProps {
  status: string | null;
  data: NormalizationProgress | null;
}

const NormalizationProgressPanel: React.FC<NormalizationProgressPanelProps> = ({ status, data }) => {
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

      {fixes && (
        <div className="flex flex-wrap gap-x-4 gap-y-0.5 text-xs opacity-80">
          {fixes.gaps_filled  > 0 && <span>{fixes.gaps_filled.toLocaleString()} bars gap-filled</span>}
          {fixes.backfilled   > 0 && <span>{fixes.backfilled.toLocaleString()} bars back-filled</span>}
          {fixes.deduped      > 0 && <span>{fixes.deduped.toLocaleString()} duplicates removed</span>}
        </div>
      )}

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
};

export default NormalizationProgressPanel;
