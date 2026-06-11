import React from 'react';
import {
  Wifi, WifiOff, RefreshCw, Activity, Target, ShieldAlert, ToggleRight, ToggleLeft,
} from 'lucide-react';
import Card from '../../components/ui/Card';
import Button from '../../components/ui/Button';
import { AccountMetric, StatRow, STATUS_CONFIG, fmtUSD, pnlColor } from './components';
import type { AccountSummary, TradingStats, TradingConfig } from '../../api/trading';

export interface AccountPanelProps {
  account: AccountSummary | null;
  fetchingAccount: boolean;
  onRefreshAccount: () => void;
  stats: TradingStats | null;
  config: TradingConfig | null;
  onUpdateConfig: (cfg: Partial<TradingConfig>) => void;
}

export function AccountPanel({
  account, fetchingAccount, onRefreshAccount, stats, config, onUpdateConfig,
}: AccountPanelProps) {
  return (
    <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
      <div className="lg:col-span-2 space-y-6">
        <Card
          title="IBKR Account"
          icon={account?.connected ? Wifi : WifiOff}
          subtitle="Live account metrics from Interactive Brokers."
          actions={
            <Button
              variant="ghost"
              size="sm"
              icon={RefreshCw}
              onClick={onRefreshAccount}
              className={fetchingAccount ? 'opacity-50 pointer-events-none' : ''}
            >
              Refresh
            </Button>
          }
        >
          {!account?.connected ? (
            <div className="flex items-center gap-3 py-8 justify-center text-gray-500">
              <WifiOff className="h-6 w-6" />
              <span>IBKR not connected. {account?.error && <span className="text-red-400 text-sm">{account.error}</span>}</span>
            </div>
          ) : (
            <>
              <div className="grid grid-cols-3 gap-4 p-4">
                <AccountMetric label="Net Liquidation" value={fmtUSD(account.net_liquidation)} />
                <AccountMetric label="Available Funds" value={fmtUSD(account.available_funds)} />
                <AccountMetric label="Buying Power"    value={fmtUSD(account.buying_power)} />
              </div>

              {account.open_broker_orders.length > 0 && (
                <div className="mt-2 border-t border-gray-800">
                  <p className="text-xs text-gray-500 uppercase tracking-wider px-4 pt-3 pb-2 font-bold">
                    Open Broker Orders
                  </p>
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="text-gray-500 text-xs uppercase border-b border-gray-800">
                        <th className="py-2 pl-4 text-left">Symbol</th>
                        <th className="py-2 text-left">Action</th>
                        <th className="py-2 text-left">Type</th>
                        <th className="py-2 text-right">Qty</th>
                        <th className="py-2 text-right">Filled</th>
                        <th className="py-2 text-right pr-4">Avg Price</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-800/50">
                      {account.open_broker_orders.map((o) => (
                        <tr key={o.order_id} className="hover:bg-gray-800/30">
                          <td className="py-2 pl-4 font-mono font-bold text-white">{o.symbol}</td>
                          <td className={`py-2 font-bold text-xs uppercase ${o.action === 'BUY' ? 'text-green-400' : 'text-red-400'}`}>{o.action}</td>
                          <td className="py-2 text-gray-400 text-xs">{o.order_type}</td>
                          <td className="py-2 text-right text-gray-300">{o.quantity}</td>
                          <td className="py-2 text-right text-gray-400">{o.filled}</td>
                          <td className="py-2 text-right pr-4 text-gray-300">{o.avg_fill_price > 0 ? fmtUSD(o.avg_fill_price) : '—'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </>
          )}
        </Card>

        {stats && stats.total_orders > 0 && (
          <Card title="30-Day Breakdown" icon={Activity}>
            <div className="grid grid-cols-4 gap-4 p-4">
              {Object.entries(stats.by_status).map(([status, count]) => {
                const cfg = STATUS_CONFIG[status];
                return (
                  <div key={status} className={`rounded-lg border px-3 py-3 text-center ${cfg?.color ?? 'text-gray-400 border-gray-700'}`}>
                    <div className="text-2xl font-black">{count as React.ReactNode}</div>
                    <div className="text-xs uppercase font-bold mt-0.5 opacity-80">{cfg?.label ?? status}</div>
                  </div>
                );
              })}
            </div>
          </Card>
        )}
      </div>

      <div className="space-y-6">
        <Card title="System Config" icon={ShieldAlert} subtitle="Master switches for live trading.">
          <div className="space-y-5 p-1">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm font-semibold text-white">Live Trading Enabled</p>
                <p className="text-xs text-gray-500 mt-0.5">
                  Disabling blocks all live (non-paper) order submissions.
                </p>
              </div>
              <button
                onClick={() => onUpdateConfig({ AUTO_TRADING_ENABLED: !config?.AUTO_TRADING_ENABLED })}
                className="flex-shrink-0"
              >
                {config?.AUTO_TRADING_ENABLED ? (
                  <ToggleRight className="h-8 w-8 text-green-500" />
                ) : (
                  <ToggleLeft className="h-8 w-8 text-gray-600" />
                )}
              </button>
            </div>

            <div className="border-t border-gray-800" />

            <div>
              <label className="block text-sm font-semibold text-white mb-1.5">
                Paper Account Size
              </label>
              <p className="text-xs text-gray-500 mb-2">
                Simulated account equity used for position sizing in paper mode.
              </p>
              <div className="flex items-center gap-2">
                <span className="text-gray-400 text-sm">$</span>
                <input
                  type="number"
                  min={1000}
                  step={1000}
                  defaultValue={config?.PAPER_ACCOUNT_SIZE ?? 100000}
                  onBlur={e => onUpdateConfig({ PAPER_ACCOUNT_SIZE: parseFloat(e.target.value) })}
                  className="flex-1 bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:ring-2 focus:ring-financial-blue"
                />
              </div>
            </div>
          </div>
        </Card>

        {stats && (
          <Card title="Performance (30d)" icon={Target}>
            <div className="space-y-3 p-1">
              <StatRow label="Total Orders"   value={String(stats.total_orders)} />
              <StatRow label="Closed"          value={String(stats.closed_count)} />
              <StatRow label="Win Rate"        value={stats.win_rate != null ? `${stats.win_rate}%` : '—'} />
              <StatRow
                label="Total P&L"
                value={fmtUSD(stats.total_pnl)}
                valueClass={pnlColor(stats.total_pnl)}
              />
              <StatRow
                label="Avg P&L / Trade"
                value={fmtUSD(stats.avg_pnl_per_trade)}
                valueClass={pnlColor(stats.avg_pnl_per_trade)}
              />
            </div>
          </Card>
        )}
      </div>
    </div>
  );
}
