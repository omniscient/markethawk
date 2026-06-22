import React, { useState } from 'react';
import { ChevronDown, ChevronRight } from 'lucide-react';
import type { QualityGateAssessment, QualityGateIssue } from '../api/scanner';
import { VERDICT_CONFIG } from './verdictConfig';

interface TrustGateSummaryProps {
  gate?: QualityGateAssessment;
}

const SEVERITY_STYLES: Record<string, string> = {
  blocker: 'bg-red-500/20 text-red-400 border-red-500/30',
  warning: 'bg-amber-500/20 text-amber-400 border-amber-500/30',
  info:    'bg-blue-500/20 text-blue-400 border-blue-500/30',
};

const ISSUE_CODE_LABELS: Record<string, string> = {
  missing_bars:              'Missing Bars',
  split_dividend_anomaly:    'Split/Dividend Anomaly',
  stale_quote_risk:          'Stale Quote Risk',
  provider_gaps:             'Provider Gap',
  timezone_session_mismatch: 'Timezone/Session Mismatch',
  survivorship_bias_risk:    'Survivorship Bias',
  stale_reference_data:      'Stale Reference Data',
};

interface IssueGroupProps {
  code: string;
  issues: QualityGateIssue[];
}

const IssueGroup: React.FC<IssueGroupProps> = ({ code, issues }) => {
  const [open, setOpen] = useState(false);
  const label = ISSUE_CODE_LABELS[code] ?? code.replace(/_/g, ' ');
  const worstSeverity = issues.some(i => i.severity === 'blocker') ? 'blocker'
    : issues.some(i => i.severity === 'warning') ? 'warning' : 'info';

  return (
    <div className="border border-gray-700/60 rounded-lg overflow-hidden">
      <button
        className="w-full flex items-center justify-between px-3 py-2 text-left hover:bg-gray-800/40 transition-colors"
        onClick={() => setOpen(v => !v)}
        aria-expanded={open}
      >
        <div className="flex items-center gap-2">
          {open ? <ChevronDown className="h-3 w-3 text-gray-500" /> : <ChevronRight className="h-3 w-3 text-gray-500" />}
          <span className="text-xs font-semibold text-gray-200">{label}</span>
          <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded border ${SEVERITY_STYLES[worstSeverity]}`}>
            {worstSeverity}
          </span>
        </div>
        <span className="text-[10px] text-gray-500">{issues.length} issue{issues.length !== 1 ? 's' : ''}</span>
      </button>

      {open && (
        <ul className="divide-y divide-gray-800/60 bg-gray-900/40">
          {issues.map((issue, i) => (
            <li key={i} className="px-4 py-2 text-xs space-y-1">
              <div className="flex items-center gap-2 flex-wrap">
                <span className={`font-bold px-1.5 py-0.5 rounded border text-[10px] ${SEVERITY_STYLES[issue.severity]}`}>
                  {issue.severity}
                </span>
                {issue.ticker && (
                  <span className="text-financial-light font-mono">{issue.ticker}</span>
                )}
                <span className="text-gray-400">{issue.scope}</span>
              </div>
              {issue.affected_inputs && (
                <div className="text-gray-500 space-y-0.5">
                  {issue.affected_inputs.timespans && (
                    <div>Timespans: {issue.affected_inputs.timespans.join(', ')}</div>
                  )}
                  {issue.affected_inputs.session && (
                    <div>Session: {issue.affected_inputs.session}</div>
                  )}
                  {issue.affected_inputs.fields && (
                    <div>Fields: {issue.affected_inputs.fields.join(', ')}</div>
                  )}
                  {issue.affected_inputs.date_range && (
                    <div>Date range: {issue.affected_inputs.date_range.start} – {issue.affected_inputs.date_range.end}</div>
                  )}
                </div>
              )}
              {issue.remediation && (
                <div className="text-gray-400 italic">
                  {issue.remediation.label}
                  {issue.remediation.automated && (
                    <span className="ml-1 text-[10px] text-green-400 font-bold">[auto]</span>
                  )}
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
};

const TrustGateSummary: React.FC<TrustGateSummaryProps> = ({ gate }) => {
  const [prevAssessmentId, setPrevAssessmentId] = useState(gate?.assessment_id);
  const [issuesOpen, setIssuesOpen] = useState(gate?.verdict === 'blocked');

  // Sync open state when a new gate arrives (React "prev-state during render" pattern)
  if (gate?.assessment_id !== prevAssessmentId) {
    setPrevAssessmentId(gate?.assessment_id);
    if (gate?.verdict === 'blocked') {
      setIssuesOpen(true);
    }
  }

  if (!gate) return null;

  const style = VERDICT_CONFIG[gate.verdict] ?? VERDICT_CONFIG.skipped;
  const Icon = style.icon;

  const grouped = gate.issues.reduce<Record<string, QualityGateIssue[]>>((acc, issue) => {
    const key = issue.issue_code;
    if (!acc[key]) acc[key] = [];
    acc[key].push(issue);
    return acc;
  }, {});

  return (
    <div className={`rounded-lg border p-4 space-y-3 ${style.bg} ${style.border}`}>
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Icon className={`h-5 w-5 ${style.text}`} />
          <span className={`text-sm font-bold uppercase tracking-wider ${style.text}`}>
            {gate.verdict}
          </span>
        </div>
        <div className="flex items-center gap-3 text-[11px]">
          {gate.summary.blocker_count > 0 && (
            <span className="bg-red-500/20 text-red-400 border border-red-500/30 px-2 py-0.5 rounded font-bold">
              {gate.summary.blocker_count} blocker{gate.summary.blocker_count !== 1 ? 's' : ''}
            </span>
          )}
          {gate.summary.warning_count > 0 && (
            <span className="bg-amber-500/20 text-amber-400 border border-amber-500/30 px-2 py-0.5 rounded font-bold">
              {gate.summary.warning_count} warning{gate.summary.warning_count !== 1 ? 's' : ''}
            </span>
          )}
          {gate.verdict === 'trusted' && (
            <span className="text-gray-500">Data quality checks passed</span>
          )}
        </div>
      </div>

      {gate.summary.most_affected_tickers.length > 0 && (
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-[10px] text-gray-500 uppercase tracking-wider">Most affected:</span>
          {gate.summary.most_affected_tickers.slice(0, 5).map(t => (
            <span key={t.ticker} className="text-[10px] font-mono text-financial-light bg-gray-800/60 px-1.5 py-0.5 rounded">
              {t.ticker}
            </span>
          ))}
        </div>
      )}

      {gate.issues.length > 0 && (
        <div className="space-y-2">
          <button
            className="flex items-center gap-1 text-[11px] text-gray-400 hover:text-gray-200 transition-colors"
            onClick={() => setIssuesOpen(v => !v)}
            aria-expanded={issuesOpen}
          >
            {issuesOpen ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
            {issuesOpen ? 'Hide' : 'Show'} issues ({gate.issues.length})
          </button>

          {issuesOpen && (
            <div className="space-y-1.5">
              {Object.entries(grouped).map(([code, issues]) => (
                <IssueGroup key={code} code={code} issues={issues} />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
};

export default TrustGateSummary;
