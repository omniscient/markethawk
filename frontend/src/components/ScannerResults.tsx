import React, { useState } from 'react';
import {
  Download,
  Eye,
  Filter,
  ChevronUp,
  ChevronDown,
  Search,
} from 'lucide-react';
import Card from './ui/Card';
import Ticker from './Ticker';
import { ScannerEvent, ScannerDiagnostics } from '../api/scanner';

interface ScannerResultsProps {
  results: {
    scan_id: string;
    status: string;
    stocks_scanned: number;
    events_detected: number;
    execution_time_ms: number;
    events?: ScannerEvent[];
    scan_start_date?: string;
    scan_end_date?: string;
    diagnostics?: ScannerDiagnostics;
  };
  onSort?: (column: string) => void;
  sortBy?: string;
  sortOrder?: 'asc' | 'desc';
}

const ScannerResults: React.FC<ScannerResultsProps> = ({ 
  results,
  onSort,
  sortBy,
  sortOrder
}) => {
  const [filterTicker, setFilterTicker] = useState('');
  const [severityFilter, setSeverityFilter] = useState<'all' | 'high' | 'medium' | 'low'>('all');

  const filteredEvents = results.events?.filter(event => {
    const matchesTicker = !filterTicker ||
      event.ticker.toLowerCase().includes(filterTicker.toLowerCase());
    const matchesSeverity = severityFilter === 'all' || event.severity === severityFilter;
    return matchesTicker && matchesSeverity;
  }) || [];

  const getSeverityStyle = (severity: string) => {
    switch (severity) {
      case 'high':
        return 'bg-red-500/20 text-red-400 border-red-500/30';
      case 'medium':
        return 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30';
      case 'low':
        return 'bg-blue-500/20 text-blue-400 border-blue-500/30';
      default:
        return 'bg-gray-500/20 text-gray-400 border-gray-500/30';
    }
  };

  const renderIndicator = (key: string, val: any) => {
    if (typeof val === 'number') {
      if (key.includes('pct')) return `${val > 0 ? '+' : ''}${val.toFixed(2)}%`;
      if (key.includes('volume') || key.includes('ratio')) return `${val.toFixed(1)}x`;
      if (val > 1000000) return `${(val/1000000).toFixed(1)}M`;
      if (val > 1000) return `${(val/1000).toFixed(1)}K`;
      return val.toFixed(2);
    }
    return String(val);
  };

  const getImportantIndicators = (event: ScannerEvent) => {
    const ind = event.indicators || {};
    const keys = Object.keys(ind);
    const preferred =
      event.scanner_type === 'liquidity_hunt_pre' || event.scanner_type === 'liquidity_hunt_post'
        ? ['session_volume_ratio', 'session_spike_pct', 'session_volume_pct_of_daily', 'regular_volume_ratio', 'regular_range_ratio']
        : ['relative_volume', 'gap_pct', 'rsi_2', 'rsi_5', 'volume_spike_ratio'];
    return keys
      .filter(k => preferred.includes(k))
      .sort((a, b) => preferred.indexOf(a) - preferred.indexOf(b))
      .slice(0, 3);
  };

  return (
    <Card title="Scanner Results" icon={Eye as any}>
      {/* Results Summary */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
        <div className="bg-gray-800/40 border border-gray-700/50 rounded-lg p-4 text-center">
          <div className="text-2xl font-bold text-financial-light">
            {results.stocks_scanned || '-'}
          </div>
          <div className="text-xs text-gray-400 uppercase tracking-wider font-semibold">Stocks Scanned</div>
        </div>
        <div className="bg-gray-800/40 border border-gray-700/50 rounded-lg p-4 text-center">
          <div className="text-2xl font-bold text-positive">
            {results.events_detected}
          </div>
          <div className="text-xs text-gray-400 uppercase tracking-wider font-semibold">Events Detected</div>
        </div>
        <div className="bg-gray-800/40 border border-gray-700/50 rounded-lg p-4 text-center">
          <div className="text-2xl font-bold text-financial-blue">
            {results.execution_time_ms}ms
          </div>
          <div className="text-xs text-gray-400 uppercase tracking-wider font-semibold">Execution Time</div>
        </div>
        <div className="bg-gray-800/40 border border-gray-700/50 rounded-lg p-4 text-center">
          <div className="text-2xl font-bold text-financial-light">
            {filteredEvents.length}
          </div>
          <div className="text-xs text-gray-400 uppercase tracking-wider font-semibold">Filtered Results</div>
        </div>
      </div>

      {results.diagnostics && (
        <div className="mb-6 p-4 bg-gray-900/60 border border-gray-800 rounded-lg">
          <div className="flex items-center justify-between mb-3">
            <div className="text-xs font-bold text-gray-500 uppercase tracking-wider">Scan Diagnostics</div>
            <div className="text-xs text-gray-500">
              {results.diagnostics.start_date}
              {results.diagnostics.end_date && results.diagnostics.end_date !== results.diagnostics.start_date
                ? ` → ${results.diagnostics.end_date}`
                : ''}
              {' · '}
              {results.diagnostics.days ?? 0} day{(results.diagnostics.days ?? 0) === 1 ? '' : 's'}
            </div>
          </div>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-sm">
            <DiagStat label="Evaluated" value={results.diagnostics.evaluated} tone="ok" />
            <DiagStat label="No data" value={results.diagnostics.no_data} tone="warn" />
            <DiagStat label="No prior close" value={results.diagnostics.no_prior_close} tone="warn" />
            <DiagStat label="No baseline" value={results.diagnostics.no_baseline} tone="warn" />
            <DiagStat label="Fired pre" value={results.diagnostics.fired_pre} tone="ok" />
            <DiagStat label="Fired post" value={results.diagnostics.fired_post} tone="ok" />
            <DiagStat label="Errors" value={results.diagnostics.errors} tone="err" />
          </div>
          {(results.events_detected === 0 && (results.diagnostics.no_data ?? 0) > 0) && (
            <p className="mt-3 text-xs text-yellow-300/80">
              No regular-session minute bars were available for {(results.diagnostics.no_data ?? 0)} ticker(s) on this date.
              The market may not have closed yet, or data ingestion is incomplete — try a previous trading day.
            </p>
          )}
        </div>
      )}

      {/* Filters */}
      <div className="flex flex-col md:flex-row gap-4 mb-6 p-4 bg-gray-900 border border-gray-800 rounded-lg shadow-inner">
        <div className="flex-1">
          <label className="block text-xs font-bold text-gray-500 uppercase mb-2">Filter by Ticker</label>
          <div className="relative">
            <Search className="absolute left-3 top-2.5 h-4 w-4 text-gray-400" />
            <input
              type="text"
              placeholder="Enter ticker..."
              value={filterTicker}
              onChange={(e) => setFilterTicker(e.target.value)}
              className="w-full pl-10 pr-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-financial-light focus:outline-none focus:ring-1 focus:ring-financial-blue transition-all"
            />
          </div>
        </div>
        <div className="w-48">
          <label className="block text-xs font-bold text-gray-500 uppercase mb-2">Severity</label>
          <select 
            value={severityFilter}
            onChange={(e) => setSeverityFilter(e.target.value as any)}
            className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-financial-light focus:outline-none focus:ring-1 focus:ring-financial-blue transition-all"
          >
            <option value="all">All Severities</option>
            <option value="high">High</option>
            <option value="medium">Medium</option>
            <option value="low">Low</option>
          </select>
        </div>
        <div className="flex items-end">
          <button className="px-5 py-2 bg-financial-blue text-white font-bold rounded-lg hover:bg-blue-600 transition-all flex items-center space-x-2 shadow-lg shadow-financial-blue/20">
            <Download className="h-4 w-4" />
            <span>EXPORT CSV</span>
          </button>
        </div>
      </div>

      {/* Results Table */}
      {filteredEvents.length > 0 ? (
        <div className="overflow-x-auto">
          <table className="w-full border-separate border-spacing-y-2">
            <thead>
              <tr className="text-left py-3 px-4 text-[10px] font-bold text-gray-500 uppercase tracking-widest">
                <SortableHeader 
                  label="Date" 
                  sortKey="event_date" 
                  currentSort={sortBy} 
                  currentOrder={sortOrder} 
                  onSort={onSort} 
                />
                <SortableHeader 
                  label="Ticker" 
                  sortKey="ticker" 
                  currentSort={sortBy} 
                  currentOrder={sortOrder} 
                  onSort={onSort} 
                />
                <th className="py-3 px-4">Scanner</th>
                <th className="py-3 px-4">Summary</th>
                <th className="py-3 px-4">Key Indicators</th>
                <SortableHeader 
                  label="Severity" 
                  sortKey="severity" 
                  currentSort={sortBy} 
                  currentOrder={sortOrder} 
                  onSort={onSort} 
                />
                <th className="py-3 px-4">Score</th>
              </tr>
            </thead>
            <tbody>
              {filteredEvents.map((event) => (
                <tr key={event.id} className="group hover:scale-[1.005] transition-transform duration-200">
                  <td className="py-4 px-4 bg-gray-800 rounded-l-xl text-gray-400 text-xs font-mono">
                    {event.event_date}
                  </td>
                  <td className="py-4 px-4 bg-gray-800">
                    <Ticker 
                      ticker={event.ticker} 
                      size="lg" 
                      showIcon={true} 
                    />
                  </td>
                  <td className="py-4 px-4 bg-gray-800">
                    <span className="text-[10px] font-bold text-gray-500 uppercase border border-gray-700 px-1.5 py-0.5 rounded-md bg-gray-900/50">
                      {event.scanner_type.replace(/_/g, ' ')}
                    </span>
                  </td>
                  <td className="py-4 px-4 bg-gray-800 max-w-xs">
                    <p className="text-sm font-medium text-gray-200 line-clamp-1" title={event.summary}>
                      {event.summary}
                    </p>
                  </td>
                  <td className="py-4 px-4 bg-gray-800">
                    <div className="flex flex-wrap gap-2 text-[10px] font-bold">
                      {getImportantIndicators(event).map(key => (
                        <div key={key} className="flex flex-col">
                          <span className="text-gray-500 uppercase tracking-tighter text-[8px]">{key.replace(/_/g, ' ')}</span>
                          <span className={event.indicators[key] > 0 || key.includes('rsi') ? 'text-financial-light' : 'text-gray-400'}>
                             {renderIndicator(key, event.indicators[key])}
                          </span>
                        </div>
                      ))}
                    </div>
                  </td>
                  <td className="py-4 px-4 bg-gray-800">
                    <span className={`inline-flex items-center px-2 py-0.5 rounded text-[10px] font-bold uppercase border shadow-sm ${getSeverityStyle(event.severity)}`}>
                      {event.severity}
                    </span>
                  </td>
                  <td className="py-4 px-4 bg-gray-800 rounded-r-xl">
                    <div className="flex items-center space-x-2">
                       <span className={`px-2 py-1 rounded text-xs font-black ${Object.values(event.criteria_met || {}).every(Boolean)
                        ? 'bg-green-500/20 text-green-400'
                        : 'bg-yellow-500/20 text-yellow-400'
                        }`}>
                        {Object.values(event.criteria_met || {}).filter(Boolean).length}/
                        {Object.values(event.criteria_met || {}).length}
                      </span>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="text-center py-20 bg-gray-900 rounded-xl border-2 border-dashed border-gray-800">
          <div className="bg-gray-800 h-16 w-16 rounded-full flex items-center justify-center mx-auto mb-4 border border-gray-700">
            <Filter className="h-8 w-8 text-gray-500" />
          </div>
          <p className="text-gray-400 font-medium">No scanner results match your filters</p>
          <button 
            onClick={() => {setFilterTicker(''); setSeverityFilter('all');}} 
            className="mt-4 text-financial-blue hover:text-blue-400 text-sm font-bold underline"
          >
            Clear all filters
          </button>
        </div>
      )}
    </Card>
  );
};

interface DiagStatProps {
  label: string;
  value: number | undefined;
  tone: 'ok' | 'warn' | 'err';
}

const DiagStat: React.FC<DiagStatProps> = ({ label, value, tone }) => {
  const v = value ?? 0;
  const colour =
    tone === 'err' && v > 0 ? 'text-red-400'
      : tone === 'warn' && v > 0 ? 'text-yellow-400'
      : tone === 'ok' && v > 0 ? 'text-green-400'
      : 'text-gray-500';
  return (
    <div className="flex justify-between items-baseline border-b border-gray-800/60 pb-1">
      <span className="text-[10px] uppercase tracking-wider text-gray-500">{label}</span>
      <span className={`font-mono font-semibold ${colour}`}>{v.toLocaleString()}</span>
    </div>
  );
};

interface SortableHeaderProps {
  label: string;
  sortKey: string;
  currentSort?: string;
  currentOrder?: 'asc' | 'desc';
  onSort?: (_key: string) => void;
}

const SortableHeader: React.FC<SortableHeaderProps> = ({ 
  label, 
  sortKey, 
  currentSort, 
  currentOrder, 
  onSort 
}) => {
  const isActive = currentSort === sortKey;
  
  return (
    <th 
      className="py-3 px-4 cursor-pointer hover:text-financial-light transition-colors group select-none"
      onClick={() => onSort?.(sortKey)}
    >
      <div className="flex items-center space-x-1">
        <span>{label}</span>
        <div className="flex flex-col opacity-30 group-hover:opacity-100 transition-opacity">
          <ChevronUp 
            className={`h-2.5 w-2.5 -mb-0.5 ${isActive && currentOrder === 'asc' ? 'text-financial-blue opacity-100' : 'text-gray-500'}`} 
          />
          <ChevronDown 
            className={`h-2.5 w-2.5 ${isActive && currentOrder === 'desc' ? 'text-financial-blue opacity-100' : 'text-gray-500'}`} 
          />
        </div>
      </div>
    </th>
  );
};

export default ScannerResults;