import React, { useState } from 'react';
import { Link } from 'react-router-dom';
import { ChevronUp, ChevronDown, ChevronLeft, ChevronRight, Check, X } from 'lucide-react';
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

const SignalTable: React.FC<SignalTableProps> = ({ scannerType, startDate, endDate, severity }) => {
  const [sortBy, setSortBy] = useState<SortField>('event_date');
  const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('desc');
  const [page, setPage] = useState(0);

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

  const SortIcon: React.FC<{ field: SortField }> = ({ field }) => {
    if (sortBy !== field) return null;
    return sortOrder === 'desc' ? (
      <ChevronDown className="h-3 w-3 inline ml-0.5" />
    ) : (
      <ChevronUp className="h-3 w-3 inline ml-0.5" />
    );
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
                Date <SortIcon field="event_date" />
              </th>
              <th
                className="px-3 py-3 cursor-pointer hover:text-gray-300 transition-colors"
                onClick={() => handleSort('ticker')}
              >
                Ticker <SortIcon field="ticker" />
              </th>
              <th className="px-3 py-3">Severity</th>
              <th className="px-3 py-3 text-right">Ref Price</th>
              <th
                className="px-3 py-3 text-right cursor-pointer hover:text-gray-300 transition-colors"
                onClick={() => handleSort('mfe_pct')}
              >
                MFE <SortIcon field="mfe_pct" />
              </th>
              <th
                className="px-3 py-3 text-right cursor-pointer hover:text-gray-300 transition-colors"
                onClick={() => handleSort('mae_pct')}
              >
                MAE <SortIcon field="mae_pct" />
              </th>
              <th
                className="px-3 py-3 text-right cursor-pointer hover:text-gray-300 transition-colors"
                onClick={() => handleSort('eod_pct_change')}
              >
                EOD <SortIcon field="eod_pct_change" />
              </th>
              <th className="px-3 py-3 text-right">MFE:MAE</th>
              <th className="px-3 py-3 text-center">FT</th>
              <th className="px-3 py-3 text-center">Status</th>
            </tr>
          </thead>
          <tbody>
            {data.signals.map((signal) => (
              <tr
                key={signal.id}
                className="border-b border-gray-800 hover:bg-gray-800/30 transition-colors"
              >
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
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
};

export default SignalTable;
