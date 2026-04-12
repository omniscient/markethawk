import React, { useState } from 'react';
import {
  Bell,
  Plus,
  Edit2,
  Trash2,
  ToggleLeft,
  ToggleRight,
  Mail,
  Smartphone,
  Webhook,
  MessageSquare,
  Activity,
  CheckCircle,
  AlertCircle,
  Clock,
  ExternalLink,
  ShieldCheck,
  ShieldAlert,
  Send,
  Loader2,
  RefreshCw
} from 'lucide-react';

// Components
import Card from '../components/ui/Card';
import Button from '../components/ui/Button';
import Modal from '../components/ui/Modal';
import MetricCard from '../components/ui/MetricCard';

// Hooks
import {
  useAlertRules,
  useAlertStats,
  useAlertLogs,
  useCreateAlertRule,
  useUpdateAlertRule,
  useDeleteAlertRule,
  useTestAlertRule,
  usePushSubscription,
  AlertRule
} from '../api/alerts';

const SCANNER_TYPES = [
  { id: 'pre_market_volume_spike', label: 'Pre-Market Volume Spike' },
  { id: 'oversold_bounce', label: 'Oversold Bounce' },
  { id: 'liquidity_hunt', label: 'Liquidity Hunt' },
  { id: 'large_cap_breakout', label: 'Large Cap Breakout' },
  { id: 'news_volume_spike', label: 'News Volume Spike' },
];

const SEVERITIES = [
  { id: 'any', label: 'Any Severity' },
  { id: 'high', label: 'High' },
  { id: 'medium', label: 'Medium' },
  { id: 'low', label: 'Low' },
];

const COOLDOWN_OPTIONS = [
  { label: 'No Limit', value: 0 },
  { label: '15 Minutes', value: 15 },
  { label: '30 Minutes', value: 30 },
  { label: '1 Hour', value: 60 },
  { label: '4 Hours', value: 240 },
  { label: 'Daily', value: 1440 },
];

const Alerts: React.FC = () => {
  // ── Queries / Mutations ──────────────────────────────────────────────────
  const { data: rules, isLoading: isLoadingRules } = useAlertRules();
  const { data: stats } = useAlertStats();
  const { data: logs } = useAlertLogs(15);

  const createRule = useCreateAlertRule();
  const updateRule = useUpdateAlertRule();
  const deleteRule = useDeleteAlertRule();
  const testRule = useTestAlertRule();
  const { subscribe, unsubscribe, isSubscribing, isUnsubscribing } = usePushSubscription();

  // ── State ────────────────────────────────────────────────────────────────
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [editingRule, setEditingRule] = useState<Partial<AlertRule> | null>(null);
  // Track whether the browser actually has an active push subscription (not just permission).
  const [hasPushSubscription, setHasPushSubscription] = useState<boolean | null>(null);

  React.useEffect(() => {
    if (!('serviceWorker' in navigator) || !('PushManager' in window)) {
      setHasPushSubscription(false);
      return;
    }
    navigator.serviceWorker.ready.then(reg =>
      reg.pushManager.getSubscription()
    ).then(sub => setHasPushSubscription(sub !== null));
  }, [stats?.push_subscriptions]); // re-check after subscribe/unsubscribe
  const [formState, setFormState] = useState<Partial<AlertRule>>({});

  // ── Handlers ─────────────────────────────────────────────────────────────
  const openCreateModal = () => {
    setEditingRule(null);
    setFormState({
      name: '',
      is_active: true,
      scanner_types: [],
      severity_filter: 'any',
      cooldown_minutes: 60,
      channels: ['browser_push'],
      channel_config: {
        email: '',
        google_chat_webhook: '',
        webhook_url: '',
      }
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

  const handleToggle = (rule: AlertRule) => {
    updateRule.mutate({ id: rule.id, is_active: !rule.is_active });
  };

  const handleDelete = (id: number) => {
    if (window.confirm('Are you sure you want to delete this alert rule?')) {
      deleteRule.mutate(id);
    }
  };

  const toggleChannel = (channel: any) => {
    const current = formState.channels || [];
    if (current.includes(channel)) {
      setFormState({ ...formState, channels: current.filter(c => c !== channel) });
    } else {
      setFormState({ ...formState, channels: [...current, channel] });
    }
  };

  const toggleScannerType = (type: string) => {
    const current = formState.scanner_types || [];
    if (current.includes(type)) {
      setFormState({ ...formState, scanner_types: current.filter(t => t !== type) });
    } else {
      setFormState({ ...formState, scanner_types: [...current, type] });
    }
  };

  // ── Render Helpers ───────────────────────────────────────────────────────
  const getSeverityColor = (sev: string) => {
    switch (sev) {
      case 'high': return 'text-red-400 bg-red-400/10 border-red-400/20';
      case 'medium': return 'text-yellow-400 bg-yellow-400/10 border-yellow-400/20';
      case 'low': return 'text-blue-400 bg-blue-400/10 border-blue-400/20';
      default: return 'text-gray-400 bg-gray-400/10 border-gray-400/20';
    }
  };

  return (
    <div className="space-y-8 animate-fade-in pb-12">
      {/* ── Header ─────────────────────────────────────────────────────────── */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h1 className="text-4xl font-extrabold text-white tracking-tight">
            Alert Center
          </h1>
          <p className="text-gray-400 mt-2 text-lg">
            Multi-channel notifications for high-confidence scanner triggers.
          </p>
        </div>
        <Button 
          variant="primary" 
          icon={Plus} 
          onClick={openCreateModal}
          size="lg"
          className="shadow-lg shadow-blue-600/20"
        >
          New Alert Rule
        </Button>
      </div>

      {/* ── Metric Grid ────────────────────────────────────────────────────── */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6">
        <MetricCard
          title="Active Rules"
          value={stats?.active_rules ?? 0}
          subtitle={`Out of ${stats?.total_rules ?? 0} total`}
          icon={Bell}
          trend={0}
        />
        <MetricCard
          title="Triggers Today"
          value={stats?.triggered_today ?? 0}
          subtitle="Real-time count"
          icon={Activity}
          trend={0}
        />
        <MetricCard
          title="Push Devices"
          value={stats?.push_subscriptions ?? 0}
          subtitle="Registered browsers"
          icon={Smartphone}
          trend={0}
        />
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
        {/* ── Alert Rules List ─────────────────────────────────────────────── */}
        <div className="lg:col-span-2 space-y-6">
          <Card 
            title="Alert Rules" 
            icon={ShieldCheck} 
            subtitle="Strategic rules determining when to notify you."
          >
            {isLoadingRules ? (
              <div className="py-12 flex justify-center">
                <Loader2 className="h-8 w-8 text-blue-500 animate-spin" />
              </div>
            ) : rules?.length === 0 ? (
              <div className="py-12 text-center">
                <div className="mb-4 inline-flex p-4 bg-gray-800 rounded-full">
                  <Bell className="h-8 w-8 text-gray-600" />
                </div>
                <h3 className="text-lg font-medium text-white">No rules configured</h3>
                <p className="text-gray-500 mt-1">Create your first rule to start getting notified.</p>
                <Button variant="secondary" className="mt-4" onClick={openCreateModal}>
                  Set up your first rule
                </Button>
              </div>
            ) : (
              <div className="space-y-4">
                {rules?.map((rule) => (
                  <div 
                    key={rule.id}
                    className="p-5 bg-gray-800/50 border border-gray-700/50 rounded-xl hover:border-gray-600 transition-all group"
                  >
                    <div className="flex items-start justify-between">
                      <div className="flex items-start space-x-4">
                        <button 
                          onClick={() => handleToggle(rule)}
                          className="mt-1 transition-colors outline-none"
                        >
                          {rule.is_active ? (
                            <ToggleRight className="h-8 w-8 text-blue-500" />
                          ) : (
                            <ToggleLeft className="h-8 w-8 text-gray-600" />
                          )}
                        </button>
                        <div>
                          <h3 className={`text-lg font-bold transition-colors ${rule.is_active ? 'text-white' : 'text-gray-500'}`}>
                            {rule.name}
                          </h3>
                          <div className="flex flex-wrap items-center gap-2 mt-2">
                             {rule.scanner_types.length === 0 ? (
                               <span className="text-xs px-2 py-0.5 rounded border border-blue-500/30 bg-blue-500/10 text-blue-300 font-medium">
                                 ALL SCANNERS
                               </span>
                             ) : (
                               rule.scanner_types.map(t => (
                                 <span key={t} className="text-xs px-2 py-0.5 rounded border border-gray-600 bg-gray-700 text-gray-300 font-medium uppercase tracking-wider">
                                   {t.replace(/_/g, ' ')}
                                 </span>
                               ))
                             )}
                             <span className={`text-xs px-2 py-0.5 rounded border font-bold uppercase ${getSeverityColor(rule.severity_filter)}`}>
                               {rule.severity_filter}
                             </span>
                          </div>
                          
                          <div className="flex items-center space-x-4 mt-3">
                            <div className="flex items-center -space-x-1">
                              {rule.channels.includes('browser_push') && <Smartphone className="h-4 w-4 text-blue-400 bg-gray-800 border border-gray-700 p-0.5 rounded-full z-30" />}
                              {rule.channels.includes('email') && <Mail className="h-4 w-4 text-purple-400 bg-gray-800 border border-gray-700 p-0.5 rounded-full z-20" />}
                              {rule.channels.includes('google_chat') && <MessageSquare className="h-4 w-4 text-green-400 bg-gray-800 border border-gray-700 p-0.5 rounded-full z-10" />}
                              {rule.channels.includes('webhook') && <Webhook className="h-4 w-4 text-amber-400 bg-gray-800 border border-gray-700 p-0.5 rounded-full z-0" />}
                            </div>
                            <span className="text-xs text-gray-500 font-medium flex items-center">
                              <Clock className="h-3 w-3 mr-1" />
                              {rule.cooldown_minutes}m cooldown
                            </span>
                          </div>
                        </div>
                      </div>
                      
                      <div className="flex items-center space-x-1 opacity-10 group-hover:opacity-100 transition-opacity">
                        <Button 
                          variant="ghost" 
                          size="sm" 
                          icon={Send} 
                          title="Send Test"
                          onClick={() => {
                            if (window.confirm(`Send a test notification for "${rule.name}"?`)) {
                              testRule.mutate(rule.id);
                            }
                          }}
                        />
                        <Button 
                          variant="ghost" 
                          size="sm" 
                          icon={Edit2} 
                          onClick={() => openEditModal(rule)}
                        />
                        <Button 
                          variant="ghost" 
                          size="sm" 
                          icon={Trash2} 
                          onClick={() => handleDelete(rule.id)}
                          className="text-red-500 hover:text-red-400 hover:bg-red-500/10"
                        />
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </Card>
        </div>

        {/* ── Sidebar ──────────────────────────────────────────────────────── */}
        <div className="space-y-8">
           {/* Browser Push Registration */}
           <Card 
            title="Browser Push" 
            icon={Smartphone}
            className="border-blue-500/20 bg-blue-500/[0.02]"
          >
            <div className="space-y-4">
              <p className="text-sm text-gray-400">
                Receive instant notifications on your desktop even when MarketHawk is closed.
              </p>
              
              {Notification.permission === 'granted' && hasPushSubscription ? (
                <div className="p-4 rounded-xl bg-green-500/10 border border-green-500/20 flex items-start space-x-3">
                  <ShieldCheck className="h-5 w-5 text-green-400 flex-shrink-0 mt-0.5" />
                  <div>
                    <h4 className="text-sm font-bold text-green-400 uppercase tracking-widest">Active</h4>
                    <p className="text-xs text-green-400/70 mt-1">This browser is registered for push alerts.</p>
                    <button
                      onClick={() => unsubscribe()}
                      className="text-xs font-bold text-gray-500 hover:text-white underline mt-3 uppercase tracking-tighter"
                    >
                      Unregister Device
                    </button>
                  </div>
                </div>
              ) : Notification.permission === 'denied' ? (
                <div className="p-4 rounded-xl bg-red-500/10 border border-red-500/20 flex items-start space-x-3">
                  <ShieldAlert className="h-5 w-5 text-red-400 flex-shrink-0 mt-0.5" />
                  <div>
                    <h4 className="text-sm font-bold text-red-400 uppercase tracking-widest">Blocked</h4>
                    <p className="text-xs text-red-400/70 mt-1">Permission has been denied. Reset site permissions in your browser to enable.</p>
                  </div>
                </div>
              ) : (
                <div className="space-y-4">
                  <Button 
                    variant="primary" 
                    fullWidth 
                    onClick={() => subscribe()}
                    loading={isSubscribing}
                  >
                    Enable Push Alerts
                  </Button>
                  <p className="text-[10px] text-gray-500 text-center uppercase font-bold tracking-widest">
                    Zero Cost · Privacy First · No Downloads
                  </p>
                </div>
              )}
            </div>
          </Card>

          {/* Recent Logs Summary */}
          <Card title="Latest Activity" icon={Activity}>
             {logs?.length === 0 ? (
               <div className="text-center py-6">
                 <p className="text-sm text-gray-500 italic">No activity yet.</p>
               </div>
             ) : (
               <div className="space-y-3">
                 {logs?.slice(0, 5).map(log => (
                   <div key={log.id} className="flex items-center justify-between text-xs p-2 rounded hover:bg-gray-800 transition-colors">
                     <div className="flex items-center space-x-2">
                       <span className={`font-bold ${log.status === 'sent' ? 'text-green-500' : 'text-red-500'}`}>
                         {log.status === 'sent' ? '✓' : '✗'}
                       </span>
                       <span className="text-white font-medium">{log.ticker}</span>
                       <span className="text-gray-500">→</span>
                       <span className="text-gray-400 truncate w-24 uppercase font-bold tracking-tighter">{log.channel.replace('_', ' ')}</span>
                     </div>
                     <span className="text-[10px] text-gray-600 font-mono">
                       {new Date(log.delivered_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                     </span>
                   </div>
                 ))}
                 <div className="pt-2">
                    <Button variant="ghost" size="sm" fullWidth className="text-[10px] uppercase font-bold text-gray-500 tracking-widest">
                       View Full System Log
                    </Button>
                 </div>
               </div>
             )}
          </Card>
        </div>
      </div>

      {/* ── Delivery Logs Table ───────────────────────────────────────────── */}
      <Card 
        title="Delivery Journal" 
        icon={RefreshCw} 
        subtitle="Complete audit trail of notification attempts."
      >
        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="border-b border-gray-700">
                <th className="pb-3 text-sm font-bold text-gray-500 uppercase tracking-widest px-4">Time</th>
                <th className="pb-3 text-sm font-bold text-gray-500 uppercase tracking-widest px-4">Ticker</th>
                <th className="pb-3 text-sm font-bold text-gray-500 uppercase tracking-widest px-4">Trigger</th>
                <th className="pb-3 text-sm font-bold text-gray-500 uppercase tracking-widest px-4">Channel</th>
                <th className="pb-3 text-sm font-bold text-gray-500 uppercase tracking-widest px-4">Status</th>
                <th className="pb-3 text-sm font-bold text-gray-500 uppercase tracking-widest px-4">Result</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-800">
              {logs?.map(log => (
                <tr key={log.id} className="group hover:bg-gray-800/50 transition-colors">
                  <td className="py-4 px-4 text-sm text-gray-400 tabular-nums">
                    {new Date(log.delivered_at).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}
                  </td>
                  <td className="py-4 px-4">
                    <span className="text-white font-bold bg-gray-700 px-2 py-1 rounded text-xs">{log.ticker || 'SYS'}</span>
                  </td>
                  <td className="py-4 px-4 text-sm text-gray-300">
                    {log.scanner_type?.replace(/_/g, ' ').toUpperCase() || 'MANUAL TEST'}
                  </td>
                  <td className="py-4 px-4">
                    <span className="text-xs font-medium text-gray-400 uppercase tracking-widest border border-gray-700 px-2 py-0.5 rounded-full inline-flex items-center">
                      {log.channel === 'browser_push' && <Smartphone className="h-3 w-3 mr-1" />}
                      {log.channel === 'email' && <Mail className="h-3 w-3 mr-1" />}
                      {log.channel === 'google_chat' && <MessageSquare className="h-3 w-3 mr-1" />}
                      {log.channel === 'webhook' && <Webhook className="h-3 w-3 mr-1" />}
                      {log.channel}
                    </span>
                  </td>
                  <td className="py-4 px-4">
                    <span className={`text-xs font-bold uppercase tracking-widest inline-flex items-center ${log.status === 'sent' ? 'text-green-500' : 'text-red-500'}`}>
                      {log.status === 'sent' ? (
                        <>
                          <CheckCircle className="h-3 w-3 mr-1" /> Delivered
                        </>
                      ) : (
                        <>
                          <AlertCircle className="h-3 w-3 mr-1" /> Failed
                        </>
                      )}
                    </span>
                  </td>
                  <td className="py-4 px-4 text-xs text-gray-500 italic max-w-xs truncate">
                    {log.error_message || 'Successfully dispatched'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      {/* ── Rule Configuration Modal ─────────────────────────────────────── */}
      <Modal
        isOpen={isModalOpen}
        onClose={() => setIsModalOpen(false)}
        title={editingRule ? 'Edit Alert Rule' : 'Create New Alert Rule'}
        size="lg"
        footer={(
          <>
            <Button variant="ghost" onClick={() => setIsModalOpen(false)}>Cancel</Button>
            <Button 
              variant="primary" 
              onClick={handleSave} 
              loading={createRule.isPending || updateRule.isPending}
            >
              {editingRule ? 'Save Changes' : 'Create Rule'}
            </Button>
          </>
        )}
      >
        <div className="space-y-6">
          {/* Basic Info */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <div className="space-y-2">
              <label className="text-xs font-bold text-gray-500 uppercase tracking-widest">Rule Name</label>
              <input 
                type="text"
                placeholder="Spike Alert, Oversold, etc."
                value={formState.name}
                onChange={e => setFormState({ ...formState, name: e.target.value })}
                className="w-full bg-gray-800 border-gray-700 border rounded-lg p-3 text-white focus:ring-2 focus:ring-blue-500 outline-none transition-all"
              />
            </div>
            
            <div className="space-y-2">
              <label className="text-xs font-bold text-gray-500 uppercase tracking-widest">Minimum Severity</label>
              <div className="grid grid-cols-2 gap-2">
                {SEVERITIES.map(sev => (
                  <button
                    key={sev.id}
                    onClick={() => setFormState({ ...formState, severity_filter: sev.id as any })}
                    className={`p-2 rounded-lg border text-xs font-bold uppercase transition-all ${
                      formState.severity_filter === sev.id 
                        ? 'bg-blue-600 border-blue-500 text-white' 
                        : 'bg-gray-800 border-gray-700 text-gray-500 hover:border-gray-500'
                    }`}
                  >
                    {sev.label}
                  </button>
                ))}
              </div>
            </div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <div className="space-y-2">
              <label className="text-xs font-bold text-gray-500 uppercase tracking-widest">Trigger Cooldown</label>
              <select
                value={formState.cooldown_minutes}
                onChange={e => setFormState({ ...formState, cooldown_minutes: parseInt(e.target.value) })}
                className="w-full bg-gray-800 border-gray-700 border rounded-lg p-3 text-white focus:ring-2 focus:ring-blue-500 outline-none transition-all appearance-none"
              >
                {COOLDOWN_OPTIONS.map(opt => (
                  <option key={opt.value} value={opt.value}>{opt.label}</option>
                ))}
              </select>
            </div>
            
            <div className="space-y-2">
               <label className="text-xs font-bold text-gray-500 uppercase tracking-widest">Status</label>
               <div className="flex items-center space-x-3 p-3 bg-gray-800 border border-gray-700 rounded-lg">
                 <button 
                   onClick={() => setFormState({ ...formState, is_active: !formState.is_active })}
                   className="transition-all outline-none"
                 >
                   {formState.is_active ? <ToggleRight className="h-6 w-6 text-blue-500" /> : <ToggleLeft className="h-6 w-6 text-gray-600" />}
                 </button>
                 <span className="text-sm font-medium text-white">{formState.is_active ? 'Enabled' : 'Disabled'}</span>
               </div>
            </div>
          </div>

          {/* Scanner Selection */}
          <div className="space-y-2">
            <label className="text-xs font-bold text-gray-500 uppercase tracking-widest">Applicable Scanners</label>
            <div className="flex flex-wrap gap-2">
              {SCANNER_TYPES.map(type => (
                <button
                  key={type.id}
                  onClick={() => toggleScannerType(type.id)}
                  className={`px-3 py-1.5 rounded-full border text-xs font-bold transition-all ${
                    formState.scanner_types?.includes(type.id)
                      ? 'bg-blue-600 border-blue-500 text-white' 
                      : 'bg-gray-800 border-gray-700 text-gray-500 hover:border-gray-500'
                  }`}
                >
                  {type.label}
                </button>
              ))}
              <button
                onClick={() => setFormState({ ...formState, scanner_types: [] })}
                className={`px-3 py-1.5 rounded-full border text-xs font-bold transition-all ${
                  (formState.scanner_types?.length ?? 0) === 0
                    ? 'bg-blue-600/20 border-blue-500/30 text-blue-400' 
                    : 'bg-gray-800 border-gray-700 text-gray-500 hover:border-gray-500'
                }`}
              >
                ALL SCANNERS
              </button>
            </div>
          </div>

          {/* Delivery Channels */}
          <div className="space-y-4 pt-4 border-t border-gray-800">
             <label className="text-xs font-bold text-gray-500 uppercase tracking-widest">Delivery Channels</label>
             <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {/* Email */}
                <div className={`p-4 rounded-xl border transition-all ${formState.channels?.includes('email') ? 'bg-purple-950/10 border-purple-500/30' : 'bg-gray-800 border-gray-700'}`}>
                  <div className="flex items-center justify-between mb-4">
                    <div className="flex items-center space-x-2">
                      <Mail className={`h-4 w-4 ${formState.channels?.includes('email') ? 'text-purple-400' : 'text-gray-500'}`} />
                      <span className={`text-sm font-bold uppercase tracking-tight ${formState.channels?.includes('email') ? 'text-purple-400' : 'text-gray-500'}`}>Email</span>
                    </div>
                    <button onClick={() => toggleChannel('email')}>
                      {formState.channels?.includes('email') ? <ToggleRight className="h-6 w-6 text-purple-500" /> : <ToggleLeft className="h-6 w-6 text-gray-600" />}
                    </button>
                  </div>
                  {formState.channels?.includes('email') && (
                    <input 
                      type="email" 
                      placeholder="address@example.com"
                      value={formState.channel_config?.email}
                      onChange={e => setFormState({ 
                        ...formState, 
                        channel_config: { ...formState.channel_config, email: e.target.value } 
                      })}
                      className="w-full bg-gray-900 border border-purple-500/20 rounded p-2 text-sm text-white focus:ring-1 focus:ring-purple-500 outline-none"
                    />
                  )}
                </div>

                {/* Google Chat */}
                <div className={`p-4 rounded-xl border transition-all ${formState.channels?.includes('google_chat') ? 'bg-green-950/10 border-green-500/30' : 'bg-gray-800 border-gray-700'}`}>
                  <div className="flex items-center justify-between mb-4">
                    <div className="flex items-center space-x-2">
                      <MessageSquare className={`h-4 w-4 ${formState.channels?.includes('google_chat') ? 'text-green-400' : 'text-gray-500'}`} />
                      <span className={`text-sm font-bold uppercase tracking-tight ${formState.channels?.includes('google_chat') ? 'text-green-400' : 'text-gray-500'}`}>Google Chat</span>
                    </div>
                    <button onClick={() => toggleChannel('google_chat')}>
                      {formState.channels?.includes('google_chat') ? <ToggleRight className="h-6 w-6 text-green-500" /> : <ToggleLeft className="h-6 w-6 text-gray-600" />}
                    </button>
                  </div>
                  {formState.channels?.includes('google_chat') && (
                    <input 
                      type="url" 
                      placeholder="Webhook URL"
                      value={formState.channel_config?.google_chat_webhook}
                      onChange={e => setFormState({ 
                        ...formState, 
                        channel_config: { ...formState.channel_config, google_chat_webhook: e.target.value } 
                      })}
                      className="w-full bg-gray-900 border border-green-500/20 rounded p-2 text-sm text-white focus:ring-1 focus:ring-green-500 outline-none"
                    />
                  )}
                </div>

                {/* Browser Push */}
                <div className={`p-4 rounded-xl border transition-all ${formState.channels?.includes('browser_push') ? 'bg-blue-950/10 border-blue-500/30' : 'bg-gray-800 border-gray-700'}`}>
                  <div className="flex items-center justify-between">
                    <div className="flex items-center space-x-2">
                      <Smartphone className={`h-4 w-4 ${formState.channels?.includes('browser_push') ? 'text-blue-400' : 'text-gray-500'}`} />
                      <span className={`text-sm font-bold uppercase tracking-tight ${formState.channels?.includes('browser_push') ? 'text-blue-400' : 'text-gray-500'}`}>Browser Push</span>
                    </div>
                    <button onClick={() => toggleChannel('browser_push')}>
                      {formState.channels?.includes('browser_push') ? <ToggleRight className="h-6 w-6 text-blue-500" /> : <ToggleLeft className="h-6 w-6 text-gray-600" />}
                    </button>
                  </div>
                  <p className="text-[10px] text-gray-500 mt-2 italic">Works even when the tab is closed.</p>
                </div>

                {/* Generic Webhook */}
                <div className={`p-4 rounded-xl border transition-all ${formState.channels?.includes('webhook') ? 'bg-amber-950/10 border-amber-500/30' : 'bg-gray-800 border-gray-700'}`}>
                  <div className="flex items-center justify-between mb-4">
                    <div className="flex items-center space-x-2">
                      <Webhook className={`h-4 w-4 ${formState.channels?.includes('webhook') ? 'text-amber-400' : 'text-gray-500'}`} />
                      <span className={`text-sm font-bold uppercase tracking-tight ${formState.channels?.includes('webhook') ? 'text-amber-400' : 'text-gray-500'}`}>Custom Webhook</span>
                    </div>
                    <button onClick={() => toggleChannel('webhook')}>
                      {formState.channels?.includes('webhook') ? <ToggleRight className="h-6 w-6 text-amber-500" /> : <ToggleLeft className="h-6 w-6 text-gray-600" />}
                    </button>
                  </div>
                  {formState.channels?.includes('webhook') && (
                    <input 
                      type="url" 
                      placeholder="POST URL (Discord, Slack, etc.)"
                      value={formState.channel_config?.webhook_url}
                      onChange={e => setFormState({ 
                         ...formState, 
                         channel_config: { ...formState.channel_config, webhook_url: e.target.value } 
                      })}
                      className="w-full bg-gray-900 border border-amber-500/20 rounded p-2 text-sm text-white focus:ring-1 focus:ring-amber-500 outline-none"
                    />
                  )}
                </div>
             </div>
          </div>
        </div>
      </Modal>
    </div>
  );
};

export default Alerts;