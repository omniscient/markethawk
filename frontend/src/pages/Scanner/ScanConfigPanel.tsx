import React from 'react';
import { format } from 'date-fns';
import { Play, X, Settings, Download, Clock, Zap } from 'lucide-react';
import Card from '../../components/ui/Card';
import Button from '../../components/ui/Button';
import ScannerConfig from '../../components/ScannerConfig';
import { todayIso } from '../../hooks/useScannerState';
import { ScanStatusCard } from './ScanStatusCard';
import { CoveragePanel } from './CoveragePanel';
import type {
  ScannerConfig as ScannerConfigType,
  StockUniverse,
  ScannerStatusBlock,
  ScannerRunResponse,
  ScannerCoverage,
  ScannerCoverageGap,
} from '../../api/scanner';

const DateRangePresets: React.FC<{
  onSelect: (_start: string, _end: string) => void;
  disabled?: boolean;
}> = ({ onSelect, disabled }) => {
  const apply = (calendarDays: number) => {
    const end = new Date();
    end.setDate(end.getDate() - 1);
    while (end.getDay() === 0 || end.getDay() === 6) end.setDate(end.getDate() - 1);
    const start = new Date(end);
    start.setDate(start.getDate() - (calendarDays - 1));
    onSelect(start.toISOString().slice(0, 10), end.toISOString().slice(0, 10));
  };

  return (
    <div className="flex space-x-1">
      {([['1D', 1], ['7D', 7], ['30D', 30], ['90D', 90]] as [string, number][]).map(([label, days]) => (
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
  configs: ScannerConfigType[];
  loadingConfigs: boolean;
  universes: StockUniverse[];
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
  statusBlock: ScannerStatusBlock | undefined;
  coverage: ScannerCoverage | undefined;
  loadingCoverage: boolean;
  onScanGap: (gap: ScannerCoverageGap) => void;
  onFillAllGaps: (gaps: ScannerCoverageGap[]) => void;
  scanHistory: ScannerRunResponse[];
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
  coverage, loadingCoverage, onScanGap, onFillAllGaps,
  scanHistory, loadingHistory, scanError, onDismissError,
  scannerMutationPending,
}: ScanConfigPanelProps) {
  return (
    <>
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-financial-light">Scanner</h1>
          <p className="text-gray-400 mt-1">Configure and run stock scanning algorithms</p>
        </div>
        <div className="flex items-end space-x-3">
          <div className="flex flex-col">
            <label htmlFor="scan-start" className="text-[10px] font-bold uppercase tracking-wider text-gray-500 mb-1">From</label>
            <input
              id="scan-start" type="date" value={scanStartDate} max={scanEndDate || todayIso()}
              onChange={(e) => { const v = e.target.value; onScanStartDate(v); if (scanEndDate && v && v > scanEndDate) onScanEndDate(v); }}
              disabled={isScanning}
              className="px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-financial-light text-sm focus:outline-none focus:ring-1 focus:ring-financial-blue disabled:opacity-50"
            />
          </div>
          <div className="flex flex-col">
            <label htmlFor="scan-end" className="text-[10px] font-bold uppercase tracking-wider text-gray-500 mb-1">To</label>
            <input
              id="scan-end" type="date" value={scanEndDate} min={scanStartDate || undefined} max={todayIso()}
              onChange={(e) => onScanEndDate(e.target.value)}
              disabled={isScanning}
              className="px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-financial-light text-sm focus:outline-none focus:ring-1 focus:ring-financial-blue disabled:opacity-50"
            />
          </div>
          <DateRangePresets disabled={isScanning} onSelect={(start, end) => { onScanStartDate(start); onScanEndDate(end); }} />
          {isScanning ? (
            <Button variant="danger" onClick={onCancelScan} icon={X}>Cancel Scan</Button>
          ) : (
            <Button variant="primary" onClick={onRunScan} icon={Play} loading={scannerMutationPending} disabled={loadingConfigs}>
              Run Scanner
            </Button>
          )}
        </div>
      </div>

      {scanError && !isScanning && (
        <Card className="bg-red-900/20 border-red-500/30">
          <div className="flex items-start justify-between space-x-3">
            <div>
              <h3 className="text-red-300 font-semibold">Scanner failed</h3>
              <p className="text-red-200 text-sm mt-1">{scanError}</p>
            </div>
            <button onClick={onDismissError} className="text-red-300 hover:text-red-100 text-sm" aria-label="Dismiss error">
              Dismiss
            </button>
          </div>
        </Card>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2">
          <Card title="Scanner Configuration" icon={Settings}>
            <ScannerConfig
              configs={configs || []} universes={universes || []}
              selectedConfig={selectedConfig} selectedUniverse={selectedUniverse}
              onConfigChange={onSelectConfig} onUniverseChange={onSelectUniverse}
              loading={loadingConfigs || loadingUniverses}
            />
          </Card>
        </div>
        <div className="space-y-4">
          <ScanStatusCard isScanning={isScanning} statusBlock={statusBlock} selectedUniverse={selectedUniverse} universes={universes} />
          <CoveragePanel
            coverage={coverage}
            isLoading={loadingCoverage}
            isScanning={isScanning}
            onScanGap={onScanGap}
            onFillAllGaps={onFillAllGaps}
          />
          <Card title="Quick Actions" icon={Zap}>
            <div className="space-y-2">
              <Button variant="secondary" size="sm" fullWidth icon={Clock}>Schedule Scan</Button>
              <Button variant="secondary" size="sm" fullWidth icon={Download}>Export Results</Button>
            </div>
          </Card>
        </div>
      </div>

      <Card title="Recent Scan History" icon={Clock}>
        <div className="space-y-4">
          {loadingHistory ? (
            <div className="text-center py-4 text-gray-400">Loading history...</div>
          ) : scanHistory && scanHistory.length > 0 ? (
            scanHistory.map((scan, index) => (
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
                  <span className={`px-2 py-1 rounded text-xs font-medium ${
                    scan.status === 'completed' ? 'bg-green-500/20 text-green-400'
                    : scan.status === 'running' ? 'bg-blue-500/20 text-blue-400'
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
