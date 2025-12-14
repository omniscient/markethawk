import React, { useState } from 'react';
import {
  Settings as SettingsIcon,
  User,
  Bell,
  Shield,
  Palette,
  Database,
  Key,
  Save,
  Mail,
  RefreshCw
} from 'lucide-react';

// Components
import Card from '../components/ui/Card';
import Button from '../components/ui/Button';
import { syncFundamentals, syncMetrics, syncTickerDetails, stopSync } from '../api/scanner'; // Import stopSync

const Settings: React.FC = () => {
  const [activeTab, setActiveTab] = useState('general');
  const [settings, setSettings] = useState({
    theme: 'dark',
    language: 'en',
    timezone: 'America/New_York',
    notifications: {
      email: true,
      push: false,
      webhook: true
    },
    scanner: {
      autoRun: true,
      frequency: '15min',
      maxConcurrent: 5
    }
  });

  const [syncingFundamentals, setSyncingFundamentals] = useState(false);
  const [syncingMetrics, setSyncingMetrics] = useState(false);
  const [syncingDetails, setSyncingDetails] = useState(false);
  const [stopping, setStopping] = useState(false);

  // Speed setting (15.0 for Free, 0.2 for Paid/Unlimited)
  const [crawlSpeed, setCrawlSpeed] = useState<number>(15.0);

  const tabs = [
    { id: 'general', name: 'General', icon: SettingsIcon as any },
    { id: 'profile', name: 'Profile', icon: User as any },
    { id: 'notifications', name: 'Notifications', icon: Bell as any },
    { id: 'security', name: 'Security', icon: Shield as any },
    { id: 'appearance', name: 'Appearance', icon: Palette as any },
    { id: 'data', name: 'Data & Storage', icon: Database as any }
  ];

  const handleSave = () => {
    // Save settings logic here
    console.log('Saving settings:', settings);
  };

  const handleStopSync = async () => {
    try {
      setStopping(true);
      const res = await stopSync();
      // @ts-ignore
      alert(res.message);
    } catch (e) {
      alert('Failed to stop sync');
    } finally {
      setStopping(false);
    }
  };


  const handleSyncFundamentals = async () => {
    try {
      setSyncingFundamentals(true);
      await syncFundamentals();
      alert('Fundamental sync started in background');
    } catch (e) {
      alert('Failed to start sync');
    } finally {
      setSyncingFundamentals(false);
    }
  };

  const handleSyncDetails = async () => {
    try {
      setSyncingDetails(true);
      // Pass the selected speed
      await syncTickerDetails(crawlSpeed);
      const speedLabel = crawlSpeed < 1 ? 'FAST' : 'SLOW';
      alert(`Details crawler started (${speedLabel} mode: ${crawlSpeed}s delay)`);
    } catch (e) {
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
    } catch (e) {
      alert('Failed to start update');
    } finally {
      setSyncingMetrics(false);
    }
  };

  return (
    <div className="space-y-6 animate-fade-in">
      {/* Header */}
      <div>
        <h1 className="text-3xl font-bold text-financial-light">Settings</h1>
        <p className="text-gray-400 mt-1">Configure your stock scanner preferences</p>
      </div>

      {/* Settings Tabs */}
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
                    className={`w-full flex items-center px-4 py-3 text-sm font-medium transition-colors duration-200 ${activeTab === tab.id
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
          {activeTab === 'general' && (
            <Card title="General Settings" icon={SettingsIcon as any}>
              <div className="space-y-6">
                <div>
                  <label className="block text-sm font-medium text-gray-300 mb-2">
                    Language
                  </label>
                  <select
                    value={settings.language}
                    onChange={(e) => setSettings({ ...settings, language: e.target.value })}
                    className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded-lg text-financial-light focus:outline-none focus:ring-2 focus:ring-financial-blue"
                  >
                    <option value="en">English</option>
                    <option value="es">Spanish</option>
                    <option value="fr">French</option>
                    <option value="de">German</option>
                  </select>
                </div>

                <div>
                  <label className="block text-sm font-medium text-gray-300 mb-2">
                    Timezone
                  </label>
                  <select
                    value={settings.timezone}
                    onChange={(e) => setSettings({ ...settings, timezone: e.target.value })}
                    className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded-lg text-financial-light focus:outline-none focus:ring-2 focus:ring-financial-blue"
                  >
                    <option value="America/New_York">Eastern Time (ET)</option>
                    <option value="America/Chicago">Central Time (CT)</option>
                    <option value="America/Denver">Mountain Time (MT)</option>
                    <option value="America/Los_Angeles">Pacific Time (PT)</option>
                    <option value="UTC">UTC</option>
                  </select>
                </div>

                <div className="flex items-center justify-between">
                  <div>
                    <h3 className="text-sm font-medium text-gray-300">Auto-Save Settings</h3>
                    <p className="text-xs text-gray-400">Automatically save changes as you make them</p>
                  </div>
                  <div className="w-12 h-6 bg-gray-600 rounded-full relative cursor-pointer">
                    <div className="w-5 h-5 bg-white rounded-full absolute top-0.5 left-0.5 transition-transform"></div>
                  </div>
                </div>
              </div>
            </Card>
          )}

          {activeTab === 'notifications' && (
            <Card title="Notification Settings" icon={Bell as any}>
              <div className="space-y-6">
                <div>
                  <h3 className="text-lg font-medium text-financial-light mb-4">Alert Delivery Methods</h3>

                  <div className="space-y-4">
                    <div className="flex items-center justify-between p-4 bg-gray-800 rounded-lg">
                      <div className="flex items-center space-x-3">
                        <Mail className="h-5 w-5 text-financial-blue" />
                        <div>
                          <h4 className="font-medium text-financial-light">Email Notifications</h4>
                          <p className="text-sm text-gray-400">Receive alerts via email</p>
                        </div>
                      </div>
                      <button
                        onClick={() => setSettings({
                          ...settings,
                          notifications: {
                            ...settings.notifications,
                            email: !settings.notifications.email
                          }
                        })}
                        className={`w-12 h-6 rounded-full relative ${settings.notifications.email ? 'bg-financial-blue' : 'bg-gray-600'
                          }`}
                      >
                        <div className={`w-5 h-5 bg-white rounded-full absolute top-0.5 transition-transform ${settings.notifications.email ? 'translate-x-6' : 'translate-x-0.5'
                          }`} />
                      </button>
                    </div>

                    <div className="flex items-center justify-between p-4 bg-gray-800 rounded-lg">
                      <div className="flex items-center space-x-3">
                        <Bell className="h-5 w-5 text-financial-blue" />
                        <div>
                          <h4 className="font-medium text-financial-light">Push Notifications</h4>
                          <p className="text-sm text-gray-400">Browser push notifications</p>
                        </div>
                      </div>
                      <button
                        onClick={() => setSettings({
                          ...settings,
                          notifications: {
                            ...settings.notifications,
                            push: !settings.notifications.push
                          }
                        })}
                        className={`w-12 h-6 rounded-full relative ${settings.notifications.push ? 'bg-financial-blue' : 'bg-gray-600'
                          }`}
                      >
                        <div className={`w-5 h-5 bg-white rounded-full absolute top-0.5 transition-transform ${settings.notifications.push ? 'translate-x-6' : 'translate-x-0.5'
                          }`} />
                      </button>
                    </div>

                    <div className="flex items-center justify-between p-4 bg-gray-800 rounded-lg">
                      <div className="flex items-center space-x-3">
                        <SettingsIcon className="h-5 w-5 text-financial-blue" />
                        <div>
                          <h4 className="font-medium text-financial-light">Webhook Alerts</h4>
                          <p className="text-sm text-gray-400">Send alerts to custom webhooks</p>
                        </div>
                      </div>
                      <button
                        onClick={() => setSettings({
                          ...settings,
                          notifications: {
                            ...settings.notifications,
                            webhook: !settings.notifications.webhook
                          }
                        })}
                        className={`w-12 h-6 rounded-full relative ${settings.notifications.webhook ? 'bg-financial-blue' : 'bg-gray-600'
                          }`}
                      >
                        <div className={`w-5 h-5 bg-white rounded-full absolute top-0.5 transition-transform ${settings.notifications.webhook ? 'translate-x-6' : 'translate-x-0.5'
                          }`} />
                      </button>
                    </div>
                  </div>
                </div>

                <div>
                  <label className="block text-sm font-medium text-gray-300 mb-2">
                    Alert Frequency
                  </label>
                  <select
                    value="immediate"
                    className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded-lg text-financial-light focus:outline-none focus:ring-2 focus:ring-financial-blue"
                  >
                    <option value="immediate">Immediate</option>
                    <option value="5min">Every 5 minutes</option>
                    <option value="15min">Every 15 minutes</option>
                    <option value="hourly">Hourly digest</option>
                    <option value="daily">Daily summary</option>
                  </select>
                </div>
              </div>
            </Card>
          )}

          {activeTab === 'scanner' && (
            <Card title="Scanner Settings" icon={SettingsIcon as any}>
              <div className="space-y-6">
                <div className="flex items-center justify-between">
                  <div>
                    <h3 className="text-sm font-medium text-gray-300">Auto-Run Scanner</h3>
                    <p className="text-xs text-gray-400">Automatically run scanner on schedule</p>
                  </div>
                  <button
                    onClick={() => setSettings({
                      ...settings,
                      scanner: {
                        ...settings.scanner,
                        autoRun: !settings.scanner.autoRun
                      }
                    })}
                    className={`w-12 h-6 rounded-full relative ${settings.scanner.autoRun ? 'bg-financial-blue' : 'bg-gray-600'
                      }`}
                  >
                    <div className={`w-5 h-5 bg-white rounded-full absolute top-0.5 transition-transform ${settings.scanner.autoRun ? 'translate-x-6' : 'translate-x-0.5'
                      }`} />
                  </button>
                </div>

                <div>
                  <label className="block text-sm font-medium text-gray-300 mb-2">
                    Scanner Frequency
                  </label>
                  <select
                    value={settings.scanner.frequency}
                    onChange={(e) => setSettings({
                      ...settings,
                      scanner: {
                        ...settings.scanner,
                        frequency: e.target.value
                      }
                    })}
                    className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded-lg text-financial-light focus:outline-none focus:ring-2 focus:ring-financial-blue"
                  >
                    <option value="5min">Every 5 minutes</option>
                    <option value="15min">Every 15 minutes</option>
                    <option value="30min">Every 30 minutes</option>
                    <option value="1hour">Every hour</option>
                    <option value="pre_market">Pre-market only</option>
                  </select>
                </div>

                <div>
                  <label className="block text-sm font-medium text-gray-300 mb-2">
                    Max Concurrent Scans
                  </label>
                  <input
                    type="number"
                    min="1"
                    max="20"
                    value={settings.scanner.maxConcurrent}
                    onChange={(e) => setSettings({
                      ...settings,
                      scanner: {
                        ...settings.scanner,
                        maxConcurrent: parseInt(e.target.value)
                      }
                    })}
                    className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded-lg text-financial-light focus:outline-none focus:ring-2 focus:ring-financial-blue"
                  />
                  <p className="text-xs text-gray-400 mt-1">
                    Maximum number of concurrent stock scans
                  </p>
                </div>
              </div>
            </Card>
          )}

          {activeTab === 'security' && (
            <Card title="Security Settings" icon={Shield as any}>
              <div className="space-y-6">
                <div>
                  <h3 className="text-lg font-medium text-financial-light mb-4">API Keys</h3>

                  <div className="space-y-4">
                    <div className="flex items-center justify-between p-4 bg-gray-800 rounded-lg">
                      <div>
                        <h4 className="font-medium text-financial-light">Yahoo Finance API</h4>
                        <p className="text-sm text-gray-400">Primary data source</p>
                      </div>
                      <div className="flex items-center space-x-2">
                        <Key className="h-4 w-4 text-green-400" />
                        <span className="text-sm text-green-400">Connected</span>
                      </div>
                    </div>

                    <div className="flex items-center justify-between p-4 bg-gray-800 rounded-lg">
                      <div>
                        <h4 className="font-medium text-financial-light">Alpha Vantage API</h4>
                        <p className="text-sm text-gray-400">Backup data source</p>
                      </div>
                      <div className="flex items-center space-x-2">
                        <Key className="h-4 w-4 text-yellow-400" />
                        <span className="text-sm text-yellow-400">Not Configured</span>
                      </div>
                    </div>
                  </div>
                </div>

                <div>
                  <h3 className="text-lg font-medium text-financial-light mb-4">Session Settings</h3>

                  <div className="space-y-4">
                    <div className="flex items-center justify-between">
                      <div>
                        <h4 className="font-medium text-financial-light">Session Timeout</h4>
                        <p className="text-sm text-gray-400">Automatically log out after inactivity</p>
                      </div>
                      <select className="px-3 py-2 bg-gray-700 border border-gray-600 rounded-lg text-financial-light">
                        <option value="30min">30 minutes</option>
                        <option value="1hour">1 hour</option>
                        <option value="4hours">4 hours</option>
                        <option value="8hours">8 hours</option>
                        <option value="never">Never</option>
                      </select>
                    </div>

                    <div className="flex items-center justify-between">
                      <div>
                        <h4 className="font-medium text-financial-light">Two-Factor Authentication</h4>
                        <p className="text-sm text-gray-400">Add an extra layer of security</p>
                      </div>
                      <Button variant="secondary" size="sm">
                        Enable 2FA
                      </Button>
                    </div>
                  </div>
                </div>
              </div>
            </Card>
          )}

          {activeTab === 'appearance' && (
            <Card title="Appearance Settings" icon={Palette as any}>
              <div className="space-y-6">
                <div>
                  <h3 className="text-lg font-medium text-financial-light mb-4">Theme</h3>

                  <div className="grid grid-cols-3 gap-4">
                    <div className="p-4 border border-gray-600 rounded-lg cursor-pointer hover:border-financial-blue">
                      <div className="w-full h-20 bg-gray-900 rounded mb-2"></div>
                      <p className="text-sm text-center text-financial-light">Dark</p>
                    </div>
                    <div className="p-4 border border-gray-600 rounded-lg cursor-pointer">
                      <div className="w-full h-20 bg-gray-100 rounded mb-2"></div>
                      <p className="text-sm text-center text-gray-400">Light</p>
                    </div>
                    <div className="p-4 border border-gray-600 rounded-lg cursor-pointer">
                      <div className="w-full h-20 bg-gradient-to-br from-gray-900 to-gray-100 rounded mb-2"></div>
                      <p className="text-sm text-center text-gray-400">Auto</p>
                    </div>
                  </div>
                </div>

                <div>
                  <h3 className="text-lg font-medium text-financial-light mb-4">Dashboard Layout</h3>

                  <div className="space-y-4">
                    <div>
                      <label className="block text-sm font-medium text-gray-300 mb-2">
                        Default View
                      </label>
                      <select className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded-lg text-financial-light">
                        <option value="dashboard">Dashboard</option>
                        <option value="scanner">Scanner</option>
                        <option value="alerts">Alerts</option>
                      </select>
                    </div>

                    <div>
                      <label className="block text-sm font-medium text-gray-300 mb-2">
                        Charts Theme
                      </label>
                      <select className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded-lg text-financial-light">
                        <option value="financial">Financial</option>
                        <option value="minimal">Minimal</option>
                        <option value="colorful">Colorful</option>
                      </select>
                    </div>
                  </div>
                </div>
              </div>
            </Card>
          )}

          {activeTab === 'data' && (
            <Card title="Data & Storage" icon={Database as any}>
              <div className="space-y-6">
                <div>
                  <h3 className="text-lg font-medium text-financial-light mb-4">Market Data Sync</h3>
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
                        <div className="flex items-center mt-2 space-x-2">
                          <span className="text-xs text-gray-500">Speed:</span>
                          <select
                            value={crawlSpeed}
                            onChange={(e) => setCrawlSpeed(parseFloat(e.target.value))}
                            className="bg-gray-800 border-none text-xs text-financial-blue font-bold rounded px-2 py-1 focus:ring-1 focus:ring-financial-blue cursor-pointer"
                          >
                            <option value={15.0}>🐢 Free (15s delay)</option>
                            <option value={0.2}>🚀 Paid (Unlimited)</option>
                          </select>
                        </div>
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

                <div>
                  <h3 className="text-lg font-medium text-financial-light mb-4">Data Retention</h3>

                  <div className="space-y-4">
                    <div>
                      <label className="block text-sm font-medium text-gray-300 mb-2">
                        Keep Scanner Results
                      </label>
                      <select className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded-lg text-financial-light">
                        <option value="7days">7 days</option>
                        <option value="30days">30 days</option>
                        <option value="90days">90 days</option>
                        <option value="1year">1 year</option>
                        <option value="forever">Forever</option>
                      </select>
                    </div>

                    <div>
                      <label className="block text-sm font-medium text-gray-300 mb-2">
                        Keep Historical Data
                      </label>
                      <select className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded-lg text-financial-light">
                        <option value="1year">1 year</option>
                        <option value="2years">2 years</option>
                        <option value="5years">5 years</option>
                        <option value="forever">Forever</option>
                      </select>
                    </div>
                  </div>
                </div>

                <div>
                  <h3 className="text-lg font-medium text-financial-light mb-4">Storage Usage</h3>

                  <div className="space-y-3">
                    <div className="flex justify-between items-center p-3 bg-gray-800 rounded-lg">
                      <span className="text-gray-400">Scanner Results</span>
                      <span className="text-financial-light">2.3 GB</span>
                    </div>
                    <div className="flex justify-between items-center p-3 bg-gray-800 rounded-lg">
                      <span className="text-gray-400">Historical Data</span>
                      <span className="text-financial-light">5.7 GB</span>
                    </div>
                    <div className="flex justify-between items-center p-3 bg-gray-800 rounded-lg">
                      <span className="text-gray-400">User Settings</span>
                      <span className="text-financial-light">15 MB</span>
                    </div>
                    <div className="flex justify-between items-center p-3 bg-financial-blue/20 rounded-lg border border-financial-blue/30">
                      <span className="text-financial-light font-medium">Total Usage</span>
                      <span className="text-financial-light font-medium">8.0 GB</span>
                    </div>
                  </div>
                </div>

                <div className="flex space-x-3">
                  <Button variant="secondary">
                    Export Data
                  </Button>
                  <Button variant="danger">
                    Clear All Data
                  </Button>
                </div>
              </div>
            </Card>
          )}

          {/* Save Button */}
          <div className="flex justify-end mt-6">
            <Button
              variant="primary"
              icon={Save as any}
              onClick={handleSave}
            >
              Save Settings
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
};

export default Settings;