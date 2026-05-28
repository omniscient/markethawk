import { apiClient } from './client';

// ---- Types ---------------------------------------------------------------- //

export interface StockDetailConsolidated {
  ticker: string;
  info: {
    longName: string;
    shortName: string;
    sector: string;
    industry: string;
    marketCap: number | null;
  };
  pre_market: {
    pre_market_volume: number;
    pre_market_high: number;
    pre_market_low: number;
    pre_market_open: number;
    pre_market_close: number;
  };
  latest_price: number | null;
  last_updated: string;
  recent_splits?: {
    execution_date: string;
    split_from: number;
    split_to: number;
    adjusted: boolean;
  }[];
  split_adjustment_pending?: boolean;
}

export interface StockDataTaskResponse {
  status: string;
  message?: string;
  task_id?: string;
}

// ---- API calls ------------------------------------------------------------ //

export const fetchStockDetails = async (ticker: string): Promise<StockDetailConsolidated> => {
  const response = await apiClient.get(`/stocks/details/${ticker}`);
  return response.data;
};

export const refreshStockData = async (
  ticker: string,
  timespan: string = 'day',
  period?: string,
): Promise<StockDataTaskResponse> => {
  const response = await apiClient.post(`/stocks/refresh/${ticker}`, null, {
    params: { timespan, period },
  });

  if (response.data?.status === 'error') {
    throw new Error(response.data.message || 'Error refreshing stock data');
  }

  return response.data;
};

export const syncMissingStockAggregates = async (ticker: string): Promise<StockDataTaskResponse> => {
  const response = await apiClient.post(`/stocks/${ticker}/sync-missing`);
  return response.data;
};
