import React, { useState } from 'react';
import { ChevronDown, ChevronRight, ShieldOff } from 'lucide-react';
import type { QualityGateAssessment } from '../api/scanner';
import TrustGateSummary from './TrustGateSummary';
import { VERDICT_CONFIG } from './verdictConfig';

interface TrustGateBannerProps {
  gate: QualityGateAssessment;
}

const TrustGateBanner: React.FC<TrustGateBannerProps> = ({ gate }) => {
  const [open, setOpen] = useState(false);
  const style = VERDICT_CONFIG[gate.verdict] ?? VERDICT_CONFIG.skipped;
  const Icon = style.icon ?? ShieldOff;

  return (
    <div className={`mb-4 rounded-lg border ${style.bg} ${style.border}`}>
      <button
        className="w-full flex items-center gap-3 px-4 py-2.5 text-left"
        onClick={() => setOpen(v => !v)}
        aria-expanded={open}
      >
        <Icon className={`h-4 w-4 flex-shrink-0 ${style.text}`} />
        <span className={`text-xs font-bold uppercase tracking-wider ${style.text}`}>
          {gate.verdict}
        </span>
        <span className="text-xs text-gray-400 flex-1">
          {gate.summary.blocker_count > 0 && (
            <span className="text-red-400 font-semibold">{gate.summary.blocker_count} blocker{gate.summary.blocker_count !== 1 ? 's' : ''}</span>
          )}
          {gate.summary.blocker_count > 0 && gate.summary.warning_count > 0 && <span className="mx-1">·</span>}
          {gate.summary.warning_count > 0 && (
            <span className="text-amber-400">{gate.summary.warning_count} warning{gate.summary.warning_count !== 1 ? 's' : ''}</span>
          )}
          {gate.verdict === 'trusted' && (
            <span>Data quality checks passed</span>
          )}
        </span>
        {open ? <ChevronDown className="h-3 w-3 text-gray-500 flex-shrink-0" /> : <ChevronRight className="h-3 w-3 text-gray-500 flex-shrink-0" />}
      </button>

      {open && (
        <div className="px-4 pb-4">
          <TrustGateSummary gate={gate} />
        </div>
      )}
    </div>
  );
};

export default TrustGateBanner;
