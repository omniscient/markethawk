import React from 'react';
import {
  ToggleLeft, ToggleRight, Mail, Smartphone, Webhook, MessageSquare,
  Bot, ChevronRight, AlertCircle,
} from 'lucide-react';
import Button from '../../components/ui/Button';
import Modal from '../../components/ui/Modal';
import type { AlertRule } from '../../api/alerts';
import type { TradingStrategy } from '../../api/trading';

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

export interface AlertRuleModalProps {
  isOpen: boolean;
  editingRule: Partial<AlertRule> | null;
  formState: Partial<AlertRule>;
  onFormState: (s: Partial<AlertRule>) => void;
  onSave: () => void;
  onClose: () => void;
  isSaving: boolean;
  strategies: TradingStrategy[];
}

export function AlertRuleModal({
  isOpen, editingRule, formState, onFormState, onSave, onClose, isSaving, strategies,
}: AlertRuleModalProps) {
  type Channel = 'email' | 'browser_push' | 'google_chat' | 'webhook';

  const toggleChannel = (channel: Channel) => {
    const current = formState.channels || [];
    onFormState({
      ...formState,
      channels: current.includes(channel) ? current.filter(c => c !== channel) : [...current, channel],
    });
  };

  const toggleScannerType = (type: string) => {
    const current = formState.scanner_types || [];
    onFormState({
      ...formState,
      scanner_types: current.includes(type) ? current.filter(t => t !== type) : [...current, type],
    });
  };

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title={editingRule?.id ? 'Edit Alert Rule' : 'Create New Alert Rule'}
      size="lg"
      footer={(
        <>
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button variant="primary" onClick={onSave} loading={isSaving}>
            {editingRule?.id ? 'Save Changes' : 'Create Rule'}
          </Button>
        </>
      )}
    >
      <div className="space-y-6">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          <div className="space-y-2">
            <label className="text-xs font-bold text-gray-500 uppercase tracking-widest">Rule Name</label>
            <input
              type="text"
              placeholder="Spike Alert, Oversold, etc."
              value={formState.name}
              onChange={e => onFormState({ ...formState, name: e.target.value })}
              className="w-full bg-gray-800 border-gray-700 border rounded-lg p-3 text-white focus:ring-2 focus:ring-blue-500 outline-none transition-all"
            />
          </div>
          <div className="space-y-2">
            <label className="text-xs font-bold text-gray-500 uppercase tracking-widest">Minimum Severity</label>
            <div className="grid grid-cols-2 gap-2">
              {SEVERITIES.map(sev => (
                <button
                  key={sev.id}
                  onClick={() => onFormState({ ...formState, severity_filter: sev.id as any })}
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
              onChange={e => onFormState({ ...formState, cooldown_minutes: parseInt(e.target.value) })}
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
                onClick={() => onFormState({ ...formState, is_active: !formState.is_active })}
                className="transition-all outline-none"
              >
                {formState.is_active
                  ? <ToggleRight className="h-6 w-6 text-blue-500" />
                  : <ToggleLeft className="h-6 w-6 text-gray-600" />}
              </button>
              <span className="text-sm font-medium text-white">{formState.is_active ? 'Enabled' : 'Disabled'}</span>
            </div>
          </div>
        </div>

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
              onClick={() => onFormState({ ...formState, scanner_types: [] })}
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

        <div className="space-y-4 pt-4 border-t border-gray-800">
          <label className="text-xs font-bold text-gray-500 uppercase tracking-widest">Delivery Channels</label>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {[
              { id: 'email' as Channel, label: 'Email', icon: Mail, color: 'purple', inputType: 'email', placeholder: 'address@example.com', field: 'email' as const },
              { id: 'google_chat' as Channel, label: 'Google Chat', icon: MessageSquare, color: 'green', inputType: 'url', placeholder: 'Webhook URL', field: 'google_chat_webhook' as const },
            ].map(ch => (
              <div key={ch.id} className={`p-4 rounded-xl border transition-all ${formState.channels?.includes(ch.id) ? `bg-${ch.color}-950/10 border-${ch.color}-500/30` : 'bg-gray-800 border-gray-700'}`}>
                <div className="flex items-center justify-between mb-4">
                  <div className="flex items-center space-x-2">
                    <ch.icon className={`h-4 w-4 ${formState.channels?.includes(ch.id) ? `text-${ch.color}-400` : 'text-gray-500'}`} />
                    <span className={`text-sm font-bold uppercase tracking-tight ${formState.channels?.includes(ch.id) ? `text-${ch.color}-400` : 'text-gray-500'}`}>{ch.label}</span>
                  </div>
                  <button onClick={() => toggleChannel(ch.id)}>
                    {formState.channels?.includes(ch.id) ? <ToggleRight className={`h-6 w-6 text-${ch.color}-500`} /> : <ToggleLeft className="h-6 w-6 text-gray-600" />}
                  </button>
                </div>
                {formState.channels?.includes(ch.id) && (
                  <input
                    type={ch.inputType}
                    placeholder={ch.placeholder}
                    value={(formState.channel_config as any)?.[ch.field] ?? ''}
                    onChange={e => onFormState({ ...formState, channel_config: { ...formState.channel_config, [ch.field]: e.target.value } })}
                    className={`w-full bg-gray-900 border border-${ch.color}-500/20 rounded p-2 text-sm text-white focus:ring-1 focus:ring-${ch.color}-500 outline-none`}
                  />
                )}
              </div>
            ))}

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
                  value={formState.channel_config?.webhook_url ?? ''}
                  onChange={e => onFormState({ ...formState, channel_config: { ...formState.channel_config, webhook_url: e.target.value } })}
                  className="w-full bg-gray-900 border border-amber-500/20 rounded p-2 text-sm text-white focus:ring-1 focus:ring-amber-500 outline-none"
                />
              )}
            </div>
          </div>
        </div>

        <div className="space-y-4 pt-4 border-t border-gray-800">
          <div className="flex items-center justify-between">
            <label className="text-xs font-bold text-gray-500 uppercase tracking-widest flex items-center gap-1.5">
              <Bot className="h-3.5 w-3.5" />
              Auto-Trading
            </label>
            <a href="/trading" className="text-xs text-financial-blue hover:text-blue-300 flex items-center gap-0.5 transition-colors">
              Manage strategies <ChevronRight className="h-3 w-3" />
            </a>
          </div>

          <div className={`flex items-center justify-between p-4 rounded-xl border transition-all ${
            formState.auto_trade ? 'bg-financial-blue/5 border-financial-blue/30' : 'bg-gray-800 border-gray-700'
          }`}>
            <div>
              <p className={`text-sm font-bold ${formState.auto_trade ? 'text-white' : 'text-gray-400'}`}>Enable Auto-Trading</p>
              <p className="text-xs text-gray-500 mt-0.5">Automatically enter bracket orders when this rule fires.</p>
            </div>
            <button onClick={() => onFormState({ ...formState, auto_trade: !formState.auto_trade, trading_strategy_id: formState.auto_trade ? null : formState.trading_strategy_id })}>
              {formState.auto_trade ? <ToggleRight className="h-7 w-7 text-financial-blue" /> : <ToggleLeft className="h-7 w-7 text-gray-600" />}
            </button>
          </div>

          {formState.auto_trade && (
            <div className="space-y-2 animate-fade-in">
              <label className="text-xs font-bold text-gray-500 uppercase tracking-widest">Trading Strategy</label>
              {!strategies?.length ? (
                <div className="flex items-center gap-2 p-3 bg-yellow-500/10 border border-yellow-500/20 rounded-lg text-yellow-300 text-sm">
                  <AlertCircle className="h-4 w-4 flex-shrink-0" />
                  <span>No active strategies found.{' '}
                    <a href="/trading" className="underline hover:text-yellow-200">Create one first.</a>
                  </span>
                </div>
              ) : (
                <select
                  value={formState.trading_strategy_id ?? ''}
                  onChange={e => onFormState({ ...formState, trading_strategy_id: e.target.value ? parseInt(e.target.value) : null })}
                  className="w-full bg-gray-800 border border-gray-700 rounded-lg p-3 text-white focus:ring-2 focus:ring-financial-blue outline-none appearance-none"
                >
                  <option value="">— Select a strategy —</option>
                  {strategies.map(s => (
                    <option key={s.id} value={s.id}>
                      {s.name}{s.paper_mode ? ' (Paper)' : ' (Live)'}{s.requires_approval ? ' · Requires Approval' : ''}
                    </option>
                  ))}
                </select>
              )}
              {formState.trading_strategy_id && strategies && (() => {
                const s = strategies.find(x => x.id === formState.trading_strategy_id);
                if (!s) return null;
                return (
                  <div className="grid grid-cols-4 gap-2 text-center text-xs">
                    {[
                      { label: 'Stop', value: `${s.stop_pct}%` },
                      { label: 'R:R', value: `${s.risk_reward_ratio}:1` },
                      { label: 'Risk/Trade', value: `${s.risk_per_trade_pct}%` },
                      { label: 'Mode', value: s.paper_mode ? 'Paper' : 'Live' },
                    ].map(item => (
                      <div key={item.label} className="bg-gray-800/80 rounded border border-gray-700 py-2">
                        <div className="text-gray-500 font-bold uppercase tracking-wide">{item.label}</div>
                        <div className={`font-black mt-0.5 ${item.label === 'Mode' ? (s.paper_mode ? 'text-blue-400' : 'text-orange-400') : 'text-white'}`}>{item.value}</div>
                      </div>
                    ))}
                  </div>
                );
              })()}
            </div>
          )}
        </div>
      </div>
    </Modal>
  );
}
