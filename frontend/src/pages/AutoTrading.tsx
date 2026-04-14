import React, { useState } from 'react';
import {
  Bot,
  Plus,
  Edit2,
  Trash2,
  ToggleLeft,
  ToggleRight,
  CheckCircle,
  XCircle,
  Ban,
  AlertTriangle,
  TrendingUp,
  TrendingDown,
  Clock,
  Loader2,
  Wifi,
  WifiOff,
  DollarSign,
  Activity,
  Target,
  ShieldAlert,
  ChevronRight,
  RefreshCw,
  Zap,
} from 'lucide-react';

import Card from '../components/ui/Card';
import Button from '../components/ui/Button';
import Modal from '../components/ui/Modal';
import MetricCard from '../components/ui/MetricCard';

import {
  useStrategies,
  useCreateStrategy,
  useUpdateStrategy,
  useDeleteStrategy,
  useAutoTradeOrders,
  useApproveOrder,
  useRejectOrder,
  useCancelOrder,
  useTradingStats,
  useTradingConfig,
  useUpdateTradingConfig,
  useAccountSummary,
  TradingStrategy,
  AutoTradeOrder,
} from '../api/trading';

// ── Constants ─────────────────────────────────────────────────────────────────

const SESSION_OPTIONS = [
  { id: 'pre', label: 'Pre-Market' },
  { id: 'regular', label: 'Regular' },
  { id: 'post', label: 'After-Hours' },
];

const DIRECTION_OPTIONS = [
  { id: 'long_only', label: 'Long Only' },
  { id: 'short_only', label: 'Short Only' },
  { id: 'both', label: 'Both' },
];

const ENTRY_TYPES = [
  { id: 'market', label: 'Market' },
  { id: 'limit', label: 'Limit' },
];

const STATUS_CONFIG: Record<string, { label: string; color: string; icon: React.ElementType }> = {
  pending_approval: { label: 'Needs Approval', color: 'text-yellow-400 bg-yellow-400/10 border-yellow-400/20', icon: Clock },
  pending:          { label: 'Pending',         color: 'text-blue-400 bg-blue-400/10 border-blue-400/20',     icon: Clock },
  submitted:        { label: 'Submitted',        color: 'text-blue-400 bg-blue-400/10 border-blue-400/20',     icon: Loader2 },
  open:             { label: 'Open',             color: 'text-green-400 bg-green-400/10 border-green-400/20',  icon: Activity },
  closed:           { label: 'Closed',           color: 'text-gray-400 bg-gray-400/10 border-gray-400/20',     icon: CheckCircle },
  cancelled:        { label: 'Cancelled',        color: 'text-gray-500 bg-gray-500/10 border-gray-500/20',     icon: Ban },
  rejected:         { label: 'Rejected',         color: 'text-red-400 bg-red-400/10 border-red-400/20',        icon: XCircle },
  error:            { label: 'Error',            color: 'text-red-400 bg-red-400/10 border-red-400/20',        icon: AlertTriangle },
};

// ── Default form state ─────────────────────────────────────────────────────────

const DEFAULT_STRATEGY: Partial<TradingStrategy> = {
  name: '',
  description: '',
  is_active: true,
  paper_mode: true,
  requires_approval: false,
  risk_per_trade_pct: 1.0,
  max_position_usd: undefined,
  max_trades_per_day: 3,
  max_concurrent_positions: 2,
  entry_type: 'market',
  limit_offset_pct: 0.0,
  stop_pct: 2.0,
  risk_reward_ratio: 2.0,
  max_slippage_pct: 0.5,
  allowed_sessions: ['regular'],
  direction: 'long_only',
};

// ── Helpers ───────────────────────────────────────────────────────────────────

const fmt = (n: number | null | undefined, decimals = 2, prefix = '') =>
  n == null ? '—' : `${prefix}${n.toFixed(decimals)}`;

const fmtUSD = (n: number | null | undefined) =>
  n == null ? '—' : `$${n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

function pnlColor(n: number | null | undefined) {
  if (n == null) return 'text-gray-400';
  return n >= 0 ? 'text-green-400' : 'text-red-400';
}

// ── Status Badge ──────────────────────────────────────────────────────────────

const StatusBadge: React.FC<{ status: string }> = ({ status }) => {
  const cfg = STATUS_CONFIG[status] ?? { label: status, color: 'text-gray-400 bg-gray-400/10 border-gray-400/20', icon: Clock };
  const Icon = cfg.icon;
  return (
    <span className={`inline-flex items-center gap-1 text-xs font-bold uppercase px-2 py-0.5 rounded border ${cfg.color}`}>
      <Icon className="h-3 w-3" />
      {cfg.label}
    </span>
  );
};

// ── AutoTrading Page ──────────────────────────────────────────────────────────

const AutoTrading: React.FC = () => {
  const [tab, setTab] = useState<'strategies' | 'orders' | 'account'>('strategies');

  // Strategies
  const { data: strategies, isLoading: loadingStrategies } = useStrategies();
  const createStrategy = useCreateStrategy();
  const updateStrategy = useUpdateStrategy();
  const deleteStrategy = useDeleteStrategy();
  const [stratModalOpen, setStratModalOpen] = useState(false);
  const [editingStrategy, setEditingStrategy] = useState<TradingStrategy | null>(null);
  const [stratForm, setStratForm] = useState<Partial<TradingStrategy>>(DEFAULT_STRATEGY);

  // Orders
  const [orderFilter, setOrderFilter] = useState<string>('');
  const { data: orders, isLoading: loadingOrders } = useAutoTradeOrders(
    orderFilter ? { status: orderFilter } : undefined
  );
  const approveOrder = useApproveOrder();
  const rejectOrder  = useRejectOrder();
  const cancelOrder  = useCancelOrder();

  // Stats / account / config
  const { data: stats } = useTradingStats(30);
  const { data: config } = useTradingConfig();
  const updateConfig = useUpdateTradingConfig();
  const { data: account, refetch: refetchAccount, isFetching: fetchingAccount } = useAccountSummary();

  // ── Strategy modal helpers ───────────────────────────────────────────────

  const openCreate = () => {
    setEditingStrategy(null);
    setStratForm({ ...DEFAULT_STRATEGY });
    setStratModalOpen(true);
  };

  const openEdit = (s: TradingStrategy) => {
    setEditingStrategy(s);
    setStratForm({ ...s });
    setStratModalOpen(true);
  };

  const handleStrategySave = async () => {
    if (editingStrategy) {
      await updateStrategy.mutateAsync({ id: editingStrategy.id, ...stratForm });
    } else {
      await createStrategy.mutateAsync(stratForm);
    }
    setStratModalOpen(false);
  };

  const handleStrategyDelete = (id: number) => {
    if (window.confirm('Deactivate this strategy? It will no longer trigger auto-trades.')) {
      deleteStrategy.mutate(id);
    }
  };

  const toggleStrategySession = (session: string) => {
    const current = stratForm.allowed_sessions ?? [];
    setStratForm({
      ...stratForm,
      allowed_sessions: current.includes(session)
        ? current.filter(s => s !== session)
        : [...current, session],
    });
  };

  const isSaving = createStrategy.isPending || updateStrategy.isPending;

  // ── Metric summary ───────────────────────────────────────────────────────

  const activeStrategies = strategies?.filter(s => s.is_active).length ?? 0;
  const pendingApprovals = orders?.filter(o => o.status === 'pending_approval').length ?? 0;

  return (
    <div className="space-y-8 animate-fade-in pb-12">

      {/* ── Header ──────────────────────────────────────────────────────────── */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h1 className="text-4xl font-extrabold text-white tracking-tight flex items-center gap-3">
            <Bot className="h-9 w-9 text-financial-blue" />
            Auto Trading
          </h1>
          <p className="text-gray-400 mt-2 text-lg">
            Rule-based order execution on IBKR. Alerts trigger bracket orders automatically.
          </p>
        </div>

        {tab === 'strategies' && (
          <Button variant="primary" icon={Plus} onClick={openCreate} size="lg" className="shadow-lg shadow-blue-600/20">
            New Strategy
          </Button>
        )}
      </div>

      {/* ── Metric cards ────────────────────────────────────────────────────── */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6">
        <MetricCard
          title="Active Strategies"
          value={activeStrategies}
          subtitle={`${strategies?.length ?? 0} total`}
          icon={Bot}
          trend={0}
        />
        <MetricCard
          title="Orders (30d)"
          value={stats?.total_orders ?? 0}
          subtitle={`${stats?.closed_count ?? 0} closed`}
          icon={Activity}
          trend={0}
        />
        <MetricCard
          title="Win Rate (30d)"
          value={stats?.win_rate != null ? `${stats.win_rate}%` : '—'}
          subtitle={`${stats?.win_count ?? 0} wins`}
          icon={Target}
          trend={0}
        />
        <MetricCard
          title="Total P&L (30d)"
          value={stats?.total_pnl != null ? fmtUSD(stats.total_pnl) : '—'}
          subtitle={pendingApprovals > 0 ? `${pendingApprovals} need approval` : 'No pending approvals'}
          icon={DollarSign}
          trend={0}
        />
      </div>

      {/* ── Kill-switch banner ───────────────────────────────────────────────── */}
      {config && !config.AUTO_TRADING_ENABLED && (
        <div className="flex items-center gap-3 bg-yellow-500/10 border border-yellow-500/30 rounded-lg px-4 py-3 text-yellow-300">
          <ShieldAlert className="h-5 w-5 flex-shrink-0" />
          <span className="text-sm font-medium">
            Live auto-trading is <strong>disabled</strong>. Enable it in the Account tab to allow real orders.
            Paper-mode strategies are unaffected.
          </span>
        </div>
      )}

      {/* ── Tabs ─────────────────────────────────────────────────────────────── */}
      <div className="flex gap-1 bg-gray-800/50 p-1 rounded-lg w-fit border border-gray-700">
        {(['strategies', 'orders', 'account'] as const).map(t => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`px-5 py-2 rounded-md text-sm font-semibold capitalize transition-all ${
              tab === t
                ? 'bg-financial-blue text-white shadow'
                : 'text-gray-400 hover:text-white'
            }`}
          >
            {t}
            {t === 'orders' && pendingApprovals > 0 && (
              <span className="ml-2 px-1.5 py-0.5 bg-yellow-500 text-black text-xs rounded-full font-bold">
                {pendingApprovals}
              </span>
            )}
          </button>
        ))}
      </div>

      {/* ═══════════════════════════════════════════════════════════════════════
          TAB: STRATEGIES
      ════════════════════════════════════════════════════════════════════════ */}
      {tab === 'strategies' && (
        <Card title="Trading Strategies" icon={Bot} subtitle="Define risk/reward parameters for automated order execution.">
          {loadingStrategies ? (
            <div className="flex items-center justify-center py-16 text-gray-500">
              <Loader2 className="h-6 w-6 animate-spin mr-2" /> Loading strategies...
            </div>
          ) : !strategies?.length ? (
            <div className="flex flex-col items-center justify-center py-16 text-center gap-3">
              <Bot className="h-12 w-12 text-gray-700" />
              <p className="text-gray-400 font-medium">No strategies yet</p>
              <p className="text-gray-600 text-sm max-w-xs">
                Create a strategy and link it to an alert rule to start auto-trading.
              </p>
              <Button variant="primary" icon={Plus} onClick={openCreate} className="mt-2">
                Create First Strategy
              </Button>
            </div>
          ) : (
            <div className="divide-y divide-gray-800">
              {strategies.map(s => (
                <StrategyRow
                  key={s.id}
                  strategy={s}
                  onEdit={() => openEdit(s)}
                  onDelete={() => handleStrategyDelete(s.id)}
                  onToggle={() => updateStrategy.mutate({ id: s.id, is_active: !s.is_active })}
                />
              ))}
            </div>
          )}
        </Card>
      )}

      {/* ═══════════════════════════════════════════════════════════════════════
          TAB: ORDERS
      ════════════════════════════════════════════════════════════════════════ */}
      {tab === 'orders' && (
        <div className="space-y-4">
          {/* Filter bar */}
          <div className="flex flex-wrap gap-2">
            {['', 'pending_approval', 'submitted', 'open', 'closed', 'cancelled', 'rejected', 'error'].map(s => (
              <button
                key={s || 'all'}
                onClick={() => setOrderFilter(s)}
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
                        strategies={strategies ?? []}
                        onApprove={() => approveOrder.mutate(o.id)}
                        onReject={() => rejectOrder.mutate({ id: o.id })}
                        onCancel={() => cancelOrder.mutate(o.id)}
                      />
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>
        </div>
      )}

      {/* ═══════════════════════════════════════════════════════════════════════
          TAB: ACCOUNT
      ════════════════════════════════════════════════════════════════════════ */}
      {tab === 'account' && (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">

          {/* IBKR Connection */}
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
                  onClick={() => refetchAccount()}
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
                          {account.open_broker_orders.map(o => (
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

            {/* Order status breakdown */}
            {stats && stats.total_orders > 0 && (
              <Card title="30-Day Breakdown" icon={Activity}>
                <div className="grid grid-cols-4 gap-4 p-4">
                  {Object.entries(stats.by_status).map(([status, count]) => {
                    const cfg = STATUS_CONFIG[status];
                    return (
                      <div key={status} className={`rounded-lg border px-3 py-3 text-center ${cfg?.color ?? 'text-gray-400 border-gray-700'}`}>
                        <div className="text-2xl font-black">{count}</div>
                        <div className="text-xs uppercase font-bold mt-0.5 opacity-80">{cfg?.label ?? status}</div>
                      </div>
                    );
                  })}
                </div>
              </Card>
            )}
          </div>

          {/* Config panel */}
          <div className="space-y-6">
            <Card title="System Config" icon={ShieldAlert} subtitle="Master switches for live trading.">
              <div className="space-y-5 p-1">
                {/* Kill-switch */}
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-sm font-semibold text-white">Live Trading Enabled</p>
                    <p className="text-xs text-gray-500 mt-0.5">
                      Disabling blocks all live (non-paper) order submissions.
                    </p>
                  </div>
                  <button
                    onClick={() =>
                      updateConfig.mutate({ AUTO_TRADING_ENABLED: !config?.AUTO_TRADING_ENABLED })
                    }
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

                {/* Paper account size */}
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
                      onBlur={e =>
                        updateConfig.mutate({ PAPER_ACCOUNT_SIZE: parseFloat(e.target.value) })
                      }
                      className="flex-1 bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:ring-2 focus:ring-financial-blue"
                    />
                  </div>
                </div>
              </div>
            </Card>

            {/* Quick stats */}
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
      )}

      {/* ═══════════════════════════════════════════════════════════════════════
          STRATEGY MODAL
      ════════════════════════════════════════════════════════════════════════ */}
      <Modal
        isOpen={stratModalOpen}
        onClose={() => setStratModalOpen(false)}
        title={editingStrategy ? `Edit Strategy — ${editingStrategy.name}` : 'New Trading Strategy'}
        size="xl"
        footer={
          <div className="flex gap-3 justify-end">
            <Button variant="ghost" onClick={() => setStratModalOpen(false)}>Cancel</Button>
            <Button
              variant="primary"
              loading={isSaving}
              onClick={handleStrategySave}
              icon={Zap}
            >
              {editingStrategy ? 'Save Changes' : 'Create Strategy'}
            </Button>
          </div>
        }
      >
        <div className="space-y-6">

          {/* Name & description */}
          <div className="grid grid-cols-1 gap-4">
            <div>
              <label className="block text-xs text-gray-400 uppercase tracking-wider mb-1.5 font-bold">Strategy Name</label>
              <input
                type="text"
                value={stratForm.name ?? ''}
                onChange={e => setStratForm({ ...stratForm, name: e.target.value })}
                placeholder="e.g. 2R Morning Momentum"
                className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-white focus:outline-none focus:ring-2 focus:ring-financial-blue"
              />
            </div>
            <div>
              <label className="block text-xs text-gray-400 uppercase tracking-wider mb-1.5 font-bold">Description <span className="text-gray-600 normal-case">(optional)</span></label>
              <textarea
                rows={2}
                value={stratForm.description ?? ''}
                onChange={e => setStratForm({ ...stratForm, description: e.target.value })}
                placeholder="What scanner conditions does this strategy trade?"
                className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-white focus:outline-none focus:ring-2 focus:ring-financial-blue resize-none"
              />
            </div>
          </div>

          {/* Mode toggles */}
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            <ToggleField
              label="Paper Mode"
              description="No real orders sent"
              value={stratForm.paper_mode ?? true}
              onChange={v => setStratForm({ ...stratForm, paper_mode: v })}
              onColor="text-blue-400"
            />
            <ToggleField
              label="Requires Approval"
              description="Human sign-off before entry"
              value={stratForm.requires_approval ?? false}
              onChange={v => setStratForm({ ...stratForm, requires_approval: v })}
            />
            <ToggleField
              label="Active"
              description="Enabled for new alerts"
              value={stratForm.is_active ?? true}
              onChange={v => setStratForm({ ...stratForm, is_active: v })}
            />
          </div>

          {/* Paper mode warning */}
          {!stratForm.paper_mode && (
            <div className="flex items-start gap-2 bg-red-500/10 border border-red-500/30 rounded-lg px-3 py-2.5 text-red-300 text-sm">
              <AlertTriangle className="h-4 w-4 flex-shrink-0 mt-0.5" />
              <span>
                <strong>Live mode active.</strong> Real orders will be sent to IBKR when this strategy fires.
                Ensure <em>Live Trading Enabled</em> is toggled on in the Account tab.
              </span>
            </div>
          )}

          <div className="border-t border-gray-800" />

          {/* Risk section */}
          <div>
            <p className="text-xs text-gray-400 uppercase tracking-wider font-bold mb-3">Risk & Sizing</p>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
              <NumberField
                label="Risk Per Trade"
                suffix="%"
                value={stratForm.risk_per_trade_pct ?? 1}
                onChange={v => setStratForm({ ...stratForm, risk_per_trade_pct: v })}
                step={0.1}
                min={0.1}
                max={10}
              />
              <NumberField
                label="Max Position"
                prefix="$"
                value={stratForm.max_position_usd ?? ''}
                placeholder="No limit"
                onChange={v => setStratForm({ ...stratForm, max_position_usd: v || undefined })}
                step={1000}
                min={0}
              />
              <NumberField
                label="Max Trades / Day"
                value={stratForm.max_trades_per_day ?? 3}
                onChange={v => setStratForm({ ...stratForm, max_trades_per_day: Math.floor(v) })}
                step={1}
                min={1}
                max={20}
              />
              <NumberField
                label="Max Concurrent"
                value={stratForm.max_concurrent_positions ?? 2}
                onChange={v => setStratForm({ ...stratForm, max_concurrent_positions: Math.floor(v) })}
                step={1}
                min={1}
                max={10}
              />
            </div>
          </div>

          {/* Stop & target */}
          <div>
            <p className="text-xs text-gray-400 uppercase tracking-wider font-bold mb-3">Stop & Target</p>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
              <NumberField
                label="Stop Loss"
                suffix="%"
                value={stratForm.stop_pct ?? 2}
                onChange={v => setStratForm({ ...stratForm, stop_pct: v })}
                step={0.1}
                min={0.1}
                max={20}
              />
              <NumberField
                label="Risk : Reward"
                suffix="R"
                value={stratForm.risk_reward_ratio ?? 2}
                onChange={v => setStratForm({ ...stratForm, risk_reward_ratio: v })}
                step={0.1}
                min={0.5}
                max={10}
              />
              <NumberField
                label="Max Slippage"
                suffix="%"
                value={stratForm.max_slippage_pct ?? 0.5}
                onChange={v => setStratForm({ ...stratForm, max_slippage_pct: v })}
                step={0.1}
                min={0}
                max={5}
              />
              {/* Implied target label */}
              <div className="bg-gray-800/50 rounded-lg border border-gray-700/50 px-3 py-2 flex flex-col justify-center">
                <span className="text-xs text-gray-500 uppercase tracking-wider font-bold mb-1">Implied Target</span>
                <span className="text-lg font-black text-green-400">
                  {((stratForm.stop_pct ?? 2) * (stratForm.risk_reward_ratio ?? 2)).toFixed(1)}%
                </span>
                <span className="text-xs text-gray-600">from entry</span>
              </div>
            </div>
          </div>

          {/* Entry */}
          <div>
            <p className="text-xs text-gray-400 uppercase tracking-wider font-bold mb-3">Entry</p>
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-4">
              <div>
                <label className="block text-xs text-gray-400 mb-1.5 font-semibold">Entry Type</label>
                <select
                  value={stratForm.entry_type ?? 'market'}
                  onChange={e => setStratForm({ ...stratForm, entry_type: e.target.value as any })}
                  className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-white focus:ring-2 focus:ring-financial-blue outline-none"
                >
                  {ENTRY_TYPES.map(t => <option key={t.id} value={t.id}>{t.label}</option>)}
                </select>
              </div>
              {stratForm.entry_type === 'limit' && (
                <NumberField
                  label="Limit Offset"
                  suffix="%"
                  value={stratForm.limit_offset_pct ?? 0}
                  onChange={v => setStratForm({ ...stratForm, limit_offset_pct: v })}
                  step={0.05}
                  min={-5}
                  max={5}
                />
              )}
              <div>
                <label className="block text-xs text-gray-400 mb-1.5 font-semibold">Direction</label>
                <select
                  value={stratForm.direction ?? 'long_only'}
                  onChange={e => setStratForm({ ...stratForm, direction: e.target.value as any })}
                  className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-white focus:ring-2 focus:ring-financial-blue outline-none"
                >
                  {DIRECTION_OPTIONS.map(d => <option key={d.id} value={d.id}>{d.label}</option>)}
                </select>
              </div>
            </div>
          </div>

          {/* Sessions */}
          <div>
            <p className="text-xs text-gray-400 uppercase tracking-wider font-bold mb-3">Eligible Sessions</p>
            <div className="flex gap-2 flex-wrap">
              {SESSION_OPTIONS.map(s => {
                const active = (stratForm.allowed_sessions ?? []).includes(s.id);
                return (
                  <button
                    key={s.id}
                    onClick={() => toggleStrategySession(s.id)}
                    className={`px-4 py-1.5 rounded-full border text-sm font-semibold transition-all ${
                      active
                        ? 'bg-financial-blue border-financial-blue text-white'
                        : 'bg-gray-800 border-gray-700 text-gray-400 hover:border-gray-500 hover:text-white'
                    }`}
                  >
                    {s.label}
                  </button>
                );
              })}
            </div>
          </div>

        </div>
      </Modal>

    </div>
  );
};

// ── Sub-components ─────────────────────────────────────────────────────────────

const StrategyRow: React.FC<{
  strategy: TradingStrategy;
  onEdit: () => void;
  onDelete: () => void;
  onToggle: () => void;
}> = ({ strategy: s, onEdit, onDelete, onToggle }) => (
  <div className="flex items-center gap-4 py-4 px-4 group hover:bg-gray-800/30 transition-colors">
    {/* Toggle */}
    <button onClick={onToggle} className="flex-shrink-0">
      {s.is_active
        ? <ToggleRight className="h-7 w-7 text-blue-500" />
        : <ToggleLeft className="h-7 w-7 text-gray-600" />}
    </button>

    {/* Name + badges */}
    <div className="flex-1 min-w-0">
      <div className="flex items-center gap-2 flex-wrap">
        <span className="font-bold text-white text-sm truncate">{s.name}</span>
        <span className={`text-xs font-bold uppercase px-2 py-0.5 rounded border ${
          s.paper_mode
            ? 'text-blue-400 bg-blue-400/10 border-blue-400/20'
            : 'text-orange-400 bg-orange-400/10 border-orange-400/20'
        }`}>
          {s.paper_mode ? 'Paper' : 'Live'}
        </span>
        {s.requires_approval && (
          <span className="text-xs font-bold uppercase px-2 py-0.5 rounded border text-yellow-400 bg-yellow-400/10 border-yellow-400/20">
            Approval Required
          </span>
        )}
      </div>
      {s.description && (
        <p className="text-xs text-gray-500 mt-0.5 truncate">{s.description}</p>
      )}
    </div>

    {/* Stats grid */}
    <div className="hidden lg:flex items-center gap-6 text-center">
      <StratStat label="Stop" value={`${s.stop_pct}%`} />
      <StratStat label="R:R" value={`${s.risk_reward_ratio}:1`} />
      <StratStat label="Risk/Trade" value={`${s.risk_per_trade_pct}%`} />
      <StratStat label="Entry" value={s.entry_type} />
      <StratStat label="Direction" value={s.direction.replace('_', ' ')} />
    </div>

    {/* Actions */}
    <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
      <button onClick={onEdit} className="p-1.5 text-gray-400 hover:text-white hover:bg-gray-700 rounded transition-colors">
        <Edit2 className="h-4 w-4" />
      </button>
      <button onClick={onDelete} className="p-1.5 text-gray-400 hover:text-red-400 hover:bg-red-400/10 rounded transition-colors">
        <Trash2 className="h-4 w-4" />
      </button>
    </div>
  </div>
);

const StratStat: React.FC<{ label: string; value: string }> = ({ label, value }) => (
  <div>
    <div className="text-xs text-gray-500 uppercase font-bold">{label}</div>
    <div className="text-sm font-semibold text-white capitalize">{value}</div>
  </div>
);

const OrderRow: React.FC<{
  order: AutoTradeOrder;
  strategies: TradingStrategy[];
  onApprove: () => void;
  onReject: () => void;
  onCancel: () => void;
}> = ({ order: o, onApprove, onReject, onCancel }) => {
  const entryPrice = o.fill_price ?? o.entry_price_target ?? o.trigger_price;
  const pnl = o.exit_price && entryPrice && o.quantity
    ? ((o.side === 'long' ? o.exit_price - entryPrice : entryPrice - o.exit_price) * o.quantity)
    : null;

  return (
    <tr className="group hover:bg-gray-800/40 transition-colors">
      <td className="py-3 pl-4">
        <span className="font-mono font-black text-white">{o.symbol}</span>
        <div className="text-xs text-gray-600">{o.event_date}</div>
      </td>
      <td className="py-3"><StatusBadge status={o.status} /></td>
      <td className="py-3">
        <span className={`text-xs font-black uppercase flex items-center gap-1 ${o.side === 'long' ? 'text-green-400' : 'text-red-400'}`}>
          {o.side === 'long' ? <TrendingUp className="h-3.5 w-3.5" /> : <TrendingDown className="h-3.5 w-3.5" />}
          {o.side}
        </span>
      </td>
      <td className="py-3 text-right font-mono text-gray-300">{fmt(o.trigger_price, 2, '$')}</td>
      <td className="py-3 text-right font-mono text-red-400">{fmt(o.calculated_stop, 2, '$')}</td>
      <td className="py-3 text-right font-mono text-green-400">{fmt(o.calculated_target, 2, '$')}</td>
      <td className="py-3 text-right text-gray-300">{o.quantity ?? '—'}</td>
      <td className="py-3 text-right font-mono text-gray-400">{fmt(o.risk_amount_usd, 0, '$')}</td>
      <td className="py-3 text-right font-mono text-white">{fmt(o.fill_price, 2, '$')}</td>
      <td className="py-3 text-right">
        {o.exit_price ? (
          <div>
            <div className="font-mono text-sm text-gray-300">{fmt(o.exit_price, 2, '$')}</div>
            <div className={`text-xs font-bold ${pnlColor(pnl)}`}>
              {pnl != null ? (pnl >= 0 ? '+' : '') + fmtUSD(pnl) : ''}
            </div>
          </div>
        ) : '—'}
      </td>
      <td className="py-3 text-center">
        <span className={`text-xs font-bold uppercase px-1.5 py-0.5 rounded ${
          o.is_paper ? 'text-blue-400 bg-blue-400/10' : 'text-orange-400 bg-orange-400/10'
        }`}>
          {o.is_paper ? 'P' : 'L'}
        </span>
      </td>
      <td className="py-3 pr-4 text-right">
        <div className="flex items-center justify-end gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
          {o.status === 'pending_approval' && (
            <>
              <button onClick={onApprove} title="Approve" className="p-1 text-green-400 hover:bg-green-400/10 rounded transition-colors">
                <CheckCircle className="h-4 w-4" />
              </button>
              <button onClick={onReject} title="Reject" className="p-1 text-red-400 hover:bg-red-400/10 rounded transition-colors">
                <XCircle className="h-4 w-4" />
              </button>
            </>
          )}
          {['submitted', 'open', 'pending', 'pending_approval'].includes(o.status) && (
            <button onClick={onCancel} title="Cancel" className="p-1 text-gray-400 hover:text-yellow-400 hover:bg-yellow-400/10 rounded transition-colors">
              <Ban className="h-4 w-4" />
            </button>
          )}
        </div>
      </td>
    </tr>
  );
};

const AccountMetric: React.FC<{ label: string; value: string }> = ({ label, value }) => (
  <div className="bg-gray-800/50 rounded-lg border border-gray-700/50 px-4 py-3 text-center">
    <div className="text-xs text-gray-500 uppercase tracking-wider font-bold mb-1">{label}</div>
    <div className="text-xl font-black text-white">{value}</div>
  </div>
);

const StatRow: React.FC<{ label: string; value: string; valueClass?: string }> = ({
  label, value, valueClass = 'text-white'
}) => (
  <div className="flex items-center justify-between py-1.5">
    <span className="text-sm text-gray-400">{label}</span>
    <span className={`text-sm font-bold ${valueClass}`}>{value}</span>
  </div>
);

// ── Small reusable form controls ──────────────────────────────────────────────

const NumberField: React.FC<{
  label: string;
  value: number | string;
  onChange: (v: number) => void;
  step?: number;
  min?: number;
  max?: number;
  suffix?: string;
  prefix?: string;
  placeholder?: string;
}> = ({ label, value, onChange, step = 1, min, max, suffix, prefix, placeholder }) => (
  <div>
    <label className="block text-xs text-gray-400 mb-1.5 font-semibold">{label}</label>
    <div className="relative flex items-center">
      {prefix && <span className="absolute left-3 text-gray-400 text-sm pointer-events-none">{prefix}</span>}
      <input
        type="number"
        value={value}
        onChange={e => onChange(parseFloat(e.target.value))}
        step={step}
        min={min}
        max={max}
        placeholder={placeholder}
        className={`w-full bg-gray-800 border border-gray-700 rounded-lg py-2 text-white text-sm focus:outline-none focus:ring-2 focus:ring-financial-blue ${prefix ? 'pl-7 pr-3' : suffix ? 'pl-3 pr-7' : 'px-3'}`}
      />
      {suffix && <span className="absolute right-3 text-gray-400 text-sm pointer-events-none">{suffix}</span>}
    </div>
  </div>
);

const ToggleField: React.FC<{
  label: string;
  description: string;
  value: boolean;
  onChange: (v: boolean) => void;
  onColor?: string;
}> = ({ label, description, value, onChange, onColor = 'text-blue-500' }) => (
  <div className="flex items-center justify-between bg-gray-800/50 rounded-lg border border-gray-700 px-3 py-2.5">
    <div>
      <p className="text-sm font-semibold text-white">{label}</p>
      <p className="text-xs text-gray-500">{description}</p>
    </div>
    <button onClick={() => onChange(!value)} className="flex-shrink-0 ml-2">
      {value
        ? <ToggleRight className={`h-7 w-7 ${onColor}`} />
        : <ToggleLeft className="h-7 w-7 text-gray-600" />}
    </button>
  </div>
);

export default AutoTrading;
