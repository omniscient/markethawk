import { apiClient } from '../client';
import type { SignalReview, SignalReviewStats, SignalQualityDistributionResponse } from './types';

export const submitReview = async (
  eventUuid: string,
  payload: { verdict: string; reject_reason?: string | null; notes?: string | null },
): Promise<SignalReview> => {
  const response = await apiClient.post(`/scanner/events/${eventUuid}/review`, payload);
  return response.data;
};

export const fetchReviewStats = async (params?: {
  scanner_type?: string;
  start_date?: string;
  end_date?: string;
}): Promise<SignalReviewStats> => {
  const response = await apiClient.get('/scanner/reviews/stats', { params });
  return response.data;
};

export const getSignalQualityDistribution = async (params: {
  scanner_type?: string;
  start_date?: string;
  end_date?: string;
} = {}): Promise<SignalQualityDistributionResponse> => {
  const query = new URLSearchParams();
  if (params.scanner_type) query.append('scanner_type', params.scanner_type);
  if (params.start_date) query.append('start_date', params.start_date);
  if (params.end_date) query.append('end_date', params.end_date);
  const response = await apiClient.get<SignalQualityDistributionResponse>(
    `/scanner/signal-quality-distribution?${query.toString()}`
  );
  return response.data;
};
