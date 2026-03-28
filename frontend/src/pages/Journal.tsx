import React, { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { 
  BookOpen, 
  Plus, 
  Download, 
  TrendingUp, 
  TrendingDown, 
  Target, 
  Activity,
  MessageSquare,
  Tag as TagIcon,
  PlusCircle
} from 'lucide-react';

// Components
import Card from '../components/ui/Card';
import Button from '../components/ui/Button';
import MetricCard from '../components/ui/MetricCard';
import Modal from '../components/ui/Modal';

// API
import { journalApi, Trade, TradeStats } from '../api/journal';

const Journal: React.FC = () => {
  const queryClient = useQueryClient();
  
  // Modals state
  const [isImportModalOpen, setIsImportModalOpen] = useState(false);
  const [isEntryModalOpen, setIsEntryModalOpen] = useState(false);
  const [isManualTradeModalOpen, setIsManualTradeModalOpen] = useState(false);

  // Import state
  const [selectedBroker, setSelectedBroker] = useState('TOS');
  const [importFile, setImportFile] = useState<File | null>(null);

  // New Entry state
  const [newEntryContent, setNewEntryContent] = useState('');
  const [newEntrySentiment, setNewEntrySentiment] = useState('neutral');

  // Manual Trade state
  const [manualTrade, setManualTrade] = useState({
    symbol: '',
    side: 'long',
    status: 'open',
    open_date: new Date().toISOString().split('T')[0],
    quantity: 0,
    avg_entry_price: 0,
    avg_exit_price: 0,
    net_pnl: 0,
    notes: ''
  });

  // Queries
  const { data: trades, isLoading: loadingTrades } = useQuery({
    queryKey: ['journalTrades'],
    queryFn: () => journalApi.getTrades(),
  });

  const { data: stats, isLoading: loadingStats } = useQuery({
    queryKey: ['journalStats'],
    queryFn: journalApi.getStats,
  });

  const { data: entries, isLoading: loadingEntries } = useQuery({
    queryKey: ['journalEntries'],
    queryFn: journalApi.getEntries,
  });

  // Mutations
  const importMutation = useMutation({
    mutationFn: ({ file, broker }: { file: File, broker: string }) => 
      journalApi.importTrades(file, broker),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['journalTrades'] });
      queryClient.invalidateQueries({ queryKey: ['journalStats'] });
      setIsImportModalOpen(false);
      setImportFile(null);
    }
  });

  const createEntryMutation = useMutation({
    mutationFn: (data: any) => journalApi.createEntry(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['journalEntries'] });
      setIsEntryModalOpen(false);
      setNewEntryContent('');
    }
  });

  const createTradeMutation = useMutation({
    mutationFn: (data: any) => journalApi.createTrade(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['journalTrades'] });
      queryClient.invalidateQueries({ queryKey: ['journalStats'] });
      setIsManualTradeModalOpen(false);
      setManualTrade({
        symbol: '',
        side: 'long',
        status: 'open',
        open_date: new Date().toISOString().split('T')[0],
        quantity: 0,
        avg_entry_price: 0,
        avg_exit_price: 0,
        net_pnl: 0,
        notes: ''
      });
    }
  });

  const handleImport = () => {
    if (importFile) {
      importMutation.mutate({ file: importFile, broker: selectedBroker });
    }
  };

  const handleCreateEntry = () => {
    createEntryMutation.mutate({
      entry_date: new Date().toISOString().split('T')[0],
      content: newEntryContent,
      sentiment: newEntrySentiment
    });
  };

  const handleCreateManualTrade = () => {
    createTradeMutation.mutate({
      ...manualTrade,
      symbol: manualTrade.symbol.toUpperCase(),
      open_date: new Date(manualTrade.open_date).toISOString()
    });
  };

  return (
    <div className="space-y-6 animate-fade-in">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-financial-light">Trade Journal</h1>
          <p className="text-gray-400 mt-1">Track and analyze your trading performance</p>
        </div>
        <div className="flex items-center space-x-3">
          <Button 
            variant="secondary" 
            icon={Download as any}
            onClick={() => setIsImportModalOpen(true)}
          >
            Import
          </Button>
          <Button 
            variant="secondary" 
            icon={PlusCircle as any}
            onClick={() => setIsManualTradeModalOpen(true)}
          >
            Manual Trade
          </Button>
          <Button 
            variant="primary" 
            icon={Plus as any}
            onClick={() => setIsEntryModalOpen(true)}
          >
            New Entry
          </Button>
        </div>
      </div>

      {/* Stats Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        <MetricCard
          title="Total PnL"
          value={`$${stats?.total_pnl?.toLocaleString() || '0'}`}
          color={stats?.total_pnl && stats.total_pnl > 0 ? 'green' : 'red'}
          icon={Activity as any}
        />
        <MetricCard
          title="Win Rate"
          value={`${((stats?.win_rate || 0) * 100).toFixed(1)}%`}
          color={(stats?.win_rate || 0) >= 0.5 ? 'green' : 'yellow'}
          icon={Target as any}
        />
        <MetricCard
          title="Profit Factor"
          value={stats?.profit_factor?.toFixed(2) || '0.00'}
          icon={TrendingUp as any}
        />
        <MetricCard
          title="Avg Profit"
          value={`$${stats?.avg_profit?.toFixed(2) || '0'}`}
          icon={TrendingDown as any}
        />
      </div>

      {/* Main Content */}
      <div className="grid grid-cols-1 xl:grid-cols-3 gap-6">
        <div className="xl:col-span-2">
          <Card title="Trade History" icon={BookOpen as any}>
            <div className="overflow-x-auto">
              <table className="w-full text-left">
                <thead>
                  <tr className="border-b border-gray-700 text-gray-400 text-sm">
                    <th className="pb-3 font-medium">Symbol</th>
                    <th className="pb-3 font-medium">Side</th>
                    <th className="pb-3 font-medium">Open Date</th>
                    <th className="pb-3 font-medium">Net PnL</th>
                    <th className="pb-3 font-medium">Return %</th>
                    <th className="pb-3 font-medium">Tags</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-800">
                  {trades?.map((trade) => (
                    <tr key={trade.id} className="hover:bg-gray-800/50 transition-colors cursor-pointer">
                      <td className="py-4 font-bold text-financial-light">{trade.symbol}</td>
                      <td className="py-4">
                        <span className={`px-2 py-1 rounded text-xs font-medium ${
                          trade.side === 'long' ? 'bg-green-500/20 text-green-400' : 'bg-red-500/20 text-red-400'
                        }`}>
                          {trade.side?.toUpperCase()}
                        </span>
                      </td>
                      <td className="py-4 text-gray-400 text-sm">
                        {trade.open_date ? new Date(trade.open_date).toLocaleDateString() : '-'}
                      </td>
                      <td className={`py-4 font-medium ${
                        (trade.net_pnl || 0) >= 0 ? 'text-financial-green' : 'text-financial-red'
                      }`}>
                        ${trade.net_pnl?.toLocaleString() || '0'}
                      </td>
                      <td className={`py-4 text-sm ${
                        (trade.return_pct || 0) >= 0 ? 'text-financial-green' : 'text-financial-red'
                      }`}>
                        {((trade.return_pct || 0) * 100).toFixed(2)}%
                      </td>
                      <td className="py-4">
                        <div className="flex gap-1">
                          {trade.tags.map(tag => (
                            <span key={tag.id} className="px-1.5 py-0.5 rounded bg-gray-700 text-[10px] text-gray-300">
                              {tag.name}
                            </span>
                          ))}
                        </div>
                      </td>
                    </tr>
                  ))}
                  {(!trades || trades.length === 0) && !loadingTrades && (
                    <tr>
                      <td colSpan={6} className="py-10 text-center text-gray-500">
                        No trades found. Import or add some data to get started!
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </Card>
        </div>

        <div className="xl:col-span-1">
          <Card title="Recent Notes" icon={MessageSquare as any}>
            <div className="space-y-4">
              {entries?.map((entry) => (
                <div key={entry.id} className="p-3 bg-gray-800/40 rounded border border-gray-700">
                  <div className="flex justify-between items-start mb-2">
                    <span className="text-financial-blue text-xs font-semibold">
                      {new Date(entry.entry_date).toLocaleDateString()}
                    </span>
                    <span className={`text-[10px] px-1.5 py-0.5 rounded ${
                      entry.sentiment === 'bullish' ? 'bg-green-500/20 text-green-400' : 
                      entry.sentiment === 'bearish' ? 'bg-red-500/20 text-red-400' : 'bg-gray-700 text-gray-400'
                    }`}>
                      {entry.sentiment?.toUpperCase()}
                    </span>
                  </div>
                  <p className="text-gray-300 text-sm line-clamp-3">{entry.content}</p>
                </div>
              ))}
              {(!entries || entries.length === 0) && !loadingEntries && (
                <div className="text-center py-6 text-gray-500 text-sm">
                  No notes recorded yet.
                </div>
              )}
            </div>
          </Card>
        </div>
      </div>

      {/* Manual Trade Modal */}
      <Modal
        isOpen={isManualTradeModalOpen}
        onClose={() => setIsManualTradeModalOpen(false)}
        title="Manual Trade Entry"
      >
        <div className="grid grid-cols-2 gap-4">
          <div className="col-span-1">
            <label className="block text-xs font-medium text-gray-400 mb-1">Symbol</label>
            <input 
              type="text"
              placeholder="e.g. AAPL"
              className="w-full bg-gray-800 border border-gray-700 rounded p-2 text-sm text-white uppercase"
              value={manualTrade.symbol}
              onChange={(e) => setManualTrade({...manualTrade, symbol: e.target.value})}
            />
          </div>
          <div className="col-span-1">
            <label className="block text-xs font-medium text-gray-400 mb-1">Side</label>
            <div className="flex space-x-1">
              {['long', 'short'].map(s => (
                <button
                  key={s}
                  onClick={() => setManualTrade({...manualTrade, side: s})}
                  className={`flex-1 py-1.5 rounded text-[10px] font-bold uppercase transition-colors ${
                    manualTrade.side === s ? 'bg-financial-blue text-white' : 'bg-gray-800 text-gray-400 border border-gray-700'
                  }`}
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
          <div className="col-span-1">
            <label className="block text-xs font-medium text-gray-400 mb-1">Date</label>
            <input 
              type="date"
              className="w-full bg-gray-800 border border-gray-700 rounded p-2 text-sm text-white"
              value={manualTrade.open_date}
              onChange={(e) => setManualTrade({...manualTrade, open_date: e.target.value})}
            />
          </div>
          <div className="col-span-1">
            <label className="block text-xs font-medium text-gray-400 mb-1">Status</label>
            <select
              className="w-full bg-gray-800 border border-gray-700 rounded p-2 text-sm text-white"
              value={manualTrade.status}
              onChange={(e) => setManualTrade({...manualTrade, status: e.target.value})}
            >
              <option value="open">Open</option>
              <option value="closed">Closed</option>
            </select>
          </div>
          <div className="col-span-1">
            <label className="block text-xs font-medium text-gray-400 mb-1">Entry Price</label>
            <input 
              type="number"
              step="0.01"
              className="w-full bg-gray-800 border border-gray-700 rounded p-2 text-sm text-white"
              value={manualTrade.avg_entry_price}
              onChange={(e) => setManualTrade({...manualTrade, avg_entry_price: parseFloat(e.target.value)})}
            />
          </div>
          <div className="col-span-1">
            <label className="block text-xs font-medium text-gray-400 mb-1">Quantity</label>
            <input 
              type="number"
              className="w-full bg-gray-800 border border-gray-700 rounded p-2 text-sm text-white"
              value={manualTrade.quantity}
              onChange={(e) => setManualTrade({...manualTrade, quantity: parseFloat(e.target.value)})}
            />
          </div>
          {manualTrade.status === 'closed' && (
            <>
              <div className="col-span-1">
                <label className="block text-xs font-medium text-gray-400 mb-1">Exit Price</label>
                <input 
                  type="number"
                  step="0.01"
                  className="w-full bg-gray-800 border border-gray-700 rounded p-2 text-sm text-white"
                  value={manualTrade.avg_exit_price}
                  onChange={(e) => setManualTrade({...manualTrade, avg_exit_price: parseFloat(e.target.value)})}
                />
              </div>
              <div className="col-span-1">
                <label className="block text-xs font-medium text-gray-400 mb-1">Net PnL ($)</label>
                <input 
                  type="number"
                  step="0.01"
                  className="w-full bg-gray-800 border border-gray-700 rounded p-2 text-sm text-white"
                  value={manualTrade.net_pnl}
                  onChange={(e) => setManualTrade({...manualTrade, net_pnl: parseFloat(e.target.value)})}
                />
              </div>
            </>
          )}
          <div className="col-span-2">
            <label className="block text-xs font-medium text-gray-400 mb-1">Notes</label>
            <textarea
              className="w-full bg-gray-800 border border-gray-700 rounded p-2 text-sm text-white h-20"
              value={manualTrade.notes}
              onChange={(e) => setManualTrade({...manualTrade, notes: e.target.value})}
            />
          </div>
          <div className="col-span-2 flex justify-end space-x-3 pt-4">
            <Button variant="secondary" onClick={() => setIsManualTradeModalOpen(false)}>Cancel</Button>
            <Button 
              variant="primary" 
              onClick={handleCreateManualTrade}
              disabled={!manualTrade.symbol}
              loading={createTradeMutation.isPending}
            >
              Add Trade
            </Button>
          </div>
        </div>
      </Modal>

      {/* Import Modal */}
      <Modal
        isOpen={isImportModalOpen}
        onClose={() => setIsImportModalOpen(false)}
        title="Import Trades"
      >
        <div className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-400 mb-1">Select Broker</label>
            <select 
              className="w-full bg-gray-800 border border-gray-700 rounded-md p-2 text-financial-light"
              value={selectedBroker}
              onChange={(e) => setSelectedBroker(e.target.value)}
            >
              <option value="TOS">Thinkorswim (TOS)</option>
              <option value="ETrade">E*Trade</option>
              <option value="Fidelity">Fidelity</option>
              <option value="Generic">Generic CSV</option>
            </select>
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-400 mb-1">Upload CSV File</label>
            <input 
              type="file" 
              accept=".csv"
              className="w-full text-gray-400 file:mr-4 file:py-2 file:px-4 file:rounded-md file:border-0 file:text-sm file:font-semibold file:bg-financial-blue file:text-white hover:file:bg-blue-600"
              onChange={(e) => setImportFile(e.target.files?.[0] || null)}
            />
          </div>
          <div className="pt-4 flex justify-end space-x-3">
            <Button variant="secondary" onClick={() => setIsImportModalOpen(false)}>Cancel</Button>
            <Button 
              variant="primary" 
              onClick={handleImport}
              disabled={!importFile}
              loading={importMutation.isPending}
            >
              Start Import
            </Button>
          </div>
        </div>
      </Modal>

      {/* New Entry Modal */}
      <Modal
        isOpen={isEntryModalOpen}
        onClose={() => setIsEntryModalOpen(false)}
        title="Daily Journal Entry"
      >
        <div className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-400 mb-1">Sentiment</label>
            <div className="flex space-x-2">
              {['bullish', 'neutral', 'bearish'].map((s) => (
                <button
                  key={s}
                  onClick={() => setNewEntrySentiment(s)}
                  className={`flex-1 py-2 px-3 rounded-md text-xs font-medium border transition-colors ${
                    newEntrySentiment === s 
                      ? 'bg-financial-blue text-white border-financial-blue' 
                      : 'bg-gray-800 text-gray-400 border-gray-700 hover:bg-gray-700'
                  }`}
                >
                  {s.toUpperCase()}
                </button>
              ))}
            </div>
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-400 mb-1">Notes</label>
            <textarea
              className="w-full bg-gray-800 border border-gray-700 rounded-md p-3 text-financial-light h-32 text-sm focus:outline-none focus:ring-2 focus:ring-financial-blue transition-all"
              placeholder="Record your market thoughts, emotions, or strategy reflections..."
              value={newEntryContent}
              onChange={(e) => setNewEntryContent(e.target.value)}
            />
          </div>
          <div className="pt-4 flex justify-end space-x-3">
            <Button variant="secondary" onClick={() => setIsEntryModalOpen(false)}>Cancel</Button>
            <Button 
              variant="primary" 
              onClick={handleCreateEntry}
              disabled={!newEntryContent.trim()}
              loading={createEntryMutation.isPending}
            >
              Save Entry
            </Button>
          </div>
        </div>
      </Modal>
    </div>
  );
};

export default Journal;
