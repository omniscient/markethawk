import React, { useState, useEffect } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Settings, Save, Plus, X, Globe } from 'lucide-react';
import { fetchNewsPreferences, updateNewsPreferences, NewsPreference } from '../api/news';
import { fetchStockUniverses } from '../api/scanner';

const NewsSettings: React.FC = () => {
    const queryClient = useQueryClient();

    // Fetch preferences
    const { data: pref, isLoading: isLoadingPref } = useQuery({
        queryKey: ['newsPreferences'],
        queryFn: fetchNewsPreferences,
    });

    // Fetch Universes
    const { data: universes, isLoading: isLoadingUniv } = useQuery({
        queryKey: ['universes'],
        queryFn: fetchStockUniverses,
    });

    const [includeGeneral, setIncludeGeneral] = useState(true);
    const [refreshInterval, setRefreshInterval] = useState(5);
    const [trackedTickers, setTrackedTickers] = useState<string[]>([]);
    const [trackedUniverses, setTrackedUniverses] = useState<number[]>([]);
    const [newTicker, setNewTicker] = useState("");

    // Setup local state when data loads
    useEffect(() => {
        if (pref) {
            setIncludeGeneral(pref.include_general_market);
            setRefreshInterval(pref.refresh_interval_minutes || 5);
            setTrackedTickers(pref.tracked_tickers || []);
            setTrackedUniverses(pref.tracked_universes || []);
        }
    }, [pref]);

    const mutation = useMutation({
        mutationFn: updateNewsPreferences,
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['newsPreferences'] });
            // Optionally could show a success toast here
        },
    });

    const handleSave = () => {
        mutation.mutate({
            include_general_market: includeGeneral,
            refresh_interval_minutes: refreshInterval,
            tracked_tickers: trackedTickers,
            tracked_universes: trackedUniverses,
        });
    };

    const handleAddTicker = () => {
        if (newTicker && !trackedTickers.includes(newTicker.toUpperCase())) {
            setTrackedTickers([...trackedTickers, newTicker.toUpperCase()]);
            setNewTicker("");
        }
    };

    const handleRemoveTicker = (t: string) => {
        setTrackedTickers(trackedTickers.filter(ticker => ticker !== t));
    };

    const handleUniverseToggle = (id: number) => {
        if (trackedUniverses.includes(id)) {
            setTrackedUniverses(trackedUniverses.filter(uId => uId !== id));
        } else {
            setTrackedUniverses([...trackedUniverses, id]);
        }
    };

    if (isLoadingPref || isLoadingUniv) {
        return <div className="p-4 text-center text-gray-400">Loading settings...</div>;
    }

    return (
        <div className="bg-gray-800 rounded-xl p-5 border border-gray-700">
            <div className="flex items-center justify-between mb-4">
                <h3 className="text-lg font-semibold text-financial-light flex items-center">
                    <Settings className="w-5 h-5 mr-2" />
                    News Filters
                </h3>
            </div>

            <div className="space-y-6">
                {/* General Market Toggle */}
                <div className="flex items-center justify-between bg-gray-900/50 p-4 rounded-lg border border-gray-700">
                    <div className="flex items-center">
                        <Globe className="w-5 h-5 text-financial-blue mr-3" />
                        <div>
                            <p className="font-medium text-financial-light">Broad Market News</p>
                            <p className="text-xs text-gray-400">Include general financial news alongside your tickers</p>
                        </div>
                    </div>
                    <label className="relative inline-flex items-center cursor-pointer">
                        <input
                            type="checkbox"
                            className="sr-only peer"
                            checked={includeGeneral}
                            onChange={(e) => setIncludeGeneral(e.target.checked)}
                        />
                        <div className="w-11 h-6 bg-gray-700 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-financial-blue"></div>
                    </label>
                </div>

                {/* Refresh Interval Slider */}
                <div>
                    <h4 className="text-sm font-medium text-gray-300 mb-2">Polling Frequency</h4>
                    <div className="bg-gray-900/50 p-4 rounded-lg border border-gray-700">
                        <div className="flex justify-between text-xs text-gray-400 mb-2">
                            <span>1 min</span>
                            <span className="text-financial-light font-medium">{refreshInterval} min</span>
                            <span>60 min</span>
                        </div>
                        <input
                            type="range"
                            min="1" max="60"
                            value={refreshInterval}
                            onChange={(e) => setRefreshInterval(Number(e.target.value))}
                            className="w-full h-1.5 bg-gray-700 rounded-lg appearance-none cursor-pointer accent-financial-blue"
                        />
                    </div>
                </div>

                {/* Stock Universes Multi-select (Checkbox list) */}
                <div>
                    <h4 className="text-sm font-medium text-gray-300 mb-2">Tracked Universes</h4>
                    <div className="bg-gray-900/50 rounded-lg border border-gray-700 p-3 max-h-40 overflow-y-auto custom-scrollbar">
                        {universes && universes.length > 0 ? (
                            universes.map(u => (
                                <label key={u.id} className="flex items-center space-x-3 p-2 hover:bg-gray-800 rounded cursor-pointer transition-colors">
                                    <input
                                        type="checkbox"
                                        checked={trackedUniverses.includes(u.id)}
                                        onChange={() => handleUniverseToggle(u.id)}
                                        className="form-checkbox h-4 w-4 text-financial-blue rounded border-gray-600 bg-gray-700"
                                    />
                                    <span className="text-sm text-gray-200">{u.name}</span>
                                </label>
                            ))
                        ) : (
                            <p className="text-xs text-gray-500 py-2">No universes configured.</p>
                        )}
                    </div>
                </div>

                {/* Individual Tickers */}
                <div>
                    <h4 className="text-sm font-medium text-gray-300 mb-2">Specific Tickers</h4>
                    <div className="flex space-x-2 mb-3">
                        <input
                            type="text"
                            value={newTicker}
                            onChange={e => setNewTicker(e.target.value)}
                            onKeyDown={e => e.key === 'Enter' && handleAddTicker()}
                            placeholder="e.g. AAPL, NVDA"
                            className="flex-1 bg-gray-900 border border-gray-700 text-white rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-financial-blue uppercase"
                        />
                        <button
                            onClick={handleAddTicker}
                            className="bg-gray-700 hover:bg-gray-600 text-white px-3 py-2 rounded-lg transition-colors flex items-center"
                        >
                            <Plus className="w-4 h-4" />
                        </button>
                    </div>
                    <div className="flex flex-wrap gap-2">
                        {trackedTickers.map(t => (
                            <span key={t} className="flex items-center text-xs font-mono bg-financial-blue/20 text-financial-light px-2 py-1 rounded-md border border-financial-blue/30">
                                {t}
                                <button onClick={() => handleRemoveTicker(t)} className="ml-1.5 text-financial-blue hover:text-white transition-colors">
                                    <X className="w-3 h-3" />
                                </button>
                            </span>
                        ))}
                    </div>
                </div>

                <button
                    onClick={handleSave}
                    disabled={mutation.isPending}
                    className="w-full flex items-center justify-center py-2.5 bg-financial-blue hover:bg-blue-600 text-white rounded-lg transition-colors font-medium text-sm disabled:opacity-50"
                >
                    {mutation.isPending ? 'Saving...' : (
                        <>
                            <Save className="w-4 h-4 mr-2" />
                            Save Filters
                        </>
                    )}
                </button>
            </div>
        </div>
    );
};

export default NewsSettings;
