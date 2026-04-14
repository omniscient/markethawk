import React, { useEffect, useRef, useState } from 'react';
import {
  Eye,
  Plus,
  Trash2,
  Edit2,
  Check,
  X,
  AlertCircle,
  Loader2,
  ExternalLink,
  Wifi,
  WifiOff,
} from 'lucide-react';
import { Link } from 'react-router-dom';
import Card from '../components/ui/Card';
import Button from '../components/ui/Button';
import {
  useWatchlist,
  useAddToWatchlist,
  useRemoveFromWatchlist,
  useUpdateWatchlistNotes,
  WatchlistItem,
} from '../api/watchlist';

const SOFT_LIMIT = 50;

// ── Live data types ────────────────────────────────────────────────────────

interface LiveTick {
  type: 'tick';
  symbol: string;
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  wap: number;
}

interface LiveMinuteBar {
  type: 'minute_bar';
  symbol: string;
  minute_ts: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  vwap: number;
  session: string;
  session_volume: number;
  minutes_elapsed: number;
  prior_close: number;
  price_change_pct: number;
}

interface LiveQuote {
  type: 'quote';
  symbol: string;
  last: number;
  bid: number | null;
  ask: number | null;
  time: number;
}

interface LiveAlert {
  type: 'alert';
  symbol: string;
  scanner_type: string;
  summary: string;
  severity: string;
  indicators: Record<string, unknown>;
  timestamp: string;
}

type LiveMessage = LiveTick | LiveQuote | LiveMinuteBar | LiveAlert;

interface SymbolLiveData {
  price: number;
  priceChangePct: number | null;  // null until we have a minute bar
  session: string | null;
  sessionVolume: number | null;
  lastTickAt: number;             // Date.now()
  alert: LiveAlert | null;
}

// ── WebSocket hook ─────────────────────────────────────────────────────────

function useWatchlistLive() {
  const [liveData, setLiveData] = useState<Record<string, SymbolLiveData>>({});
  const [connected, setConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    let destroyed = false;

    function connect() {
      if (destroyed) return;

      const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws';
      const ws = new WebSocket(`${protocol}://${window.location.host}/api/live/ws/watchlist`);
      wsRef.current = ws;

      ws.onopen = () => {
        if (destroyed) {
          // Component unmounted while the socket was still connecting — close cleanly now.
          ws.close();
          return;
        }
        setConnected(true);
      };

      ws.onmessage = (evt) => {
        if (destroyed) return;
        try {
          const msg: LiveMessage = JSON.parse(evt.data);
          if (msg.type === 'quote') {
            // reqMktData — fires on every last-price change (sub-second)
            setLiveData((prev) => ({
              ...prev,
              [msg.symbol]: {
                ...prev[msg.symbol],
                price: msg.last,
                lastTickAt: Date.now(),
                alert: prev[msg.symbol]?.alert ?? null,
                priceChangePct: prev[msg.symbol]?.priceChangePct ?? null,
                session: prev[msg.symbol]?.session ?? null,
                sessionVolume: prev[msg.symbol]?.sessionVolume ?? null,
              },
            }));
          } else if (msg.type === 'tick') {
            // reqRealTimeBars 5s bar — fallback price if no quote yet
            setLiveData((prev) => ({
              ...prev,
              [msg.symbol]: {
                ...prev[msg.symbol],
                price: prev[msg.symbol]?.price || msg.close,
                lastTickAt: Date.now(),
                alert: prev[msg.symbol]?.alert ?? null,
                priceChangePct: prev[msg.symbol]?.priceChangePct ?? null,
                session: prev[msg.symbol]?.session ?? null,
                sessionVolume: prev[msg.symbol]?.sessionVolume ?? null,
              },
            }));
          } else if (msg.type === 'minute_bar') {
            setLiveData((prev) => ({
              ...prev,
              [msg.symbol]: {
                ...prev[msg.symbol],
                price: msg.close,
                priceChangePct: msg.price_change_pct,
                session: msg.session,
                sessionVolume: msg.session_volume,
                lastTickAt: Date.now(),
                alert: prev[msg.symbol]?.alert ?? null,
              },
            }));
          } else if (msg.type === 'alert') {
            setLiveData((prev) => ({
              ...prev,
              [msg.symbol]: {
                ...prev[msg.symbol],
                alert: msg,
                lastTickAt: prev[msg.symbol]?.lastTickAt ?? Date.now(),
                price: prev[msg.symbol]?.price ?? 0,
                priceChangePct: prev[msg.symbol]?.priceChangePct ?? null,
                session: prev[msg.symbol]?.session ?? null,
                sessionVolume: prev[msg.symbol]?.sessionVolume ?? null,
              },
            }));
          }
        } catch {
          // ignore parse errors
        }
      };

      ws.onclose = () => {
        if (destroyed) return;
        setConnected(false);
        // Reconnect after 3 s
        reconnectTimer.current = setTimeout(connect, 3000);
      };

      ws.onerror = () => ws.close();
    }

    connect();

    return () => {
      destroyed = true;
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current);
      // Only close if the handshake is done — closing a CONNECTING socket
      // triggers a spurious browser warning. onopen checks `destroyed` and
      // will close it cleanly once the connection finishes.
      const ws = wsRef.current;
      if (ws && ws.readyState !== WebSocket.CONNECTING) {
        ws.close();
      }
    };
  }, []);

  return { liveData, connected };
}

// ── Add Symbol Form ────────────────────────────────────────────────────────

const INPUT_CLS =
  'px-3 py-2 bg-gray-800 border border-gray-600 rounded-lg text-financial-light placeholder-gray-500 focus:outline-none focus:border-financial-blue text-sm';

function AddSymbolForm() {
  const [symbol, setSymbol] = useState('');
  const [securityType, setSecurityType] = useState<'STK' | 'FUT'>('STK');
  const [exchange, setExchange] = useState('');
  const [notes, setNotes] = useState('');
  const [error, setError] = useState<string | null>(null);
  const add = useAddToWatchlist();

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = symbol.trim().toUpperCase();
    if (!trimmed) return;
    setError(null);

    add.mutate(
      {
        symbol: trimmed,
        security_type: securityType,
        exchange: exchange.trim().toUpperCase() || undefined,
        notes: notes.trim() || undefined,
      },
      {
        onSuccess: () => {
          setSymbol('');
          setExchange('');
          setNotes('');
        },
        onError: (err: any) => {
          setError(err?.response?.data?.detail ?? 'Failed to add symbol.');
        },
      }
    );
  };

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-2">
      <div className="flex flex-wrap gap-2 items-end">
        <input
          type="text"
          value={symbol}
          onChange={(e) => setSymbol(e.target.value.toUpperCase())}
          placeholder="Symbol (e.g. NVDA)"
          maxLength={20}
          className={`w-36 ${INPUT_CLS} font-mono uppercase`}
        />
        <select
          value={securityType}
          onChange={(e) => {
            const val = e.target.value as 'STK' | 'FUT';
            setSecurityType(val);
            if (val === 'FUT' && !exchange) setExchange('CME');
            if (val === 'STK') setExchange('');
          }}
          className={`w-24 ${INPUT_CLS} cursor-pointer`}
        >
          <option value="STK">STK</option>
          <option value="FUT">FUT</option>
        </select>
        <input
          type="text"
          value={exchange}
          onChange={(e) => setExchange(e.target.value.toUpperCase())}
          placeholder={securityType === 'FUT' ? 'Exchange (e.g. CME)' : 'Exchange (opt.)'}
          maxLength={20}
          className={`w-40 ${INPUT_CLS} font-mono uppercase`}
        />
        <input
          type="text"
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          placeholder="Notes (optional)"
          maxLength={500}
          className={`flex-1 min-w-40 ${INPUT_CLS}`}
        />
        <Button
          type="submit"
          icon={add.isPending ? undefined : Plus}
          loading={add.isPending}
          disabled={!symbol.trim()}
        >
          Add
        </Button>
      </div>
      {error && (
        <p className="text-sm text-red-400 flex items-center gap-1">
          <AlertCircle className="h-4 w-4 flex-none" />
          {error}
        </p>
      )}
    </form>
  );
}

// ── Price cell ─────────────────────────────────────────────────────────────

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

// ── Session cell ───────────────────────────────────────────────────────────

function SessionCell({ live }: { live: SymbolLiveData | undefined }) {
  if (!live?.session || live.session === 'closed') {
    return <span className="text-gray-600 text-xs">—</span>;
  }

  const sessionLabel: Record<string, string> = {
    pre: 'PRE',
    regular: 'REG',
    post: 'POST',
  };

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

// ── Alert badge ────────────────────────────────────────────────────────────

function AlertBadge({ alert }: { alert: LiveAlert | null }) {
  if (!alert) return null;

  const age = Date.now() - new Date(alert.timestamp).getTime();
  if (age > 3_600_000) return null; // hide alerts older than 1 hour

  const color =
    alert.severity === 'high' ? 'bg-red-900/60 text-red-300 border-red-700'
    : alert.severity === 'medium' ? 'bg-yellow-900/50 text-yellow-300 border-yellow-700'
    : 'bg-gray-800 text-gray-400 border-gray-600';

  return (
    <span className={`inline-block text-xs px-1.5 py-0.5 rounded border ${color}`} title={alert.summary}>
      {alert.scanner_type === 'live_volume_spike' ? 'VOL' : 'MOVE'}
    </span>
  );
}

// ── Watchlist Row ──────────────────────────────────────────────────────────

function WatchlistRow({
  item,
  live,
}: {
  item: WatchlistItem;
  live: SymbolLiveData | undefined;
}) {
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
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  });

  const isLive = live && live.price > 0 && Date.now() - live.lastTickAt < 15_000;

  return (
    <tr className="border-b border-gray-700 hover:bg-gray-800/40 transition-colors">
      {/* Symbol */}
      <td className="py-3 px-4">
        <div className="flex items-center gap-2">
          {isLive && (
            <span className="w-1.5 h-1.5 rounded-full bg-positive animate-pulse flex-none" title="Live data" />
          )}
          <span className="font-mono font-semibold text-financial-light text-sm">
            {item.symbol}
          </span>
          <Link
            to={`/stock/${item.symbol}`}
            className="text-gray-500 hover:text-financial-blue transition-colors"
            title="Open stock detail"
          >
            <ExternalLink className="h-3.5 w-3.5" />
          </Link>
          <AlertBadge alert={live?.alert ?? null} />
        </div>
      </td>

      {/* Price + change % */}
      <td className="py-3 px-4">
        <PriceCell live={live} />
      </td>

      {/* Session + volume */}
      <td className="py-3 px-4">
        <SessionCell live={live} />
      </td>

      {/* Type / Exchange */}
      <td className="py-3 px-4">
        <span
          className={`text-xs font-mono font-semibold px-1.5 py-0.5 rounded ${
            item.security_type === 'FUT'
              ? 'bg-purple-900/50 text-purple-300'
              : 'bg-blue-900/40 text-blue-300'
          }`}
        >
          {item.security_type}
        </span>
        {item.exchange && (
          <span className="ml-1.5 text-xs text-gray-500 font-mono">{item.exchange}</span>
        )}
      </td>

      {/* Notes */}
      <td className="py-3 px-4">
        {editing ? (
          <div className="flex items-center gap-2">
            <input
              autoFocus
              type="text"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') saveNotes();
                if (e.key === 'Escape') cancelEdit();
              }}
              maxLength={500}
              className="flex-1 px-2 py-1 bg-gray-700 border border-gray-500 rounded text-sm text-financial-light focus:outline-none focus:border-financial-blue"
            />
            <button
              onClick={saveNotes}
              disabled={updateNotes.isPending}
              className="text-positive hover:text-green-400 disabled:opacity-50"
              title="Save"
            >
              {updateNotes.isPending ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Check className="h-4 w-4" />
              )}
            </button>
            <button
              onClick={cancelEdit}
              className="text-gray-400 hover:text-white"
              title="Cancel"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        ) : (
          <div className="flex items-center gap-2 group">
            <span className="text-sm text-gray-400 italic">
              {item.notes || <span className="text-gray-600">—</span>}
            </span>
            <button
              onClick={() => {
                setDraft(item.notes ?? '');
                setEditing(true);
              }}
              className="text-gray-600 hover:text-gray-300 opacity-0 group-hover:opacity-100 transition-opacity"
              title="Edit notes"
            >
              <Edit2 className="h-3.5 w-3.5" />
            </button>
          </div>
        )}
      </td>

      {/* Added */}
      <td className="py-3 px-4 text-sm text-gray-500 whitespace-nowrap">{addedDate}</td>

      {/* Remove */}
      <td className="py-3 px-4 text-right">
        <button
          onClick={() => remove.mutate(item.symbol)}
          disabled={remove.isPending}
          className="text-gray-600 hover:text-red-400 disabled:opacity-50 transition-colors"
          title={`Remove ${item.symbol}`}
        >
          {remove.isPending ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Trash2 className="h-4 w-4" />
          )}
        </button>
      </td>
    </tr>
  );
}

// ── Page ───────────────────────────────────────────────────────────────────

export default function ActiveWatchlist() {
  const { data: items = [], isLoading, isError } = useWatchlist();
  const { liveData, connected } = useWatchlistLive();

  const count = items.length;
  const atLimit = count >= SOFT_LIMIT;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-financial-light flex items-center gap-2">
            <Eye className="h-6 w-6 text-financial-blue" />
            Active Watchlist
          </h1>
          <p className="text-sm text-gray-400 mt-1">
            Symbols under live observation. Add them manually; remove when done.
          </p>
        </div>
        <div className="flex items-center gap-6">
          {/* Live connection status */}
          <div className="flex items-center gap-1.5 text-xs">
            {connected ? (
              <>
                <Wifi className="h-3.5 w-3.5 text-positive" />
                <span className="text-positive">Live</span>
              </>
            ) : (
              <>
                <WifiOff className="h-3.5 w-3.5 text-gray-500" />
                <span className="text-gray-500">Connecting…</span>
              </>
            )}
          </div>

          {/* Symbol count */}
          <div className="text-right">
            <span
              className={`text-2xl font-bold ${
                atLimit ? 'text-red-400' : 'text-financial-light'
              }`}
            >
              {count}
            </span>
            <span className="text-gray-500 text-sm"> / {SOFT_LIMIT}</span>
            <p className="text-xs text-gray-500 mt-0.5">symbols tracked</p>
          </div>
        </div>
      </div>

      {/* Limit warning */}
      {atLimit && (
        <div className="flex items-center gap-2 px-4 py-3 bg-red-900/30 border border-red-700 rounded-lg text-sm text-red-300">
          <AlertCircle className="h-4 w-4 flex-none" />
          Watchlist is full ({SOFT_LIMIT} symbols). Remove a symbol before adding a new one.
        </div>
      )}

      {/* Add form */}
      {!atLimit && (
        <Card>
          <div className="p-4">
            <h2 className="text-sm font-semibold text-gray-300 mb-3">Add Symbol</h2>
            <AddSymbolForm />
          </div>
        </Card>
      )}

      {/* Table */}
      <Card>
        {isLoading ? (
          <div className="flex items-center justify-center py-16 text-gray-500">
            <Loader2 className="h-6 w-6 animate-spin mr-2" />
            Loading watchlist…
          </div>
        ) : isError ? (
          <div className="flex items-center justify-center py-16 text-red-400 gap-2">
            <AlertCircle className="h-5 w-5" />
            Failed to load watchlist.
          </div>
        ) : items.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-16 text-gray-500 gap-2">
            <Eye className="h-10 w-10 text-gray-700" />
            <p className="text-sm">No symbols in the watchlist yet.</p>
            <p className="text-xs text-gray-600">Add a symbol above to start tracking it.</p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr className="border-b border-gray-700">
                  <th className="text-left py-3 px-4 text-xs font-semibold text-gray-400 uppercase tracking-wider">
                    Symbol
                  </th>
                  <th className="text-left py-3 px-4 text-xs font-semibold text-gray-400 uppercase tracking-wider">
                    Price
                  </th>
                  <th className="text-left py-3 px-4 text-xs font-semibold text-gray-400 uppercase tracking-wider">
                    Session
                  </th>
                  <th className="text-left py-3 px-4 text-xs font-semibold text-gray-400 uppercase tracking-wider">
                    Type
                  </th>
                  <th className="text-left py-3 px-4 text-xs font-semibold text-gray-400 uppercase tracking-wider">
                    Notes
                  </th>
                  <th className="text-left py-3 px-4 text-xs font-semibold text-gray-400 uppercase tracking-wider">
                    Added
                  </th>
                  <th className="py-3 px-4" />
                </tr>
              </thead>
              <tbody>
                {items.map((item) => (
                  <WatchlistRow
                    key={item.symbol}
                    item={item}
                    live={liveData[item.symbol]}
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
