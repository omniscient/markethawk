import React from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import Modal from './ui/Modal';
import Button from './ui/Button';
import { RefreshCw, TrendingUp, Calendar, DownloadCloud } from 'lucide-react';
import { StockUniverse, MonitoredStock, refreshUniverseStocks, fetchUniverseStocks, syncUniverseAggregates } from '../api/scanner';

interface UniverseDetailsModalProps {
    isOpen: boolean;
    onClose: () => void;
    universe: StockUniverse | null;
}

const UniverseDetailsModal: React.FC<UniverseDetailsModalProps> = ({
    isOpen,
    onClose,
    universe
}) => {
    const queryClient = useQueryClient();

    // Fetch stocks for this universe
    const { data: stocks, isLoading: stocksLoading, refetch: refetchStocks } = useQuery({
        queryKey: ['universeStocks', universe?.id],
        queryFn: () => fetchUniverseStocks(universe!.id),
        enabled: isOpen && !!universe,
    });

    // Refresh mutation
    const refreshMutation = useMutation({
        mutationFn: () => refreshUniverseStocks(universe!.id),
        onSuccess: () => {
            refetchStocks();
            queryClient.invalidateQueries({ queryKey: ['universeStocks', universe?.id] });
        },
    });

    // Sync mutation
    const syncMutation = useMutation({
        mutationFn: () => {
            // Default to last 7 days for now to keep UI simple
            // In a real app we'd add a date picker
            const end = new Date();
            const start = new Date();
            start.setDate(end.getDate() - 7);

            return syncUniverseAggregates(
                universe!.id,
                start.toISOString().split('T')[0],
                end.toISOString().split('T')[0]
            );
        },
        onSuccess: () => {
            // Maybe show a toast
        }
    });

    if (!universe) return null;

    const formatMarketCap = (cap?: number) => {
        if (!cap) return 'N/A';
        if (cap >= 1e12) return `$${(cap / 1e12).toFixed(2)}T`;
        if (cap >= 1e9) return `$${(cap / 1e9).toFixed(2)}B`;
        if (cap >= 1e6) return `$${(cap / 1e6).toFixed(2)}M`;
        return `$${cap.toLocaleString()}`;
    };

    return (
        <Modal
            isOpen={isOpen}
            onClose={onClose}
            title={universe.name}
            footer={
                <div className="flex justify-between w-full">
                    <Button
                        variant="primary"
                        icon={RefreshCw}
                        onClick={() => refreshMutation.mutate()}
                        disabled={refreshMutation.isPending}
                    >
                        {refreshMutation.isPending ? 'Refreshing...' : 'Refresh Stocks'}
                    </Button>

                    <Button
                        variant="secondary"
                        icon={DownloadCloud}
                        onClick={() => {
                            if (confirm("Sync pre-market aggregates for the last 7 days for all stocks?")) {
                                syncMutation.mutate();
                            }
                        }}
                        disabled={syncMutation.isPending}
                    >
                        {syncMutation.isPending ? 'Syncing...' : 'Sync Data'}
                    </Button>

                    <Button variant="secondary" onClick={onClose}>Close</Button>
                </div>
            }
        >
            <div className="space-y-6">
                <div>
                    <h4 className="text-sm font-medium text-gray-400 mb-1">Description</h4>
                    <p className="text-financial-light">
                        {universe.description || 'No description provided.'}
                    </p>
                </div>

                <div className="grid grid-cols-2 gap-4">
                    <div>
                        <h4 className="text-sm font-medium text-gray-400 mb-1">Created At</h4>
                        <p className="text-financial-light">
                            {new Date(universe.created_at).toLocaleString()}
                        </p>
                    </div>
                    <div>
                        <h4 className="text-sm font-medium text-gray-400 mb-1">Status</h4>
                        <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${universe.is_active
                            ? 'bg-green-500/20 text-green-400'
                            : 'bg-red-500/20 text-red-400'
                            }`}>
                            {universe.is_active ? 'Active' : 'Inactive'}
                        </span>
                    </div>
                </div>

                <div>
                    <h4 className="text-sm font-medium text-gray-400 mb-2">Criteria</h4>
                    <div className="bg-gray-800 rounded-lg p-4 border border-gray-700">
                        <pre className="text-xs text-green-400 font-mono overflow-auto max-h-40">
                            {JSON.stringify(universe.criteria, null, 2)}
                        </pre>
                    </div>
                </div>

                <div>
                    <div className="flex items-center justify-between mb-3">
                        <h4 className="text-sm font-medium text-gray-400 flex items-center gap-2">
                            <TrendingUp className="h-4 w-4" />
                            Stocks in Universe
                            {stocks && (
                                <span className="bg-financial-blue/20 text-financial-blue px-2 py-0.5 rounded-full text-xs">
                                    {stocks.length}
                                </span>
                            )}
                        </h4>
                    </div>

                    {refreshMutation.isSuccess && (
                        <div className="mb-3 p-3 bg-green-500/10 border border-green-500/30 rounded-lg text-green-400 text-sm">
                            {refreshMutation.data?.message}
                        </div>
                    )}

                    {syncMutation.isSuccess && (
                        <div className="mb-3 p-3 bg-blue-500/10 border border-blue-500/30 rounded-lg text-blue-400 text-sm">
                            {syncMutation.data?.message}
                        </div>
                    )}

                    {stocksLoading ? (
                        <div className="text-center py-8 text-gray-400">
                            Loading stocks...
                        </div>
                    ) : stocks && stocks.length > 0 ? (
                        <div className="bg-gray-800 rounded-lg border border-gray-700 overflow-hidden">
                            <table className="w-full text-sm">
                                <thead className="bg-gray-700/50">
                                    <tr>
                                        <th className="text-left px-4 py-2 text-gray-400 font-medium">Ticker</th>
                                        <th className="text-left px-4 py-2 text-gray-400 font-medium">Company</th>
                                        <th className="text-left px-4 py-2 text-gray-400 font-medium">Sector</th>
                                        <th className="text-right px-4 py-2 text-gray-400 font-medium">Market Cap</th>
                                    </tr>
                                </thead>
                                <tbody className="divide-y divide-gray-700">
                                    {stocks.map((stock: MonitoredStock) => (
                                        <tr key={stock.id} className="hover:bg-gray-700/30 transition-colors">
                                            <td className="px-4 py-2 text-financial-blue font-semibold">{stock.ticker}</td>
                                            <td className="px-4 py-2 text-financial-light">{stock.company_name || 'N/A'}</td>
                                            <td className="px-4 py-2 text-gray-400">{stock.sector || 'N/A'}</td>
                                            <td className="px-4 py-2 text-right text-financial-light">
                                                {formatMarketCap(stock.market_cap)}
                                            </td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    ) : (
                        <div className="text-center py-8 bg-gray-800 rounded-lg border border-gray-700">
                            <p className="text-gray-400 mb-2">No stocks in this universe yet.</p>
                            <p className="text-gray-500 text-sm">Click "Refresh Stocks" to scan for matching stocks.</p>
                        </div>
                    )}
                </div>
            </div>
        </Modal>
    );
};

export default UniverseDetailsModal;
