import React, { useMemo } from 'react';
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Cell,
} from 'recharts';

// Per spec Req 7: library cast, does not count against @ts-expect-error budget.
// strictFunctionTypes: (value: number) not assignable to (value: ValueType | undefined) because
// ValueType includes string and array; runtime behavior is correct — this chart only passes numbers.
type TooltipFormatterFn = NonNullable<React.ComponentProps<typeof Tooltip>['formatter']>;
import { DistributionPoint } from '../../api/outcomes';

interface DistributionChartProps {
  data: DistributionPoint[];
  isLoading: boolean;
}

interface Bin {
  label: string;
  count: number;
  midpoint: number;
}

const BIN_SIZE = 1;
const BIN_MIN = -6;
const BIN_MAX = 10;

const colorForMidpoint = (mid: number): string => {
  if (mid < -0.5) return '#f85149';
  if (mid <= 0.5) return '#1f6feb';
  return '#3fb950';
};

const DistributionChart: React.FC<DistributionChartProps> = ({ data, isLoading }) => {
  const bins = useMemo<Bin[]>(() => {
    const buckets: Bin[] = [];
    for (let low = BIN_MIN; low < BIN_MAX; low += BIN_SIZE) {
      const mid = low + BIN_SIZE / 2;
      buckets.push({
        label: `${low >= 0 ? '+' : ''}${low}%`,
        count: 0,
        midpoint: mid,
      });
    }
    for (const pt of data) {
      const idx = Math.floor((pt.value - BIN_MIN) / BIN_SIZE);
      const clamped = Math.max(0, Math.min(buckets.length - 1, idx));
      buckets[clamped].count += 1;
    }
    return buckets;
  }, [data]);

  if (isLoading) {
    return (
      <div className="bg-financial-gray rounded-lg border border-gray-700 p-4">
        <div className="text-sm font-semibold text-financial-light mb-3">MFE Distribution</div>
        <div className="h-[250px] bg-gray-800/50 rounded-lg animate-pulse" />
      </div>
    );
  }

  if (!data || data.length === 0) {
    return (
      <div className="bg-financial-gray rounded-lg border border-gray-700 p-4">
        <div className="text-sm font-semibold text-financial-light mb-3">MFE Distribution</div>
        <div className="h-[250px] flex items-center justify-center text-gray-500 text-sm">
          No distribution data available
        </div>
      </div>
    );
  }

  return (
    <div className="bg-financial-gray rounded-lg border border-gray-700 p-4">
      <div className="text-sm font-semibold text-financial-light mb-3">MFE Distribution</div>
      <div className="h-[250px]">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={bins} margin={{ top: 5, right: 20, bottom: 5, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#374151" vertical={false} />
            <XAxis
              dataKey="label"
              stroke="#4B5563"
              tick={{ fontSize: 9, fontWeight: 'bold' }}
              interval={0}
              angle={-45}
              textAnchor="end"
              height={40}
            />
            <YAxis
              stroke="#4B5563"
              tick={{ fontSize: 10, fontWeight: 'bold' }}
              allowDecimals={false}
            />
            <Tooltip
              contentStyle={{
                backgroundColor: '#161b22',
                border: '1px solid #30363d',
                borderRadius: '8px',
              }}
              itemStyle={{ color: '#F9FAFB', fontSize: '12px' }}
              labelStyle={{ color: '#9CA3AF', fontSize: '10px', fontWeight: 'bold' }}
              formatter={((value: number) => [`${value} events`, 'Count']) as unknown as TooltipFormatterFn}
            />
            <Bar dataKey="count" radius={[4, 4, 0, 0]}>
              {bins.map((bin, i) => (
                <Cell key={i} fill={colorForMidpoint(bin.midpoint)} fillOpacity={0.8} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
};

export default DistributionChart;
