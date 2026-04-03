/// <reference types="vite/client" />
import { apiClient } from './client';

// ---- Types ---------------------------------------------------------------- //

export interface NewsPreference {
  id?: number;
  tracked_tickers: string[];
  tracked_universes: number[];
  refresh_interval_minutes: number;
}

export interface NewsArticle {
  id: number;
  title: string;
  author?: string;
  published_utc: string;
  article_url: string;
  image_url?: string;
  description?: string;
  provider?: string;
  tickers?: string[];
}

// ---- API calls ------------------------------------------------------------ //

export const fetchNewsPreferences = async (): Promise<NewsPreference> => {
  const response = await apiClient.get('/news/preferences');
  return response.data;
};

export const updateNewsPreferences = async (prefs: NewsPreference): Promise<NewsPreference> => {
  const response = await apiClient.put('/news/preferences', prefs);
  return response.data;
};

export const fetchRecentNews = async (ticker?: string): Promise<NewsArticle[]> => {
  const response = await apiClient.get('/news/recent', { params: { ticker } });
  return response.data;
};

export const triggerNewsRefresh = async (): Promise<{ status: string; task_id: string }> => {
  const response = await apiClient.post('/news/refresh');
  return response.data;
};
