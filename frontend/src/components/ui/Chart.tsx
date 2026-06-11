import React from 'react';
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend,
} from 'recharts';

import StockChart from './StockChart';
import type { StockBarRow } from './StockChart';
import type { ScannerEvent } from '../../api/scanner';
import type { LiveStockData } from '../../hooks/useLiveStockData';

interface ChartProps {
  data: StockBarRow[] | ScannerEvent[];
  type: 'line' | 'area' | 'bar' | 'candlestick';
  xKey: string;
  yKey?: string; // Optional if candlestick
  events?: ScannerEvent[];
  highlightDate?: string;
  color?: string;
  height?: number;
  timespan?: string;
  symbol?: string;
  liveData?: LiveStockData | null;
  showGrid?: boolean;
  showTooltip?: boolean;
  showLegend?: boolean;
  showDoubleSuperTrend?: boolean;
}

const Chart: React.FC<ChartProps> = ({
  data,
  type,
  xKey,
  yKey,
  events,
  highlightDate,
  color = '#0ea5e9',
  height = 300,
  timespan = 'day',
  symbol,
  liveData,
  showGrid = true,
  showTooltip = true,
  showLegend = false,
  showDoubleSuperTrend = false
}) => {
  const CustomTooltip = ({ active, payload, label }: { active?: boolean; payload?: { value: unknown }[]; label?: string }) => {
    if (active && payload && payload.length) {
      return (
        <div className="bg-gray-800 border border-gray-600 rounded-lg p-3 shadow-lg">
          <p className="text-gray-400 text-sm">{`${xKey}: ${label}`}</p>
          <p className="text-financial-light font-medium">
            {`${yKey}: ${payload[0].value}`}
          </p>
        </div>
      );
    }
    return null;
  };

  const renderChart = () => {
    // For time-series data (line/area/candlestick), use the high-performance StockChart
    if (type === 'candlestick' || type === 'line' || type === 'area') {
      return (
        <div style={{ height: `${height}px` }} className="w-full">
          <StockChart 
            data={data} 
            type={type} 
            timespan={timespan}
            height={height} 
            events={events}
            highlightDate={highlightDate}
            symbol={symbol}
            liveData={liveData}
            showDoubleSuperTrend={showDoubleSuperTrend}
            colors={{
              background: 'transparent', // Let the card handle background
              upColor: '#10b981',
              downColor: '#ef4444',
            }}
          />
        </div>
      );
    }

    // Fallback to Recharts for simple bar charts or other types
    // Recharts needs an array of a union, not a union of arrays
    const commonProps = {
      data: data as (StockBarRow | ScannerEvent)[],
      margin: { top: 5, right: 30, left: 20, bottom: 5 }
    };

    switch (type) {
      case 'bar':
        return (
          <ResponsiveContainer width="100%" height={height}>
            <BarChart {...commonProps}>
              {showGrid && <CartesianGrid strokeDasharray="3 3" stroke="#374151" />}
              <XAxis 
                dataKey={xKey} 
                stroke="#9ca3af"
                fontSize={12}
                tickLine={false}
              />
              <YAxis 
                stroke="#9ca3af"
                fontSize={12}
                tickLine={false}
              />
              {showTooltip && <Tooltip content={<CustomTooltip />} />}
              {showLegend && <Legend />}
              <Bar
                dataKey={yKey!}
                fill={color}
                radius={[4, 4, 0, 0]}
              />
            </BarChart>
          </ResponsiveContainer>
        );
      
      default:
        return null;
    }
  };

  return (
    <div className="w-full">
      {renderChart()}
    </div>
  );
};

export default Chart;