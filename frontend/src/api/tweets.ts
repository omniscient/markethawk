/// <reference types="vite/client" />
import { apiClient } from './client';

// ---- Types ---------------------------------------------------------------- //

export interface TweetSignal {
  id: number;
  tweet_id: string;
  tweet_url: string;
  handle: string | null;
  display_name: string | null;
  full_text: string;
  classification: 'CALLOUT' | 'CELEBRATION' | 'UPDATE' | 'RETWEET' | 'UNKNOWN';
  confidence: number;
  tickers: string[];
  price_levels: Record<string, Record<string, number>>;
  direction: 'long' | 'short' | null;
  promoted: boolean;
  scanner_event_id: number | null;
  posted_at: string;
  scraped_at: string | null;
}

// ---- API calls ------------------------------------------------------------ //

export const fetchRecentTweets = async (
  limit = 50,
  classificationFilter?: string,
  promotedOnly = false,
): Promise<TweetSignal[]> => {
  const response = await apiClient.get('/tweets/recent', {
    params: {
      limit,
      classification: classificationFilter,
      promoted_only: promotedOnly,
    },
  });
  return response.data;
};
