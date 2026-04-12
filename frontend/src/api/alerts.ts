import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import axios from 'axios';

const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL || '',
});

export interface AlertRule {
  id: number;
  name: string;
  is_active: boolean;
  scanner_types: string[];
  severity_filter: 'any' | 'high' | 'medium' | 'low';
  cooldown_minutes: number;
  channels: ('browser_push' | 'email' | 'google_chat' | 'webhook')[];
  channel_config: {
    email?: string;
    google_chat_webhook?: string;
    webhook_url?: string;
  };
  created_at?: string;
  updated_at?: string;
}

export interface AlertLog {
  id: number;
  rule_id: number | null;
  ticker: string;
  scanner_type: string;
  channel: string;
  status: 'sent' | 'failed';
  error_message: string | null;
  delivered_at: string;
}

export interface AlertStats {
  active_rules: number;
  total_rules: number;
  triggered_today: number;
  delivery_rate: number;
  push_subscriptions: number;
}

// ── Stats ────────────────────────────────────────────────────────────────────

export const useAlertStats = () => {
  return useQuery<AlertStats>({
    queryKey: ['alerts', 'stats'],
    queryFn: async () => {
      const { data } = await api.get('/api/alerts/stats');
      return data;
    },
    refetchInterval: 30000, // Refresh every 30s
  });
};

// ── Rules ────────────────────────────────────────────────────────────────────

export const useAlertRules = () => {
  return useQuery<AlertRule[]>({
    queryKey: ['alerts', 'rules'],
    queryFn: async () => {
      const { data } = await api.get('/api/alerts/rules');
      return data;
    },
  });
};

export const useCreateAlertRule = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (newRule: Partial<AlertRule>) => {
      const { data } = await api.post('/api/alerts/rules', newRule);
      return data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['alerts', 'rules'] });
      queryClient.invalidateQueries({ queryKey: ['alerts', 'stats'] });
    },
  });
};

export const useUpdateAlertRule = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({ id, ...updates }: Partial<AlertRule> & { id: number }) => {
      const { data } = await api.patch(`/api/alerts/rules/${id}`, updates);
      return data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['alerts', 'rules'] });
      queryClient.invalidateQueries({ queryKey: ['alerts', 'stats'] });
    },
  });
};

export const useDeleteAlertRule = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (id: number) => {
      await api.delete(`/api/alerts/rules/${id}`);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['alerts', 'rules'] });
      queryClient.invalidateQueries({ queryKey: ['alerts', 'stats'] });
    },
  });
};

export const useTestAlertRule = () => {
  return useMutation({
    mutationFn: async (id: number) => {
      const { data } = await api.post(`/api/alerts/rules/${id}/test`);
      return data;
    },
  });
};

// ── Logs ─────────────────────────────────────────────────────────────────────

export const useAlertLogs = (limit = 20) => {
  return useQuery<AlertLog[]>({
    queryKey: ['alerts', 'logs', limit],
    queryFn: async () => {
      const { data } = await api.get(`/api/alerts/logs?limit=${limit}`);
      return data;
    },
    refetchInterval: 10000, // Refresh every 10s
  });
};

// ── Push Notifications Helpers ───────────────────────────────────────────────

function urlBase64ToUint8Array(base64String: string) {
  const padding = '='.repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/');
  const rawData = window.atob(base64);
  const outputArray = new Uint8Array(rawData.length);
  for (let i = 0; i < rawData.length; ++i) {
    outputArray[i] = rawData.charCodeAt(i);
  }
  return outputArray;
}

export const usePushSubscription = () => {
  const queryClient = useQueryClient();

  const subscribeMutation = useMutation({
    mutationFn: async () => {
      // 1. Get VAPID public key
      const { data: { public_key } } = await api.get('/api/alerts/push/vapid-key');

      // 2. Ensure service worker is registered and active before subscribing
      await navigator.serviceWorker.register('/sw.js');
      const registration = await navigator.serviceWorker.ready;

      // 3. Prompt for permission
      const permission = await Notification.requestPermission();
      if (permission !== 'granted') {
        throw new Error('Notification permission denied');
      }

      // 4. Subscribe (unsubscribe first if a stale subscription exists)
      const existing = await registration.pushManager.getSubscription();
      if (existing) await existing.unsubscribe();

      const subscription = await registration.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: urlBase64ToUint8Array(public_key),
      });

      // 5. Save to backend
      await api.post('/api/alerts/push/subscribe', subscription);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['alerts', 'stats'] });
    },
  });

  const unsubscribeMutation = useMutation({
    mutationFn: async () => {
      const registration = await navigator.serviceWorker.ready;
      const subscription = await registration.pushManager.getSubscription();
      if (subscription) {
        await api.delete('/api/alerts/push/unsubscribe', { data: { endpoint: subscription.endpoint } });
        await subscription.unsubscribe();
      }
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['alerts', 'stats'] });
    },
  });

  return {
    subscribe: subscribeMutation.mutateAsync,
    isSubscribing: subscribeMutation.isPending,
    unsubscribe: unsubscribeMutation.mutateAsync,
    isUnsubscribing: unsubscribeMutation.isPending,
  };
};
