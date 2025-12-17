import React from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import Modal from './ui/Modal';
import Button from './ui/Button';
import { DownloadCloud, Calendar } from 'lucide-react';
import { StockUniverse, syncUniverseAggregates, SyncAggregatesOptions } from '../api/scanner';

interface SyncUniverseModalProps {
    isOpen: boolean;
    onClose: () => void;
    universe: StockUniverse | null;
}

const SyncUniverseModal: React.FC<SyncUniverseModalProps> = ({
    isOpen,
    onClose,
    universe
}) => {
    // Default sync options
    const [syncOptions, setSyncOptions] = React.useState<SyncAggregatesOptions>({
        from_date: new Date(Date.now() - 7 * 24 * 60 * 60 * 1000).toISOString().split('T')[0],
        to_date: new Date().toISOString().split('T')[0],
        multiplier: 1,
        timespan: 'minute',
        adjusted: true,
        sort: 'asc',
        limit: 50000
    });

    // Sync mutation
    const syncMutation = useMutation({
        mutationFn: () => {
            if (!universe) throw new Error("No universe selected");
            return syncUniverseAggregates(universe.id, syncOptions);
        },
        onSuccess: (data) => {
            alert(data.message); // Simple feedback for now
            onClose();
        }
    });

    if (!universe) return null;

    return (
        <Modal
            isOpen={isOpen}
            onClose={onClose}
            title={`Sync Data: ${universe.name}`}
            footer={
                <div className="flex justify-end gap-2 w-full">
                    <Button variant="secondary" onClick={onClose}>Cancel</Button>
                    <Button
                        variant="primary"
                        icon={DownloadCloud}
                        onClick={() => syncMutation.mutate()}
                        disabled={syncMutation.isPending}
                    >
                        {syncMutation.isPending ? 'Syncing...' : 'Start Sync'}
                    </Button>
                </div>
            }
        >
            <div className="space-y-4">
                <div className="bg-blue-500/10 border border-blue-500/20 rounded-lg p-3 mb-4">
                    <p className="text-sm text-blue-400">
                        This will schedule a background task to fetch aggregate data from Polygon.io for all stocks in this universe.
                    </p>
                </div>

                <div className="grid grid-cols-2 gap-4">
                    <div>
                        <label className="block text-xs text-gray-400 mb-1">From Date</label>
                        <input
                            type="date"
                            className="w-full bg-gray-900 border border-gray-700 rounded px-2 py-1 text-sm text-white focus:border-financial-blue focus:outline-none"
                            value={syncOptions.from_date}
                            onChange={(e) => setSyncOptions({ ...syncOptions, from_date: e.target.value })}
                        />
                    </div>
                    <div>
                        <label className="block text-xs text-gray-400 mb-1">To Date</label>
                        <input
                            type="date"
                            className="w-full bg-gray-900 border border-gray-700 rounded px-2 py-1 text-sm text-white focus:border-financial-blue focus:outline-none"
                            value={syncOptions.to_date}
                            onChange={(e) => setSyncOptions({ ...syncOptions, to_date: e.target.value })}
                        />
                    </div>
                </div>

                <div className="grid grid-cols-2 gap-4">
                    <div>
                        <label className="block text-xs text-gray-400 mb-1">Timespan</label>
                        <select
                            className="w-full bg-gray-900 border border-gray-700 rounded px-2 py-1 text-sm text-white focus:border-financial-blue focus:outline-none"
                            value={syncOptions.timespan}
                            onChange={(e) => setSyncOptions({ ...syncOptions, timespan: e.target.value })}
                        >
                            <option value="minute">Minute</option>
                            <option value="hour">Hour</option>
                            <option value="day">Day</option>
                            <option value="week">Week</option>
                            <option value="month">Month</option>
                            <option value="quarter">Quarter</option>
                            <option value="year">Year</option>
                        </select>
                    </div>
                    <div>
                        <label className="block text-xs text-gray-400 mb-1">Multiplier</label>
                        <input
                            type="number"
                            min="1"
                            className="w-full bg-gray-900 border border-gray-700 rounded px-2 py-1 text-sm text-white focus:border-financial-blue focus:outline-none"
                            value={syncOptions.multiplier}
                            onChange={(e) => setSyncOptions({ ...syncOptions, multiplier: parseInt(e.target.value) || 1 })}
                        />
                    </div>
                </div>

                <div className="grid grid-cols-2 gap-4">
                    <div>
                        <label className="flex items-center gap-2 cursor-pointer mt-4">
                            <input
                                type="checkbox"
                                className="form-checkbox bg-gray-900 border-gray-700 text-financial-blue rounded"
                                checked={syncOptions.adjusted}
                                onChange={(e) => setSyncOptions({ ...syncOptions, adjusted: e.target.checked })}
                            />
                            <span className="text-sm text-gray-300">Adjusted Results</span>
                        </label>
                    </div>
                    <div>
                        <label className="block text-xs text-gray-400 mb-1">Limit</label>
                        <input
                            type="number"
                            step="1000"
                            className="w-full bg-gray-900 border border-gray-700 rounded px-2 py-1 text-sm text-white focus:border-financial-blue focus:outline-none"
                            value={syncOptions.limit}
                            onChange={(e) => setSyncOptions({ ...syncOptions, limit: parseInt(e.target.value) || 50000 })}
                        />
                    </div>
                </div>
            </div>
        </Modal>
    );
};

export default SyncUniverseModal;
