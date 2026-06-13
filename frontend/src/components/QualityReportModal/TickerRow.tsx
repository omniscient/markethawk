import React, { useState } from 'react';
import { ChevronDown, ChevronRight, Trash2 } from 'lucide-react';
import Ticker from '../Ticker';
import type { QualityTickerResult } from '../../api/universe';
import GradeBadge from './GradeBadge';
import ScoreBar from './ScoreBar';
import CoverageBreakdown from './CoverageBreakdown';

interface TickerRowProps {
  result: QualityTickerResult;
  onDelete: (r: QualityTickerResult) => void;
}

const TickerRow: React.FC<TickerRowProps> = ({ result, onDelete }) => {
  const [expanded, setExpanded] = useState(false);
  const hasGaps = result.gaps.length > 0;
  const hasIssues = result.bad_bar_count > 0 || result.duplicate_count > 0;
  const hasCoverageDetail = result.coverage_pct < 100 && !!result.coverage_detail;

  const isExpandable = hasGaps || hasIssues || hasCoverageDetail;

  return (
    <>
      <tr
        className={`border-b border-gray-800 hover:bg-gray-800/40 ${isExpandable ? 'cursor-pointer' : ''}`}
        onClick={() => isExpandable && setExpanded((v) => !v)}
      >
        <td className="px-3 py-2">
          <div className="flex items-center gap-1.5">
            {isExpandable
              ? (expanded ? <ChevronDown className="h-3.5 w-3.5 text-gray-500 flex-shrink-0" /> : <ChevronRight className="h-3.5 w-3.5 text-gray-500 flex-shrink-0" />)
              : <span className="w-3.5" />}
            <Ticker
              ticker={result.ticker}
              assetClass={result.asset_class}
              size="sm"
            />
          </div>
        </td>
        <td className="px-3 py-2">
          <span className="text-xs text-gray-400 font-mono">
            {result.timespan ? `${result.multiplier !== 1 ? result.multiplier : ''}${result.timespan}` : '—'}
          </span>
        </td>
        <td className="px-3 py-2"><GradeBadge grade={result.grade} size="sm" /></td>
        <td className="px-3 py-2 w-36"><ScoreBar value={result.coverage_pct} /></td>
        <td className="px-3 py-2 text-right">
          <span className={`text-xs font-mono ${result.gap_count > 0 ? 'text-orange-400' : 'text-gray-500'}`}>
            {result.gap_count}
          </span>
        </td>
        <td className="px-3 py-2 text-right">
          <span className={`text-xs font-mono ${result.bad_bar_count > 0 ? 'text-red-400' : 'text-gray-500'}`}>
            {result.bad_bar_count}
          </span>
        </td>
        <td className="px-3 py-2 text-right text-xs text-gray-500 font-mono">
          {result.actual_bars.toLocaleString()}
        </td>
        <td className="px-3 py-2 text-right text-xs text-gray-500 font-mono">
          {result.first_bar ? new Date(result.first_bar).toLocaleDateString() : '—'}
        </td>
        <td className="px-3 py-2 text-right text-xs text-gray-500 font-mono">
          {result.last_bar ? new Date(result.last_bar).toLocaleDateString() : '—'}
        </td>
        <td className="px-3 py-2 text-right">
          <button
            onClick={(e) => { e.stopPropagation(); onDelete(result); }}
            className="p-1 text-gray-600 hover:text-red-400 transition-colors rounded"
            title="Remove ticker from universe"
          >
            <Trash2 className="h-3.5 w-3.5" />
          </button>
        </td>
      </tr>
      {expanded && isExpandable && (
        <tr className="bg-gray-900/60 border-b border-gray-800">
          <td colSpan={10} className="px-6 py-3 space-y-3">
            {hasIssues && (
              <div className="flex gap-4 text-xs">
                {result.bad_bar_count > 0 && (
                  <span className="text-red-400">{result.bad_bar_count} bad bar{result.bad_bar_count !== 1 ? 's' : ''} (OHLCV integrity)</span>
                )}
                {result.duplicate_count > 0 && (
                  <span className="text-orange-400">{result.duplicate_count} duplicate timestamp{result.duplicate_count !== 1 ? 's' : ''}</span>
                )}
              </div>
            )}
            {hasGaps && (
              <div className="space-y-1">
                <p className="text-xs text-gray-500 mb-1">Data gaps ({result.gap_count} total{result.gaps.length < result.gap_count ? `, showing first ${result.gaps.length}` : ''}):</p>
                <div className="grid gap-1">
                  {result.gaps.map((gap, i) => (
                    <div key={i} className="flex items-center gap-3 text-xs font-mono">
                      <span className="text-gray-400">{new Date(gap.from).toLocaleString()}</span>
                      <span className="text-gray-600">→</span>
                      <span className="text-gray-400">{new Date(gap.to).toLocaleString()}</span>
                      <span className="text-orange-400">{gap.duration_hours}h gap</span>
                      <span className="text-gray-500">~{gap.missing_bars} missing bars</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
            {hasCoverageDetail && result.coverage_detail && (
              <CoverageBreakdown detail={result.coverage_detail} coveragePct={result.coverage_pct} />
            )}
          </td>
        </tr>
      )}
    </>
  );
};

export default TickerRow;
