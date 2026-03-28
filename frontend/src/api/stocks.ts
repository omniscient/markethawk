import axios from 'axios';

const API_BASE_URL = '/api';

const apiClient = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
});

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

export const fetchStockDetails = async (ticker: string): Promise<StockDetailConsolidated> => {
  const response = await apiClient.get(`/stocks/details/${ticker}`);
  return response.data;
};
