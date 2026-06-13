import { useEffect, useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  fetchQualityReport,
  triggerQualityAnalysis,
  triggerNormalization,
  deleteTickerAggregates,
  StockUniverse,
  QualityReport,
  QualityTickerResult,
} from '../api/universe';

export interface UseQualityReportReturn {
  report: QualityReport | null | undefined;
  isLoading: boolean;
  removedTickers: Set<string>;
  normalizationTriggered: boolean;
  isAnalyzing: boolean;
  isNormalizing: boolean;
  isBusy: boolean;
  deleteMutation: ReturnType<typeof useMutation<
    { deleted_bars: number; removed_from_universe: boolean },
    Error,
    QualityTickerResult
  >>;
  analyzeMutation: ReturnType<typeof useMutation<{ status: string; message: string }, Error, void>>;
  normalizeMutation: ReturnType<typeof useMutation<
    { status: string; resume: boolean; message: string },
    Error,
    string[]
  >>;
}

export function useQualityReport(
  universe: StockUniverse | null,
  isOpen: boolean,
): UseQualityReportReturn {
  const queryClient = useQueryClient();
  const [removedTickers, setRemovedTickers] = useState<Set<string>>(new Set());
  const [normalizationTriggered, setNormalizationTriggered] = useState(false);

  const { data: report, isLoading } = useQuery({
    queryKey: ['qualityReport', universe?.id],
    queryFn: () => fetchQualityReport(universe!.id),
    enabled: !!universe && isOpen,
  });

  // Polling while quality analysis or normalization is active
  useEffect(() => {
    const qualityActive = report?.status === 'pending' || report?.status === 'running';
    const normActive = report?.normalization_status === 'pending' || report?.normalization_status === 'running';
    const postNormPending = normalizationTriggered && report?.normalization_status === 'complete' && report?.status !== 'complete';
    if ((!qualityActive && !normActive && !postNormPending) || !universe || !isOpen) return;
    const timer = setInterval(() => {
      queryClient.invalidateQueries({ queryKey: ['qualityReport', universe.id] });
    }, 2000);
    return () => clearInterval(timer);
  }, [report?.status, report?.normalization_status, normalizationTriggered, universe, universe?.id, isOpen, queryClient]);

  // Clear optimistic removals when a fresh analysis completes
  useEffect(() => {
    if (report?.status === 'complete' && removedTickers.size > 0) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setRemovedTickers(new Set());
    }
  }, [report?.status, removedTickers]);

  // Adopt in-progress normalization when opening modal with one already running
  useEffect(() => {
    if (report?.normalization_status === 'pending' || report?.normalization_status === 'running') {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setNormalizationTriggered(true);
    }
  }, [report?.normalization_status]);

  // Reset deep state when universe changes
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setRemovedTickers(new Set());
    setNormalizationTriggered(false);
  }, [universe?.id]);

  const deleteMutation = useMutation({
    mutationFn: (row: QualityTickerResult) =>
      deleteTickerAggregates(universe!.id, {
        ticker: row.ticker,
        asset_class: row.asset_class,
      }),
    onSuccess: (_data, row) => {
      setRemovedTickers((prev) => new Set([...prev, row.ticker]));
      queryClient.invalidateQueries({ queryKey: ['stockUniverses'] });
    },
  });

  const analyzeMutation = useMutation({
    mutationFn: () => triggerQualityAnalysis(universe!.id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['qualityReport', universe?.id] });
      queryClient.invalidateQueries({ queryKey: ['stockUniverses'] });
    },
  });

  const normalizeMutation = useMutation({
    mutationFn: (targetTickers: string[]) => triggerNormalization(universe!.id, targetTickers),
    onSuccess: () => {
      setNormalizationTriggered(true);
      queryClient.invalidateQueries({ queryKey: ['qualityReport', universe?.id] });
    },
  });

  const isAnalyzing = report?.status === 'pending' || report?.status === 'running' || analyzeMutation.isPending;
  const isNormalizing = normalizeMutation.isPending || (
    normalizationTriggered && (
      report?.normalization_status === 'pending' ||
      report?.normalization_status === 'running'
    )
  );
  const isBusy = isAnalyzing || isNormalizing || (
    normalizationTriggered && report?.normalization_status === 'complete' && report?.status !== 'complete'
  );

  return {
    report,
    isLoading,
    removedTickers,
    normalizationTriggered,
    isAnalyzing,
    isNormalizing,
    isBusy,
    deleteMutation,
    analyzeMutation,
    normalizeMutation,
  };
}
