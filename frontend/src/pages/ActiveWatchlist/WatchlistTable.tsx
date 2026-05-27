import React, { useState } from 'react';
import { Link } from 'react-router-dom';
import { Edit2, Check, X, ExternalLink, Loader2, Trash2 } from 'lucide-react';
import { useRemoveFromWatchlist, useUpdateWatchlistNotes, WatchlistItem } from '../../api/watchlist';
import type { SymbolLiveData } from '../../hooks/useWatchlistLive';
import { AlertBadge } from './AlertBadges';

function PriceCell({ live }: { live: SymbolLiveData | undefined }) {
  if (!live || live.price === 0) {
    return <span className="text-gray-600 text-sm font-mono">—</span>;
  }

  const isStale = Date.now() - live.lastTickAt > 15_000;
  const pct = live.priceChangePct;
  const pctColor =
    pct === null ? 'text-gray-400'
    : pct > 0 ? 'text-positive'
    : pct < 0 ? 'text-negative'
    : 'text-gray-400';

  return (
    <div className="flex flex-col">
      <span className={`font-mono font-semibold text-sm ${isStale ? 'text-gray-500' : 'text-financial-light'}`}>
        {live.price.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
      </span>
      {pct !== null && (
        <span className={`text-xs font-mono ${pctColor}`}>
          {pct >= 0 ? '+' : ''}{pct.toFixed(2)}%
        </span>
      )}
    </div>
  );
}

function SessionCell({ live }: { live: SymbolLiveData | undefined }) {
  if (!live?.session || live.session === 'closed') {
    return <span className="text-gray-600 text-xs">—</span>;
  }

  const sessionLabel: Record<string, string> = { pre: 'PRE', regular: 'REG', post: 'POST' };
  const sessionColor: Record<string, string> = {
    pre: 'text-yellow-400',
    regular: 'text-positive',
    post: 'text-blue-400',
  };

  const vol = live.sessionVolume;

  return (
    <div className="flex flex-col">
      <span className={`text-xs font-mono font-semibold ${sessionColor[live.session] ?? 'text-gray-400'}`}>
        {sessionLabel[live.session] ?? live.session}
      </span>
      {vol !== null && (
        <span className="text-xs text-gray-500 font-mono">
          {vol >= 1_000_000
            ? `${(vol / 1_000_000).toFixed(1)}M`
            : vol >= 1_000
            ? `${(vol / 1_000).toFixed(0)}K`
            : vol}
        </span>
      )}
    </div>
  );
}

function WatchlistRow({ item, live }: { item: WatchlistItem; live: SymbolLiveData | undefined }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(item.notes ?? '');
  const remove = useRemoveFromWatchlist();
  const updateNotes = useUpdateWatchlistNotes();

  const saveNotes = () => {
    updateNotes.mutate(
      { symbol: item.symbol, notes: draft.trim() || null },
      { onSuccess: () => setEditing(false) }
    );
  };

  const cancelEdit = () => {
    setDraft(item.notes ?? '');
    setEditing(false);
  };

  const addedDate = new Date(item.added_at).toLocaleDateString(undefined, {
    month: 'short', day: 'numeric', year: 'numeric',
  });
  const isLive = live && live.price > 0 && Date.now() - live.lastTickAt < 15_000;

  return (
    <tr className="border-b border-gray-700 hover:bg-gray-800/40 transition-colors">
      <td className="py-3 px-4">
        <div className="flex items-center gap-2">
          {isLive && <span className="w-1.5 h-1.5 rounded-full bg-positive animate-pulse flex-none" title="Live data" />}
          <span className="font-mono font-semibold text-financial-light text-sm">{item.symbol}</span>
          <Link to={`/stock/${item.symbol}`} className="text-gray-500 hover:text-financial-blue transition-colors" title="Open stock detail">
            <ExternalLink className="h-3.5 w-3.5" />
          </Link>
          <AlertBadge alert={live?.alert ?? null} />
        </div>
      </td>
      <td className="py-3 px-4"><PriceCell live={live} /></td>
      <td className="py-3 px-4"><SessionCell live={live} /></td>
      <td className="py-3 px-4">
        <span className={`text-xs font-mono font-semibold px-1.5 py-0.5 rounded ${item.security_type === 'FUT' ? 'bg-purple-900/50 text-purple-300' : 'bg-blue-900/40 text-blue-300'}`}>
          {item.security_type}
        </span>
        {item.exchange && <span className="ml-1.5 text-xs text-gray-500 font-mono">{item.exchange}</span>}
      </td>
      <td className="py-3 px-4">
        {editing ? (
          <div className="flex items-center gap-2">
            <input
              autoFocus
              type="text"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') saveNotes(); if (e.key === 'Escape') cancelEdit(); }}
              maxLength={500}
              className="flex-1 px-2 py-1 bg-gray-700 border border-gray-500 rounded text-sm text-financial-light focus:outline-none focus:border-financial-blue"
            />
            <button onClick={saveNotes} disabled={updateNotes.isPending} className="text-positive hover:text-green-400 disabled:opacity-50" title="Save">
              {updateNotes.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Check className="h-4 w-4" />}
            </button>
            <button onClick={cancelEdit} className="text-gray-400 hover:text-white" title="Cancel">
              <X className="h-4 w-4" />
            </button>
          </div>
        ) : (
          <div className="flex items-center gap-2 group">
            <span className="text-sm text-gray-400 italic">
              {item.notes || <span className="text-gray-600">—</span>}
            </span>
            <button
              onClick={() => { setDraft(item.notes ?? ''); setEditing(true); }}
              className="text-gray-600 hover:text-gray-300 opacity-0 group-hover:opacity-100 transition-opacity"
              title="Edit notes"
            >
              <Edit2 className="h-3.5 w-3.5" />
            </button>
          </div>
        )}
      </td>
      <td className="py-3 px-4 text-sm text-gray-500 whitespace-nowrap">{addedDate}</td>
      <td className="py-3 px-4 text-right">
        <button
          onClick={() => remove.mutate(item.symbol)}
          disabled={remove.isPending}
          className="text-gray-600 hover:text-red-400 disabled:opacity-50 transition-colors"
          title={`Remove ${item.symbol}`}
        >
          {remove.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Trash2 className="h-4 w-4" />}
        </button>
      </td>
    </tr>
  );
}

export interface WatchlistTableProps {
  items: WatchlistItem[];
  liveData: Record<string, SymbolLiveData>;
}

export function WatchlistTable({ items, liveData }: WatchlistTableProps) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full">
        <thead>
          <tr className="border-b border-gray-700">
            {['Symbol', 'Price', 'Session', 'Type', 'Notes', 'Added', ''].map((h, i) => (
              <th key={i} className={`${h ? 'text-left' : ''} py-3 px-4 text-xs font-semibold text-gray-400 uppercase tracking-wider`}>
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {items.map((item) => (
            <WatchlistRow key={item.symbol} item={item} live={liveData[item.symbol]} />
          ))}
        </tbody>
      </table>
    </div>
  );
}
