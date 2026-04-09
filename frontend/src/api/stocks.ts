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
): Promise<any> => {
  const response = await apiClient.post(`/stocks/refresh/${ticker}`, null, {
    params: { timespan, period },
  });
  return response.data;
};

export const syncMissingStockAggregates = async (ticker: string): Promise<any> => {
  const response = await apiClient.post(`/stocks/${ticker}/sync-missing`);
  return response.data;
};
