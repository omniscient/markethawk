import React, { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  TrendingUp,
  TrendingDown,
  Activity,
  Bell,
  Calendar,
  Zap
} from 'lucide-react';
import { format, formatDistanceToNow } from 'date-fns';

// Components
import Card from '../components/ui/Card';
import MetricCard from '../components/ui/MetricCard';
import Chart from '../components/ui/Chart';
import AlertList from '../components/AlertList';
import RecentEvents from '../components/RecentEvents';
import NewsFeed from '../components/NewsFeed';
import NewsSettings from '../components/NewsSettings';

// API functions
import { fetchScannerResults, fetchMarketStats } from '../api/scanner';

const Dashboard: React.FC = () => {
  const [sortBy, setSortBy] = useState<string>('created_at');
  const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('desc');

  // Fetch recent scanner results
  const { data: scannerResults, isLoading: loadingResults } = useQuery({
    queryKey: ['scannerResults', { limit: 50, sortBy, sortOrder }],
    queryFn: () => fetchScannerResults({ limit: 50, sort_by: sortBy, sort_order: sortOrder }),
    refetchInterval: 60000, // Refetch every minute
  });

  // Fetch market statistics
  const { data: marketStats, isLoading: loadingStats } = useQuery({
    queryKey: ['marketStats'],
    queryFn: fetchMarketStats,
  });

  if (loadingResults || loadingStats) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-financial-blue"></div>
      </div>
    );
  }

  const recentEvents = scannerResults?.slice(0, 10) || [];
  const recentAlerts = (scannerResults?.slice(0, 5) || []).map((event: any) => ({
    id: event.uuid || String(event.id),
    ticker: event.ticker,
    type: event.event_type === 'volume_spike' ? 'volume_spike' : 'price_movement',
    message: `${event.ticker} triggered a ${event.event_type || 'scanner'} alert with ${(event.relative_volume || 0).toFixed(1)}x relative volume.`,
    timestamp: event.created_at || event.event_date || new Date().toISOString(),
    severity: (event.relative_volume || 0) > 5 ? 'high' : ((event.relative_volume || 0) > 3 ? 'medium' : 'low'),
  }));
  const totalEvents = scannerResults?.length || 0;
  const todayEvents = scannerResults?.filter(
    (event: any) => event.event_date === format(new Date(), 'yyyy-MM-dd')
  ).length || 0;

  const lastScanTime = scannerResults && scannerResults.length > 0 
    ? new Date(Math.max(...scannerResults
        .map((e: any) => e.created_at ? new Date(e.created_at).getTime() : 0)
        .filter((t: number) => !isNaN(t) && t > 0)
      ))
    : null;
  
  const lastScanValid = lastScanTime && !isNaN(lastScanTime.getTime()) && lastScanTime.getTime() > 0;
  
  const lastScanFormatted = lastScanValid 
    ? formatDistanceToNow(lastScanTime, { addSuffix: true })
    : 'Never';

  return (
    <div className="space-y-6 animate-fade-in">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-financial-light">Dashboard</h1>
          <p className="text-gray-400 mt-1">Real-time stock scanner insights and alerts</p>
        </div>
        <div className="flex items-center space-x-3">
          <button className="flex items-center px-4 py-2 bg-financial-blue text-white rounded-lg hover:bg-blue-600 transition-colors">
            <Zap className="h-4 w-4 mr-2" />
            Run Scanner
          </button>
        </div>
      </div>

      {/* Metrics Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        <MetricCard
          title="Today's Events"
          value={todayEvents}
          change={12}
          icon={Activity as any}
          color="blue"
        />
        <MetricCard
          title="Total Events"
          value={totalEvents}
          change={8}
          icon={TrendingUp as any}
          color="green"
        />
        <MetricCard
          title="Active Alerts"
          value={marketStats?.activeAlerts || 0}
          change={-3}
          icon={Bell as any}
          color="yellow"
        />
        <MetricCard
          title="Avg Volume Spike"
          value={`${marketStats?.avgVolumeSpike || 0}x`}
          change={15}
          icon={TrendingDown as any}
          color="purple"
        />
      </div>

      {/* Charts and Lists */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Volume Spike Chart */}
        <div className="lg:col-span-2">
          <Card title="Volume Spike Trends" icon={TrendingUp as any}>
            <Chart
              data={scannerResults || []}
              type="line"
              xKey="event_date"
              yKey="relative_volume"
              height={300}
            />
          </Card>
        </div>

        {/* Recent Alerts */}
        <div>
          <Card title="Recent Alerts" icon={Bell as any}>
            <AlertList alerts={recentAlerts as any} />
          </Card>
        </div>
      </div>

      {/* Recent Events Table */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Card title="Recent Volume Events" icon={Activity as any}>
          <RecentEvents 
            events={recentEvents as any} 
            sortBy={sortBy}
            sortOrder={sortOrder}
            onSort={(column) => {
              if (column === sortBy) {
                setSortOrder(sortOrder === 'asc' ? 'desc' : 'asc');
              } else {
                setSortBy(column);
                setSortOrder('desc');
              }
            }}
          />
        </Card>

        {/* Market Overview */}
        <Card title="Market Overview" icon={Calendar as any}>
          <div className="space-y-4">
            <div className="flex justify-between items-center p-3 bg-gray-800 rounded-lg">
              <span className="text-gray-400">Market Status</span>
              <span className="text-positive font-semibold">Open</span>
            </div>
            <div className="flex justify-between items-center p-3 bg-gray-800 rounded-lg">
              <span className="text-gray-400">Pre-Market Hours</span>
              <span className="text-financial-light">4:00 AM - 9:30 AM EST</span>
            </div>
            <div className="flex justify-between items-center p-3 bg-gray-800 rounded-lg">
              <span className="text-gray-400">Last Scanner Run</span>
              <span className="text-financial-light">{lastScanFormatted}</span>
            </div>
            <div className="flex justify-between items-center p-3 bg-gray-800 rounded-lg">
              <span className="text-gray-400">Scanner Schedule</span>
              <span className="text-financial-light">Every 15 minutes</span>
            </div>
          </div>
        </Card>
      </div>

      {/* News Feed Section */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2">
          <NewsFeed />
        </div>
        <div>
          <NewsSettings />
        </div>
      </div>
    </div>
  );
};

export default Dashboard;