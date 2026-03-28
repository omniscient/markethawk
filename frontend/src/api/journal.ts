import axios from 'axios';

const API_BASE_URL = 'http://localhost:8000/api';

export interface Trade {
  id: number;
  symbol: string;
  status: string;
  side?: string;
  open_date?: string;
  close_date?: string;
  quantity?: number;
  avg_entry_price?: number;
  avg_exit_price?: number;
  gross_pnl?: number;
  net_pnl?: number;
  commissions: number;
  return_pct?: number;
  notes?: string;
  executions: TradeExecution[];
  tags: Tag[];
  created_at: string;
  updated_at: string;
}

export interface TradeExecution {
  id: number;
  trade_id: number;
  timestamp: string;
  side: string;
  price: number;
  quantity: number;
  commission: number;
}

export interface Tag {
  id: number;
  name: string;
  color?: string;
}

export interface TradeStats {
  total_trades: number;
  winning_trades: number;
  losing_trades: number;
  win_rate: number;
  total_pnl: number;
  avg_profit: number;
  profit_factor: number;
}

export interface JournalEntry {
  id: number;
  entry_date: string;
  content: string;
  sentiment?: string;
  created_at: string;
  updated_at: string;
}

export const journalApi = {
  getTrades: async (symbol?: string, status?: string) => {
    const params = new URLSearchParams();
    if (symbol) params.append('symbol', symbol);
    if (status) params.append('status', status);
    const response = await axios.get<Trade[]>(`${API_BASE_URL}/journal/trades?${params.toString()}`);
    return response.data;
  },

  getTrade: async (tradeId: number) => {
    const response = await axios.get<Trade>(`${API_BASE_URL}/journal/trades/${tradeId}`);
    return response.data;
  },

  createTrade: async (trade: any) => {
    const response = await axios.post<Trade>(`${API_BASE_URL}/journal/trades`, trade);
    return response.data;
  },

  updateTrade: async (tradeId: number, data: any) => {
    const response = await axios.patch<Trade>(`${API_BASE_URL}/journal/trades/${tradeId}`, data);
    return response.data;
  },

  getStats: async () => {
    const response = await axios.get<TradeStats>(`${API_BASE_URL}/journal/stats`);
    return response.data;
  },

  importTrades: async (file: File, broker: string) => {
    const formData = new FormData();
    formData.append('file', file);
    const response = await axios.post(`${API_BASE_URL}/journal/import?broker=${broker}`, formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
    return response.data;
  },

  getEntries: async () => {
    const response = await axios.get<JournalEntry[]>(`${API_BASE_URL}/journal/entries`);
    return response.data;
  },

  createEntry: async (data: any) => {
    const response = await axios.post<JournalEntry>(`${API_BASE_URL}/journal/entries`, data);
    return response.data;
  },

  getTags: async () => {
    const response = await axios.get<Tag[]>(`${API_BASE_URL}/journal/tags`);
    return response.data;
  },

  createTag: async (data: any) => {
    const response = await axios.post<Tag>(`${API_BASE_URL}/journal/tags`, data);
    return response.data;
  },
};
