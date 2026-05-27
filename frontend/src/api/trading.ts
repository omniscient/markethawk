import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { apiClient as api } from './client';

// ── Types ─────────────────────────────────────────────────────────────────────

export interface TradingStrategy {
  id: number;
  name: string;
  description: string | null;
  is_active: boolean;
  paper_mode: boolean;
  requires_approval: boolean;
  risk_per_trade_pct: number;
  max_position_usd: number | null;
  max_trades_per_day: number;
  max_concurrent_positions: number;
  entry_type: 'market' | 'limit';
  limit_offset_pct: number;
  stop_pct: number;
  risk_reward_ratio: number;
  max_slippage_pct: number;
  allowed_sessions: string[];
  direction: 'long_only' | 'short_only' | 'both';
  created_at?: string;
  updated_at?: string;
}

export type AutoTradeStatus =
  | 'pending_approval'
  | 'pending'
  | 'submitted'
  | 'open'
  | 'closed'
  | 'cancelled'
  | 'rejected'
  | 'error';

export interface AutoTradeOrder {
  id: number;
  alert_rule_id: number | null;
  scanner_event_id: number | null;
  trading_strategy_id: number | null;
  symbol: string;
  side: 'long' | 'short';
  event_date: string;
  status: AutoTradeStatus;
  rejection_reason: string | null;
  trigger_price: number | null;
  entry_price_target: number | null;
  calculated_stop: number | null;
  calculated_target: number | null;
  quantity: number | null;
  risk_amount_usd: number | null;
  is_paper: boolean;
  broker_order_id: string | null;
  broker_stop_id: string | null;
  broker_target_id: string | null;
  fill_price: number | null;
  filled_at: string | null;
  exit_price: number | null;
  exited_at: string | null;
  exit_reason: 'stop' | 'target' | 'manual' | null;
  trade_id: number | null;
  created_at?: string;
  updated_at?: string;
}

export interface TradingStats {
  period_days: number;
  total_orders: number;
  by_status: Record<string, number>;
  closed_count: number;
  win_count: number;
  win_rate: number | null;
  total_pnl: number;
  avg_pnl_per_trade: number | null;
}

export interface TradingConfig {
  AUTO_TRADING_ENABLED: boolean;
  PAPER_ACCOUNT_SIZE: number;
}

export interface AccountSummary {
  net_liquidation: number | null;
  available_funds: number | null;
  buying_power: number | null;
  currency: string;
  connected: boolean;
  error?: string;
  open_broker_orders: {
    order_id: number;
    symbol: string;
    action: string;
    order_type: string;
    quantity: number;
    status: string;
    filled: number;
    avg_fill_price: number;
  }[];
}

// ── Strategy hooks ────────────────────────────────────────────────────────────

export const useStrategies = (activeOnly = false) =>
  useQuery<TradingStrategy[]>({
    queryKey: ['trading', 'strategies', activeOnly],
    queryFn: async () => {
      const { data } = await api.get('/trading/strategies', {
        params: activeOnly ? { active_only: true } : {},
      });
      return data;
    },
  });

export const useCreateStrategy = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (payload: Partial<TradingStrategy>) => {
      const { data } = await api.post('/trading/strategies', payload);
      return data as TradingStrategy;
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['trading', 'strategies'] }),
  });
};

export const useUpdateStrategy = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ id, ...rest }: Partial<TradingStrategy> & { id: number }) => {
      const { data } = await api.patch(`/trading/strategies/${id}`, rest);
      return data as TradingStrategy;
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['trading', 'strategies'] }),
  });
};

export const useDeleteStrategy = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (id: number) => {
      await api.delete(`/trading/strategies/${id}`);
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['trading', 'strategies'] }),
  });
};

// ── Order hooks ───────────────────────────────────────────────────────────────

export const useAutoTradeOrders = (params?: {
  status?: string;
  symbol?: string;
  strategy_id?: number;
  from_date?: string;
  limit?: number;
}) =>
  useQuery<AutoTradeOrder[]>({
    queryKey: ['trading', 'orders', params],
    queryFn: async () => {
      const { data } = await api.get('/trading/orders', { params });
      return data;
    },
    refetchInterval: 30000,
  });

export const useApproveOrder = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (id: number) => {
      const { data } = await api.post(`/trading/orders/${id}/approve`);
      return data as AutoTradeOrder;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['trading', 'orders'] });
      qc.invalidateQueries({ queryKey: ['trading', 'stats'] });
    },
  });
};

export const useRejectOrder = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ id, reason }: { id: number; reason?: string }) => {
      const { data } = await api.post(`/trading/orders/${id}/reject`, { reason });
      return data as AutoTradeOrder;
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['trading', 'orders'] }),
  });
};

export const useCancelOrder = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (id: number) => {
      const { data } = await api.post(`/trading/orders/${id}/cancel`);
      return data as AutoTradeOrder;
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['trading', 'orders'] }),
  });
};

// ── Stats / config / account ──────────────────────────────────────────────────

export const useTradingStats = (days = 30) =>
  useQuery<TradingStats>({
    queryKey: ['trading', 'stats', days],
    queryFn: async () => {
      const { data } = await api.get('/trading/stats', { params: { days } });
      return data;
    },
    refetchInterval: 60000,
  });

export const useTradingConfig = () =>
  useQuery<TradingConfig>({
    queryKey: ['trading', 'config'],
    queryFn: async () => {
      const { data } = await api.get('/trading/config');
      return data;
    },
  });

export const useUpdateTradingConfig = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (payload: Partial<TradingConfig>) => {
      const { data } = await api.patch('/trading/config', payload);
      return data as TradingConfig;
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['trading', 'config'] }),
  });
};

export const useAccountSummary = () =>
  useQuery<AccountSummary>({
    queryKey: ['trading', 'account'],
    queryFn: async () => {
      const { data } = await api.get('/trading/account');
      return data;
    },
    refetchInterval: 30000,
    retry: false, // Don't retry on IBKR unavailable
  });
