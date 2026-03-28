import React, { useState, useMemo } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import Modal from './ui/Modal';
import Button from './ui/Button';
import { RefreshCw, TrendingUp, Search, ChevronUp, ChevronDown, ChevronsUpDown } from 'lucide-react';
import { StockUniverse, MonitoredStock, refreshUniverseStocks, fetchUniverseStocks } from '../api/scanner';

type SortField = 'ticker' | 'company_name' | 'sector' | 'market_cap';
type SortDirection = 'asc' | 'desc';

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
    const [searchTerm, setSearchTerm] = useState('');
    const [sortField, setSortField] = useState<SortField>('ticker');
    const [sortDirection, setSortDirection] = useState<SortDirection>('asc');

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
            // Also refresh the parent universe list so cards show updated ticker counts
            queryClient.invalidateQueries({ queryKey: ['stockUniverses'] });
        },
    });

    // Filter and sort stocks
    const filteredAndSortedStocks = useMemo(() => {
        if (!stocks) return [];

        // Filter
        const lowerSearch = searchTerm.toLowerCase().trim();
        const filtered = lowerSearch
            ? stocks.filter((stock: MonitoredStock) =>
                stock.ticker.toLowerCase().includes(lowerSearch) ||
                (stock.company_name?.toLowerCase().includes(lowerSearch)) ||
                (stock.sector?.toLowerCase().includes(lowerSearch))
            )
            : stocks;

        // Sort
        const sorted = [...filtered].sort((a: MonitoredStock, b: MonitoredStock) => {
            let valA: string | number;
            let valB: string | number;

            switch (sortField) {
                case 'ticker':
                    valA = a.ticker.toLowerCase();
                    valB = b.ticker.toLowerCase();
                    break;
                case 'company_name':
                    valA = (a.company_name || '').toLowerCase();
                    valB = (b.company_name || '').toLowerCase();
                    break;
                case 'sector':
                    valA = (a.sector || '').toLowerCase();
                    valB = (b.sector || '').toLowerCase();
                    break;
                case 'market_cap':
                    valA = a.market_cap || 0;
                    valB = b.market_cap || 0;
                    break;
                default:
                    return 0;
            }

            if (valA < valB) return sortDirection === 'asc' ? -1 : 1;
            if (valA > valB) return sortDirection === 'asc' ? 1 : -1;
            return 0;
        });

        return sorted;
    }, [stocks, searchTerm, sortField, sortDirection]);

    const handleSort = (field: SortField) => {
        if (sortField === field) {
            setSortDirection(prev => prev === 'asc' ? 'desc' : 'asc');
        } else {
            setSortField(field);
            setSortDirection('asc');
        }
    };

    const SortIcon: React.FC<{ field: SortField }> = ({ field }) => {
        if (sortField !== field) {
            return <ChevronsUpDown className="h-3.5 w-3.5 text-gray-500 ml-1 inline-block" />;
        }
        return sortDirection === 'asc'
            ? <ChevronUp className="h-3.5 w-3.5 text-financial-blue ml-1 inline-block" />
            : <ChevronDown className="h-3.5 w-3.5 text-financial-blue ml-1 inline-block" />;
    };

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
                                    {searchTerm && filteredAndSortedStocks.length !== stocks.length
                                        ? `${filteredAndSortedStocks.length} / ${stocks.length}`
                                        : stocks.length}
                                </span>
                            )}
                        </h4>
                    </div>

                    {/* Search bar */}
                    {stocks && stocks.length > 0 && (
                        <div className="relative mb-3">
                            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400" />
                            <input
                                id="universe-stock-search"
                                type="text"
                                placeholder="Search by ticker, company, or sector..."
                                value={searchTerm}
                                onChange={(e) => setSearchTerm(e.target.value)}
                                className="w-full pl-10 pr-4 py-2 bg-gray-800 border border-gray-700 rounded-lg text-financial-light placeholder-gray-500 text-sm focus:outline-none focus:ring-2 focus:ring-financial-blue focus:border-transparent transition-all"
                            />
                            {searchTerm && (
                                <button
                                    onClick={() => setSearchTerm('')}
                                    className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-200 text-sm transition-colors"
                                    aria-label="Clear search"
                                >
                                    ✕
                                </button>
                            )}
                        </div>
                    )}

                    {refreshMutation.isSuccess && (
                        <div className="mb-3 p-3 bg-green-500/10 border border-green-500/30 rounded-lg text-green-400 text-sm">
                            {refreshMutation.data?.message}
                        </div>
                    )}

                    {stocksLoading ? (
                        <div className="text-center py-8 text-gray-400">
                            Loading stocks...
                        </div>
                    ) : stocks && stocks.length > 0 ? (
                        filteredAndSortedStocks.length > 0 ? (
                            <div className="bg-gray-800 rounded-lg border border-gray-700 overflow-hidden">
                                <table className="w-full text-sm">
                                    <thead className="bg-gray-700/50">
                                        <tr>
                                            <th
                                                className="text-left px-4 py-2 text-gray-400 font-medium cursor-pointer select-none hover:text-financial-light transition-colors"
                                                onClick={() => handleSort('ticker')}
                                            >
                                                Ticker<SortIcon field="ticker" />
                                            </th>
                                            <th
                                                className="text-left px-4 py-2 text-gray-400 font-medium cursor-pointer select-none hover:text-financial-light transition-colors"
                                                onClick={() => handleSort('company_name')}
                                            >
                                                Company<SortIcon field="company_name" />
                                            </th>
                                            <th
                                                className="text-left px-4 py-2 text-gray-400 font-medium cursor-pointer select-none hover:text-financial-light transition-colors"
                                                onClick={() => handleSort('sector')}
                                            >
                                                Sector<SortIcon field="sector" />
                                            </th>
                                            <th
                                                className="text-right px-4 py-2 text-gray-400 font-medium cursor-pointer select-none hover:text-financial-light transition-colors"
                                                onClick={() => handleSort('market_cap')}
                                            >
                                                Market Cap<SortIcon field="market_cap" />
                                            </th>
                                        </tr>
                                    </thead>
                                    <tbody className="divide-y divide-gray-700">
                                        {filteredAndSortedStocks.map((stock: MonitoredStock) => (
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
                                <Search className="h-8 w-8 text-gray-600 mx-auto mb-2" />
                                <p className="text-gray-400 mb-1">No stocks match "<span className="text-financial-light">{searchTerm}</span>"</p>
                                <p className="text-gray-500 text-sm">Try a different ticker, company name, or sector.</p>
                            </div>
                        )
                    ) : (
                        <div className="text-center py-8 bg-gray-800 rounded-lg border border-gray-700">
                            <p className="text-gray-400 mb-2">No stocks in this universe yet.</p>
                            <p className="text-gray-500 text-sm">Click "Refresh Stocks" to scan for matching stocks.</p>
                        </div>
                    )}
                </div>
            </div>
        </Modal >
    );
};

export default UniverseDetailsModal;
