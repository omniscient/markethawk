import React, { useState, useCallback, useRef, useEffect } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  Database,
  Plus,
  Edit,
  Trash2,
  Eye,
  Filter,
  Search,
  DownloadCloud
} from 'lucide-react';

// Components
import Card from '../components/ui/Card';
import Button from '../components/ui/Button';
import UniverseFormModal from '../components/UniverseFormModal';
import UniverseDetailsModal from '../components/UniverseDetailsModal';
import SyncUniverseModal from '../components/SyncUniverseModal';
import { StockUniverse } from '../api/scanner';

// API functions
import { fetchStockUniverses, deleteStockUniverse } from '../api/scanner';

const Universes: React.FC = () => {
  const [searchTerm, setSearchTerm] = useState('');
  const [showFormModal, setShowFormModal] = useState(false);
  const [editingUniverse, setEditingUniverse] = useState<StockUniverse | null>(null);
  const [selectedUniverse, setSelectedUniverse] = useState<StockUniverse | null>(null);
  const [syncingUniverse, setSyncingUniverse] = useState<StockUniverse | null>(null);
  const [isPolling, setIsPolling] = useState(false);
  const pollingTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const queryClient = useQueryClient();

  // Start polling after a sync is triggered so the UI updates as background tasks complete
  const handleSyncStarted = useCallback(() => {
    setIsPolling(true);
    // Stop polling after 2 minutes
    if (pollingTimerRef.current) clearTimeout(pollingTimerRef.current);
    pollingTimerRef.current = setTimeout(() => setIsPolling(false), 2 * 60 * 1000);
  }, []);

  // Clean up timer on unmount
  useEffect(() => {
    return () => {
      if (pollingTimerRef.current) clearTimeout(pollingTimerRef.current);
    };
  }, []);

  const deleteMutation = useMutation({
    mutationFn: deleteStockUniverse,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['stockUniverses'] });
    },
  });

  const handleDelete = (id: number) => {
    if (window.confirm('Are you sure you want to delete this universe?')) {
      deleteMutation.mutate(id);
    }
  };

  // Fetch stock universes (polls every 10s while a sync is in progress)
  const { data: universes, isLoading } = useQuery({
    queryKey: ['stockUniverses'],
    queryFn: fetchStockUniverses,
    refetchInterval: isPolling ? 10_000 : false,
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
          {filteredUniverses?.map((universe) => (
            <Card key={universe.id} className="hover:border-financial-blue/50 transition-colors">
              <div className="flex items-start justify-between mb-4">
                <div className="flex items-center space-x-2">
                  <Database className="h-5 w-5 text-financial-blue" />
                  <h3 className="text-lg font-semibold text-financial-light">
                    {universe.name}
                  </h3>
                </div>
                <span className={`px-2 py-1 rounded text-xs font-medium ${universe.is_active
                  ? 'bg-green-500/20 text-green-400'
                  : 'bg-gray-500/20 text-gray-400'
                  }`}>
                  {universe.is_active ? 'Active' : 'Inactive'}
                </span>
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
              </div>

              <div className="flex flex-wrap gap-2">
                <Button
                  variant="secondary"
                  size="sm"
                  icon={DownloadCloud}
                  onClick={() => setSyncingUniverse(universe)}
                >
                  <span className="hidden xl:inline">Sync</span>
                </Button>
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
          ))}
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
        onSyncStarted={handleSyncStarted}
      />
    </div>
  );
};

export default Universes;