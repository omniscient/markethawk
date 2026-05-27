import React from 'react';
import { AlertTriangle, Zap } from 'lucide-react';
import Button from '../../components/ui/Button';
import Modal from '../../components/ui/Modal';
import { NumberField, ToggleField, SESSION_OPTIONS, DIRECTION_OPTIONS, ENTRY_TYPES } from './components';
import type { TradingStrategy } from '../../api/trading';

export interface ConfigPanelProps {
  isOpen: boolean;
  editingStrategy: TradingStrategy | null;
  stratForm: Partial<TradingStrategy>;
  onStratForm: (form: Partial<TradingStrategy>) => void;
  onSave: () => void;
  onClose: () => void;
  isSaving: boolean;
}

export function ConfigPanel({
  isOpen, editingStrategy, stratForm, onStratForm, onSave, onClose, isSaving,
}: ConfigPanelProps) {
  const toggleSession = (session: string) => {
    const current = stratForm.allowed_sessions ?? [];
    onStratForm({
      ...stratForm,
      allowed_sessions: current.includes(session)
        ? current.filter(s => s !== session)
        : [...current, session],
    });
  };

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title={editingStrategy ? `Edit Strategy — ${editingStrategy.name}` : 'New Trading Strategy'}
      size="xl"
      footer={
        <div className="flex gap-3 justify-end">
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button
            variant="primary"
            loading={isSaving}
            onClick={onSave}
            icon={Zap}
          >
            {editingStrategy ? 'Save Changes' : 'Create Strategy'}
          </Button>
        </div>
      }
    >
      <div className="space-y-6">
        <div className="grid grid-cols-1 gap-4">
          <div>
            <label className="block text-xs text-gray-400 uppercase tracking-wider mb-1.5 font-bold">Strategy Name</label>
            <input
              type="text"
              value={stratForm.name ?? ''}
              onChange={e => onStratForm({ ...stratForm, name: e.target.value })}
              placeholder="e.g. 2R Morning Momentum"
              className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-white focus:outline-none focus:ring-2 focus:ring-financial-blue"
            />
          </div>
          <div>
            <label className="block text-xs text-gray-400 uppercase tracking-wider mb-1.5 font-bold">Description <span className="text-gray-600 normal-case">(optional)</span></label>
            <textarea
              rows={2}
              value={stratForm.description ?? ''}
              onChange={e => onStratForm({ ...stratForm, description: e.target.value })}
              placeholder="What scanner conditions does this strategy trade?"
              className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-white focus:outline-none focus:ring-2 focus:ring-financial-blue resize-none"
            />
          </div>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          <ToggleField
            label="Paper Mode"
            description="No real orders sent"
            value={stratForm.paper_mode ?? true}
            onChange={v => onStratForm({ ...stratForm, paper_mode: v })}
            onColor="text-blue-400"
          />
          <ToggleField
            label="Requires Approval"
            description="Human sign-off before entry"
            value={stratForm.requires_approval ?? false}
            onChange={v => onStratForm({ ...stratForm, requires_approval: v })}
          />
          <ToggleField
            label="Active"
            description="Enabled for new alerts"
            value={stratForm.is_active ?? true}
            onChange={v => onStratForm({ ...stratForm, is_active: v })}
          />
        </div>

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

        <div>
          <p className="text-xs text-gray-400 uppercase tracking-wider font-bold mb-3">Risk & Sizing</p>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
            <NumberField
              label="Risk Per Trade"
              suffix="%"
              value={stratForm.risk_per_trade_pct ?? 1}
              onChange={v => onStratForm({ ...stratForm, risk_per_trade_pct: v })}
              step={0.1}
              min={0.1}
              max={10}
            />
            <NumberField
              label="Max Position"
              prefix="$"
              value={stratForm.max_position_usd ?? ''}
              placeholder="No limit"
              onChange={v => onStratForm({ ...stratForm, max_position_usd: v || undefined })}
              step={1000}
              min={0}
            />
            <NumberField
              label="Max Trades / Day"
              value={stratForm.max_trades_per_day ?? 3}
              onChange={v => onStratForm({ ...stratForm, max_trades_per_day: Math.floor(v) })}
              step={1}
              min={1}
              max={20}
            />
            <NumberField
              label="Max Concurrent"
              value={stratForm.max_concurrent_positions ?? 2}
              onChange={v => onStratForm({ ...stratForm, max_concurrent_positions: Math.floor(v) })}
              step={1}
              min={1}
              max={10}
            />
          </div>
        </div>

        <div>
          <p className="text-xs text-gray-400 uppercase tracking-wider font-bold mb-3">Stop & Target</p>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
            <NumberField
              label="Stop Loss"
              suffix="%"
              value={stratForm.stop_pct ?? 2}
              onChange={v => onStratForm({ ...stratForm, stop_pct: v })}
              step={0.1}
              min={0.1}
              max={20}
            />
            <NumberField
              label="Risk : Reward"
              suffix="R"
              value={stratForm.risk_reward_ratio ?? 2}
              onChange={v => onStratForm({ ...stratForm, risk_reward_ratio: v })}
              step={0.1}
              min={0.5}
              max={10}
            />
            <NumberField
              label="Max Slippage"
              suffix="%"
              value={stratForm.max_slippage_pct ?? 0.5}
              onChange={v => onStratForm({ ...stratForm, max_slippage_pct: v })}
              step={0.1}
              min={0}
              max={5}
            />
            <div className="bg-gray-800/50 rounded-lg border border-gray-700/50 px-3 py-2 flex flex-col justify-center">
              <span className="text-xs text-gray-500 uppercase tracking-wider font-bold mb-1">Implied Target</span>
              <span className="text-lg font-black text-green-400">
                {((stratForm.stop_pct ?? 2) * (stratForm.risk_reward_ratio ?? 2)).toFixed(1)}%
              </span>
              <span className="text-xs text-gray-600">from entry</span>
            </div>
          </div>
        </div>

        <div>
          <p className="text-xs text-gray-400 uppercase tracking-wider font-bold mb-3">Entry</p>
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-4">
            <div>
              <label className="block text-xs text-gray-400 mb-1.5 font-semibold">Entry Type</label>
              <select
                value={stratForm.entry_type ?? 'market'}
                onChange={e => onStratForm({ ...stratForm, entry_type: e.target.value as any })}
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
                onChange={v => onStratForm({ ...stratForm, limit_offset_pct: v })}
                step={0.05}
                min={-5}
                max={5}
              />
            )}
            <div>
              <label className="block text-xs text-gray-400 mb-1.5 font-semibold">Direction</label>
              <select
                value={stratForm.direction ?? 'long_only'}
                onChange={e => onStratForm({ ...stratForm, direction: e.target.value as any })}
                className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-white focus:ring-2 focus:ring-financial-blue outline-none"
              >
                {DIRECTION_OPTIONS.map(d => <option key={d.id} value={d.id}>{d.label}</option>)}
              </select>
            </div>
          </div>
        </div>

        <div>
          <p className="text-xs text-gray-400 uppercase tracking-wider font-bold mb-3">Eligible Sessions</p>
          <div className="flex gap-2 flex-wrap">
            {SESSION_OPTIONS.map(s => {
              const active = (stratForm.allowed_sessions ?? []).includes(s.id);
              return (
                <button
                  key={s.id}
                  onClick={() => toggleSession(s.id)}
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
  );
}
