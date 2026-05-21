import React, { useState } from 'react';
import type { CorrelationResponse } from '../api/analysis';

interface Props {
  data: CorrelationResponse;
}

function interpolateColor(r: number): string {
  // r in [-1, 1]: -1 → red #EF4444, 0 → dark gray #374151, 1 → green #10B981
  const clamp = Math.max(-1, Math.min(1, r));
  if (clamp >= 0) {
    const t = clamp;
    const red = Math.round(55 + (16 - 55) * t);
    const green = Math.round(65 + (185 - 65) * t);
    const blue = Math.round(81 + (129 - 81) * t);
    return `rgb(${red}, ${green}, ${blue})`;
  } else {
    const t = -clamp;
    const red = Math.round(55 + (239 - 55) * t);
    const green = Math.round(65 + (68 - 65) * t);
    const blue = Math.round(81 + (68 - 81) * t);
    return `rgb(${red}, ${green}, ${blue})`;
  }
}

const CorrelationHeatmap: React.FC<Props> = ({ data }) => {
  const [mode, setMode] = useState<'pearson' | 'spearman'>('pearson');

  const matrix = mode === 'pearson' ? data.pearson : data.spearman;

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        {(['pearson', 'spearman'] as const).map((m) => (
          <button
            key={m}
            onClick={() => setMode(m)}
            className={`px-3 py-1 text-[10px] font-black uppercase tracking-widest rounded-md transition-all ${
              mode === m
                ? 'bg-financial-blue text-white'
                : 'text-gray-500 hover:text-white border border-gray-700'
            }`}
          >
            {m}
          </button>
        ))}
        <span className="text-gray-500 text-xs ml-2">
          {data.event_count.toLocaleString()} events
        </span>
      </div>

      <div className="overflow-x-auto">
        <table className="text-xs border-collapse w-full">
          <thead>
            <tr>
              <th className="text-left text-gray-400 font-medium py-1 pr-4 whitespace-nowrap">
                Feature
              </th>
              {data.intervals.map((interval) => (
                <th
                  key={interval}
                  className="text-center text-gray-400 font-medium py-1 px-2 whitespace-nowrap uppercase tracking-wider"
                >
                  {interval}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data.features.map((feature, fi) => (
              <tr key={feature}>
                <td className="text-gray-300 pr-4 py-1 whitespace-nowrap font-mono text-[11px]">
                  {feature}
                </td>
                {data.intervals.map((_, ii) => {
                  const val = matrix[fi]?.[ii] ?? 0;
                  return (
                    <td
                      key={ii}
                      className="text-center py-1 px-2 font-mono text-[11px] font-bold rounded"
                      style={{ backgroundColor: interpolateColor(val), color: '#F9FAFB' }}
                    >
                      {val.toFixed(2)}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
};

export default CorrelationHeatmap;
