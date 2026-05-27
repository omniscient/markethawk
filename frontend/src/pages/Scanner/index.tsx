import React, { useEffect } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  runScanner, fetchScannerConfigs, fetchStockUniverses, fetchScannerResults,
  fetchScannerHistory, handleApiError, fetchScanStatus,
  fetchScanStatusBlock,
} from '../../api/scanner';
import {
  useScannerState, ACTIVE_SCAN_LS_KEY, EMPTY_PROGRESS,
  type ActiveScanRef, type LiveProgress,
} from '../../hooks/useScannerState';
import { useScannerWs } from '../../hooks/useScannerWs';
import { ScanConfigPanel } from './ScanConfigPanel';
import { LiveProgressPanel } from './LiveProgressPanel';
import { ResultsPanel } from './ResultsPanel';

const Scanner: React.FC = () => {
  const state = useScannerState();
  const queryClient = useQueryClient();
  const { attachWebSocket } = useScannerWs(state, queryClient);

  const { data: configs, isLoading: loadingConfigs } = useQuery({
    queryKey: ['scannerConfigs'],
    queryFn: fetchScannerConfigs,
  });

  const { data: universes, isLoading: loadingUniverses } = useQuery({
    queryKey: ['stockUniverses'],
    queryFn: () => fetchStockUniverses(),
  });

  const { data: scanHistory, isLoading: loadingHistory } = useQuery({
    queryKey: ['scannerHistory'],
    queryFn: () => fetchScannerHistory(10),
  });

  const { data: statusBlock } = useQuery({
    queryKey: ['scanStatusBlock', state.selectedConfig, state.selectedUniverse],
    queryFn: () => fetchScanStatusBlock(state.selectedConfig, state.selectedUniverse),
    refetchInterval: state.isScanning ? 5000 : false,
  });

  const { data: existingResults } = useQuery({
    queryKey: ['scannerResults', state.selectedUniverse, state.selectedConfig, state.sortBy, state.sortOrder],
    queryFn: () => fetchScannerResults({
      universe_id: state.selectedUniverse,
      scanner_type: state.selectedConfig,
      sort_by: state.sortBy,
      sort_order: state.sortOrder,
      limit: 100,
    }),
    enabled: !!state.selectedUniverse && !!state.selectedConfig,
  });

  React.useEffect(() => {
    if (!existingResults) return;
    state.setScanResults((prev: any) => {
      if (prev && prev.scan_id !== 'historical') return prev;
      return { scan_id: 'historical', status: 'completed', stocks_scanned: 0, events_detected: existingResults.length, execution_time_ms: 0, events: existingResults };
    });
  }, [existingResults]);

  const scannerMutation = useMutation({
    mutationFn: runScanner,
    onSuccess: (data) => {
      const ref: ActiveScanRef = {
        scan_id: data.scan_id, task_id: data.task_id, scanner_type: data.scanner_type,
        universe_id: data.universe_id ?? state.selectedUniverse ?? 0,
        start_date: data.scan_start_date ?? state.scanStartDate,
        end_date: data.scan_end_date ?? state.scanEndDate,
        started_at: data.started_at,
      };
      state.setActiveScan(ref);
      state.setLiveProgress(EMPTY_PROGRESS);
      state.setIsScanning(true);
      state.setScanError(null);
      localStorage.setItem(ACTIVE_SCAN_LS_KEY, JSON.stringify(ref));
      attachWebSocket(data.task_id);
    },
    onError: (error: any) => {
      const status = error?.response?.status;
      const detail = error?.response?.data?.detail;
      if (status === 409 && detail && typeof detail === 'object' && detail.task_id) {
        const ref: ActiveScanRef = {
          scan_id: detail.scan_id, task_id: detail.task_id, scanner_type: state.selectedConfig,
          universe_id: state.selectedUniverse || 0,
          start_date: state.scanStartDate, end_date: state.scanEndDate, started_at: detail.started_at,
        };
        state.setActiveScan(ref);
        state.setIsScanning(true);
        state.setScanError(null);
        localStorage.setItem(ACTIVE_SCAN_LS_KEY, JSON.stringify(ref));
        attachWebSocket(detail.task_id);
        return;
      }
      console.error('Scanner error:', error);
      state.setScanError(handleApiError(error));
      state.setIsScanning(false);
    },
  });

  const handleRunScanner = async () => {
    if (!state.selectedUniverse || !state.selectedConfig) {
      state.setScanError('Please select a universe and a scanner type'); return;
    }
    if (state.scanStartDate && state.scanEndDate && state.scanEndDate < state.scanStartDate) {
      state.setScanError('End date must be on or after start date'); return;
    }
    state.setScanError(null);
    scannerMutation.mutate({
      scanner_type: state.selectedConfig, universe_id: state.selectedUniverse,
      tickers: [], dry_run: false,
      start_date: state.scanStartDate || undefined,
      end_date: state.scanEndDate || state.scanStartDate || undefined,
    });
  };

  const handleCancelScanner = async () => {
    if (!state.activeScan) return;
    try {
      const { cancelScan } = await import('../../api/scanner');
      await cancelScan(state.activeScan.scan_id);
    } catch (e) {
      console.error('cancel failed', e);
      state.setScanError(handleApiError(e));
    }
  };

  const handleSort = (column: string) => {
    if (column === state.sortBy) state.setSortOrder(state.sortOrder === 'asc' ? 'desc' : 'asc');
    else { state.setSortBy(column); state.setSortOrder('desc'); }
  };

  // Reattach to an in-flight scan after page reload.
  useEffect(() => {
    const raw = localStorage.getItem(ACTIVE_SCAN_LS_KEY);
    if (!raw) return;
    let ref: ActiveScanRef;
    try { ref = JSON.parse(raw); } catch { localStorage.removeItem(ACTIVE_SCAN_LS_KEY); return; }
    fetchScanStatus(ref.scan_id)
      .then((status) => {
        if (status.status === 'queued' || status.status === 'running') {
          state.setActiveScan(ref);
          state.setIsScanning(true);
          if (status.progress) state.setLiveProgress((p: LiveProgress) => ({ ...p, ...status.progress } as LiveProgress));
          attachWebSocket(ref.task_id);
        } else {
          localStorage.removeItem(ACTIVE_SCAN_LS_KEY);
          queryClient.invalidateQueries({ queryKey: ['scannerResults'] });
          queryClient.invalidateQueries({ queryKey: ['scannerHistory'] });
        }
      })
      .catch(() => localStorage.removeItem(ACTIVE_SCAN_LS_KEY));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="space-y-6 animate-fade-in">
      <ScanConfigPanel
        configs={configs ?? []} loadingConfigs={loadingConfigs}
        universes={universes ?? []} loadingUniverses={loadingUniverses}
        selectedConfig={state.selectedConfig} onSelectConfig={state.setSelectedConfig}
        selectedUniverse={state.selectedUniverse} onSelectUniverse={state.setSelectedUniverse}
        scanStartDate={state.scanStartDate} onScanStartDate={state.setScanStartDate}
        scanEndDate={state.scanEndDate} onScanEndDate={state.setScanEndDate}
        isScanning={state.isScanning} onRunScan={handleRunScanner} onCancelScan={handleCancelScanner}
        statusBlock={statusBlock} scanHistory={scanHistory ?? []} loadingHistory={loadingHistory}
        scanError={state.scanError} onDismissError={() => state.setScanError(null)}
        scannerMutationPending={scannerMutation.isPending}
      />
      <LiveProgressPanel isScanning={state.isScanning} activeScan={state.activeScan} progress={state.liveProgress} />
      <ResultsPanel scanResults={state.scanResults} sortBy={state.sortBy} sortOrder={state.sortOrder} onSort={handleSort} />
    </div>
  );
};

export default Scanner;
