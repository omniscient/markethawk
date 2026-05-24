import React from 'react';
import { useQuery } from '@tanstack/react-query';
import { BarChart3 } from 'lucide-react';
import Card from './ui/Card';
import { fetchReviewStats } from '../api/scanner';

const SignalReviewStats: React.FC = () => {
  const { data: stats, isLoading } = useQuery({
    queryKey: ['reviewStats'],
    queryFn: () => fetchReviewStats(),
    refetchInterval: 60_000,
  });

  if (isLoading || !stats) {
    return null;
  }

  if (stats.total_events === 0) {
    return null;
  }

  const coveragePct = stats.total_events > 0
    ? Math.round((stats.reviewed_count / stats.total_events) * 100)
    : 0;

  return (
    <Card title="Signal Quality" icon={BarChart3}>
      <div className="p-6 space-y-4">
        {/* Coverage */}
        <div>
          <div className="flex justify-between text-xs text-gray-400 mb-1">
            <span>Review Coverage</span>
            <span>{stats.reviewed_count} / {stats.total_events} ({coveragePct}%)</span>
          </div>
          <div className="w-full bg-gray-800 rounded-full h-2">
            <div
              className="bg-financial-blue h-2 rounded-full transition-all"
              style={{ width: `${coveragePct}%` }}
            />
          </div>
        </div>

        {/* Acceptance Rate */}
        <div className="p-3 bg-gray-800/40 border border-gray-700/50 rounded-lg text-center">
          <div className="text-2xl font-bold text-financial-light">
            {stats.reviewed_count > 0 ? `${Math.round(stats.acceptance_rate * 100)}%` : '—'}
          </div>
          <div className="text-[10px] text-gray-500 uppercase tracking-wider font-semibold">Acceptance Rate</div>
        </div>

        {/* By Scanner Type */}
        {stats.by_scanner_type.length > 0 && (
          <div>
            <div className="text-[10px] font-bold text-gray-500 uppercase tracking-wider mb-2">By Scanner Type</div>
            <div className="space-y-1">
              {stats.by_scanner_type.map((row) => (
                <div key={row.scanner_type} className="flex items-center justify-between text-xs py-1 border-b border-gray-800/60">
                  <span className="text-gray-400 truncate">{row.scanner_type.replace(/_/g, ' ')}</span>
                  <div className="flex gap-2 text-[10px] font-mono">
                    <span className="text-green-400" title="Confirmed">{row.confirmed}</span>
                    <span className="text-red-400" title="Rejected">{row.rejected}</span>
                    <span className="text-gray-400" title="Uncertain">{row.uncertain}</span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Top Rejection Reasons */}
        {stats.top_rejection_reasons.length > 0 && (
          <div>
            <div className="text-[10px] font-bold text-gray-500 uppercase tracking-wider mb-2">Top Rejection Reasons</div>
            <div className="space-y-1">
              {stats.top_rejection_reasons.map((item) => (
                <div key={item.reason} className="flex items-center justify-between text-xs py-1">
                  <span className="text-gray-400">{item.reason.replace(/_/g, ' ')}</span>
                  <span className="text-red-400 font-mono">{item.count}</span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </Card>
  );
};

export default SignalReviewStats;
