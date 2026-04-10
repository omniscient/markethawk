import React, { useState, useEffect } from 'react';
import { 
  TrendingUp, 
  TrendingDown, 
  Search, 
  RefreshCw, 
  ExternalLink,
  ChevronUp,
  ChevronDown,
  Volume2,
  DollarSign,
  Percent
} from 'lucide-react';
import { Link } from 'react-router-dom';
import Ticker from '../components/Ticker';
import Layout from '../components/Layout';
import Card from '../components/ui/Card';
import MetricCard from '../components/ui/MetricCard';
import { fetchPreMarketMovers, PreMarketMover } from '../api/scanner';

const PreMarketMovers: React.FC = () => {
  const [movers, setMovers] = useState<PreMarketMover[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filterTicker, setFilterTicker] = useState('');
  const [minVolume, setMinVolume] = useState(50000);
  const [sortBy, setSortBy] = useState<string>('change_percent');
  const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('desc');
  const [lastUpdated, setLastUpdated] = useState<Date>(new Date());

  const fetchData = async () => {
    setLoading(true);
    try {
      const response = await fetchPreMarketMovers({ 
        min_volume: 1000, // Fetch more then filter locally for responsiveness
        limit: 200 
      });
      setMovers(response.movers);
      setLastUpdated(new Date(response.timestamp));
      setError(null);
    } catch (err: any) {
      setError(err.message || 'Failed to fetch movers');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 60000); // Refresh every minute
    return () => clearInterval(interval);
  }, []);

  const handleSort = (key: string) => {
    if (sortBy === key) {
      setSortOrder(sortOrder === 'asc' ? 'desc' : 'asc');
    } else {
      setSortBy(key);
      setSortOrder('desc');
    }
  };

  const filteredMovers = movers
    .filter(mover => {
      const matchesTicker = mover.ticker.toLowerCase().includes(filterTicker.toLowerCase());
      const matchesVolume = mover.volume >= minVolume;
      return matchesTicker && matchesVolume;
    })
    .sort((a, b) => {
      const aValue = a[sortBy as keyof PreMarketMover] ?? 0;
      const bValue = b[sortBy as keyof PreMarketMover] ?? 0;
      
      if (typeof aValue === 'number' && typeof bValue === 'number') {
        return sortOrder === 'desc' ? bValue - aValue : aValue - bValue;
      }
      return 0;
    });

  const topGainer = movers.length > 0 ? [...movers].sort((a, b) => b.change_percent - a.change_percent)[0] : null;
  const topLoser = movers.length > 0 ? [...movers].sort((a, b) => a.change_percent - b.change_percent)[0] : null;
  const maxVolume = movers.length > 0 ? [...movers].sort((a, b) => b.volume - a.volume)[0] : null;

  return (
    <div className="space-y-6">
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
          <div>
            <h1 className="text-2xl font-bold text-financial-light">Pre-market Movers</h1>
            <p className="text-gray-400">Top gainers and losers from 4:00 AM ET</p>
          </div>
          <div className="flex items-center space-x-4">
            <div className="text-right">
              <div className="text-xs text-gray-500 uppercase font-bold tracking-wider">Last Updated</div>
              <div className="text-financial-light text-sm">{lastUpdated.toLocaleTimeString()}</div>
            </div>
            <button 
              onClick={fetchData}
              disabled={loading}
              className="p-2 bg-gray-800 hover:bg-gray-700 rounded-lg text-financial-blue transition-colors disabled:opacity-50"
            >
              <RefreshCw className={`h-5 w-5 ${loading ? 'animate-spin' : ''}`} />
            </button>
          </div>
        </div>

        {/* Stats Summary */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          <MetricCard 
            title={`Top Gainer: ${topGainer?.ticker || ''}`}
            value={topGainer ? `+${topGainer.change_percent.toFixed(2)}%` : 'N/A'}
            icon={TrendingUp as any}
            color="green"
          />
          <MetricCard 
            title={`Top Loser: ${topLoser?.ticker || ''}`}
            value={topLoser ? `${topLoser.change_percent.toFixed(2)}%` : 'N/A'}
            icon={TrendingDown as any}
            color="red"
          />
          <MetricCard 
            title={`Highest Volume: ${maxVolume?.ticker || ''}`}
            value={maxVolume ? maxVolume.volume.toLocaleString() : 'N/A'}
            icon={Volume2 as any}
            color="blue"
          />
        </div>

        {/* Filters */}
        <Card>
          <div className="flex flex-col md:flex-row gap-6">
            <div className="flex-1">
              <label className="block text-sm font-medium text-gray-400 mb-2">Search Ticker</label>
              <div className="relative">
                <Search className="absolute left-3 top-2.5 h-4 w-4 text-gray-500" />
                <input
                  type="text"
                  placeholder="e.g. NVDA, AAPL..."
                  value={filterTicker}
                  onChange={(e) => setFilterTicker(e.target.value)}
                  className="w-full pl-10 pr-4 py-2 bg-gray-800 border border-gray-700 rounded-lg text-financial-light focus:outline-none focus:ring-2 focus:ring-financial-blue transition-all"
                />
              </div>
            </div>
            <div className="flex-1">
              <label className="block text-sm font-medium text-gray-400 mb-2">Min Pre-market Volume: {minVolume.toLocaleString()}</label>
              <input
                type="range"
                min="0"
                max="1000000"
                step="50000"
                value={minVolume}
                onChange={(e) => setMinVolume(parseInt(e.target.value))}
                className="w-full h-2 bg-gray-700 rounded-lg appearance-none cursor-pointer accent-financial-blue"
              />
              <div className="flex justify-between text-xs text-gray-500 mt-1">
                <span>0</span>
                <span>500k</span>
                <span>1M+</span>
              </div>
            </div>
          </div>
        </Card>

        {/* Main Table */}
        <Card title="Movers List" noPadding>
          {loading && movers.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-20">
              <RefreshCw className="h-10 w-10 text-financial-blue animate-spin mb-4" />
              <p className="text-gray-400">Loading pre-market data...</p>
            </div>
          ) : error ? (
            <div className="flex flex-col items-center justify-center py-20">
              <p className="text-negative font-medium mb-4">{error}</p>
              <button onClick={fetchData} className="px-4 py-2 bg-financial-blue text-white rounded-lg">Retry</button>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left border-collapse">
                <thead>
                  <tr className="bg-gray-800/50 border-b border-gray-700">
                    <SortableHeader label="Ticker" sortKey="ticker" active={sortBy === 'ticker'} order={sortOrder} onClick={handleSort} />
                    <th className="px-6 py-4 text-xs font-bold text-gray-500 uppercase tracking-wider">Industry</th>
                    <SortableHeader label="Price" sortKey="price" active={sortBy === 'price'} order={sortOrder} onClick={handleSort} />
                    <SortableHeader label="% Change" sortKey="change_percent" active={sortBy === 'change_percent'} order={sortOrder} onClick={handleSort} />
                    <SortableHeader label="Change $" sortKey="change_value" active={sortBy === 'change_value'} order={sortOrder} onClick={handleSort} />
                    <SortableHeader label="Volume" sortKey="volume" active={sortBy === 'volume'} order={sortOrder} onClick={handleSort} />
                    <th className="px-6 py-4 text-xs font-bold text-gray-500 uppercase tracking-wider text-right">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-800">
                  {filteredMovers.map((mover) => (
                    <tr key={mover.ticker} className="hover:bg-gray-800/30 transition-colors group">
                      <td className="px-6 py-4">
                        <div className="flex items-center">
                          <div className="h-8 w-8 rounded-full bg-financial-blue/10 flex items-center justify-center mr-3">
                            <span className="text-financial-blue font-bold text-xs">{mover.ticker[0]}</span>
                          </div>
                          <div>
                            <Ticker ticker={mover.ticker} className="block" />
                            <span className="text-gray-500 text-xs truncate max-w-[150px] block">
                              {mover.market_cap ? `$${(mover.market_cap / 1e9).toFixed(1)}B` : ''} 
                              {mover.market_cap && mover.name ? ' • ' : ''}
                              {mover.name || 'Stock'}
                            </span>
                          </div>
                        </div>
                      </td>
                      <td className="px-6 py-4">
                        <span className="text-gray-400 text-sm truncate max-w-[120px] block">
                          {mover.sector || 'N/A'}
                        </span>
                      </td>
                      <td className="px-6 py-4 text-financial-light font-medium">
                        ${mover.price.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                      </td>
                      <td className="px-6 py-4">
                        <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-bold ${
                          mover.change_percent >= 0 ? 'bg-positive/10 text-positive' : 'bg-negative/10 text-negative'
                        }`}>
                          {mover.change_percent >= 0 ? <TrendingUp className="h-3 w-3 mr-1" /> : <TrendingDown className="h-3 w-3 mr-1" />}
                          {mover.change_percent >= 0 ? '+' : ''}{mover.change_percent.toFixed(2)}%
                        </span>
                      </td>
                      <td className="px-6 py-4">
                        <span className={`text-sm ${mover.change_value >= 0 ? 'text-positive' : 'text-negative'}`}>
                          {mover.change_value >= 0 ? '+' : ''}${mover.change_value.toFixed(2)}
                        </span>
                      </td>
                      <td className="px-6 py-4">
                        <div className="flex flex-col">
                          <span className="text-financial-light font-medium">{mover.volume.toLocaleString()}</span>
                          <div className="w-24 h-1 bg-gray-700 rounded-full mt-1 overflow-hidden">
                            <div 
                              className="h-full bg-financial-blue" 
                              style={{ width: `${Math.min(100, (mover.volume / (maxVolume?.volume || 1)) * 100)}%` }}
                            />
                          </div>
                        </div>
                      </td>
                      <td className="px-6 py-4 text-right">
                        <Ticker 
                          ticker={mover.ticker}
                          className="px-3 py-1.5 bg-gray-800 hover:bg-financial-blue text-gray-400 hover:text-white rounded-lg"
                        >
                          <span className="mr-2 text-sm">Analyze</span>
                          <ExternalLink className="h-4 w-4" />
                        </Ticker>
                      </td>
                    </tr>
                  ))}
                  {filteredMovers.length === 0 && !loading && (
                    <tr>
                      <td colSpan={6} className="px-6 py-20 text-center text-gray-500 italic">
                        No movers found matching your filters.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      </div>
  );
};

interface SortableHeaderProps {
  label: string;
  sortKey: string;
  active: boolean;
  order: 'asc' | 'desc';
  onClick: (key: string) => void;
}

const SortableHeader: React.FC<SortableHeaderProps> = ({ label, sortKey, active, order, onClick }) => (
  <th 
    className="px-6 py-4 text-xs font-bold text-gray-500 uppercase tracking-wider cursor-pointer hover:text-financial-light transition-colors"
    onClick={() => onClick(sortKey)}
  >
    <div className="flex items-center space-x-1">
      <span>{label}</span>
      <div className="flex flex-col">
        <ChevronUp className={`h-3 w-3 -mb-1 ${active && order === 'asc' ? 'text-financial-blue' : 'text-gray-700'}`} />
        <ChevronDown className={`h-3 w-3 ${active && order === 'desc' ? 'text-financial-blue' : 'text-gray-700'}`} />
      </div>
    </div>
  </th>
);

export default PreMarketMovers;
