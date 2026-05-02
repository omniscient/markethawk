import React from 'react';
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from 'recharts';
import { EdgeDecayPoint } from '../../api/outcomes';

interface EdgeDecayChartProps {
  data: EdgeDecayPoint[];
  isLoading: boolean;
}

const EdgeDecayChart: React.FC<EdgeDecayChartProps> = ({ data, isLoading }) => {
  if (isLoading) {
    return (
      <div className="bg-financial-gray rounded-lg border border-gray-700 p-4">
        <div className="text-sm font-semibold text-financial-light mb-3">Edge Decay</div>
        <div className="h-[250px] bg-gray-800/50 rounded-lg animate-pulse" />
      </div>
    );
  }

  if (!data || data.length === 0) {
    return (
      <div className="bg-financial-gray rounded-lg border border-gray-700 p-4">
        <div className="text-sm font-semibold text-financial-light mb-3">Edge Decay</div>
        <div className="h-[250px] flex items-center justify-center text-gray-500 text-sm">
          Not enough data for edge decay analysis
        </div>
      </div>
    );
  }

  return (
    <div className="bg-financial-gray rounded-lg border border-gray-700 p-4">
      <div className="text-sm font-semibold text-financial-light mb-3">Edge Decay</div>
      <div className="h-[250px]">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 5, right: 20, bottom: 5, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#374151" vertical={false} />
            <XAxis
              dataKey="period"
              stroke="#4B5563"
              tick={{ fontSize: 10, fontWeight: 'bold' }}
            />
            <YAxis
              stroke="#4B5563"
              tick={{ fontSize: 10, fontWeight: 'bold' }}
              tickFormatter={(v: number) => `${v}%`}
            />
            <Tooltip
              contentStyle={{
                backgroundColor: '#161b22',
                border: '1px solid #30363d',
                borderRadius: '8px',
              }}
              itemStyle={{ color: '#F9FAFB', fontSize: '12px' }}
              labelStyle={{ color: '#9CA3AF', fontSize: '10px', fontWeight: 'bold' }}
            />
            <Legend
              verticalAlign="bottom"
              height={36}
              iconType="rect"
              wrapperStyle={{ fontSize: '10px', fontWeight: 'bold', textTransform: 'uppercase' }}
            />
            <Line
              type="monotone"
              dataKey="win_rate"
              name="Win Rate"
              stroke="#1f6feb"
              strokeWidth={2}
              dot={{ r: 3 }}
              activeDot={{ r: 5 }}
            />
            <Line
              type="monotone"
              dataKey="avg_mfe"
              name="Avg MFE"
              stroke="#3fb950"
              strokeWidth={2}
              dot={{ r: 3 }}
              activeDot={{ r: 5 }}
            />
            <Line
              type="monotone"
              dataKey="avg_mae"
              name="Avg MAE"
              stroke="#f85149"
              strokeWidth={2}
              dot={{ r: 3 }}
              activeDot={{ r: 5 }}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
};

export default EdgeDecayChart;
