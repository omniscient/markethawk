import React, { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { ChevronUp, ChevronDown, ChevronLeft, ChevronRight, Check, X, Sparkles } from 'lucide-react';
import { fetchAISignalBrief } from '../../api/outcomes';
import type { AISignalBrief } from '../../api/outcomes';
import { useSignals } from '../../hooks/useScorecard';

interface SignalTableProps {
  scannerType: string;
  startDate?: string;
  endDate?: string;
  severity?: string;
}

type SortField = 'event_date' | 'ticker' | 'mfe_pct' | 'mae_pct' | 'eod_pct_change';

const PAGE_SIZE = 20;

const colorForPct = (val: number | null): string => {
  if (val === null) return 'text-gray-500';
  if (val > 0) return 'text-green-400';
  if (val < 0) return 'text-red-400';
  return 'text-financial-light';
};

const severityBadge = (severity: string | null) => {
  const colors: Record<string, string> = {
    high: 'bg-red-500/20 text-red-400 border-red-500/30',
    medium: 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30',
    low: 'bg-blue-500/20 text-blue-400 border-blue-500/30',
  };
  const cls = colors[severity ?? ''] ?? 'bg-gray-700/30 text-gray-400 border-gray-600/30';
  return (
    <span className={`px-1.5 py-0.5 text-[10px] font-bold uppercase rounded border ${cls}`}>
      {severity ?? '—'}
    </span>
  );
};

const fmtPct = (val: number | null): string => {
  if (val === null) return '—';
  return `${val > 0 ? '+' : ''}${val.toFixed(2)}%`;
};

const fmtPrice = (val: number | null): string => {
  if (val === null) return '—';
  return `$${val.toFixed(2)}`;
};

const SortIcon: React.FC<{ field: SortField; sortBy: SortField; sortOrder: 'asc' | 'desc' }> = (
  { field, sortBy, sortOrder },
) => {
  if (sortBy !== field) return null;
  return sortOrder === 'desc' ? (
    <ChevronDown className="h-3 w-3 inline ml-0.5" />
  ) : (
    <ChevronUp className="h-3 w-3 inline ml-0.5" />
  );
};

const SignalTable: React.FC<SignalTableProps> = ({ scannerType, startDate, endDate, severity }) => {
  const [sortBy, setSortBy] = useState<SortField>('event_date');
  const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('desc');
  const [page, setPage] = useState(0);
  const [expandedEventId, setExpandedEventId] = useState<number | null>(null);

  const { data, isLoading } = useSignals(scannerType, {
    start_date: startDate,
    end_date: endDate,
    severity: severity || undefined,
    sort_by: sortBy,
    sort_order: sortOrder,
    limit: PAGE_SIZE,
    offset: page * PAGE_SIZE,
  });

  const handleSort = (field: SortField) => {
    if (sortBy === field) {
      setSortOrder(sortOrder === 'desc' ? 'asc' : 'desc');
    } else {
      setSortBy(field);
      setSortOrder('desc');
    }
    setPage(0);
  };

  const totalPages = data ? Math.ceil(data.total / PAGE_SIZE) : 0;

  if (isLoading) {
    return (
      <div className="bg-financial-gray rounded-lg border border-gray-700 p-4">
        <div className="text-sm font-semibold text-financial-light mb-3">Signals</div>
        <div className="space-y-2">
          {Array.from({ length: 5 }).map((_, i) => (
            <div key={i} className="h-10 bg-gray-800/50 rounded animate-pulse" />
          ))}
        </div>
      </div>
    );
  }

  if (!data || data.total === 0) {
    return (
      <div className="bg-financial-gray rounded-lg border border-gray-700 p-4">
        <div className="text-sm font-semibold text-financial-light mb-3">Signals</div>
        <div className="h-32 flex items-center justify-center text-gray-500 text-sm">
          No signals found for this period
        </div>
      </div>
    );
  }

  return (
    <div className="bg-financial-gray rounded-lg border border-gray-700 p-4">
      <div className="flex items-center justify-between mb-3">
        <div className="text-sm font-semibold text-financial-light">
          Signals
          <span className="text-gray-500 font-normal ml-2">{data.total} total</span>
        </div>
        {totalPages > 1 && (
          <div className="flex items-center gap-2 text-xs text-gray-400">
            <button
              onClick={() => setPage(Math.max(0, page - 1))}
              disabled={page === 0}
              className="p-1 rounded hover:bg-gray-800 disabled:opacity-30 disabled:cursor-not-allowed"
            >
              <ChevronLeft className="h-4 w-4" />
            </button>
            <span>
              {page + 1} / {totalPages}
            </span>
            <button
              onClick={() => setPage(Math.min(totalPages - 1, page + 1))}
              disabled={page >= totalPages - 1}
              className="p-1 rounded hover:bg-gray-800 disabled:opacity-30 disabled:cursor-not-allowed"
            >
              <ChevronRight className="h-4 w-4" />
            </button>
          </div>
        )}
      </div>

      <div className="overflow-x-auto">
        <table className="min-w-full">
          <thead>
            <tr className="text-left text-[10px] font-bold text-gray-500 uppercase tracking-wider border-b border-gray-700">
              <th
                className="px-3 py-3 cursor-pointer hover:text-gray-300 transition-colors"
                onClick={() => handleSort('event_date')}
              >
                Date <SortIcon field="event_date" sortBy={sortBy} sortOrder={sortOrder} />
              </th>
              <th
                className="px-3 py-3 cursor-pointer hover:text-gray-300 transition-colors"
                onClick={() => handleSort('ticker')}
              >
                Ticker <SortIcon field="ticker" sortBy={sortBy} sortOrder={sortOrder} />
              </th>
              <th className="px-3 py-3">Severity</th>
              <th className="px-3 py-3 text-right">Ref Price</th>
              <th
                className="px-3 py-3 text-right cursor-pointer hover:text-gray-300 transition-colors"
                onClick={() => handleSort('mfe_pct')}
              >
                MFE <SortIcon field="mfe_pct" sortBy={sortBy} sortOrder={sortOrder} />
              </th>
              <th
                className="px-3 py-3 text-right cursor-pointer hover:text-gray-300 transition-colors"
                onClick={() => handleSort('mae_pct')}
              >
                MAE <SortIcon field="mae_pct" sortBy={sortBy} sortOrder={sortOrder} />
              </th>
              <th
                className="px-3 py-3 text-right cursor-pointer hover:text-gray-300 transition-colors"
                onClick={() => handleSort('eod_pct_change')}
              >
                EOD <SortIcon field="eod_pct_change" sortBy={sortBy} sortOrder={sortOrder} />
              </th>
              <th className="px-3 py-3 text-right">MFE:MAE</th>
              <th className="px-3 py-3 text-center">FT</th>
              <th className="px-3 py-3 text-center">Status</th>
              <th className="px-3 py-3 text-center">Intel</th>
            </tr>
          </thead>
          <tbody>
            {data.signals.map((signal) => (
              <React.Fragment key={signal.id}>
              <tr className="border-b border-gray-800 hover:bg-gray-800/30 transition-colors">
                <td className="px-3 py-2.5 text-sm font-mono text-gray-300">{signal.event_date}</td>
                <td className="px-3 py-2.5">
                  <Link
                    to={`/stock/${signal.ticker}`}
                    className="text-sm font-bold text-financial-blue hover:text-blue-300 transition-colors"
                  >
                    {signal.ticker}
                  </Link>
                </td>
                <td className="px-3 py-2.5">{severityBadge(signal.severity)}</td>
                <td className="px-3 py-2.5 text-sm text-right font-mono text-gray-300">
                  {fmtPrice(signal.reference_price)}
                </td>
                <td className={`px-3 py-2.5 text-sm text-right font-mono ${colorForPct(signal.mfe_pct)}`}>
                  {fmtPct(signal.mfe_pct)}
                </td>
                <td className={`px-3 py-2.5 text-sm text-right font-mono ${colorForPct(signal.mae_pct)}`}>
                  {fmtPct(signal.mae_pct)}
                </td>
                <td className={`px-3 py-2.5 text-sm text-right font-mono ${colorForPct(signal.eod_pct_change)}`}>
                  {fmtPct(signal.eod_pct_change)}
                </td>
                <td className="px-3 py-2.5 text-sm text-right font-mono text-gray-300">
                  {signal.mfe_mae_ratio !== null ? signal.mfe_mae_ratio.toFixed(1) : '—'}
                </td>
                <td className="px-3 py-2.5 text-center">
                  {signal.follow_through === null ? (
                    <span className="text-gray-600">—</span>
                  ) : signal.follow_through ? (
                    <Check className="h-4 w-4 text-green-400 inline" />
                  ) : (
                    <X className="h-4 w-4 text-red-400 inline" />
                  )}
                </td>
                <td className="px-3 py-2.5 text-center">
                  {signal.is_complete === null ? (
                    <span className="text-[10px] font-bold text-gray-600 uppercase">no data</span>
                  ) : signal.is_complete ? (
                    <span className="text-[10px] font-bold text-green-500/70 uppercase">complete</span>
                  ) : (
                    <span className="text-[10px] font-bold text-yellow-500/70 uppercase">pending</span>
                  )}
                </td>
                <td className="px-3 py-2.5 text-center">
                  <button
                    type="button"
                    onClick={() => setExpandedEventId(expandedEventId === signal.id ? null : signal.id)}
                    aria-expanded={expandedEventId === signal.id}
                    className="inline-flex items-center gap-1 rounded border border-gray-700 px-2 py-1 text-[11px] font-semibold text-gray-300 hover:border-financial-blue hover:text-financial-blue"
                  >
                    <Sparkles className="h-3 w-3" />
                    Brief
                  </button>
                </td>
              </tr>
              {expandedEventId === signal.id && (
                <tr className="border-b border-gray-800 bg-gray-950/30">
                  <td colSpan={11} className="px-3 py-3">
                    <SignalIntelligencePanel eventId={signal.id} />
                  </td>
                </tr>
              )}
              </React.Fragment>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
};

const SignalIntelligencePanel: React.FC<{ eventId: number }> = ({ eventId }) => {
  const { data, isLoading, isError } = useQuery<AISignalBrief>({
    queryKey: ['aiSignalBrief', eventId],
    queryFn: () => fetchAISignalBrief(eventId),
  });

  if (isLoading) {
    return (
      <div className="rounded border border-gray-800 bg-gray-950/50 p-4 text-sm text-gray-400">
        Loading deterministic brief...
      </div>
    );
  }

  if (isError || !data) {
    return (
      <div className="rounded border border-red-900/60 bg-red-950/20 p-4 text-sm text-red-300">
        Deterministic brief is unavailable.
      </div>
    );
  }

  const summary = data.outcome_context.summary;
  const analogs = data.analogs.slice(0, 3);

  return (
    <div className="rounded border border-gray-800 bg-gray-950/60 p-4">
      <div className="mb-4 flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <div className="text-sm font-semibold text-financial-light">
            Deterministic Signal Brief
          </div>
          <div className="mt-1 text-xs text-gray-400">
            Facts only. Generated narrative can be added later, but this panel does not infer beyond stored data.
          </div>
        </div>
        <div className="text-xs font-mono text-gray-400">
          {data.facts.ticker} - {data.facts.event_date ?? 'no date'}
        </div>
      </div>

      <div className="grid gap-3 lg:grid-cols-3">
        <BriefBlock title="Explanation">
          {data.why.length > 0 ? (
            <ul className="space-y-1">
              {data.why.map((why) => (
                <li key={why}>{why}</li>
              ))}
            </ul>
          ) : (
            <span>No explanation bullets are stored.</span>
          )}
        </BriefBlock>

        <BriefBlock title="Expected behavior">
          {analogs.length > 0 ? (
            <ul className="space-y-2">
              {analogs.map((analog) => (
                <li key={analog.event_id} className="flex items-center justify-between gap-3">
                  <span>
                    <span className="font-semibold text-financial-light">{analog.ticker}</span>
                    <span className="text-gray-500"> - {Math.round(analog.similarity_score * 100)}% similar</span>
                  </span>
                  <span className={colorForPct(analog.outcome_summary?.eod_pct_change ?? null)}>
                    EOD {fmtPct(analog.outcome_summary?.eod_pct_change ?? null)}
                  </span>
                </li>
              ))}
            </ul>
          ) : (
            <span>No historical analogs were available.</span>
          )}
        </BriefBlock>

        <BriefBlock title="Archetype / Outcome">
          <div className="space-y-2">
            <div>
              <span className="text-gray-500">Archetype </span>
              <span className="font-semibold text-financial-light">
                {data.archetype ? `${data.archetype.label} (${data.archetype.event_count})` : 'Unassigned'}
              </span>
            </div>
            <div className="grid grid-cols-3 gap-2 font-mono">
              <Metric label="EOD" value={summary?.eod_pct_change ?? null} />
              <Metric label="MFE" value={summary?.mfe_pct ?? null} />
              <Metric label="MAE" value={summary?.mae_pct ?? null} />
            </div>
          </div>
        </BriefBlock>
      </div>

      {data.risks.length > 0 && (
        <div className="mt-3 rounded border border-yellow-700/40 bg-yellow-950/20 p-3">
          <div className="mb-1 text-[11px] font-bold uppercase text-yellow-300">Risk flags</div>
          <ul className="space-y-1 text-xs text-yellow-100">
            {data.risks.map((risk) => (
              <li key={risk}>{risk}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
};

const BriefBlock: React.FC<{ title: string; children: React.ReactNode }> = ({ title, children }) => (
  <div className="rounded border border-gray-800 bg-gray-900/40 p-3 text-xs text-gray-300">
    <div className="mb-2 text-[11px] font-bold uppercase text-gray-500">{title}</div>
    {children}
  </div>
);

const Metric: React.FC<{ label: string; value: number | null }> = ({ label, value }) => (
  <div>
    <div className="text-[10px] uppercase text-gray-500">{label}</div>
    <div className={colorForPct(value)}>
      {label} {fmtPct(value)}
    </div>
  </div>
);

export default SignalTable;
