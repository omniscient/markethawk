import React, { useState, useCallback, useEffect } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  Database,
  Plus,
  Edit,
  Trash2,
  Eye,
  Filter,
  Search,
  DownloadCloud,
  RefreshCw,
  Loader2,
} from 'lucide-react';

// Components
import Card from '../components/ui/Card';
import Button from '../components/ui/Button';
import UniverseFormModal from '../components/UniverseFormModal';
import UniverseDetailsModal from '../components/UniverseDetailsModal';
import SyncUniverseModal from '../components/SyncUniverseModal';
import { StockUniverse } from '../api/scanner';

// API functions
import { fetchStockUniverses, deleteStockUniverse, fetchUniverseSyncStatus, syncMissingAggregates } from '../api/scanner';

const Universes: React.FC = () => {
  const [searchTerm, setSearchTerm] = useState('');
  const [showFormModal, setShowFormModal] = useState(false);
  const [editingUniverse, setEditingUniverse] = useState<StockUniverse | null>(null);
  const [selectedUniverse, setSelectedUniverse] = useState<StockUniverse | null>(null);
  const [syncingUniverse, setSyncingUniverse] = useState<StockUniverse | null>(null);
  // Map of universeId → sync progress info
  const [syncingIds, setSyncingIds] = useState<Record<number, { pending: number; total: number }>>({});
  const queryClient = useQueryClient();

  // Called by SyncUniverseModal when tasks are queued
  const handleSyncStarted = useCallback((universeId: number) => {
    setSyncingIds(prev => ({ ...prev, [universeId]: { pending: 1, total: 1 } }));
  }, []);

  // Poll sync status for all active syncs every 5 seconds
  useEffect(() => {
    const ids = Object.keys(syncingIds).map(Number);
    if (ids.length === 0) return;

    const interval = setInterval(async () => {
      const completed: number[] = [];
      const updates: Record<number, { pending: number; total: number }> = {};

      await Promise.all(
        ids.map(async (id) => {
          try {
            const status = await fetchUniverseSyncStatus(id);
            if (!status.is_syncing) {
              completed.push(id);
            } else {
              // Timeout: if tasks are still "syncing" after 20 min assume stuck/failed
              const stale = status.started_at
                ? Date.now() - new Date(status.started_at).getTime() > 20 * 60 * 1000
                : false;
              if (stale) {
                completed.push(id);
              } else {
                updates[id] = { pending: status.pending, total: status.total };
              }
            }
          } catch {
            completed.push(id); // treat error as done
          }
        })
      );

      if (completed.length > 0) {
        setSyncingIds(prev => {
          const next = { ...prev };
          completed.forEach(id => delete next[id]);
          return next;
        });
        queryClient.invalidateQueries({ queryKey: ['stockUniverses'] });
      }

      if (Object.keys(updates).length > 0) {
        setSyncingIds(prev => ({ ...prev, ...updates }));
      }
    }, 5000);

    return () => clearInterval(interval);
  }, [syncingIds, queryClient]);

  const deleteMutation = useMutation({
    mutationFn: deleteStockUniverse,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['stockUniverses'] });
    },
  });

  const catchUpMutation = useMutation({
    mutationFn: (id: number) => syncMissingAggregates(id),
    onSuccess: (data, id) => {
      if (data.status === 'accepted') {
        handleSyncStarted(id);
      } else {
        // skipped / no data — still refresh stats
        queryClient.invalidateQueries({ queryKey: ['stockUniverses'] });
      }
    },
    onError: () => {
      queryClient.invalidateQueries({ queryKey: ['stockUniverses'] });
    },
  });

  const handleDelete = (id: number) => {
    if (window.confirm('Are you sure you want to delete this universe?')) {
      deleteMutation.mutate(id);
    }
  };

  const { data: universes, isLoading } = useQuery({
    queryKey: ['stockUniverses'],
    queryFn: fetchStockUniverses,
  });

  const filteredUniverses = universes?.filter(universe =>
    universe.name.toLowerCase().includes(searchTerm.toLowerCase()) ||
    universe.description?.toLowerCase().includes(searchTerm.toLowerCase())
  );

  return (
    <div className="space-y-6 animate-fade-in">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-financial-light">Stock Universes</h1>
          <p className="text-gray-400 mt-1">Manage your stock scanning universes and criteria</p>
        </div>
        <Button
          variant="primary"
          icon={Plus}
          onClick={() => {
            setEditingUniverse(null);
            setShowFormModal(true);
          }}
        >
          Create Universe
        </Button>
      </div>

      {/* Search and Filter */}
      <div className="flex flex-col md:flex-row gap-4">
        <div className="flex-1">
          <div className="relative">
            <Search className="absolute left-3 top-3 h-4 w-4 text-gray-400" />
            <input
              type="text"
              placeholder="Search universes..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              className="w-full pl-10 pr-4 py-2 bg-gray-800 border border-gray-700 rounded-lg text-financial-light focus:outline-none focus:ring-2 focus:ring-financial-blue"
            />
          </div>
        </div>
        <div className="flex items-center space-x-2">
          <Button variant="secondary" icon={Filter}>
            Filter
          </Button>
        </div>
      </div>

      {/* Universes Grid */}
      {isLoading ? (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {[1, 2, 3].map((i) => (
            <Card key={i} className="animate-pulse">
              <div className="h-6 bg-gray-700 rounded w-3/4 mb-4"></div>
              <div className="h-4 bg-gray-700 rounded w-full mb-2"></div>
              <div className="h-4 bg-gray-700 rounded w-2/3"></div>
            </Card>
          ))}
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {filteredUniverses?.map((universe) => {
            const sync = syncingIds[universe.id];
            const isSyncing = !!sync;
            return (
            <Card key={universe.id} className={`hover:border-financial-blue/50 transition-colors ${isSyncing ? 'border-yellow-500/40' : ''}`}>
              <div className="flex items-start justify-between mb-4">
                <div className="flex items-center space-x-2">
                  <Database className={`h-5 w-5 ${isSyncing ? 'text-yellow-400' : 'text-financial-blue'}`} />
                  <h3 className="text-lg font-semibold text-financial-light">
                    {universe.name}
                  </h3>
                </div>
                <div className="flex items-center gap-2">
                  {isSyncing && (
                    <span className="flex items-center gap-1 px-2 py-1 rounded text-xs font-medium bg-yellow-500/20 text-yellow-400">
                      <Loader2 className="h-3 w-3 animate-spin" />
                      {sync.total > 1 ? `${sync.pending}/${sync.total}` : 'Syncing'}
                    </span>
                  )}
                  <span className={`px-2 py-1 rounded text-xs font-medium ${universe.is_active
                    ? 'bg-green-500/20 text-green-400'
                    : 'bg-gray-500/20 text-gray-400'
                    }`}>
                    {universe.is_active ? 'Active' : 'Inactive'}
                  </span>
                </div>
              </div>

              <p className="text-gray-400 text-sm mb-4">
                {universe.description || 'No description available'}
              </p>

              <div className="space-y-2 mb-4">
                <div className="flex justify-between text-sm">
                  <span className="text-gray-400">Created:</span>
                  <span className="text-financial-light">
                    {new Date(universe.created_at).toLocaleDateString()}
                  </span>
                </div>
                <div className="flex justify-between text-sm">
                  <span className="text-gray-400">Criteria Count:</span>
                  <span className="text-financial-light">
                    {Object.keys(universe.criteria).length}
                  </span>
                </div>
                {/* New Stats */}
                <div className="flex justify-between text-sm">
                                            <span className="text-gray-400">Instrument Count:</span>
                  <span className="text-financial-light">
                    {universe.ticker_count || 0}
                  </span>
                </div>
                <div className="flex justify-between text-sm">
                  <span className="text-gray-400">Aggregate Records:</span>
                  <span className="text-financial-light">
                    {universe.aggregate_count?.toLocaleString() || 0}
                  </span>
                </div>
                <div className="flex justify-between text-sm">
                  <span className="text-gray-400">Min Date:</span>
                  <span className="text-financial-light">
                    {universe.min_aggregate_date ? new Date(universe.min_aggregate_date).toLocaleDateString() : 'N/A'}
                  </span>
                </div>
                <div className="flex justify-between text-sm">
                  <span className="text-gray-400">Max Date:</span>
                  <span className="text-financial-light">
                    {universe.max_aggregate_date ? new Date(universe.max_aggregate_date).toLocaleDateString() : 'N/A'}
                  </span>
                </div>
                {universe.available_timespans && universe.available_timespans.length > 0 && (
                  <div className="flex justify-between text-sm">
                    <span className="text-gray-400">Timespans:</span>
                    <span className="flex gap-1">
                      {universe.available_timespans.map(ts => (
                        <span key={ts} className="px-1.5 py-0.5 bg-financial-blue/20 text-financial-blue rounded text-[10px] font-mono uppercase">
                          {ts}
                        </span>
                      ))}
                    </span>
                  </div>
                )}
              </div>

              <div className="flex flex-wrap gap-2">
                <Button
                  variant="secondary"
                  size="sm"
                  icon={DownloadCloud}
                  onClick={() => setSyncingUniverse(universe)}
                  disabled={isSyncing}
                >
                  <span className="hidden xl:inline">Sync</span>
                </Button>
                {(universe.aggregate_count ?? 0) > 0 && (
                  <Button
                    variant="secondary"
                    size="sm"
                    icon={catchUpMutation.isPending && catchUpMutation.variables === universe.id ? Loader2 : RefreshCw}
                    onClick={() => catchUpMutation.mutate(universe.id)}
                    disabled={isSyncing || catchUpMutation.isPending}
                    title="Fetch missing bars for all recorded timespans up to today"
                  >
                    <span className="hidden xl:inline">Catch Up</span>
                  </Button>
                )}
                <Button
                  variant="secondary"
                  size="sm"
                  icon={Eye}
                  onClick={() => setSelectedUniverse(universe)}
                >
                  <span className="hidden xl:inline">View</span>
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => {
                    setEditingUniverse(universe);
                    setShowFormModal(true);
                  }}
                >
                  <Edit className="h-4 w-4 xl:mr-2" />
                  <span className="hidden xl:inline">Edit</span>
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  className="text-red-400 hover:text-red-300"
                  onClick={() => handleDelete(universe.id)}
                >
                  <Trash2 className="h-4 w-4 xl:mr-2" />
                  <span className="hidden xl:inline">Delete</span>
                </Button>
              </div>
            </Card>
            );
          })}
        </div>
      )}

      {/* Empty State */}
      {!isLoading && filteredUniverses?.length === 0 && (
        <Card className="text-center py-12">
          <Database className="h-16 w-16 text-gray-600 mx-auto mb-4" />
          <h3 className="text-xl font-semibold text-financial-light mb-2">
            No Universes Found
          </h3>
          <p className="text-gray-400 mb-6">
            {searchTerm
              ? 'No universes match your search criteria.'
              : 'Create your first stock universe to get started.'}
          </p>
          <Button
            variant="primary"
            icon={Plus}
            onClick={() => {
              setEditingUniverse(null);
              setShowFormModal(true);
            }}
          >
            Create Universe
          </Button>
        </Card>
      )}

      <UniverseFormModal
        isOpen={showFormModal}
        onClose={() => setShowFormModal(false)}
        initialData={editingUniverse}
      />

      <UniverseDetailsModal
        isOpen={!!selectedUniverse}
        onClose={() => setSelectedUniverse(null)}
        universe={selectedUniverse}
      />

      <SyncUniverseModal
        isOpen={!!syncingUniverse}
        onClose={() => setSyncingUniverse(null)}
        universe={syncingUniverse}
        onSyncStarted={(id) => handleSyncStarted(id)}
      />
    </div>
  );
};

export default Universes;