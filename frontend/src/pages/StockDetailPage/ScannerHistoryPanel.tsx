import React from 'react';
import { Zap } from 'lucide-react';
import Card from '../../components/ui/Card';
import RecentEvents from '../../components/RecentEvents';
import ForceScanDialog from '../../components/ForceScanDialog';

export interface ScanTaskState {
  status: string;
  done: number;
  total: number;
  error: string | null | undefined;
}

export interface ScannerHistoryPanelProps {
  symbol: string;
  events: any[];
  clearConfirmOpen: boolean;
  onClearConfirmOpen: (v: boolean) => void;
  onClearHistory: () => void;
  clearHistoryPending: boolean;
  scanDialogOpen: boolean;
  onScanDialogOpen: (v: boolean) => void;
  scanTask: ScanTaskState;
  scanDoneMsg: string | null;
  onScanSubmit: (types: string[], startDate: string, endDate: string, fetchData: boolean) => void;
  scanSubmitting: boolean;
  onHighlightDate: (date: string) => void;
}

export function ScannerHistoryPanel({
  symbol, events,
  clearConfirmOpen, onClearConfirmOpen, onClearHistory, clearHistoryPending,
  scanDialogOpen, onScanDialogOpen, scanTask, scanDoneMsg,
  onScanSubmit, scanSubmitting, onHighlightDate,
}: ScannerHistoryPanelProps) {
  const isRunning = scanTask.status === 'connecting' || scanTask.status === 'running';

  return (
    <>
      <Card
        title="Scanner Event History"
        icon={Zap as any}
        actions={
          <div className="flex items-center space-x-2">
            {scanTask.status === 'connecting' && (
              <span className="text-xs text-gray-400 font-semibold animate-pulse">Queued…</span>
            )}
            {scanTask.status === 'running' && scanTask.total === 0 && (
              <span className="text-xs text-financial-blue font-semibold animate-pulse">Preparing…</span>
            )}
            {scanTask.status === 'running' && scanTask.total > 0 && (
              <span className="text-xs text-financial-blue font-semibold animate-pulse">
                Scanning… {scanTask.done} / {scanTask.total} days
              </span>
            )}
            {scanDoneMsg && (
              <span className="text-xs text-positive font-semibold">{scanDoneMsg}</span>
            )}
            {scanTask.status === 'failed' && (
              <span className="text-xs text-negative font-semibold" title={scanTask.error ?? ''}>
                Scan failed
              </span>
            )}
            <button
              onClick={() => onScanDialogOpen(true)}
              disabled={isRunning}
              className={`flex items-center space-x-2 px-3 py-1 text-xs font-bold rounded-md border transition-all ${
                isRunning
                  ? 'bg-gray-800 border-gray-700 text-gray-500 cursor-not-allowed'
                  : 'bg-financial-blue/10 border-financial-blue/30 text-financial-blue hover:bg-financial-blue hover:text-white'
              }`}
            >
              <Zap className={`h-3 w-3 ${scanTask.status === 'running' ? 'animate-pulse' : ''}`} />
              <span>Run Scanner</span>
            </button>
            <button
              onClick={() => onClearConfirmOpen(true)}
              className="flex items-center space-x-2 px-3 py-1 text-xs font-bold rounded-md border border-negative/30 text-negative hover:bg-negative hover:text-white transition-all"
            >
              <span>Clear History</span>
            </button>
          </div>
        }
      >
        {clearConfirmOpen && (
          <div className="mb-4 p-4 bg-gray-800 border border-negative/40 rounded-lg">
            <p className="text-sm text-financial-light mb-3">
              Are you sure you want to clear all scanner event history for <strong>{symbol}</strong>? This cannot be undone.
            </p>
            <div className="flex items-center space-x-2">
              <button
                onClick={onClearHistory}
                disabled={clearHistoryPending}
                className="px-3 py-1 text-xs font-bold rounded-md bg-negative text-white hover:bg-red-700 transition-all disabled:opacity-50"
              >
                {clearHistoryPending ? 'Clearing…' : 'Yes, Clear'}
              </button>
              <button
                onClick={() => onClearConfirmOpen(false)}
                className="px-3 py-1 text-xs font-bold rounded-md border border-gray-600 text-gray-400 hover:text-white hover:border-gray-400 transition-all"
              >
                No, Cancel
              </button>
            </div>
          </div>
        )}
        <RecentEvents
          events={events}
          maxItems={10}
          onEventClick={(event: any) => onHighlightDate(event.event_date)}
        />
      </Card>

      <ForceScanDialog
        isOpen={scanDialogOpen}
        isSubmitting={scanSubmitting}
        onClose={() => onScanDialogOpen(false)}
        onSubmit={onScanSubmit}
      />
    </>
  );
}
