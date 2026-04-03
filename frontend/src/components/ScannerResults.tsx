import React, { useState } from 'react';
import {
  TrendingUp,
  TrendingDown,
  Download,
  Eye,
  Filter,
  ChevronUp,
  ChevronDown,
  Search
} from 'lucide-react';
import { Link } from 'react-router-dom';
import Card from './ui/Card';

interface ScannerResultsProps {
  results: {
    scan_id: string;
    status: string;
    stocks_scanned: number;
    events_detected: number;
    execution_time_ms: number;
    events?: any[];
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
  const [minVolumeSpike, setMinVolumeSpike] = useState(0);

  const getCatalystColor = (tag: string) => {
    const t = tag.toLowerCase();
    if (t.includes('dilution') || t.includes('miss') || t.includes('downgrade')) return 'bg-red-500/20 text-red-400 border-red-500/30';
    if (t.includes('beat') || t.includes('upgrade') || t.includes('won') || t.includes('fda') || t.includes('earnings_beat')) return 'bg-green-500/20 text-green-400 border-green-500/30';
    return 'bg-blue-500/20 text-blue-400 border-blue-500/30';
  };

  const filteredEvents = results.events?.filter(event => {
    const matchesTicker = !filterTicker ||
      event.ticker.toLowerCase().includes(filterTicker.toLowerCase());
    const matchesVolumeSpike = event.volume_spike_ratio >= minVolumeSpike;
    return matchesTicker && matchesVolumeSpike;
  }) || [];

  return (
    <Card title="Scanner Results" icon={Eye as any}>
      {/* Results Summary */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
        <div className="bg-gray-800 rounded-lg p-4 text-center">
          <div className="text-2xl font-bold text-financial-light">
            {results.stocks_scanned}
          </div>
          <div className="text-sm text-gray-400">Stocks Scanned</div>
        </div>
        <div className="bg-gray-800 rounded-lg p-4 text-center">
          <div className="text-2xl font-bold text-positive">
            {results.events_detected}
          </div>
          <div className="text-sm text-gray-400">Events Detected</div>
        </div>
        <div className="bg-gray-800 rounded-lg p-4 text-center">
          <div className="text-2xl font-bold text-financial-blue">
            {results.execution_time_ms}ms
          </div>
          <div className="text-sm text-gray-400">Execution Time</div>
        </div>
        <div className="bg-gray-800 rounded-lg p-4 text-center">
          <div className="text-2xl font-bold text-financial-light">
            {filteredEvents.length}
          </div>
          <div className="text-sm text-gray-400">Filtered Results</div>
        </div>
      </div>

      {/* Filters */}
      <div className="flex flex-col md:flex-row gap-4 mb-6 p-4 bg-gray-800 rounded-lg">
        <div className="flex-1">
          <label className="block text-sm text-gray-400 mb-1">Filter by Ticker</label>
          <div className="relative">
            <Search className="absolute left-3 top-2.5 h-4 w-4 text-gray-400" />
            <input
              type="text"
              placeholder="Enter ticker symbol..."
              value={filterTicker}
              onChange={(e) => setFilterTicker(e.target.value)}
              className="w-full pl-10 pr-3 py-2 bg-gray-700 border border-gray-600 rounded-lg text-financial-light focus:outline-none focus:ring-2 focus:ring-financial-blue"
            />
          </div>
        </div>
        <div className="flex-1">
          <label className="block text-sm text-gray-400 mb-1">Min Volume Spike</label>
          <div className="flex items-center space-x-2">
            <input
              type="range"
              min="0"
              max="10"
              step="0.5"
              value={minVolumeSpike}
              onChange={(e) => setMinVolumeSpike(parseFloat(e.target.value))}
              className="flex-1"
            />
            <span className="text-financial-light font-medium w-12">
              {minVolumeSpike}x
            </span>
          </div>
        </div>
        <div className="flex items-end">
          <button className="px-4 py-2 bg-financial-blue text-white rounded-lg hover:bg-blue-600 transition-colors flex items-center space-x-2">
            <Download className="h-4 w-4" />
            <span>Export</span>
          </button>
        </div>
      </div>

      {/* Results Table */}
      {filteredEvents.length > 0 ? (
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr className="border-b border-gray-700">
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
                <SortableHeader 
                  label="Volume Spike" 
                  sortKey="volume_spike_ratio" 
                  currentSort={sortBy} 
                  currentOrder={sortOrder} 
                  onSort={onSort} 
                />
                <SortableHeader 
                  label="Rel Volume" 
                  sortKey="relative_volume" 
                  currentSort={sortBy} 
                  currentOrder={sortOrder} 
                  onSort={onSort} 
                />
                <SortableHeader 
                  label="Gap %" 
                  sortKey="price_gap_pct" 
                  currentSort={sortBy} 
                  currentOrder={sortOrder} 
                  onSort={onSort} 
                />
                <SortableHeader 
                  label="Pre-Market Vol" 
                  sortKey="pre_market_volume" 
                  currentSort={sortBy} 
                  currentOrder={sortOrder} 
                  onSort={onSort} 
                />
                <SortableHeader 
                  label="Float Rot %" 
                  sortKey="float_rotation_pct" 
                  currentSort={sortBy} 
                  currentOrder={sortOrder} 
                  onSort={onSort} 
                />
                <th className="text-left py-3 px-4 text-sm font-medium text-gray-400">Catalysts</th>
                <th className="text-left py-3 px-4 text-sm font-medium text-gray-400">Criteria</th>
              </tr>
            </thead>
            <tbody>
              {filteredEvents.map((event) => (
                <tr key={event.id} className="border-b border-gray-800 hover:bg-gray-800/50">
                  <td className="py-3 px-4 text-gray-400 text-sm">
                    {event.event_date}
                  </td>
                  <td className="py-3 px-4">
                    <div>
                      <Link 
                        to={`/stock/${event.ticker}`}
                        className="font-medium text-financial-blue hover:text-blue-400 transition-colors"
                      >
                        {event.ticker}
                      </Link>
                      <div className="text-xs text-gray-400">{event.company_name}</div>
                    </div>
                  </td>
                  <td className="py-3 px-4">
                    <div className="flex items-center space-x-1">
                      <TrendingUp className="h-4 w-4 text-positive" />
                      <span className="text-positive font-medium">
                        {event.volume_spike_ratio}x
                      </span>
                    </div>
                  </td>
                  <td className="py-3 px-4">
                    <span className="text-financial-light font-medium">
                      {event.relative_volume.toFixed(1)}x
                    </span>
                  </td>
                  <td className="py-3 px-4">
                    {(event.price_gap_pct || 0) > 0 ? (
                      <div className="flex items-center space-x-1">
                        <TrendingUp className="h-4 w-4 text-positive" />
                        <span className="text-positive font-medium">
                          +{(event.price_gap_pct || 0).toFixed(1)}%
                        </span>
                      </div>
                    ) : (
                      <div className="flex items-center space-x-1">
                        <TrendingDown className="h-4 w-4 text-negative" />
                        <span className="text-negative font-medium">
                          {(event.price_gap_pct || 0).toFixed(1)}%
                        </span>
                      </div>
                    )}
                  </td>
                  <td className="py-3 px-4 text-financial-light">
                    {event.pre_market_volume.toLocaleString()}
                  </td>
                  <td className="py-3 px-4">
                    <span className={`px-2 py-1 rounded text-xs font-medium ${Object.values(event.criteria_met).every(Boolean)
                      ? 'bg-green-500/20 text-green-400'
                      : 'bg-yellow-500/20 text-yellow-400'
                      }`}>
                      {Object.values(event.criteria_met).filter(Boolean).length}/
                      {Object.values(event.criteria_met).length}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="text-center py-12">
          <Filter className="h-12 w-12 text-gray-600 mx-auto mb-4" />
          <p className="text-gray-400">No events match your current filters</p>
        </div>
      )}
    </Card>
  );
};

interface SortableHeaderProps {
  label: string;
  sortKey: string;
  currentSort?: string;
  currentOrder?: 'asc' | 'desc';
  onSort?: (key: string) => void;
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
      className="text-left py-3 px-4 text-sm font-medium text-gray-400 cursor-pointer hover:text-financial-light transition-colors group"
      onClick={() => onSort?.(sortKey)}
    >
      <div className="flex items-center space-x-1">
        <span>{label}</span>
        <div className="flex flex-col">
          <ChevronUp 
            className={`h-3 w-3 -mb-1 ${isActive && currentOrder === 'asc' ? 'text-financial-blue' : 'text-gray-600 group-hover:text-gray-400'}`} 
          />
          <ChevronDown 
            className={`h-3 w-3 ${isActive && currentOrder === 'desc' ? 'text-financial-blue' : 'text-gray-600 group-hover:text-gray-400'}`} 
          />
        </div>
      </div>
    </th>
  );
};

export default ScannerResults;