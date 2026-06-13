import React from 'react';

interface QualityFiltersBarProps {
  timespanFilter: string;
  onTimespanChange: (ts: string) => void;
  minScore: number;
  onMinScoreChange: (v: number) => void;
  availableTimespans: string[];
  totalCount: number;
  activeCount: number;
}

const QualityFiltersBar: React.FC<QualityFiltersBarProps> = ({
  timespanFilter,
  onTimespanChange,
  minScore,
  onMinScoreChange,
  availableTimespans,
  totalCount,
  activeCount,
}) => (
  <div className="flex flex-wrap items-center gap-6 px-1 py-1">
    <div className="flex flex-col gap-1.5">
      <span className="text-[10px] uppercase tracking-wider text-gray-500 font-bold ml-0.5">Timespans</span>
      <div className="flex gap-1 bg-gray-900/40 p-1 rounded-lg border border-gray-800">
        <button
          onClick={() => onTimespanChange('all')}
          className={`px-3 py-1 text-xs rounded transition-all ${
            timespanFilter === 'all' ? 'bg-financial-blue text-white shadow-lg shadow-financial-blue/20' : 'text-gray-400 hover:text-gray-200'
          }`}
        >
          All
        </button>
        {availableTimespans.map((ts) => (
          <button
            key={ts}
            onClick={() => onTimespanChange(ts)}
            className={`px-3 py-1 text-xs rounded transition-all ${
              timespanFilter === ts ? 'bg-financial-blue text-white shadow-lg shadow-financial-blue/20' : 'text-gray-400 hover:text-gray-200'
            }`}
          >
            {ts}
          </button>
        ))}
      </div>
    </div>

    <div className="flex flex-col gap-1.5 flex-1 min-w-[200px]">
      <div className="flex justify-between items-end ml-0.5">
        <span className="text-[10px] uppercase tracking-wider text-gray-500 font-bold">Min Coverage Score</span>
        <span className={`text-xs font-mono font-bold ${minScore > 90 ? 'text-green-400' : minScore > 70 ? 'text-yellow-400' : 'text-financial-blue'}`}>
          {minScore}%
        </span>
      </div>
      <div className="relative flex items-center h-8">
        <input
          type="range"
          min="0"
          max="100"
          step="1"
          value={minScore}
          onChange={(e) => onMinScoreChange(parseInt(e.target.value))}
          className="w-full h-1.5 bg-gray-800 rounded-lg appearance-none cursor-pointer accent-financial-blue hover:accent-financial-blue/80 transition-all"
        />
        <div className="absolute top-6 left-0 w-full flex justify-between px-0.5 pointer-events-none">
          {[0, 25, 50, 75, 100].map(v => (
            <span key={v} className="text-[8px] text-gray-600 font-mono">{v}</span>
          ))}
        </div>
      </div>
    </div>

    <div className="flex-shrink-0 bg-gray-900/40 px-3 py-2.5 rounded-lg border border-gray-800 flex flex-col items-center">
      <span className="text-[10px] uppercase tracking-wider text-gray-500 font-bold mb-0.5">Active Selection</span>
      <span className="text-sm font-mono text-financial-light font-bold">
        {activeCount} <span className="text-[10px] text-gray-500 font-normal">of {totalCount}</span>
      </span>
    </div>
  </div>
);

export default QualityFiltersBar;
