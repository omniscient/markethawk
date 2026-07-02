import React from 'react';
import { AlertTriangle, CheckCircle2, History, XCircle } from 'lucide-react';
import type { ScannerExplanation, ScannerCriterionExplanation } from '../api/scanner';

interface ScannerExplanationPanelProps {
  explanation?: ScannerExplanation | null;
}

const formatValue = (value: unknown, unit?: string | null): string => {
  if (value == null) return 'n/a';
  const suffix = unit ? unit : '';
  if (typeof value === 'number') {
    return `${Number.isInteger(value) ? value.toLocaleString() : value.toFixed(2)}${suffix}`;
  }
  return `${String(value)}${suffix}`;
};

const CriteriaPill: React.FC<{
  criterion: ScannerCriterionExplanation;
  passed: boolean;
}> = ({ criterion, passed }) => {
  const Icon = passed ? CheckCircle2 : XCircle;
  const tone = passed
    ? 'border-emerald-500/25 bg-emerald-500/10 text-emerald-300'
    : 'border-rose-500/25 bg-rose-500/10 text-rose-300';
  const observed = formatValue(criterion.observed, criterion.unit);
  const threshold =
    criterion.operator === 'exists'
      ? 'exists'
      : `${criterion.operator} ${formatValue(criterion.threshold, criterion.unit)}`;

  return (
    <span
      className={`inline-flex max-w-full items-center gap-1 rounded border px-1.5 py-0.5 text-[10px] font-semibold ${tone}`}
      title={`${criterion.label}: ${observed} ${threshold}`}
    >
      <Icon className="h-3 w-3 shrink-0" />
      <span className="truncate">{criterion.label}</span>
      <span className="font-mono text-[9px] opacity-80">{observed}</span>
    </span>
  );
};

const ScannerExplanationPanel: React.FC<ScannerExplanationPanelProps> = ({ explanation }) => {
  if (!explanation) return null;

  const passed = Object.values(explanation.criteria_passed || {}).slice(0, 2);
  const failed = Object.values(explanation.criteria_failed || {}).slice(0, 2);
  const warnings = explanation.data_quality_warnings || [];

  return (
    <div className="mt-2 space-y-2 rounded-md border border-gray-700/70 bg-gray-900/55 p-2">
      <div className="flex items-start justify-between gap-2">
        <p className="min-w-0 text-xs leading-5 text-gray-300">{explanation.why[0]}</p>
        {explanation.evidence.reconstructed && (
          <span
            className="inline-flex shrink-0 items-center gap-1 rounded border border-blue-500/25 bg-blue-500/10 px-1.5 py-0.5 text-[10px] font-bold uppercase text-blue-300"
            title={explanation.evidence.reconstruction_quality ?? 'reconstructed'}
          >
            <History className="h-3 w-3" />
            Rebuilt
          </span>
        )}
      </div>

      {(passed.length > 0 || failed.length > 0) && (
        <div className="flex max-w-full flex-wrap gap-1.5">
          {passed.map((criterion) => (
            <CriteriaPill
              key={`passed-${criterion.label}`}
              criterion={criterion}
              passed
            />
          ))}
          {failed.map((criterion) => (
            <CriteriaPill
              key={`failed-${criterion.label}`}
              criterion={criterion}
              passed={false}
            />
          ))}
        </div>
      )}

      {warnings.length > 0 && (
        <div className="flex items-start gap-1.5 text-[11px] leading-4 text-amber-300">
          <AlertTriangle className="mt-0.5 h-3 w-3 shrink-0" />
          <span>{warnings[0].message}</span>
        </div>
      )}
    </div>
  );
};

export default ScannerExplanationPanel;
