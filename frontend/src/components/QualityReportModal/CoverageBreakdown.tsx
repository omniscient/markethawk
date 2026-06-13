import React, { useState } from 'react';
import type { CoverageDetail } from '../../api/universe';

interface CoverageBreakdownProps {
  detail: CoverageDetail;
  coveragePct: number;
}

const CoverageBreakdown: React.FC<CoverageBreakdownProps> = ({ detail, coveragePct }) => {
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
};

export default CoverageBreakdown;
