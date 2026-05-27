import React, { useState } from 'react';
import { Eye, Plus, AlertCircle, Loader2, Wifi, WifiOff } from 'lucide-react';
import Card from '../../components/ui/Card';
import Button from '../../components/ui/Button';
import { useWatchlist, useAddToWatchlist } from '../../api/watchlist';
import { useWatchlistLive } from '../../hooks/useWatchlistLive';
import { WatchlistTable } from './WatchlistTable';

const SOFT_LIMIT = 50;

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
        onSuccess: () => { setSymbol(''); setExchange(''); setNotes(''); },
        onError: (err: any) => { setError(err?.response?.data?.detail ?? 'Failed to add symbol.'); },
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
        <Button type="submit" icon={add.isPending ? undefined : Plus} loading={add.isPending} disabled={!symbol.trim()}>
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

export default function ActiveWatchlist() {
  const { data: items = [], isLoading, isError } = useWatchlist();
  const { liveData, connected } = useWatchlistLive();

  const count = items.length;
  const atLimit = count >= SOFT_LIMIT;

  return (
    <div className="space-y-6">
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
          <div className="flex items-center gap-1.5 text-xs">
            {connected ? (
              <><Wifi className="h-3.5 w-3.5 text-positive" /><span className="text-positive">Live</span></>
            ) : (
              <><WifiOff className="h-3.5 w-3.5 text-gray-500" /><span className="text-gray-500">Connecting…</span></>
            )}
          </div>
          <div className="text-right">
            <span className={`text-2xl font-bold ${atLimit ? 'text-red-400' : 'text-financial-light'}`}>{count}</span>
            <span className="text-gray-500 text-sm"> / {SOFT_LIMIT}</span>
            <p className="text-xs text-gray-500 mt-0.5">symbols tracked</p>
          </div>
        </div>
      </div>

      {atLimit && (
        <div className="flex items-center gap-2 px-4 py-3 bg-red-900/30 border border-red-700 rounded-lg text-sm text-red-300">
          <AlertCircle className="h-4 w-4 flex-none" />
          Watchlist is full ({SOFT_LIMIT} symbols). Remove a symbol before adding a new one.
        </div>
      )}

      {!atLimit && (
        <Card>
          <div className="p-4">
            <h2 className="text-sm font-semibold text-gray-300 mb-3">Add Symbol</h2>
            <AddSymbolForm />
          </div>
        </Card>
      )}

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
          <WatchlistTable items={items} liveData={liveData} />
        )}
      </Card>
    </div>
  );
}
