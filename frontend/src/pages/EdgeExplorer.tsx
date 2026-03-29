import React, { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { 
  BarChart2, 
  TrendingUp, 
  TrendingDown, 
  Filter, 
  Download,
  Calendar,
  Layers,
  Search
} from 'lucide-react';
import { format } from 'date-fns';

// Components
import Card from '../components/ui/Card';
import MetricCard from '../components/ui/MetricCard';
import { 
  BarChart, 
  Bar, 
  XAxis, 
  YAxis, 
  CartesianGrid, 
  Tooltip, 
  ResponsiveContainer, 
  ScatterChart, 
  Scatter, 
  ZAxis,
  Cell,
  Legend,
  LineChart,
  Line,
  AreaChart,
  Area
} from 'recharts';

const EdgeExplorer: React.FC = () => {
  const [period, setPeriod] = useState<'weekly' | 'monthly' | 'quarterly'>('monthly');
  const [ticker, setTicker] = useState<string>('');

  // Placeholder for real API calls
  const { data: stats, isLoading } = useQuery({
    queryKey: ['edgeStats', period, ticker],
    queryFn: async () => {
      // This will be replaced by actual API call to /api/scanner/edge-stats
      const response = await fetch(`/api/scanner/edge-stats?period=${period}${ticker ? `&ticker=${ticker}` : ''}`);
      if (!response.ok) return [];
      return response.json();
    }
  });

  const { data: distribution } = useQuery({
    queryKey: ['edgeDistribution', ticker],
    queryFn: async () => {
      const response = await fetch(`/api/scanner/edge-distribution${ticker ? `?ticker=${ticker}` : ''}`);
      if (!response.ok) return { events: [] };
      return response.json();
    }
  });

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-financial-blue"></div>
      </div>
    );
  }

  const events = distribution?.events || [];
  
  // Calculate aggregate metrics
  const avgGap = events.length > 0 ? events.reduce((acc: number, e: any) => acc + (e.gap_pct || 0), 0) / events.length : 0;
  const avgFade = events.length > 0 ? events.reduce((acc: number, e: any) => acc + (e.fade_pct || 0), 0) / events.length : 0;
  const avgRange = events.length > 0 ? events.reduce((acc: number, e: any) => acc + (e.day_range_pct || 0), 0) / events.length : 0;

  return (
    <div className="space-y-6 animate-fade-in">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold text-financial-light">Statistical Edge Explorer</h1>
          <p className="text-gray-400 mt-1">Identify historical patterns and performance probabilities</p>
        </div>
        
        <div className="flex items-center space-x-3 bg-gray-800 p-2 rounded-lg">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 h-4 w-4 text-gray-500" />
            <input 
              type="text" 
              placeholder="Filter Ticker..." 
              className="pl-9 pr-4 py-2 bg-gray-900 border border-gray-700 rounded-md text-sm focus:outline-none focus:ring-1 focus:ring-financial-blue text-white"
              value={ticker}
              onChange={(e) => setTicker(e.target.value)}
            />
          </div>
          
          <div className="flex items-center bg-gray-900 rounded-md p-1 border border-gray-700">
            {(['weekly', 'monthly', 'quarterly'] as const).map((p) => (
              <button
                key={p}
                onClick={() => setPeriod(p)}
                className={`px-3 py-1 text-xs rounded-md capitalize transition-colors ${
                  period === p ? 'bg-financial-blue text-white' : 'text-gray-400 hover:text-white'
                }`}
              >
                {p}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Metrics Row */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        <MetricCard
          title="Avg Daily Gappers"
          value={stats && stats.length > 0 ? (stats.reduce((acc: number, s: any) => acc + s.event_count, 0) / stats.length).toFixed(1) : 0}
          icon={Layers as any}
          color="blue"
        />
        <MetricCard
          title="Avg Gap %"
          value={`${avgGap.toFixed(2)}%`}
          icon={TrendingUp as any}
          color="green"
        />
        <MetricCard
          title="Avg Fade from Top"
          value={`${avgFade.toFixed(2)}%`}
          icon={TrendingDown as any}
          color="red"
        />
        <MetricCard
          title="Avg Day Range"
          value={`${avgRange.toFixed(2)}%`}
          icon={BarChart2 as any}
          color="purple"
        />
      </div>

      {/* Distribution Charts */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Card title="Gap % vs. Fade % Correlation" icon={TrendingUp as any}>
          <div className="h-[400px]">
            <ResponsiveContainer width="100%" height="100%">
              <ScatterChart margin={{ top: 20, right: 20, bottom: 20, left: 20 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#374151" vertical={false} />
                <XAxis 
                  type="number" 
                  dataKey="gap_pct" 
                  name="Gap %" 
                  unit="%" 
                  stroke="#9CA3AF"
                  label={{ value: 'Gap %', position: 'bottom', fill: '#9CA3AF', dy: 10 }}
                />
                <YAxis 
                  type="number" 
                  dataKey="fade_pct" 
                  name="Fade %" 
                  unit="%" 
                  stroke="#9CA3AF"
                  label={{ value: 'Fade %', angle: -90, position: 'insideLeft', fill: '#9CA3AF' }}
                />
                <ZAxis type="number" range={[60, 400]} />
                <Tooltip 
                  cursor={{ strokeDasharray: '3 3' }} 
                  contentStyle={{ backgroundColor: '#111827', border: '1px solid #374151', borderRadius: '8px' }}
                />
                <Legend verticalAlign="top" height={36}/>
                <Scatter name="Events" data={events} fill="#3B82F6">
                  {events.map((entry: any, index: number) => (
                    <Cell key={`cell-${index}`} fill={entry.fade_pct > entry.gap_pct ? '#EF4444' : '#10B981'} />
                  ))}
                </Scatter>
              </ScatterChart>
            </ResponsiveContainer>
          </div>
          <p className="text-xs text-gray-500 mt-4 text-center">
            Green dots: Market held or improved from open. Red dots: Market faded significantly from peak.
          </p>
        </Card>

        <Card title="Historical Pattern Trends" icon={Calendar as any}>
          <div className="h-[400px]">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={stats || []} margin={{ top: 10, right: 30, left: 0, bottom: 0 }}>
                <defs>
                  <linearGradient id="colorGap" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#10B981" stopOpacity={0.3}/>
                    <stop offset="95%" stopColor="#10B981" stopOpacity={0}/>
                  </linearGradient>
                  <linearGradient id="colorFade" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#EF4444" stopOpacity={0.3}/>
                    <stop offset="95%" stopColor="#EF4444" stopOpacity={0}/>
                  </linearGradient>
                </defs>
                <XAxis dataKey="label" stroke="#9CA3AF" />
                <YAxis stroke="#9CA3AF" />
                <CartesianGrid strokeDasharray="3 3" stroke="#374151" vertical={false} />
                <Tooltip 
                  contentStyle={{ backgroundColor: '#111827', border: '1px solid #374151', borderRadius: '8px' }}
                />
                <Legend verticalAlign="top" height={36}/>
                <Area 
                  type="monotone" 
                  dataKey="avg_gap_pct" 
                  name="Avg Gap %"
                  stroke="#10B981" 
                  fillOpacity={1} 
                  fill="url(#colorGap)" 
                />
                <Area 
                  type="monotone" 
                  dataKey="avg_fade_pct" 
                  name="Avg Fade %"
                  stroke="#EF4444" 
                  fillOpacity={1} 
                  fill="url(#colorFade)" 
                />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </Card>
      </div>

      {/* Aggregate Table */}
      <Card title="Period Performance Breakdown" icon={BarChart2 as any}>
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-gray-700">
            <thead>
              <tr className="bg-gray-800">
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-400 uppercase tracking-wider">Period</th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-400 uppercase tracking-wider">Event Count</th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-400 uppercase tracking-wider">Avg Gap %</th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-400 uppercase tracking-wider">Avg Fade %</th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-400 uppercase tracking-wider">Avg Range %</th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-400 uppercase tracking-wider">Avg Rel Vol</th>
              </tr>
            </thead>
            <tbody className="bg-transparent divide-y divide-gray-800">
              {stats?.map((row: any, i: number) => (
                <tr key={i} className="hover:bg-gray-800/50 transition-colors">
                  <td className="px-6 py-4 whitespace-nowrap text-sm font-medium text-financial-light">{row.label}</td>
                  <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-300">{row.event_count}</td>
                  <td className="px-6 py-4 whitespace-nowrap text-sm text-positive">{row.avg_gap_pct}%</td>
                  <td className="px-6 py-4 whitespace-nowrap text-sm text-negative">{row.avg_fade_pct}%</td>
                  <td className="px-6 py-4 whitespace-nowrap text-sm text-purple-400">{row.avg_day_range_pct}%</td>
                  <td className="px-6 py-4 whitespace-nowrap text-sm text-blue-400">{row.avg_rel_vol}x</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
};

export default EdgeExplorer;
