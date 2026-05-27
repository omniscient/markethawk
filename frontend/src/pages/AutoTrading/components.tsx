import React from 'react';
import {
  Clock,
  Loader2,
  Activity,
  CheckCircle,
  Ban,
  XCircle,
  AlertTriangle,
  TrendingUp,
  TrendingDown,
  ToggleRight,
  ToggleLeft,
  Edit2,
  Trash2,
} from 'lucide-react';
import type { TradingStrategy, AutoTradeOrder } from '../../api/trading';

// ── Constants ─────────────────────────────────────────────────────────────────

export const SESSION_OPTIONS = [
  { id: 'pre', label: 'Pre-Market' },
  { id: 'regular', label: 'Regular' },
  { id: 'post', label: 'After-Hours' },
];

export const DIRECTION_OPTIONS = [
  { id: 'long_only', label: 'Long Only' },
  { id: 'short_only', label: 'Short Only' },
  { id: 'both', label: 'Both' },
];

export const ENTRY_TYPES = [
  { id: 'market', label: 'Market' },
  { id: 'limit', label: 'Limit' },
];

export const STATUS_CONFIG: Record<string, { label: string; color: string; icon: React.ElementType }> = {
  pending_approval: { label: 'Needs Approval', color: 'text-yellow-400 bg-yellow-400/10 border-yellow-400/20', icon: Clock },
  pending:          { label: 'Pending',         color: 'text-blue-400 bg-blue-400/10 border-blue-400/20',     icon: Clock },
  submitted:        { label: 'Submitted',        color: 'text-blue-400 bg-blue-400/10 border-blue-400/20',     icon: Loader2 },
  open:             { label: 'Open',             color: 'text-green-400 bg-green-400/10 border-green-400/20',  icon: Activity },
  closed:           { label: 'Closed',           color: 'text-gray-400 bg-gray-400/10 border-gray-400/20',     icon: CheckCircle },
  cancelled:        { label: 'Cancelled',        color: 'text-gray-500 bg-gray-500/10 border-gray-500/20',     icon: Ban },
  rejected:         { label: 'Rejected',         color: 'text-red-400 bg-red-400/10 border-red-400/20',        icon: XCircle },
  error:            { label: 'Error',            color: 'text-red-400 bg-red-400/10 border-red-400/20',        icon: AlertTriangle },
};

export const DEFAULT_STRATEGY: Partial<TradingStrategy> = {
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

export const fmt = (n: number | null | undefined, decimals = 2, prefix = '') =>
  n == null ? '—' : `${prefix}${n.toFixed(decimals)}`;

export const fmtUSD = (n: number | null | undefined) =>
  n == null ? '—' : `$${n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

export function pnlColor(n: number | null | undefined) {
  if (n == null) return 'text-gray-400';
  return n >= 0 ? 'text-green-400' : 'text-red-400';
}

// ── Sub-components ─────────────────────────────────────────────────────────────

export const StatusBadge: React.FC<{ status: string }> = ({ status }) => {
  const cfg = STATUS_CONFIG[status] ?? { label: status, color: 'text-gray-400 bg-gray-400/10 border-gray-400/20', icon: Clock };
  const Icon = cfg.icon;
  return (
    <span className={`inline-flex items-center gap-1 text-xs font-bold uppercase px-2 py-0.5 rounded border ${cfg.color}`}>
      <Icon className="h-3 w-3" />
      {cfg.label}
    </span>
  );
};

export const StrategyRow: React.FC<{
  strategy: TradingStrategy;
  onEdit: () => void;
  onDelete: () => void;
  onToggle: () => void;
}> = ({ strategy: s, onEdit, onDelete, onToggle }) => (
  <div className="flex items-center gap-4 py-4 px-4 group hover:bg-gray-800/30 transition-colors">
    <button onClick={onToggle} className="flex-shrink-0">
      {s.is_active
        ? <ToggleRight className="h-7 w-7 text-blue-500" />
        : <ToggleLeft className="h-7 w-7 text-gray-600" />}
    </button>
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
    <div className="hidden lg:flex items-center gap-6 text-center">
      <StratStat label="Stop" value={`${s.stop_pct}%`} />
      <StratStat label="R:R" value={`${s.risk_reward_ratio}:1`} />
      <StratStat label="Risk/Trade" value={`${s.risk_per_trade_pct}%`} />
      <StratStat label="Entry" value={s.entry_type} />
      <StratStat label="Direction" value={s.direction.replace('_', ' ')} />
    </div>
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

export const StratStat: React.FC<{ label: string; value: string }> = ({ label, value }) => (
  <div>
    <div className="text-xs text-gray-500 uppercase font-bold">{label}</div>
    <div className="text-sm font-semibold text-white capitalize">{value}</div>
  </div>
);

export const OrderRow: React.FC<{
  order: AutoTradeOrder;
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

export const AccountMetric: React.FC<{ label: string; value: string }> = ({ label, value }) => (
  <div className="bg-gray-800/50 rounded-lg border border-gray-700/50 px-4 py-3 text-center">
    <div className="text-xs text-gray-500 uppercase tracking-wider font-bold mb-1">{label}</div>
    <div className="text-xl font-black text-white">{value}</div>
  </div>
);

export const StatRow: React.FC<{ label: string; value: string; valueClass?: string }> = ({
  label, value, valueClass = 'text-white'
}) => (
  <div className="flex items-center justify-between py-1.5">
    <span className="text-sm text-gray-400">{label}</span>
    <span className={`text-sm font-bold ${valueClass}`}>{value}</span>
  </div>
);

export const NumberField: React.FC<{
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

export const ToggleField: React.FC<{
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
