import React from 'react';
import { formatDistanceToNow } from 'date-fns';
import { Eye } from 'lucide-react';
import Card from '../../components/ui/Card';

export interface ScanStatusCardProps {
  isScanning: boolean;
  statusBlock: any;
  selectedUniverse: number | null;
  universes: any[];
}

export function ScanStatusCard({ isScanning, statusBlock, selectedUniverse, universes }: ScanStatusCardProps) {
  const universe = universes?.find(u => u.id === selectedUniverse);
  const universeCount = universe?.ticker_count || universe?.aggregate_count || 0;

  return (
    <Card title="Scan Status" icon={Eye as any}>
      <div className="space-y-3">
        <div className="flex justify-between items-center">
          <span className="text-gray-400">Status</span>
          <span className={`px-2 py-1 rounded text-xs font-medium ${
            isScanning ? 'bg-blue-500/20 text-blue-400'
            : statusBlock?.next_run ? 'bg-purple-500/20 text-purple-400'
            : 'bg-green-500/20 text-green-400'
          }`}>
            {isScanning ? 'Running' : statusBlock?.next_run ? 'Scheduled' : 'Ready'}
          </span>
        </div>
        <div className="flex justify-between items-center">
          <span className="text-gray-400">Last Run</span>
          <span className="text-financial-light text-right">
            {statusBlock?.last_run?.timestamp ? (
              <span>
                {formatDistanceToNow(new Date(statusBlock.last_run.timestamp), { addSuffix: true })}
                <span className="ml-1 text-xs text-gray-500">· {statusBlock.last_run.events_detected} events</span>
              </span>
            ) : 'Never'}
          </span>
        </div>
        <div className="flex justify-between items-center">
          <span className="text-gray-400">Next Run</span>
          <span className="text-financial-light">
            {statusBlock === undefined ? '—'
              : statusBlock?.next_run ? formatDistanceToNow(new Date(statusBlock.next_run), { addSuffix: true })
              : 'Manual only'}
          </span>
        </div>
        <div className="flex justify-between items-center">
          <span className="text-gray-400">Stocks in Universe</span>
          <span className="text-financial-light">{universeCount}</span>
        </div>
        <div className="flex justify-between items-center">
          <span className="text-gray-400">Total Events</span>
          <span className="text-financial-light">
            {statusBlock !== undefined ? statusBlock.total_events.toLocaleString() : '—'}
          </span>
        </div>
        {statusBlock?.last_run?.duration_ms != null && statusBlock.last_run.duration_ms > 0 && (
          <div className="flex justify-between items-center">
            <span className="text-gray-400">Last Duration</span>
            <span className="text-financial-light">
              {statusBlock.last_run.duration_ms < 1000
                ? `${statusBlock.last_run.duration_ms}ms`
                : `${(statusBlock.last_run.duration_ms / 1000).toFixed(1)}s`}
            </span>
          </div>
        )}
        {statusBlock?.success_rate != null && (
          <div className="flex justify-between items-center">
            <span className="text-gray-400">Success Rate</span>
            <span className={`text-financial-light ${
              statusBlock.success_rate < 80 ? 'text-red-400'
              : statusBlock.success_rate < 95 ? 'text-yellow-400'
              : 'text-green-400'
            }`}>
              {statusBlock.success_rate}%
              <span className="ml-1 text-xs text-gray-500">last 20</span>
            </span>
          </div>
        )}
        {statusBlock?.avg_events_per_scan != null && (
          <div className="flex justify-between items-center">
            <span className="text-gray-400">Avg Events/Scan</span>
            <span className="text-financial-light">{statusBlock.avg_events_per_scan}</span>
          </div>
        )}
        {statusBlock?.sparkline && statusBlock.sparkline.length > 1 && (() => {
          const pts = statusBlock.sparkline;
          const maxVal = Math.max(...pts.map((p: any) => p.events_detected), 1);
          const w = 100, h = 28, barW = Math.floor(w / pts.length) - 1;
          return (
            <div className="pt-1">
              <span className="text-xs text-gray-500 mb-1 block">Events/run (last {pts.length})</span>
              <svg width={w} height={h} className="w-full" viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none">
                {pts.map((p: any, i: number) => {
                  const barH = Math.max(2, Math.round((p.events_detected / maxVal) * (h - 2)));
                  const fill = p.status === 'completed' ? '#60a5fa' : p.status === 'failed' ? '#f87171' : '#6b7280';
                  return <rect key={i} x={i * (barW + 1)} y={h - barH} width={barW} height={barH} fill={fill} rx={1} />;
                })}
              </svg>
            </div>
          );
        })()}
      </div>
    </Card>
  );
}
