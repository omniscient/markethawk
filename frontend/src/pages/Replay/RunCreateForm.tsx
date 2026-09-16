import React, { useMemo, useState } from 'react';
import { Play } from 'lucide-react';
import Button from '../../components/ui/Button';
import type { ScannerConfig } from '../../api/scanner';
import type { TradingStrategy } from '../../api/trading';
import type { StockUniverse } from '../../api/universe';
import { useCreateReplayRun } from '../../api/replay';
import type { ReplayRunSummary } from '../../api/replay';

interface RunCreateFormProps {
  scannerConfigs: ScannerConfig[];
  strategies: TradingStrategy[];
  universes: StockUniverse[];
  onCreated: (run: ReplayRunSummary) => void;
}

const dateDaysAgo = (days: number): string => {
  const date = new Date();
  date.setDate(date.getDate() - days);
  return date.toISOString().slice(0, 10);
};

const today = (): string => new Date().toISOString().slice(0, 10);

const RunCreateForm: React.FC<RunCreateFormProps> = ({
  scannerConfigs,
  strategies,
  universes,
  onCreated,
}) => {
  const scannerOptions = useMemo(
    () => Array.from(new Set(scannerConfigs.map((config) => config.scanner_type))).sort(),
    [scannerConfigs],
  );
  const [scannerType, setScannerType] = useState(scannerOptions[0] ?? '');
  const [universeId, setUniverseId] = useState<number | ''>(universes[0]?.id ?? '');
  const [strategyId, setStrategyId] = useState<number | ''>('');
  const [start, setStart] = useState(dateDaysAgo(90));
  const [end, setEnd] = useState(today());
  const [maxHoldDays, setMaxHoldDays] = useState(3);
  const [exitFidelity, setExitFidelity] = useState<'intraday' | 'daily'>('intraday');
  const [benchmarkSymbol, setBenchmarkSymbol] = useState('SPY');

  const createRun = useCreateReplayRun();
  const effectiveScannerType = scannerType || scannerOptions[0] || '';
  const effectiveUniverseId = universeId === '' ? universes[0]?.id ?? null : universeId;
  const canSubmit = Boolean(effectiveScannerType.trim()) && effectiveUniverseId !== null && start <= end && maxHoldDays > 0;

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!canSubmit || effectiveUniverseId === null) return;
    const selectedUniverseId = effectiveUniverseId;

    const run = await createRun.mutateAsync({
      scanner_type: effectiveScannerType.trim(),
      universe_id: selectedUniverseId,
      trading_strategy_id: strategyId === '' ? null : strategyId,
      start_date: start,
      end_date: end,
      max_hold_days: maxHoldDays,
      exit_fidelity: exitFidelity,
      benchmark_symbol: benchmarkSymbol.trim().toUpperCase() || 'SPY',
    });
    onCreated(run);
  };

  return (
    <form onSubmit={submit} className="grid grid-cols-1 xl:grid-cols-12 gap-3">
      <label className="xl:col-span-2">
        <span className="block text-xs font-bold uppercase tracking-wider text-gray-500 mb-1">Scanner</span>
        <input
          list="replay-scanner-types"
          value={effectiveScannerType}
          onChange={(event) => setScannerType(event.target.value)}
          className="w-full bg-gray-900 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:ring-1 focus:ring-financial-blue"
          placeholder="scanner_type"
          required
        />
        <datalist id="replay-scanner-types">
          {scannerOptions.map((scanner) => (
            <option key={scanner} value={scanner} />
          ))}
        </datalist>
      </label>

      <label className="xl:col-span-2">
        <span className="block text-xs font-bold uppercase tracking-wider text-gray-500 mb-1">Universe</span>
        <select
          value={effectiveUniverseId ?? ''}
          onChange={(event) => setUniverseId(Number(event.target.value))}
          className="w-full bg-gray-900 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:ring-1 focus:ring-financial-blue"
          required
        >
          <option value="" disabled>Pick universe</option>
          {universes.map((universe) => (
            <option key={universe.id} value={universe.id}>{universe.name}</option>
          ))}
        </select>
      </label>

      <label className="xl:col-span-2">
        <span className="block text-xs font-bold uppercase tracking-wider text-gray-500 mb-1">Strategy</span>
        <select
          value={strategyId}
          onChange={(event) => setStrategyId(event.target.value ? Number(event.target.value) : '')}
          className="w-full bg-gray-900 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:ring-1 focus:ring-financial-blue"
        >
          <option value="">Scanner defaults</option>
          {strategies.map((strategy) => (
            <option key={strategy.id} value={strategy.id}>{strategy.name}</option>
          ))}
        </select>
      </label>

      <label className="xl:col-span-1">
        <span className="block text-xs font-bold uppercase tracking-wider text-gray-500 mb-1">Start</span>
        <input
          type="date"
          value={start}
          onChange={(event) => setStart(event.target.value)}
          className="w-full bg-gray-900 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:ring-1 focus:ring-financial-blue"
          required
        />
      </label>

      <label className="xl:col-span-1">
        <span className="block text-xs font-bold uppercase tracking-wider text-gray-500 mb-1">End</span>
        <input
          type="date"
          value={end}
          onChange={(event) => setEnd(event.target.value)}
          className="w-full bg-gray-900 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:ring-1 focus:ring-financial-blue"
          required
        />
      </label>

      <label className="xl:col-span-1">
        <span className="block text-xs font-bold uppercase tracking-wider text-gray-500 mb-1">Hold</span>
        <input
          type="number"
          min={1}
          max={30}
          value={maxHoldDays}
          onChange={(event) => setMaxHoldDays(Number(event.target.value))}
          className="w-full bg-gray-900 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:ring-1 focus:ring-financial-blue"
        />
      </label>

      <label className="xl:col-span-1">
        <span className="block text-xs font-bold uppercase tracking-wider text-gray-500 mb-1">Fidelity</span>
        <select
          value={exitFidelity}
          onChange={(event) => setExitFidelity(event.target.value as 'intraday' | 'daily')}
          className="w-full bg-gray-900 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:ring-1 focus:ring-financial-blue"
        >
          <option value="intraday">Intraday</option>
          <option value="daily">Daily</option>
        </select>
      </label>

      <label className="xl:col-span-1">
        <span className="block text-xs font-bold uppercase tracking-wider text-gray-500 mb-1">Benchmark</span>
        <input
          value={benchmarkSymbol}
          onChange={(event) => setBenchmarkSymbol(event.target.value.toUpperCase())}
          className="w-full bg-gray-900 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:ring-1 focus:ring-financial-blue"
        />
      </label>

      <div className="xl:col-span-1 flex items-end">
        <Button type="submit" icon={Play} loading={createRun.isPending} disabled={!canSubmit} fullWidth>
          Run
        </Button>
      </div>
    </form>
  );
};

export default RunCreateForm;
