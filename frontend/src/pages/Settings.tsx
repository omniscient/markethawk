import React, { useState, useEffect } from 'react';
import { Database, RefreshCw, Newspaper } from 'lucide-react';

import Card from '../components/ui/Card';
import Button from '../components/ui/Button';
import NewsSettings from '../components/NewsSettings';
import { syncFundamentals, syncMetrics, syncTickerDetails, stopSync, fetchStorageStats, StorageStats } from '../api/scanner';

const tabs = [
  { id: 'data', name: 'Data & Storage', icon: Database },
  { id: 'news', name: 'News', icon: Newspaper },
];

const Settings: React.FC = () => {
  const [activeTab, setActiveTab] = useState('data');

  const [syncingFundamentals, setSyncingFundamentals] = useState(false);
  const [syncingMetrics, setSyncingMetrics] = useState(false);
  const [syncingDetails, setSyncingDetails] = useState(false);
  const [stopping, setStopping] = useState(false);
  const [crawlSpeed, setCrawlSpeed] = useState<number>(15.0);
  const [storageStats, setStorageStats] = useState<StorageStats | null>(null);
  const [loadingStorage, setLoadingStorage] = useState(false);

  useEffect(() => {
    if (activeTab === 'data') {
      const load = async () => {
        try {
          setLoadingStorage(true);
          setStorageStats(await fetchStorageStats());
        } catch (e) {
          console.error('Failed to fetch storage stats:', e);
        } finally {
          setLoadingStorage(false);
        }
      };
      load();
    }
  }, [activeTab]);

  const handleSyncFundamentals = async () => {
    try {
      setSyncingFundamentals(true);
      await syncFundamentals(crawlSpeed);
      const label = crawlSpeed < 1 ? 'FAST' : 'SLOW';
      alert(`Fundamental sync started in background (${label} mode: ${crawlSpeed}s delay)`);
    } catch {
      alert('Failed to start sync');
    } finally {
      setSyncingFundamentals(false);
    }
  };

  const handleSyncDetails = async () => {
    try {
      setSyncingDetails(true);
      await syncTickerDetails(crawlSpeed);
      const label = crawlSpeed < 1 ? 'FAST' : 'SLOW';
      alert(`Details crawler started (${label} mode: ${crawlSpeed}s delay)`);
    } catch {
      alert('Failed to start details sync');
    } finally {
      setSyncingDetails(false);
    }
  };

  const handleSyncMetrics = async () => {
    try {
      setSyncingMetrics(true);
      await syncMetrics();
      alert('Metrics update started in background');
    } catch {
      alert('Failed to start update');
    } finally {
      setSyncingMetrics(false);
    }
  };

  const handleStopSync = async () => {
    try {
      setStopping(true);
      const res = await stopSync();
      // @ts-ignore
      alert(res.message);
    } catch {
      alert('Failed to stop sync');
    } finally {
      setStopping(false);
    }
  };

  return (
    <div className="space-y-6 animate-fade-in">
      <div>
        <h1 className="text-3xl font-bold text-financial-light">Settings</h1>
        <p className="text-gray-400 mt-1">Configure your stock scanner preferences</p>
      </div>

      <div className="flex flex-col lg:flex-row gap-6">
        {/* Tab Navigation */}
        <div className="lg:w-64">
          <Card className="p-0">
            <nav className="space-y-1">
              {tabs.map((tab) => {
                const Icon = tab.icon;
                return (
                  <button
                    key={tab.id}
                    onClick={() => setActiveTab(tab.id)}
                    className={`w-full flex items-center px-4 py-3 text-sm font-medium transition-colors duration-200 ${
                      activeTab === tab.id
                        ? 'bg-financial-blue text-white border-r-2 border-financial-blue'
                        : 'text-gray-300 hover:bg-gray-700 hover:text-white'
                    }`}
                  >
                    <Icon className="h-4 w-4 mr-3" />
                    {tab.name}
                  </button>
                );
              })}
            </nav>
          </Card>
        </div>

        {/* Tab Content */}
        <div className="flex-1">
          {activeTab === 'data' && (
            <Card title="Data & Storage" icon={Database as any}>
              <div className="space-y-6">
                {/* Market Data Sync */}
                <div>
                  <div className="flex items-center justify-between mb-4">
                    <h3 className="text-lg font-medium text-financial-light">Market Data Sync</h3>
                    <div className="flex items-center space-x-2 bg-gray-900/50 px-3 py-1.5 rounded-lg border border-gray-700">
                      <span className="text-sm text-gray-400">Global API Speed:</span>
                      <select
                        value={crawlSpeed}
                        onChange={(e) => setCrawlSpeed(parseFloat(e.target.value))}
                        className="bg-transparent border-none text-sm text-financial-blue font-bold focus:ring-0 cursor-pointer"
                      >
                        <option value={15.0}>🐢 Free (15s delay)</option>
                        <option value={0.2}>🚀 Paid (Unlimited)</option>
                        <option value={0.05}>⚡ Paid (Turbo)</option>
                      </select>
                    </div>
                  </div>

                  <div className="p-4 bg-gray-800 rounded-lg space-y-4">
                    <div className="flex items-center justify-between">
                      <div>
                        <h4 className="font-medium text-financial-light">Master Ticker List</h4>
                        <p className="text-sm text-gray-400">Syncs ~10,000 active tickers and their fundamentals (Market Cap, Shares, etc.)</p>
                      </div>
                      <Button
                        variant="secondary"
                        size="sm"
                        icon={RefreshCw}
                        loading={syncingFundamentals}
                        onClick={handleSyncFundamentals}
                      >
                        Sync Fundamentals
                      </Button>
                    </div>

                    <div className="border-t border-gray-700 pt-4 flex items-center justify-between">
                      <div>
                        <h4 className="font-medium text-financial-light">Ticker Details Crawler</h4>
                        <p className="text-sm text-gray-400">Deep sync for Description, Employees, etc.</p>
                      </div>
                      <div className="flex gap-2">
                        <Button
                          variant="danger"
                          size="sm"
                          loading={stopping}
                          onClick={handleStopSync}
                        >
                          Stop
                        </Button>
                        <Button
                          variant="secondary"
                          size="sm"
                          icon={RefreshCw}
                          loading={syncingDetails}
                          onClick={handleSyncDetails}
                        >
                          Sync
                        </Button>
                      </div>
                    </div>

                    <div className="border-t border-gray-700 pt-4 flex items-center justify-between">
                      <div>
                        <h4 className="font-medium text-financial-light">Daily Technical Metrics</h4>
                        <p className="text-sm text-gray-400">Updates SMA, Volume, and Price data for the entire market (Run after close)</p>
                      </div>
                      <Button
                        variant="secondary"
                        size="sm"
                        icon={RefreshCw}
                        loading={syncingMetrics}
                        onClick={handleSyncMetrics}
                      >
                        Update Metrics
                      </Button>
                    </div>
                  </div>
                </div>

                {/* Storage Usage */}
                <div>
                  <h3 className="text-lg font-medium text-financial-light mb-4">Storage Usage</h3>
                  <div className="space-y-3">
                    <div className="flex justify-between items-center p-3 bg-gray-800 rounded-lg">
                      <span className="text-gray-400">Scanner Results</span>
                      <span className="text-financial-light">
                        {loadingStorage ? 'Loading...' : storageStats?.scanner.formatted || '0.0 B'}
                      </span>
                    </div>
                    <div className="flex justify-between items-center p-3 bg-gray-800 rounded-lg">
                      <span className="text-gray-400">Historical Data</span>
                      <span className="text-financial-light">
                        {loadingStorage ? 'Loading...' : storageStats?.historical.formatted || '0.0 B'}
                      </span>
                    </div>
                    <div className="flex justify-between items-center p-3 bg-gray-800 rounded-lg">
                      <span className="text-gray-400">User Settings</span>
                      <span className="text-financial-light">
                        {loadingStorage ? 'Loading...' : storageStats?.settings.formatted || '0.0 B'}
                      </span>
                    </div>
                    <div className="flex justify-between items-center p-3 bg-financial-blue/20 rounded-lg border border-financial-blue/30">
                      <span className="text-financial-light font-medium">Total Usage</span>
                      <span className="text-financial-light font-medium">
                        {loadingStorage ? 'Loading...' : storageStats?.total.formatted || '0.0 B'}
                      </span>
                    </div>
                  </div>
                </div>
              </div>
            </Card>
          )}

          {activeTab === 'news' && (
            <NewsSettings />
          )}
        </div>
      </div>
    </div>
  );
};

export default Settings;
