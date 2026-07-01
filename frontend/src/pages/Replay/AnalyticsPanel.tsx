import React from 'react';
import {
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import Card from '../../components/ui/Card';
import type { ReplayMetrics } from '../../api/replay';

interface AnalyticsPanelProps {
  metrics: ReplayMetrics | undefined;
}

const tooltipStyle = {
  backgroundColor: '#111827',
  border: '1px solid #374151',
  borderRadius: '8px',
  color: '#f9fafb',
};

const AnalyticsPanel: React.FC<AnalyticsPanelProps> = ({ metrics }) => {
  const equityCurve = metrics?.equity_curve ?? [];
  const calendarDecay = metrics?.calendar_decay ?? [];
  const holdingDecay = metrics?.holding_period_decay ?? [];
  const regimeBreakdown = metrics?.regime_breakdown ?? [];

  return (
    <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
      <Card title="Equity Curve">
        <div className="h-72">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={equityCurve}>
              <CartesianGrid stroke="#1f2937" vertical={false} />
              <XAxis dataKey="trade_index" stroke="#6b7280" tick={{ fontSize: 11 }} />
              <YAxis stroke="#6b7280" tick={{ fontSize: 11 }} />
              <Tooltip contentStyle={tooltipStyle} />
              <Line type="monotone" dataKey="equity_r" stroke="#38bdf8" strokeWidth={2} dot={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </Card>

      <Card title="Calendar Decay">
        <div className="h-72">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={calendarDecay}>
              <CartesianGrid stroke="#1f2937" vertical={false} />
              <XAxis dataKey="bucket" stroke="#6b7280" tick={{ fontSize: 11 }} />
              <YAxis stroke="#6b7280" tick={{ fontSize: 11 }} />
              <Tooltip contentStyle={tooltipStyle} />
              <Bar dataKey="expectancy_r" fill="#22c55e" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </Card>

      <Card title="Holding Period">
        <div className="h-72">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={holdingDecay}>
              <CartesianGrid stroke="#1f2937" vertical={false} />
              <XAxis dataKey="bars_held" stroke="#6b7280" tick={{ fontSize: 11 }} />
              <YAxis stroke="#6b7280" tick={{ fontSize: 11 }} />
              <Tooltip contentStyle={tooltipStyle} />
              <Bar dataKey="expectancy_r" fill="#f59e0b" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </Card>

      <Card title="Regime Breakdown" noPadding>
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-gray-800">
            <thead className="bg-gray-900/80">
              <tr>
                {['Trend', 'Volatility', 'Trades', 'Expectancy', 'Hit Rate'].map((header) => (
                  <th key={header} className="px-4 py-3 text-left text-[10px] font-bold uppercase tracking-widest text-gray-500">
                    {header}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-800">
              {regimeBreakdown.map((row) => (
                <tr key={`${row.trend}-${row.volatility}`} className="hover:bg-gray-800/40">
                  <td className="px-4 py-3 text-sm text-gray-200">{row.trend}</td>
                  <td className="px-4 py-3 text-sm text-gray-300">{row.volatility}</td>
                  <td className="px-4 py-3 text-sm text-gray-300">{row.trades}</td>
                  <td className="px-4 py-3 text-sm text-gray-300">{row.expectancy_r == null ? '-' : `${row.expectancy_r.toFixed(2)}R`}</td>
                  <td className="px-4 py-3 text-sm text-gray-300">{row.hit_rate == null ? '-' : `${(row.hit_rate * 100).toFixed(1)}%`}</td>
                </tr>
              ))}
              {regimeBreakdown.length === 0 && (
                <tr>
                  <td colSpan={5} className="px-4 py-10 text-center text-sm text-gray-500">No regime metrics yet.</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
};

export default AnalyticsPanel;
