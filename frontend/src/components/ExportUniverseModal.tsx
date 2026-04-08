import React, { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import Modal from './ui/Modal';
import Button from './ui/Button';
import { Download, Search, CheckSquare, Square } from 'lucide-react';
import {
  StockUniverse,
  fetchUniverseStocks,
  exportUniverseAggregates,
  ExportAggregatesOptions,
} from '../api/scanner';

interface ExportUniverseModalProps {
  isOpen: boolean;
  onClose: () => void;
  universe: StockUniverse | null;
}

const ExportUniverseModal: React.FC<ExportUniverseModalProps> = ({ isOpen, onClose, universe }) => {
  const today = new Date().toISOString().split('T')[0];

  const defaultFrom = useMemo(() => {
    if (universe?.min_aggregate_date) return universe.min_aggregate_date.split('T')[0];
    return new Date(Date.now() - 30 * 24 * 60 * 60 * 1000).toISOString().split('T')[0];
  }, [universe?.min_aggregate_date]);

  const defaultTo = useMemo(() => {
    if (universe?.max_aggregate_date) return universe.max_aggregate_date.split('T')[0];
    return today;
  }, [universe?.max_aggregate_date]);

  // Parse the first available timespan label (e.g. "1minute" → { multiplier:1, timespan:"minute" })
  const defaultTimespan = useMemo(() => {
    const label = universe?.available_timespans?.[0] ?? 'day';
    const match = label.match(/^(\d+)?(.+)$/);
    return { multiplier: parseInt(match?.[1] ?? '1'), timespan: match?.[2] ?? label };
  }, [universe?.available_timespans]);

  const [search, setSearch] = useState('');
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [fromDate, setFromDate] = useState(defaultFrom);
  const [toDate, setToDate] = useState(defaultTo);
  const [timespan, setTimespan] = useState(defaultTimespan.timespan);
  const [multiplier, setMultiplier] = useState(defaultTimespan.multiplier);
  const [zipFormat, setZipFormat] = useState<'per_ticker' | 'single_csv'>('per_ticker');
  const [isExporting, setIsExporting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Reset state when universe changes
  React.useEffect(() => {
    setSelected(new Set());
    setSearch('');
    setError(null);
    setFromDate(defaultFrom);
    setToDate(defaultTo);
    setTimespan(defaultTimespan.timespan);
    setMultiplier(defaultTimespan.multiplier);
  }, [universe?.id]);

  const { data: stocks = [], isLoading: stocksLoading } = useQuery({
    queryKey: ['universeStocks', universe?.id],
    queryFn: () => fetchUniverseStocks(universe!.id),
    enabled: !!universe && isOpen,
  });

  const filtered = useMemo(
    () =>
      stocks.filter(
        (s) =>
          s.ticker.toLowerCase().includes(search.toLowerCase()) ||
          (s.company_name ?? '').toLowerCase().includes(search.toLowerCase()),
      ),
    [stocks, search],
  );

  const allFilteredSelected = filtered.length > 0 && filtered.every((s) => selected.has(s.ticker));

  const toggleTicker = (ticker: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      next.has(ticker) ? next.delete(ticker) : next.add(ticker);
      return next;
    });
  };

  const selectAll = () => setSelected(new Set(filtered.map((s) => s.ticker)));
  const deselectAll = () =>
    setSelected((prev) => {
      const next = new Set(prev);
      filtered.forEach((s) => next.delete(s.ticker));
      return next;
    });

  const handleExport = async () => {
    if (!universe || selected.size === 0) return;
    setIsExporting(true);
    setError(null);
    try {
      const options: ExportAggregatesOptions = {
        tickers: Array.from(selected),
        timespan,
        multiplier,
        from_date: fromDate || undefined,
        to_date: toDate || undefined,
        zip_format: zipFormat,
      };
      const blob = await exportUniverseAggregates(universe.id, options);
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `${universe.name.replace(/\s+/g, '_')}_export.zip`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e: any) {
      setError(e?.response?.data?.detail ?? e?.message ?? 'Export failed');
    } finally {
      setIsExporting(false);
    }
  };

  if (!universe) return null;

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title={`Export Aggregates: ${universe.name}`}
      footer={
        <div className="flex items-center justify-between w-full">
          <span className="text-sm text-gray-400">
            {selected.size} / {stocks.length} ticker{stocks.length !== 1 ? 's' : ''} selected
          </span>
          <div className="flex gap-2">
            <Button variant="secondary" onClick={onClose}>Cancel</Button>
            <Button
              variant="primary"
              icon={Download}
              onClick={handleExport}
              disabled={isExporting || selected.size === 0}
            >
              {isExporting ? 'Exporting…' : 'Download ZIP'}
            </Button>
          </div>
        </div>
      }
    >
      <div className="flex flex-col gap-4">
        {error && (
          <div className="bg-red-500/10 border border-red-500/30 rounded-lg p-3 text-sm text-red-400">
            {error}
          </div>
        )}

        {/* Ticker selector */}
        <div className="flex flex-col gap-2">
          <div className="flex items-center gap-2">
            <div className="relative flex-1">
              <Search className="absolute left-2.5 top-2.5 h-3.5 w-3.5 text-gray-400" />
              <input
                type="text"
                placeholder="Search tickers…"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="w-full pl-8 pr-3 py-2 bg-gray-900 border border-gray-700 rounded text-sm text-white focus:border-financial-blue focus:outline-none"
              />
            </div>
            <button
              onClick={allFilteredSelected ? deselectAll : selectAll}
              className="flex items-center gap-1.5 px-3 py-2 text-xs text-gray-300 bg-gray-800 border border-gray-700 rounded hover:border-gray-500 transition-colors"
            >
              {allFilteredSelected
                ? <><Square className="h-3.5 w-3.5" /> Deselect all</>
                : <><CheckSquare className="h-3.5 w-3.5" /> Select all</>}
            </button>
          </div>

          <div className="h-48 overflow-y-auto border border-gray-700 rounded bg-gray-900">
            {stocksLoading ? (
              <div className="flex items-center justify-center h-full text-gray-500 text-sm">Loading…</div>
            ) : filtered.length === 0 ? (
              <div className="flex items-center justify-center h-full text-gray-500 text-sm">No tickers found</div>
            ) : (
              filtered.map((stock) => (
                <label
                  key={stock.ticker}
                  className="flex items-center gap-2.5 px-3 py-2 hover:bg-gray-800 cursor-pointer border-b border-gray-800 last:border-0"
                >
                  <input
                    type="checkbox"
                    checked={selected.has(stock.ticker)}
                    onChange={() => toggleTicker(stock.ticker)}
                    className="form-checkbox rounded bg-gray-700 border-gray-600 text-financial-blue"
                  />
                  <span className="font-mono text-sm text-financial-light">{stock.ticker}</span>
                  {stock.asset_class && stock.asset_class !== 'stocks' && (
                    <span className="px-1.5 py-0.5 text-[10px] rounded bg-financial-blue/20 text-financial-blue font-medium uppercase">
                      {stock.asset_class}
                    </span>
                  )}
                  {stock.company_name && (
                    <span className="text-xs text-gray-400 truncate">{stock.company_name}</span>
                  )}
                </label>
              ))
            )}
          </div>
        </div>

        {/* Export options */}
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="block text-xs text-gray-400 mb-1">From Date</label>
            <input
              type="date"
              value={fromDate}
              onChange={(e) => setFromDate(e.target.value)}
              className="w-full bg-gray-900 border border-gray-700 rounded px-2 py-1.5 text-sm text-white focus:border-financial-blue focus:outline-none"
            />
          </div>
          <div>
            <label className="block text-xs text-gray-400 mb-1">To Date</label>
            <input
              type="date"
              value={toDate}
              onChange={(e) => setToDate(e.target.value)}
              className="w-full bg-gray-900 border border-gray-700 rounded px-2 py-1.5 text-sm text-white focus:border-financial-blue focus:outline-none"
            />
          </div>
          <div>
            <label className="block text-xs text-gray-400 mb-1">Timespan</label>
            <select
              value={timespan}
              onChange={(e) => setTimespan(e.target.value)}
              className="w-full bg-gray-900 border border-gray-700 rounded px-2 py-1.5 text-sm text-white focus:border-financial-blue focus:outline-none"
            >
              <option value="minute">Minute</option>
              <option value="hour">Hour</option>
              <option value="day">Day</option>
              <option value="week">Week</option>
              <option value="month">Month</option>
            </select>
          </div>
          <div>
            <label className="block text-xs text-gray-400 mb-1">Multiplier</label>
            <input
              type="number"
              min="1"
              value={multiplier}
              onChange={(e) => setMultiplier(parseInt(e.target.value) || 1)}
              className="w-full bg-gray-900 border border-gray-700 rounded px-2 py-1.5 text-sm text-white focus:border-financial-blue focus:outline-none"
            />
          </div>
        </div>

        <div>
          <label className="block text-xs text-gray-400 mb-1.5">ZIP Format</label>
          <div className="flex gap-3">
            {(['per_ticker', 'single_csv'] as const).map((fmt) => (
              <label key={fmt} className="flex items-center gap-2 cursor-pointer">
                <input
                  type="radio"
                  name="zip_format"
                  value={fmt}
                  checked={zipFormat === fmt}
                  onChange={() => setZipFormat(fmt)}
                  className="text-financial-blue"
                />
                <span className="text-sm text-gray-300">
                  {fmt === 'per_ticker' ? 'One CSV per ticker' : 'Single combined CSV'}
                </span>
              </label>
            ))}
          </div>
        </div>
      </div>
    </Modal>
  );
};

export default ExportUniverseModal;
