import React from 'react';
import { CalendarRange, ChevronDown, ChevronRight, RefreshCw } from 'lucide-react';
import Card from '../../components/ui/Card';
import Button from '../../components/ui/Button';
import type { ScannerCoverage, ScannerCoverageGap, ScannerCoverageRange } from '../../api/scanner';

interface CoveragePanelProps {
  coverage: ScannerCoverage | undefined;
  isLoading: boolean;
  isScanning: boolean;
  onScanGap: (gap: ScannerCoverageGap) => void;
  onFillAllGaps: (gaps: ScannerCoverageGap[]) => void;
}

type TimelineSegment =
  | (ScannerCoverageRange & { kind: 'covered'; weekdays: number })
  | (ScannerCoverageGap & { kind: 'gap'; events?: never; runs?: never });

function daysBetween(start: string, end: string): number {
  const startMs = new Date(`${start}T00:00:00Z`).getTime();
  const endMs = new Date(`${end}T00:00:00Z`).getTime();
  return Math.max(1, Math.round((endMs - startMs) / 86_400_000) + 1);
}

function formatRange(start: string, end: string): string {
  return start === end ? start : `${start} - ${end}`;
}

function weekdayLabel(count: number): string {
  return `${count} ${count === 1 ? 'weekday' : 'weekdays'}`;
}

function buildSegments(coverage: ScannerCoverage): TimelineSegment[] {
  return [
    ...coverage.covered.map((range) => ({
      ...range,
      kind: 'covered' as const,
      weekdays: daysBetween(range.start, range.end),
    })),
    ...coverage.gaps.map((gap) => ({ ...gap, kind: 'gap' as const })),
  ].sort((a, b) => a.start.localeCompare(b.start));
}

export function CoveragePanel({
  coverage,
  isLoading,
  isScanning,
  onScanGap,
  onFillAllGaps,
}: CoveragePanelProps) {
  const [open, setOpen] = React.useState(true);
  const gaps = coverage?.gaps ?? [];
  const segments = coverage ? buildSegments(coverage) : [];
  const totalDays = Math.max(
    1,
    segments.reduce((sum, segment) => sum + daysBetween(segment.start, segment.end), 0),
  );

  return (
    <Card
      title="Coverage"
      icon={CalendarRange}
      actions={(
        <button
          type="button"
          onClick={() => setOpen((value) => !value)}
          className="p-1 rounded text-gray-400 hover:text-financial-light hover:bg-gray-700 focus:outline-none focus:ring-2 focus:ring-financial-blue"
          aria-label={open ? 'Collapse coverage' : 'Expand coverage'}
        >
          {open ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
        </button>
      )}
    >
      {open && (
        <div className="space-y-4">
          {isLoading ? (
            <div className="text-sm text-gray-400">Loading coverage...</div>
          ) : !coverage ? (
            <div className="text-sm text-gray-500">Select a universe to see coverage.</div>
          ) : (
            <>
              <div className="space-y-2">
                <div className="flex items-center justify-between text-xs text-gray-500">
                  <span>{segments[0]?.start ?? coverage.latest_trading_day}</span>
                  <span>{coverage.latest_trading_day}</span>
                </div>
                <div className="relative h-5 overflow-hidden rounded border border-gray-700 bg-gray-950">
                  <div className="flex h-full">
                    {segments.map((segment) => {
                      const width = `${(daysBetween(segment.start, segment.end) / totalDays) * 100}%`;
                      const isGap = segment.kind === 'gap';
                      const title = isGap
                        ? `Gap: ${formatRange(segment.start, segment.end)}, ${weekdayLabel(segment.weekdays)}`
                        : `Covered: ${formatRange(segment.start, segment.end)}, ${segment.events} events`;
                      return (
                        <div
                          key={`${segment.kind}-${segment.start}-${segment.end}`}
                          title={title}
                          className={isGap ? 'h-full border-x border-red-400/70 bg-red-500/10' : 'h-full bg-financial-blue/80'}
                          style={{ width, minWidth: isGap ? '8px' : '6px' }}
                        />
                      );
                    })}
                  </div>
                  <div
                    className="absolute right-0 top-0 h-full w-px bg-yellow-300"
                    title={`Latest completed trading day: ${coverage.latest_trading_day}`}
                  />
                </div>
              </div>

              {gaps.length > 0 ? (
                <div className="space-y-3">
                  <div className="space-y-2">
                    {gaps.map((gap) => (
                      <div
                        key={`${gap.start}-${gap.end}`}
                        className="flex items-center justify-between gap-3 rounded border border-gray-700 bg-gray-800 px-3 py-2"
                      >
                        <div>
                          <div className="text-sm font-medium text-financial-light">{formatRange(gap.start, gap.end)}</div>
                          <div className="text-xs text-gray-400">{weekdayLabel(gap.weekdays)}</div>
                        </div>
                        <Button
                          size="sm"
                          variant="secondary"
                          icon={RefreshCw}
                          disabled={isScanning}
                          onClick={() => onScanGap(gap)}
                        >
                          Scan this gap
                        </Button>
                      </div>
                    ))}
                  </div>
                  <Button
                    size="sm"
                    variant="primary"
                    fullWidth
                    icon={RefreshCw}
                    disabled={isScanning}
                    onClick={() => onFillAllGaps(gaps)}
                  >
                    Fill all gaps
                  </Button>
                  {isScanning && (
                    <p className="text-xs text-amber-300">Scan running; coverage actions are paused.</p>
                  )}
                </div>
              ) : (
                <div className="rounded border border-green-500/30 bg-green-500/10 px-3 py-2 text-sm text-green-300">
                  Covered through {coverage.latest_trading_day}
                </div>
              )}
            </>
          )}
        </div>
      )}
    </Card>
  );
}
