import { apiClient } from './client';

// ---- Types ---------------------------------------------------------------- //

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

export interface CreateTradeRequest {
  symbol: string;
  side?: string;
  open_date?: string;
  quantity?: number;
  avg_entry_price?: number;
  notes?: string;
}

export interface CreateJournalEntryRequest {
  entry_date: string;
  content: string;
  sentiment?: string;
}

export interface CreateTagRequest {
  name: string;
  color?: string;
}

export interface ImportTradesResponse {
  imported: number;
  skipped: number;
  errors: string[];
}

// ---- API calls ------------------------------------------------------------ //

export const journalApi = {
  getTrades: async (symbol?: string, status?: string): Promise<Trade[]> => {
    const response = await apiClient.get<Trade[]>('/journal/trades', {
      params: { symbol, status },
    });
    return response.data;
  },

  getTrade: async (tradeId: number): Promise<Trade> => {
    const response = await apiClient.get<Trade>(`/journal/trades/${tradeId}`);
    return response.data;
  },

  createTrade: async (trade: CreateTradeRequest): Promise<Trade> => {
    const response = await apiClient.post<Trade>('/journal/trades', trade);
    return response.data;
  },

  updateTrade: async (tradeId: number, data: Partial<CreateTradeRequest>): Promise<Trade> => {
    const response = await apiClient.patch<Trade>(`/journal/trades/${tradeId}`, data);
    return response.data;
  },

  getStats: async (): Promise<TradeStats> => {
    const response = await apiClient.get<TradeStats>('/journal/stats');
    return response.data;
  },

  importTrades: async (file: File, broker: string): Promise<ImportTradesResponse> => {
    const formData = new FormData();
    formData.append('file', file);
    const response = await apiClient.post(`/journal/import`, formData, {
      params: { broker },
      headers: { 'Content-Type': 'multipart/form-data' },
    });
    return response.data;
  },

  getEntries: async (): Promise<JournalEntry[]> => {
    const response = await apiClient.get<JournalEntry[]>('/journal/entries');
    return response.data;
  },

  createEntry: async (data: CreateJournalEntryRequest): Promise<JournalEntry> => {
    const response = await apiClient.post<JournalEntry>('/journal/entries', data);
    return response.data;
  },

  getTags: async (): Promise<Tag[]> => {
    const response = await apiClient.get<Tag[]>('/journal/tags');
    return response.data;
  },

  createTag: async (data: CreateTagRequest): Promise<Tag> => {
    const response = await apiClient.post<Tag>('/journal/tags', data);
    return response.data;
  },
};
