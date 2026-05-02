import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { fetchScannerConfigs, ScannerConfig } from '../api/scanner';
import {
  fetchScorecard,
  fetchEdgeDecay,
  fetchIntervals,
  fetchDistribution,
  fetchSignals,
  triggerBackfill,
  Scorecard,
  EdgeDecayPoint,
  IntervalBreakdown,
  DistributionPoint,
  SignalListResponse,
  BackfillRequest,
  BackfillResponse,
} from '../api/outcomes';

export const useScannerConfigs = () => {
  return useQuery<ScannerConfig[]>({
    queryKey: ['scannerConfigs'],
    queryFn: fetchScannerConfigs,
  });
};

export const useScorecard = (
  scannerType: string | undefined,
  params?: { start_date?: string; end_date?: string; severity?: string },
) => {
  return useQuery<Scorecard>({
    queryKey: ['scorecard', scannerType, params],
    queryFn: () => fetchScorecard({ scanner_type: scannerType!, ...params }),
    enabled: !!scannerType,
  });
};

export const useEdgeDecay = (
  scannerType: string | undefined,
  params?: { start_date?: string; end_date?: string; period?: string },
) => {
  return useQuery<EdgeDecayPoint[]>({
    queryKey: ['edgeDecay', scannerType, params],
    queryFn: () => fetchEdgeDecay(scannerType!, params),
    enabled: !!scannerType,
  });
};

export const useIntervals = (scannerType: string | undefined) => {
  return useQuery<Record<string, IntervalBreakdown>>({
    queryKey: ['intervals', scannerType],
    queryFn: () => fetchIntervals(scannerType!),
    enabled: !!scannerType,
  });
};

export const useDistribution = (
  scannerType: string | undefined,
  metric: string = 'mfe_pct',
) => {
  return useQuery<DistributionPoint[]>({
    queryKey: ['distribution', scannerType, metric],
    queryFn: () => fetchDistribution(scannerType!, metric),
    enabled: !!scannerType,
  });
};

export const useSignals = (
  scannerType: string | undefined,
  params?: {
    start_date?: string;
    end_date?: string;
    severity?: string;
    sort_by?: string;
    sort_order?: string;
    limit?: number;
    offset?: number;
  },
) => {
  return useQuery<SignalListResponse>({
    queryKey: ['signals', scannerType, params],
    queryFn: () => fetchSignals({ scanner_type: scannerType!, ...params }),
    enabled: !!scannerType,
  });
};

export const useBackfillMutation = () => {
  const queryClient = useQueryClient();
  return useMutation<BackfillResponse, Error, BackfillRequest>({
    mutationFn: triggerBackfill,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['scorecard'] });
      queryClient.invalidateQueries({ queryKey: ['edgeDecay'] });
      queryClient.invalidateQueries({ queryKey: ['intervals'] });
      queryClient.invalidateQueries({ queryKey: ['distribution'] });
    },
  });
};
