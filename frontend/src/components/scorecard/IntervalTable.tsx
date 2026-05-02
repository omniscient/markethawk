import React from 'react';
import { IntervalBreakdown } from '../../api/outcomes';

interface IntervalTableProps {
  data: Record<string, IntervalBreakdown>;
  isLoading: boolean;
}

const INTERVAL_ORDER = ['1h', '4h', 'eod', '1d', '2d', '5d'];

const colorForPct = (val: number): string => {
  if (val > 0) return 'text-green-400';
  if (val < 0) return 'text-red-400';
  return 'text-financial-light';
};

const colorForWinRate = (val: number): string => {
  if (val >= 50) return 'text-green-400';
  return 'text-red-400';
};

const IntervalTable: React.FC<IntervalTableProps> = ({ data, isLoading }) => {
  if (isLoading) {
    return (
      <div className="bg-financial-gray rounded-lg border border-gray-700 p-4">
        <div className="text-sm font-semibold text-financial-light mb-3">Interval Breakdown</div>
        <div className="space-y-2">
          {[1, 2, 3, 4, 5, 6].map((i) => (
            <div key={i} className="h-10 bg-gray-800/50 rounded animate-pulse" />
          ))}
        </div>
      </div>
    );
  }

  if (!data || Object.keys(data).length === 0) {
    return (
      <div className="bg-financial-gray rounded-lg border border-gray-700 p-4">
        <div className="text-sm font-semibold text-financial-light mb-3">Interval Breakdown</div>
        <div className="h-40 flex items-center justify-center text-gray-500 text-sm">
          No interval data available
        </div>
      </div>
    );
  }

  const sortedKeys = INTERVAL_ORDER.filter((k) => k in data);
  const extraKeys = Object.keys(data).filter((k) => !INTERVAL_ORDER.includes(k));
  const allKeys = [...sortedKeys, ...extraKeys];

  return (
    <div className="bg-financial-gray rounded-lg border border-gray-700 p-4">
      <div className="text-sm font-semibold text-financial-light mb-3">Interval Breakdown</div>
      <div className="overflow-x-auto">
        <table className="min-w-full">
          <thead>
            <tr className="text-left text-[10px] font-bold text-gray-500 uppercase tracking-wider border-b border-gray-700">
              <th className="px-4 py-3">Interval</th>
              <th className="px-4 py-3 text-right">Avg %</th>
              <th className="px-4 py-3 text-right">Median %</th>
              <th className="px-4 py-3 text-right">Std Dev</th>
              <th className="px-4 py-3 text-right">Win Rate</th>
              <th className="px-4 py-3 text-right">Samples</th>
            </tr>
          </thead>
          <tbody>
            {allKeys.map((key) => {
              const row = data[key];
              return (
                <tr key={key} className="border-b border-gray-800 hover:bg-gray-800/30 transition-colors">
                  <td className="px-4 py-3 text-sm font-semibold text-financial-light uppercase">{key}</td>
                  <td className={`px-4 py-3 text-sm text-right font-mono ${colorForPct(row.avg_pct)}`}>
                    {row.avg_pct > 0 ? '+' : ''}{row.avg_pct.toFixed(1)}%
                  </td>
                  <td className="px-4 py-3 text-sm text-right font-mono text-financial-light">
                    {row.median_pct > 0 ? '+' : ''}{row.median_pct.toFixed(1)}%
                  </td>
                  <td className="px-4 py-3 text-sm text-right font-mono text-gray-400">
                    {row.stddev_pct.toFixed(1)}
                  </td>
                  <td className={`px-4 py-3 text-sm text-right font-mono ${colorForWinRate(row.win_rate)}`}>
                    {row.win_rate.toFixed(0)}%
                  </td>
                  <td className="px-4 py-3 text-sm text-right font-mono text-gray-400">
                    {row.sample_size}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
};

export default IntervalTable;
