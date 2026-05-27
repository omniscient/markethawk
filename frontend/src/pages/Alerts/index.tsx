import React, { useState } from 'react';
import { Bell, Plus, Activity, Smartphone, CheckCircle } from 'lucide-react';
import Button from '../../components/ui/Button';
import MetricCard from '../../components/ui/MetricCard';
import {
  useAlertRules,
  useAlertStats,
  useAlertLogs,
  useCreateAlertRule,
  useUpdateAlertRule,
  useDeleteAlertRule,
  useTestAlertRule,
  usePushSubscription,
  type AlertRule,
} from '../../api/alerts';
import { useStrategies } from '../../api/trading';
import { AlertRulesPanel } from './AlertRulesPanel';
import { AlertRuleModal } from './AlertRuleModal';
import { AlertLogsPanel, AlertActivityCard } from './AlertLogsPanel';
import { ChannelConfigPanel } from './ChannelConfigPanel';

const Alerts: React.FC = () => {
  const { data: rules, isLoading: isLoadingRules } = useAlertRules();
  const { data: stats } = useAlertStats();
  const { data: logs } = useAlertLogs(15);
  const { data: strategies } = useStrategies(true);

  const createRule = useCreateAlertRule();
  const updateRule = useUpdateAlertRule();
  const deleteRule = useDeleteAlertRule();
  const testRule = useTestAlertRule();
  const { subscribe, unsubscribe, isSubscribing } = usePushSubscription();

  const [isModalOpen, setIsModalOpen] = useState(false);
  const [editingRule, setEditingRule] = useState<Partial<AlertRule> | null>(null);
  const [hasPushSubscription, setHasPushSubscription] = useState<boolean | null>(null);
  const [formState, setFormState] = useState<Partial<AlertRule>>({});

  React.useEffect(() => {
    if (!('serviceWorker' in navigator) || !('PushManager' in window)) {
      setHasPushSubscription(false);
      return;
    }
    navigator.serviceWorker.ready.then(reg =>
      reg.pushManager.getSubscription()
    ).then(sub => setHasPushSubscription(sub !== null));
  }, [stats?.push_subscriptions]);

  const openCreateModal = () => {
    setEditingRule(null);
    setFormState({
      name: '',
      is_active: true,
      scanner_types: [],
      severity_filter: 'any',
      cooldown_minutes: 60,
      channels: ['browser_push'],
      channel_config: { email: '', google_chat_webhook: '', webhook_url: '' },
      auto_trade: false,
      trading_strategy_id: null,
    });
    setIsModalOpen(true);
  };

  const openEditModal = (rule: AlertRule) => {
    setEditingRule(rule);
    setFormState({ ...rule });
    setIsModalOpen(true);
  };

  const handleSave = async () => {
    if (editingRule?.id) {
      await updateRule.mutateAsync({ id: editingRule.id, ...formState });
    } else {
      await createRule.mutateAsync(formState);
    }
    setIsModalOpen(false);
  };

  const handleDelete = (id: number) => {
    if (window.confirm('Are you sure you want to delete this alert rule?')) {
      deleteRule.mutate(id);
    }
  };

  return (
    <div className="space-y-8 animate-fade-in pb-12">
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h1 className="text-4xl font-extrabold text-white tracking-tight">Alert Center</h1>
          <p className="text-gray-400 mt-2 text-lg">
            Multi-channel notifications for high-confidence scanner triggers.
          </p>
        </div>
        <Button variant="primary" icon={Plus} onClick={openCreateModal} size="lg" className="shadow-lg shadow-blue-600/20">
          New Alert Rule
        </Button>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6">
        <MetricCard title="Active Rules" value={stats?.active_rules ?? 0} subtitle={`Out of ${stats?.total_rules ?? 0} total`} icon={Bell} trend={0} />
        <MetricCard title="Triggers Today" value={stats?.triggered_today ?? 0} subtitle="Real-time count" icon={Activity} trend={0} />
        <MetricCard title="Push Devices" value={stats?.push_subscriptions ?? 0} subtitle="Registered browsers" icon={Smartphone} trend={0} />
        <MetricCard
          title="Delivery Rate"
          value={`${stats?.delivery_rate ?? 100}%`}
          subtitle="All channels combined"
          icon={CheckCircle}
          trend={0}
          valueColor={stats?.delivery_rate && stats.delivery_rate < 90 ? 'text-red-400' : 'text-green-400'}
        />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
        <div className="lg:col-span-2 space-y-6">
          <AlertRulesPanel
            rules={rules ?? []}
            isLoadingRules={isLoadingRules}
            onOpenCreate={openCreateModal}
            onOpenEdit={openEditModal}
            onToggle={(rule) => updateRule.mutate({ id: rule.id, is_active: !rule.is_active })}
            onDelete={handleDelete}
            onTest={(id) => testRule.mutate(id)}
          />
        </div>

        <div className="space-y-8">
          <ChannelConfigPanel
            hasPushSubscription={hasPushSubscription}
            onSubscribe={() => subscribe()}
            onUnsubscribe={() => unsubscribe()}
            isSubscribing={isSubscribing}
          />
          <AlertActivityCard logs={logs ?? []} />
        </div>
      </div>

      <AlertLogsPanel logs={logs ?? []} />

      <AlertRuleModal
        isOpen={isModalOpen}
        editingRule={editingRule}
        formState={formState}
        onFormState={setFormState}
        onSave={handleSave}
        onClose={() => setIsModalOpen(false)}
        isSaving={createRule.isPending || updateRule.isPending}
        strategies={strategies ?? []}
      />
    </div>
  );
};

export default Alerts;
