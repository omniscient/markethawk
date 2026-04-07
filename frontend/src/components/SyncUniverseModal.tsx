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
    onSyncStarted?: (universeId: number) => void;
}

const SyncUniverseModal: React.FC<SyncUniverseModalProps> = ({
    isOpen,
    onClose,
    universe,
    onSyncStarted
}) => {
    const today = new Date().toISOString().split('T')[0];

    // If the universe has a max_aggregate_date, default from_date to the day after it
    // so the user can easily do an incremental "sync missing data" refresh.
    const defaultFromDate = React.useMemo(() => {
        if (universe?.max_aggregate_date) {
            const next = new Date(universe.max_aggregate_date);
            next.setDate(next.getDate() + 1);
            return next.toISOString().split('T')[0];
        }
        return new Date(Date.now() - 7 * 24 * 60 * 60 * 1000).toISOString().split('T')[0];
    }, [universe?.max_aggregate_date]);

    const defaultTimespan = universe?.available_timespans?.[0] ?? 'minute';

    // Default sync options
    const [syncOptions, setSyncOptions] = React.useState<SyncAggregatesOptions>({
        from_date: defaultFromDate,
        to_date: today,
        multiplier: 1,
        timespan: defaultTimespan,
        adjusted: true,
        sort: 'asc',
        limit: 50000
    });

    // Re-sync defaults when universe changes (e.g. opening for a different universe)
    React.useEffect(() => {
        setSyncOptions(prev => ({
            ...prev,
            from_date: defaultFromDate,
            timespan: defaultTimespan,
            to_date: today,
        }));
        setSyncError(null);
    }, [universe?.id]);

    const queryClient = useQueryClient();
    const [syncError, setSyncError] = React.useState<string | null>(null);

    // Sync mutation
    const syncMutation = useMutation({
        mutationFn: () => {
            if (!universe) throw new Error("No universe selected");
            return syncUniverseAggregates(universe.id, syncOptions);
        },
        onSuccess: (data) => {
            queryClient.invalidateQueries({ queryKey: ['stockUniverses'] });
            if (universe) onSyncStarted?.(universe.id);
            onClose();
        },
        onError: (error: any) => {
            const msg = error?.response?.data?.detail ?? error?.message ?? 'Failed to start sync';
            setSyncError(msg);
            queryClient.invalidateQueries({ queryKey: ['stockUniverses'] });
        },
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
                {syncError && (
                    <div className="bg-red-500/10 border border-red-500/30 rounded-lg p-3 text-sm text-red-400">
                        {syncError}
                    </div>
                )}
                <div className="bg-blue-500/10 border border-blue-500/20 rounded-lg p-3 mb-4 space-y-1">
                    <p className="text-sm text-blue-400">
                        Schedules a background task to fetch aggregate data for all instruments in this universe.
                    </p>
                    {universe.max_aggregate_date && (
                        <p className="text-xs text-gray-400">
                            Last recorded data: <span className="text-financial-light font-medium">
                                {new Date(universe.max_aggregate_date).toLocaleDateString()}
                            </span>
                            {universe.available_timespans && universe.available_timespans.length > 0 && (
                                <> &nbsp;·&nbsp; Timespans: <span className="text-financial-light font-medium">{universe.available_timespans.join(', ')}</span></>
                            )}
                            &nbsp;— <span className="text-green-400">from_date pre-filled to sync only missing data.</span>
                        </p>
                    )}
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
