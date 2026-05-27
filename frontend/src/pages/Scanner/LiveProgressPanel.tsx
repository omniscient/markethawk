import React from 'react';
import Card from '../../components/ui/Card';
import type { ActiveScanRef, LiveProgress } from '../../hooks/useScannerState';

const ProgressChip: React.FC<{ label: string; value: number; tone: 'ok' | 'warn' | 'err' }> = ({
  label, value, tone,
}) => {
  const colour =
    tone === 'err' && value > 0 ? 'text-red-400'
      : tone === 'warn' && value > 0 ? 'text-yellow-400'
      : tone === 'ok' && value > 0 ? 'text-green-400'
      : 'text-gray-500';
  return (
    <div className="flex justify-between border-b border-gray-800/60 pb-0.5">
      <span className="text-[9px] uppercase tracking-wider text-gray-500">{label}</span>
      <span className={`font-semibold ${colour}`}>{value.toLocaleString()}</span>
    </div>
  );
};

const LiveProgressCard: React.FC<{
  scan: ActiveScanRef;
  progress: LiveProgress;
}> = ({ scan, progress }) => {
  const total = progress.estimated_pairs || (progress.total_days * progress.total_tickers) || 0;
  const done = progress.evaluated + progress.no_data + progress.no_prior_close + progress.no_baseline;
  const pct = total > 0 ? Math.min(100, Math.round((done / total) * 100)) : 0;

  return (
    <Card className="bg-blue-900/20 border-blue-500/30">
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center space-x-3">
            <div className="animate-spin rounded-full h-5 w-5 border-b-2 border-financial-blue"></div>
            <div>
              <h3 className="text-financial-light font-semibold">
                Scanning <span className="font-mono text-sm text-blue-300">{scan.scanner_type}</span>
              </h3>
              <p className="text-gray-400 text-xs">
                {scan.start_date}{scan.end_date && scan.end_date !== scan.start_date ? ` → ${scan.end_date}` : ''}
                {progress.total_days > 0 && (
                  <> · day {progress.day_index || 0}/{progress.total_days}{progress.last_day ? ` (${progress.last_day})` : ''}</>
                )}
              </p>
            </div>
          </div>
          <div className="text-right">
            <div className="text-2xl font-bold text-financial-light tabular-nums">{progress.events_detected}</div>
            <div className="text-[10px] uppercase tracking-wider text-gray-500">events so far</div>
          </div>
        </div>

        <div className="w-full bg-gray-800 rounded-full h-2 overflow-hidden">
          <div
            className="h-2 bg-financial-blue transition-all duration-300"
            style={{ width: `${pct}%` }}
          />
        </div>
        <div className="flex justify-between text-[11px] text-gray-400 font-mono tabular-nums">
          <span>{done.toLocaleString()} / {total.toLocaleString() || '—'} pairs</span>
          <span>{pct}%</span>
        </div>

        <div className="grid grid-cols-3 md:grid-cols-6 gap-2 pt-1 text-[11px] font-mono tabular-nums">
          <ProgressChip label="evaluated" value={progress.evaluated} tone="ok" />
          <ProgressChip label="fired pre" value={progress.fired_pre} tone="ok" />
          <ProgressChip label="fired post" value={progress.fired_post} tone="ok" />
          <ProgressChip label="no data" value={progress.no_data} tone="warn" />
          <ProgressChip label="no baseline" value={progress.no_baseline} tone="warn" />
          <ProgressChip label="errors" value={progress.errors} tone="err" />
        </div>
      </div>
    </Card>
  );
};

export interface LiveProgressPanelProps {
  isScanning: boolean;
  activeScan: ActiveScanRef | null;
  progress: LiveProgress;
}

export function LiveProgressPanel({ isScanning, activeScan, progress }: LiveProgressPanelProps) {
  if (!isScanning || !activeScan) return null;
  return <LiveProgressCard scan={activeScan} progress={progress} />;
}
