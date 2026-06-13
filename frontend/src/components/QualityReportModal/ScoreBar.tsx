import React from 'react';

interface ScoreBarProps {
  value: number;
}

const ScoreBar: React.FC<ScoreBarProps> = ({ value }) => {
  const color = value >= 95 ? 'bg-green-500' : value >= 85 ? 'bg-emerald-500' : value >= 70 ? 'bg-yellow-500' : value >= 50 ? 'bg-orange-500' : 'bg-red-500';
  return (
    <div className="flex items-center gap-2 min-w-0">
      <div className="flex-1 h-1.5 bg-gray-700 rounded-full overflow-hidden">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${value}%` }} />
      </div>
      <span className="text-xs text-gray-400 w-10 text-right">{value.toFixed(1)}%</span>
    </div>
  );
};

export default ScoreBar;
