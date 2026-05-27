import React from 'react';
import { format } from 'date-fns';
import { formatDistanceToNow } from 'date-fns';
import { Play, X, Settings, Download, Eye, Clock, Zap } from 'lucide-react';
import Card from '../../components/ui/Card';
import Button from '../../components/ui/Button';
import ScannerConfig from '../../components/ScannerConfig';
import { todayIso } from '../../hooks/useScannerState';

const DateRangePresets: React.FC<{
  onSelect: (_start: string, _end: string) => void;
  disabled?: boolean;
}> = ({ onSelect, disabled }) => {
  const apply = (calendarDays: number) => {
    const end = new Date();
    end.setDate(end.getDate() - 1);
    while (end.getDay() === 0 || end.getDay() === 6) {
      end.setDate(end.getDate() - 1);
    }
    const start = new Date(end);
    start.setDate(start.getDate() - (calendarDays - 1));
    onSelect(start.toISOString().slice(0, 10), end.toISOString().slice(0, 10));
  };

  const presets: [string, number][] = [
    ['1D', 1],
    ['7D', 7],
    ['30D', 30],
    ['90D', 90],
  ];

  return (
    <div className="flex space-x-1">
      {presets.map(([label, days]) => (
        <button
          key={label}
          type="button"
          disabled={disabled}
          onClick={() => apply(days)}
          className="px-2 py-1 text-[10px] font-bold uppercase tracking-wider bg-gray-800 hover:bg-gray-700 border border-gray-700 rounded text-gray-300 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
        >
          {label}
        </button>
      ))}
    </div>
  );
};

export interface ScanConfigPanelProps {
  configs: any[];
  loadingConfigs: boolean;
  universes: any[];
  loadingUniverses: boolean;
  selectedConfig: string;
  onSelectConfig: (v: string) => void;
  selectedUniverse: number | null;
  onSelectUniverse: (v: number | null) => void;
  scanStartDate: string;
  onScanStartDate: (v: string) => void;
  scanEndDate: string;
  onScanEndDate: (v: string) => void;
  isScanning: boolean;
  onRunScan: () => void;
  onCancelScan: () => void;
  statusBlock: any;
  scanHistory: any[];
  loadingHistory: boolean;
  scanError: string | null;
  onDismissError: () => void;
  scannerMutationPending: boolean;
}

export function ScanConfigPanel({
  configs, loadingConfigs, universes, loadingUniverses,
  selectedConfig, onSelectConfig, selectedUniverse, onSelectUniverse,
  scanStartDate, onScanStartDate, scanEndDate, onScanEndDate,
  isScanning, onRunScan, onCancelScan, statusBlock,
  scanHistory, loadingHistory, scanError, onDismissError,
  scannerMutationPending,
}: ScanConfigPanelProps) {
  return (
    <>
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-financial-light">Scanner</h1>
          <p className="text-gray-400 mt-1">Configure and run stock scanning algorithms</p>
        </div>
        <div className="flex items-end space-x-3">
          <div className="flex flex-col">
            <label htmlFor="scan-start" className="text-[10px] font-bold uppercase tracking-wider text-gray-500 mb-1">
              From
            </label>
            <input
              id="scan-start"
              type="date"
              value={scanStartDate}
              max={scanEndDate || todayIso()}
              onChange={(e) => {
                const v = e.target.value;
                onScanStartDate(v);
                if (scanEndDate && v && v > scanEndDate) onScanEndDate(v);
              }}
              disabled={isScanning}
              className="px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-financial-light text-sm focus:outline-none focus:ring-1 focus:ring-financial-blue disabled:opacity-50"
            />
          </div>
          <div className="flex flex-col">
            <label htmlFor="scan-end" className="text-[10px] font-bold uppercase tracking-wider text-gray-500 mb-1">
              To
            </label>
            <input
              id="scan-end"
              type="date"
              value={scanEndDate}
              min={scanStartDate || undefined}
              max={todayIso()}
              onChange={(e) => onScanEndDate(e.target.value)}
              disabled={isScanning}
              className="px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-financial-light text-sm focus:outline-none focus:ring-1 focus:ring-financial-blue disabled:opacity-50"
            />
          </div>
          <DateRangePresets
            disabled={isScanning}
            onSelect={(start, end) => {
              onScanStartDate(start);
              onScanEndDate(end);
            }}
          />
          {isScanning ? (
            <Button
              variant="danger"
              onClick={onCancelScan}
              icon={X as any}
            >
              Cancel Scan
            </Button>
          ) : (
            <Button
              variant="primary"
              onClick={onRunScan}
              icon={Play as any}
              loading={scannerMutationPending}
              disabled={loadingConfigs}
            >
              Run Scanner
            </Button>
          )}
        </div>
      </div>

      {/* Error card */}
      {scanError && !isScanning && (
        <Card className="bg-red-900/20 border-red-500/30">
          <div className="flex items-start justify-between space-x-3">
            <div>
              <h3 className="text-red-300 font-semibold">Scanner failed</h3>
              <p className="text-red-200 text-sm mt-1">{scanError}</p>
            </div>
            <button
              onClick={onDismissError}
              className="text-red-300 hover:text-red-100 text-sm"
              aria-label="Dismiss error"
            >
              Dismiss
            </button>
          </div>
        </Card>
      )}

      {/* Configuration grid */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2">
          <Card title="Scanner Configuration" icon={Settings as any}>
            <ScannerConfig
              configs={configs || []}
              universes={universes || []}
              selectedConfig={selectedConfig}
              selectedUniverse={selectedUniverse}
              onConfigChange={onSelectConfig}
              onUniverseChange={onSelectUniverse}
              loading={loadingConfigs || loadingUniverses}
            />
          </Card>
        </div>

        {/* Quick Stats */}
        <div className="space-y-4">
          <Card title="Scan Status" icon={Eye as any}>
            <div className="space-y-3">
              <div className="flex justify-between items-center">
                <span className="text-gray-400">Status</span>
                <span className={`px-2 py-1 rounded text-xs font-medium ${isScanning
                  ? 'bg-blue-500/20 text-blue-400'
                  : statusBlock?.next_run
                    ? 'bg-purple-500/20 text-purple-400'
                    : 'bg-green-500/20 text-green-400'
                  }`}>
                  {isScanning ? 'Running' : statusBlock?.next_run ? 'Scheduled' : 'Ready'}
                </span>
              </div>

              <div className="flex justify-between items-center">
                <span className="text-gray-400">Last Run</span>
                <span className="text-financial-light text-right">
                  {statusBlock?.last_run?.timestamp
                    ? (
                      <span>
                        {formatDistanceToNow(new Date(statusBlock.last_run.timestamp), { addSuffix: true })}
                        <span className="ml-1 text-xs text-gray-500">
                          · {statusBlock.last_run.events_detected} events
                        </span>
                      </span>
                    )
                    : 'Never'}
                </span>
              </div>

              <div className="flex justify-between items-center">
                <span className="text-gray-400">Next Run</span>
                <span className="text-financial-light">
                  {statusBlock === undefined
                    ? '—'
                    : statusBlock?.next_run
                      ? formatDistanceToNow(new Date(statusBlock.next_run), { addSuffix: true })
                      : 'Manual only'}
                </span>
              </div>

              <div className="flex justify-between items-center">
                <span className="text-gray-400">Stocks in Universe</span>
                <span className="text-financial-light">
                  {universes?.find(u => u.id === selectedUniverse)?.ticker_count || universes?.find(u => u.id === selectedUniverse)?.aggregate_count || 0}
                </span>
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
                  <span className={`text-financial-light ${statusBlock.success_rate < 80 ? 'text-red-400' : statusBlock.success_rate < 95 ? 'text-yellow-400' : 'text-green-400'}`}>
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
                        const x = i * (barW + 1);
                        const fill = p.status === 'completed' ? '#60a5fa' : p.status === 'failed' ? '#f87171' : '#6b7280';
                        return (
                          <rect key={i} x={x} y={h - barH} width={barW} height={barH} fill={fill} rx={1} />
                        );
                      })}
                    </svg>
                  </div>
                );
              })()}
            </div>
          </Card>

          <Card title="Quick Actions" icon={Zap as any}>
            <div className="space-y-2">
              <Button
                variant="secondary"
                size="sm"
                fullWidth
                icon={Clock as any}
              >
                Schedule Scan
              </Button>
              <Button
                variant="secondary"
                size="sm"
                fullWidth
                icon={Download as any}
              >
                Export Results
              </Button>
            </div>
          </Card>
        </div>
      </div>

      {/* Recent Scan History */}
      <Card title="Recent Scan History" icon={Clock as any}>
        <div className="space-y-4">
          {loadingHistory ? (
            <div className="text-center py-4 text-gray-400">Loading history...</div>
          ) : scanHistory && scanHistory.length > 0 ? (
            scanHistory.map((scan: any, index: number) => (
              <div key={index} className="flex items-center justify-between p-4 bg-gray-800 rounded-lg">
                <div className="flex-1">
                  <div className="flex items-center space-x-2">
                    <div className="text-financial-light font-medium">
                      {scan.created_at ? format(new Date(scan.created_at), 'yyyy-MM-dd HH:mm:ss') : 'Unknown Date'}
                    </div>
                    <span className="text-xs text-gray-500 uppercase">({scan.scanner_type.replace(/_/g, ' ')})</span>
                  </div>
                  <div className="flex items-center space-x-3 mt-1">
                    <div className="text-gray-400 text-sm">{scan.stocks_scanned} stocks analyzed</div>
                    <div className="text-financial-blue text-sm font-semibold">{scan.events_detected} events found</div>
                  </div>
                  {scan.status === 'failed' && scan.error_message && (
                    <div className="text-red-400 text-xs mt-1 italic">Error: {scan.error_message}</div>
                  )}
                </div>
                <div className="flex items-center space-x-3">
                  <span className="text-gray-400 text-sm">{(scan.execution_time_ms / 1000).toFixed(1)}s</span>
                  <span className={`px-2 py-1 rounded text-xs font-medium ${scan.status === 'completed'
                    ? 'bg-green-500/20 text-green-400'
                    : scan.status === 'running'
                      ? 'bg-blue-500/20 text-blue-400'
                      : 'bg-red-500/20 text-red-400'
                    }`}>
                    {scan.status}
                  </span>
                </div>
              </div>
            ))
          ) : (
            <div className="text-center py-8 text-gray-500">No scan history found</div>
          )}
        </div>
      </Card>
    </>
  );
}
