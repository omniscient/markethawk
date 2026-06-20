import React from 'react';
import { useNavigate } from 'react-router-dom';
import { AreaChart, Area, ResponsiveContainer } from 'recharts';
import { Scorecard } from '../../api/outcomes';

interface ScannerSummaryCardProps {
  scannerType: string;
  scannerName: string;
  scorecard: Scorecard | null;
  isLoading: boolean;
}

const fmt = (val: number | null, suffix: string = '%'): string => {
  if (val === null || val === undefined) return '—';
  return `${val.toFixed(1)}${suffix}`;
};

const ScannerSummaryCard: React.FC<ScannerSummaryCardProps> = ({
  scannerType,
  scannerName,
  scorecard,
  isLoading,
}) => {
  const navigate = useNavigate();

  if (isLoading) {
    return (
      <div className="bg-financial-gray rounded-lg border border-gray-700 p-5 animate-pulse">
        <div className="h-5 bg-gray-700 rounded w-2/3 mb-3" />
        <div className="h-4 bg-gray-700 rounded w-1/3 mb-4" />
        <div className="grid grid-cols-4 gap-3 mb-4">
          {[1, 2, 3, 4].map((i) => (
            <div key={i}>
              <div className="h-3 bg-gray-700 rounded w-full mb-1" />
              <div className="h-6 bg-gray-700 rounded w-2/3" />
            </div>
          ))}
        </div>
        <div className="h-10 bg-gray-700 rounded" />
      </div>
    );
  }

  const sparkData = (scorecard?.edge_decay ?? []).slice(-10).map((pt) => ({
    value: pt.win_rate,
  }));

  const winRateColor =
    scorecard?.win_rate_pct !== null && scorecard?.win_rate_pct !== undefined
      ? scorecard.win_rate_pct >= 50
        ? 'text-green-400'
        : 'text-red-400'
      : 'text-financial-light';

  const expectancyColor =
    scorecard?.expectancy !== null && scorecard?.expectancy !== undefined
      ? scorecard.expectancy > 0
        ? 'text-green-400'
        : scorecard.expectancy < 0
          ? 'text-red-400'
          : 'text-yellow-400'
      : 'text-financial-light';

  const precisionPct = scorecard?.precision_pct ?? null;
  const reviewCoveragePct = scorecard?.review_coverage_pct ?? null;
  const reviewSampleN = scorecard?.review_sample_n ?? 0;
  const lowCoverage = reviewCoveragePct !== null && reviewCoveragePct < 20;

  const precisionColor =
    precisionPct === null
      ? 'text-gray-500'
      : precisionPct >= 60
        ? 'text-green-400'
        : precisionPct >= 40
          ? 'text-yellow-400'
          : 'text-red-400';

  const statGridClass =
    scorecard && scorecard.complete_signals < 5 ? 'grid grid-cols-4 gap-3 mb-4 opacity-40' : 'grid grid-cols-4 gap-3 mb-4';

  return (
    <div
      onClick={() => navigate(`/scorecard/${scannerType}`)}
      className="bg-financial-gray rounded-lg border border-gray-700 p-5 cursor-pointer hover:border-financial-blue transition-colors duration-200"
    >
      <div className="flex justify-between items-start mb-4">
        <div>
          <h4 className="text-base font-semibold text-financial-light">{scannerName}</h4>
          <p className="text-xs text-gray-500 mt-0.5">
            {scorecard ? `${scorecard.total_signals} signals • ${scorecard.complete_signals} complete` : 'No data'}
          </p>
        </div>
        {scorecard && scorecard.complete_signals > 0 && (
          <span className="text-xs font-semibold text-green-400">{'▲'} Active</span>
        )}
      </div>

      <div className={statGridClass}>
        <div>
          <div className="text-[9px] uppercase tracking-wider text-gray-500 font-medium">Win Rate</div>
          <div className={`text-lg font-bold ${winRateColor}`}>{fmt(scorecard?.win_rate_pct ?? null)}</div>
        </div>
        <div>
          <div className="text-[9px] uppercase tracking-wider text-gray-500 font-medium">MFE:MAE</div>
          <div className="text-lg font-bold text-financial-light">
            {scorecard?.mfe_mae_ratio !== null && scorecard?.mfe_mae_ratio !== undefined
              ? scorecard.mfe_mae_ratio.toFixed(1)
              : '—'}
          </div>
        </div>
        <div>
          <div className="text-[9px] uppercase tracking-wider text-gray-500 font-medium">Expectancy</div>
          <div className={`text-lg font-bold ${expectancyColor}`}>
            {scorecard?.expectancy !== null && scorecard?.expectancy !== undefined
              ? `${scorecard.expectancy > 0 ? '+' : ''}${scorecard.expectancy.toFixed(1)}%`
              : '—'}
          </div>
        </div>
        <div>
          <div className="text-[9px] uppercase tracking-wider text-gray-500 font-medium">Follow-thru</div>
          <div className="text-lg font-bold text-financial-light">{fmt(scorecard?.follow_through_rate_pct ?? null)}</div>
        </div>
      </div>

      {scorecard && (
        <div className={`flex items-center gap-2 mb-3 ${lowCoverage ? 'opacity-50' : ''}`}>
          <span className={`text-xs font-semibold border rounded px-2 py-0.5 ${
            lowCoverage
              ? 'border-gray-600 text-gray-500'
              : precisionColor.replace('text-', 'border-').replace('-400', '-500') + ' ' + precisionColor
          }`}>
            {precisionPct !== null ? `${precisionPct.toFixed(0)}% confirmed` : 'No reviews'}{reviewSampleN > 0 ? ` · n=${reviewSampleN} · 90d` : ''}
          </span>
          {lowCoverage && (
            <span className="text-[9px] text-gray-500 italic">needs more reviews</span>
          )}
        </div>
      )}

      {sparkData.length > 1 && (
        <>
          <div className="h-10">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={sparkData} margin={{ top: 0, right: 0, bottom: 0, left: 0 }}>
                <defs>
                  <linearGradient id={`spark-${scannerType}`} x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#1f6feb" stopOpacity={0.3} />
                    <stop offset="95%" stopColor="#1f6feb" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <Area
                  type="monotone"
                  dataKey="value"
                  stroke="#1f6feb"
                  strokeWidth={1.5}
                  fill={`url(#spark-${scannerType})`}
                />
              </AreaChart>
            </ResponsiveContainer>
          </div>
          <div className="text-[9px] text-gray-500 mt-1">Win rate trend (last {sparkData.length} periods)</div>
        </>
      )}
    </div>
  );
};

export default ScannerSummaryCard;
