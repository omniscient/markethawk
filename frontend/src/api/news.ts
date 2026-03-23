/// <reference types="vite/client" />
import axios from 'axios';

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';
const api = axios.create({
    baseURL: API_URL,
});

export interface NewsPreference {
    id?: number;
    include_general_market: boolean;
    tracked_tickers: string[];
    tracked_universes: number[];
    refresh_interval_minutes: number;
}

export const fetchNewsPreferences = async (): Promise<NewsPreference> => {
    const response = await api.get('/api/news/preferences');
    return response.data;
};

export const updateNewsPreferences = async (prefs: NewsPreference): Promise<NewsPreference> => {
    const response = await api.put('/api/news/preferences', prefs);
    return response.data;
};

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

export const fetchRecentNews = async (): Promise<NewsArticle[]> => {
    const response = await api.get('/api/news/recent');
    return response.data;
};
