import React from 'react';
import GradeBadge, { GRADE_STYLES, GRADE_LABEL } from './GradeBadge';
import type { QualityReport } from '../../api/universe';

type ReportData = NonNullable<QualityReport['report_data']>;

interface QualityOverviewCardProps {
  rd: ReportData;
  gradeFilter: string;
  onGradeFilterChange: (grade: string) => void;
}

const QualityOverviewCard: React.FC<QualityOverviewCardProps> = ({ rd, gradeFilter, onGradeFilterChange }) => (
  <div className="flex items-center gap-6 bg-gray-800/50 rounded-lg p-4">
    <div className="flex flex-col items-center gap-1">
      <GradeBadge grade={rd.overall_grade} size="lg" />
      <span className="text-[10px] text-gray-500 text-center max-w-[90px] leading-tight">
        {GRADE_LABEL[rd.overall_grade]}
      </span>
    </div>
    <div className="flex-1 grid grid-cols-2 gap-x-8 gap-y-2 text-sm">
      <div className="flex justify-between">
        <span className="text-gray-400">Overall score</span>
        <span className="text-financial-light font-mono">{rd.overall_score.toFixed(1)}</span>
      </div>
      <div className="flex justify-between">
        <span className="text-gray-400">Tickers</span>
        <span className="text-financial-light font-mono">{rd.ticker_count}</span>
      </div>
      <div className="flex justify-between">
        <span className="text-gray-400">Timespans</span>
        <span className="text-financial-light font-mono">{rd.timespans_analyzed.join(', ') || '—'}</span>
      </div>
      <div className="flex justify-between">
        <span className="text-gray-400">Combinations</span>
        <span className="text-financial-light font-mono">{rd.analyzed_count}</span>
      </div>
    </div>
    <div className="flex gap-1.5 flex-wrap justify-end">
      {(['A', 'B', 'C', 'D', 'F'] as const).map((g) => {
        const count = rd.grade_distribution[g] ?? 0;
        if (!count) return null;
        return (
          <button
            key={g}
            onClick={() => onGradeFilterChange(gradeFilter === g ? 'all' : g)}
            className={`flex flex-col items-center px-2 py-1 rounded border text-xs transition-all ${
              GRADE_STYLES[g]
            } ${gradeFilter === g ? 'opacity-100' : 'opacity-60 hover:opacity-100'}`}
          >
            <span className="font-bold font-mono">{g}</span>
            <span>{count}</span>
          </button>
        );
      })}
    </div>
  </div>
);

export default QualityOverviewCard;
