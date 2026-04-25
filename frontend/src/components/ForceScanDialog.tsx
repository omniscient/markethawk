import React from 'react';
import { X, Zap } from 'lucide-react';

const SCANNER_OPTIONS = [
  { key: 'pre_market_volume_spike', label: 'Pre-Market Volume Spike' },
  { key: 'liquidity_hunt',          label: 'Liquidity Hunt' },
  { key: 'oversold_bounce',         label: 'Oversold Bounce' },
] as const;

const LS_TYPES  = 'force_scan_types';
const LS_START  = 'force_scan_start_date';
const LS_END    = 'force_scan_end_date';
const LS_FETCH  = 'force_scan_fetch_data';

function todayIso(): string {
  return new Date().toISOString().slice(0, 10);
}

function defaultStartIso(): string {
  const d = new Date();
  d.setDate(d.getDate() - 30);
  return d.toISOString().slice(0, 10);
}

function loadState() {
  const raw = localStorage.getItem(LS_TYPES);
  const types: string[] = raw
    ? JSON.parse(raw)
    : SCANNER_OPTIONS.map(o => o.key);
  return {
    types,
    startDate: localStorage.getItem(LS_START) || defaultStartIso(),
    endDate:   localStorage.getItem(LS_END)   || todayIso(),
    fetchData: localStorage.getItem(LS_FETCH) !== 'false',
  };
}

interface Props {
  isOpen: boolean;
  isSubmitting: boolean;
  onClose: () => void;
  onSubmit: (types: string[], startDate: string, endDate: string, fetchData: boolean) => void;
}

const ForceScanDialog: React.FC<Props> = ({ isOpen, isSubmitting, onClose, onSubmit }) => {
  const [selectedTypes, setSelectedTypes] = React.useState<string[]>([]);
  const [startDate, setStartDate]         = React.useState('');
  const [endDate, setEndDate]             = React.useState('');
  const [fetchData, setFetchData]         = React.useState(true);

  React.useEffect(() => {
    if (isOpen) {
      const saved = loadState();
      setSelectedTypes(saved.types);
      setStartDate(saved.startDate);
      setEndDate(saved.endDate);
      setFetchData(saved.fetchData);
    }
  }, [isOpen]);

  const toggleType = (key: string) => {
    setSelectedTypes(prev =>
      prev.includes(key) ? prev.filter(k => k !== key) : [...prev, key]
    );
  };

  const handleSubmit = () => {
    localStorage.setItem(LS_TYPES,  JSON.stringify(selectedTypes));
    localStorage.setItem(LS_START,  startDate);
    localStorage.setItem(LS_END,    endDate);
    localStorage.setItem(LS_FETCH,  String(fetchData));
    onSubmit(selectedTypes, startDate, endDate, fetchData);
  };

  const isValid =
    selectedTypes.length > 0 &&
    startDate &&
    endDate &&
    startDate <= endDate;

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-black/60" onClick={onClose} />
      <div className="relative bg-gray-900 border border-gray-700 rounded-xl shadow-2xl w-full max-w-md mx-4 p-6 space-y-5">

        {/* Header */}
        <div className="flex items-center justify-between">
          <div className="flex items-center space-x-2">
            <Zap className="h-5 w-5 text-financial-blue" />
            <h2 className="text-lg font-bold text-financial-light">Run Scanner</h2>
          </div>
          <button onClick={onClose} className="text-gray-500 hover:text-white transition-colors">
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* Scanner Type Multi-Select */}
        <div>
          <p className="text-xs font-bold text-gray-400 uppercase tracking-wider mb-2">Scanner Types</p>
          <div className="space-y-2">
            {SCANNER_OPTIONS.map(({ key, label }) => (
              <label key={key} className="flex items-center space-x-3 cursor-pointer group">
                <input
                  type="checkbox"
                  checked={selectedTypes.includes(key)}
                  onChange={() => toggleType(key)}
                  className="w-4 h-4 rounded border-gray-600 bg-gray-800 text-financial-blue focus:ring-financial-blue"
                />
                <span className="text-sm text-gray-300 group-hover:text-white transition-colors">{label}</span>
              </label>
            ))}
          </div>
          {selectedTypes.length === 0 && (
            <p className="text-xs text-negative mt-2">Select at least one scanner type.</p>
          )}
        </div>

        {/* Date Range */}
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="text-xs font-bold text-gray-400 uppercase tracking-wider block mb-1">
              Start Date
            </label>
            <input
              type="date"
              value={startDate}
              max={endDate || todayIso()}
              onChange={e => setStartDate(e.target.value)}
              className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-financial-light focus:outline-none focus:border-financial-blue"
            />
          </div>
          <div>
            <label className="text-xs font-bold text-gray-400 uppercase tracking-wider block mb-1">
              End Date
            </label>
            <input
              type="date"
              value={endDate}
              min={startDate}
              max={todayIso()}
              onChange={e => setEndDate(e.target.value)}
              className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-financial-light focus:outline-none focus:border-financial-blue"
            />
          </div>
        </div>

        {/* Fetch Missing Data */}
        <label className="flex items-center space-x-3 cursor-pointer group">
          <input
            type="checkbox"
            checked={fetchData}
            onChange={e => setFetchData(e.target.checked)}
            className="w-4 h-4 rounded border-gray-600 bg-gray-800 text-financial-blue focus:ring-financial-blue"
          />
          <span className="text-sm text-gray-300 group-hover:text-white transition-colors">
            Fetch missing data from Polygon before scanning
          </span>
        </label>

        {/* Footer */}
        <div className="flex justify-end space-x-3 pt-1">
          <button
            onClick={onClose}
            className="px-4 py-2 text-sm font-semibold text-gray-400 hover:text-white transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={handleSubmit}
            disabled={!isValid || isSubmitting}
            className={`flex items-center space-x-2 px-4 py-2 text-sm font-bold rounded-lg transition-all ${
              isValid && !isSubmitting
                ? 'bg-financial-blue text-white hover:bg-blue-600'
                : 'bg-gray-700 text-gray-500 cursor-not-allowed'
            }`}
          >
            <Zap className="h-4 w-4" />
            <span>{isSubmitting ? 'Queuing…' : 'Run Scan'}</span>
          </button>
        </div>
      </div>
    </div>
  );
};

export default ForceScanDialog;
