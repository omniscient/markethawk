import type { ScannerRunResponse } from '../../api/scanner';

export interface ProviderDegradedBannerProps {
  run?: ScannerRunResponse | null;
}

/** Live Polygon degradation recorded on the latest scan run (#388, ADR-0013). */
export function ProviderDegradedBanner({ run }: ProviderDegradedBannerProps) {
  const gaps = run?.live_provider_gaps ?? [];
  if (gaps.length === 0) return null;
  return (
    <div
      role="alert"
      className="flex items-start gap-3 rounded-lg border border-amber-400 bg-amber-50 px-4 py-3 text-amber-800 dark:border-amber-500 dark:bg-amber-900/20 dark:text-amber-300"
    >
      <span className="mt-0.5 text-lg leading-none">⚠️</span>
      <div className="flex-1 text-sm">
        <span className="font-semibold">Market data degraded during this scan</span> — results may be
        incomplete{run?.status === 'failed' ? ' and the scan was stopped' : ''}.
        <ul className="mt-1 list-disc pl-5">
          {gaps.map((gap, i) => (
            <li key={`${gap.detail.reason}-${i}`}>
              {gap.message}
              {typeof gap.detail.coverage_ratio === 'number' &&
                ` (coverage ${Math.round(gap.detail.coverage_ratio * 100)}%)`}
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
