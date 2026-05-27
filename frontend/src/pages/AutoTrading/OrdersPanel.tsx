import React from 'react';
import { Activity, Loader2 } from 'lucide-react';
import Card from '../../components/ui/Card';
import { OrderRow } from './components';
import type { AutoTradeOrder, TradingStrategy } from '../../api/trading';

export interface OrdersPanelProps {
  orders: AutoTradeOrder[];
  loadingOrders: boolean;
  orderFilter: string;
  onOrderFilter: (v: string) => void;
  strategies: TradingStrategy[];
  onApprove: (id: number) => void;
  onReject: (id: number) => void;
  onCancel: (id: number) => void;
}

export function OrdersPanel({
  orders, loadingOrders, orderFilter, onOrderFilter,
  strategies, onApprove, onReject, onCancel,
}: OrdersPanelProps) {
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-2">
        {['', 'pending_approval', 'submitted', 'open', 'closed', 'cancelled', 'rejected', 'error'].map(s => (
          <button
            key={s || 'all'}
            onClick={() => onOrderFilter(s)}
            className={`px-3 py-1.5 rounded-full text-xs font-bold uppercase border transition-all ${
              orderFilter === s
                ? 'bg-financial-blue border-financial-blue text-white'
                : 'bg-gray-800 border-gray-700 text-gray-400 hover:border-gray-500 hover:text-white'
            }`}
          >
            {s || 'All'}
          </button>
        ))}
      </div>

      <Card title="Auto-Trade Orders" icon={Activity} subtitle="Real-time log of every automated trade decision.">
        {loadingOrders ? (
          <div className="flex items-center justify-center py-16 text-gray-500">
            <Loader2 className="h-6 w-6 animate-spin mr-2" /> Loading orders...
          </div>
        ) : !orders?.length ? (
          <div className="flex flex-col items-center justify-center py-16 text-center gap-2">
            <Activity className="h-12 w-12 text-gray-700" />
            <p className="text-gray-400 font-medium">No orders found</p>
            <p className="text-gray-600 text-sm">Orders appear here when alert rules with auto-trading fire.</p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-gray-500 uppercase text-xs tracking-wider border-b border-gray-800">
                  <th className="py-3 text-left pl-4">Symbol</th>
                  <th className="py-3 text-left">Status</th>
                  <th className="py-3 text-left">Side</th>
                  <th className="py-3 text-right">Trigger</th>
                  <th className="py-3 text-right">Stop</th>
                  <th className="py-3 text-right">Target</th>
                  <th className="py-3 text-right">Qty</th>
                  <th className="py-3 text-right">Risk</th>
                  <th className="py-3 text-right">Fill</th>
                  <th className="py-3 text-right">Exit / P&L</th>
                  <th className="py-3 text-center">Mode</th>
                  <th className="py-3 text-right pr-4">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-800/50">
                {orders.map(o => (
                  <OrderRow
                    key={o.id}
                    order={o}
                    onApprove={() => onApprove(o.id)}
                    onReject={() => onReject(o.id)}
                    onCancel={() => onCancel(o.id)}
                  />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}
