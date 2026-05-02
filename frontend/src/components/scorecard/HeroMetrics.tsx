import React from 'react';
import { Scorecard } from '../../api/outcomes';

interface HeroMetricsProps {
  scorecard: Scorecard;
}

const fmt = (val: number | null, suffix: string = '%'): string => {
  if (val === null || val === undefined) return '—';
  return `${val.toFixed(1)}${suffix}`;
};

const fmtRatio = (val: number | null): string => {
  if (val === null || val === undefined) return '—';
  return `${val.toFixed(1)} : 1`;
};

const colorByThreshold = (val: number | null, threshold: number): string => {
  if (val === null) return 'text-financial-light';
  return val >= threshold ? 'text-green-400' : 'text-red-400';
};

const HeroMetrics: React.FC<HeroMetricsProps> = ({ scorecard }) => {
  return (
    <div className="space-y-4">
      {/* Primary metrics */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="bg-financial-gray rounded-lg border border-gray-700 p-5">
          <div className="text-[10px] uppercase tracking-wider text-gray-400 font-medium mb-1">Win Rate</div>
          <div className={`text-3xl font-bold ${colorByThreshold(scorecard.win_rate_pct, 50)}`}>
            {fmt(scorecard.win_rate_pct)}
          </div>
          <div className="text-xs text-gray-500 mt-1">
            {scorecard.complete_signals} / {scorecard.total_signals} signals
          </div>
        </div>

        <div className="bg-financial-gray rounded-lg border border-gray-700 p-5">
          <div className="text-[10px] uppercase tracking-wider text-gray-400 font-medium mb-1">MFE : MAE</div>
          <div className="text-3xl font-bold text-financial-light">
            {fmtRatio(scorecard.mfe_mae_ratio)}
          </div>
          <div className="text-xs text-gray-500 mt-1">
            Avg MFE {fmt(scorecard.avg_mfe_pct)} / MAE {fmt(scorecard.avg_mae_pct)}
          </div>
        </div>

        <div className="bg-financial-gray rounded-lg border border-gray-700 p-5">
          <div className="text-[10px] uppercase tracking-wider text-gray-400 font-medium mb-1">Expectancy</div>
          <div className={`text-3xl font-bold ${colorByThreshold(scorecard.expectancy, 0)}`}>
            {scorecard.expectancy !== null ? `${scorecard.expectancy > 0 ? '+' : ''}${scorecard.expectancy.toFixed(1)}%` : '—'}
          </div>
          <div className="text-xs text-gray-500 mt-1">Per signal avg return</div>
        </div>

        <div className="bg-financial-gray rounded-lg border border-gray-700 p-5">
          <div className="text-[10px] uppercase tracking-wider text-gray-400 font-medium mb-1">Follow-Through</div>
          <div className="text-3xl font-bold text-financial-light">
            {fmt(scorecard.follow_through_rate_pct)}
          </div>
          <div className="text-xs text-gray-500 mt-1">
            Hit ≥2% threshold
          </div>
        </div>
      </div>

      {/* Secondary metrics */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <div className="bg-financial-gray rounded-lg border border-gray-700 p-4">
          <div className="text-[10px] uppercase tracking-wider text-gray-400 font-medium">Profit Factor</div>
          <div className={`text-xl font-semibold mt-1 ${colorByThreshold(scorecard.profit_factor, 1)}`}>
            {scorecard.profit_factor !== null ? scorecard.profit_factor.toFixed(1) : '—'}
          </div>
        </div>

        <div className="bg-financial-gray rounded-lg border border-gray-700 p-4">
          <div className="text-[10px] uppercase tracking-wider text-gray-400 font-medium">Avg R-Multiple</div>
          <div className={`text-xl font-semibold mt-1 ${colorByThreshold(scorecard.avg_r_multiple, 0)}`}>
            {scorecard.avg_r_multiple !== null ? `${scorecard.avg_r_multiple > 0 ? '+' : ''}${scorecard.avg_r_multiple.toFixed(1)}R` : '—'}
          </div>
        </div>

        <div className="bg-financial-gray rounded-lg border border-gray-700 p-4">
          <div className="text-[10px] uppercase tracking-wider text-gray-400 font-medium">Total / Complete</div>
          <div className="text-xl font-semibold mt-1 text-financial-light">
            {scorecard.total_signals} / {scorecard.complete_signals}
          </div>
        </div>
      </div>
    </div>
  );
};

export default HeroMetrics;
