import React, { useState } from 'react';
import { Bot, Plus, DollarSign, Activity, Target, ShieldAlert } from 'lucide-react';
import Button from '../../components/ui/Button';
import MetricCard from '../../components/ui/MetricCard';
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
  type TradingStrategy,
} from '../../api/trading';
import { DEFAULT_STRATEGY, fmtUSD } from './components';
import { StrategyPanel } from './StrategyPanel';
import { OrdersPanel } from './OrdersPanel';
import { AccountPanel } from './AccountPanel';
import { ConfigPanel } from './ConfigPanel';

const AutoTrading: React.FC = () => {
  const [tab, setTab] = useState<'strategies' | 'orders' | 'account'>('strategies');

  const { data: strategies, isLoading: loadingStrategies } = useStrategies();
  const createStrategy = useCreateStrategy();
  const updateStrategy = useUpdateStrategy();
  const deleteStrategy = useDeleteStrategy();
  const [stratModalOpen, setStratModalOpen] = useState(false);
  const [editingStrategy, setEditingStrategy] = useState<TradingStrategy | null>(null);
  const [stratForm, setStratForm] = useState<Partial<TradingStrategy>>(DEFAULT_STRATEGY);

  const [orderFilter, setOrderFilter] = useState<string>('');
  const { data: orders, isLoading: loadingOrders } = useAutoTradeOrders(
    orderFilter ? { status: orderFilter } : undefined
  );
  const approveOrder = useApproveOrder();
  const rejectOrder  = useRejectOrder();
  const cancelOrder  = useCancelOrder();

  const { data: stats } = useTradingStats(30);
  const { data: config } = useTradingConfig();
  const updateConfig = useUpdateTradingConfig();
  const { data: account, refetch: refetchAccount, isFetching: fetchingAccount } = useAccountSummary();

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

  const isSaving = createStrategy.isPending || updateStrategy.isPending;

  const activeStrategies = strategies?.filter(s => s.is_active).length ?? 0;
  const pendingApprovals = orders?.filter(o => o.status === 'pending_approval').length ?? 0;

  return (
    <div className="space-y-8 animate-fade-in pb-12">
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

      {config && !config.AUTO_TRADING_ENABLED && (
        <div className="flex items-center gap-3 bg-yellow-500/10 border border-yellow-500/30 rounded-lg px-4 py-3 text-yellow-300">
          <ShieldAlert className="h-5 w-5 flex-shrink-0" />
          <span className="text-sm font-medium">
            Live auto-trading is <strong>disabled</strong>. Enable it in the Account tab to allow real orders.
            Paper-mode strategies are unaffected.
          </span>
        </div>
      )}

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

      {tab === 'strategies' && (
        <StrategyPanel
          strategies={strategies ?? []}
          loadingStrategies={loadingStrategies}
          onOpenCreate={openCreate}
          onEditStrategy={openEdit}
          onDeleteStrategy={handleStrategyDelete}
          onToggleStrategy={(id, isActive) => updateStrategy.mutate({ id, is_active: !isActive })}
        />
      )}

      {tab === 'orders' && (
        <OrdersPanel
          orders={orders ?? []}
          loadingOrders={loadingOrders}
          orderFilter={orderFilter}
          onOrderFilter={setOrderFilter}
          strategies={strategies ?? []}
          onApprove={(id) => approveOrder.mutate(id)}
          onReject={(id) => rejectOrder.mutate({ id })}
          onCancel={(id) => cancelOrder.mutate(id)}
        />
      )}

      {tab === 'account' && (
        <AccountPanel
          account={account}
          fetchingAccount={fetchingAccount}
          onRefreshAccount={() => refetchAccount()}
          stats={stats}
          config={config}
          onUpdateConfig={(cfg) => updateConfig.mutate(cfg)}
        />
      )}

      <ConfigPanel
        isOpen={stratModalOpen}
        editingStrategy={editingStrategy}
        stratForm={stratForm}
        onStratForm={setStratForm}
        onSave={handleStrategySave}
        onClose={() => setStratModalOpen(false)}
        isSaving={isSaving}
      />
    </div>
  );
};

export default AutoTrading;
