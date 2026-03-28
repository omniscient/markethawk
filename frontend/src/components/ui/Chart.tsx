import React from 'react';
import {
  LineChart,
  Line,
  AreaChart,
  Area,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend,
  Cell,
  ComposedChart
} from 'recharts';

interface ChartProps {
  data: any[];
  type: 'line' | 'area' | 'bar' | 'candlestick';
  xKey: string;
  yKey?: string; // Optional if candlestick
  color?: string;
  height?: number;
  showGrid?: boolean;
  showTooltip?: boolean;
  showLegend?: boolean;
}

const Chart: React.FC<ChartProps> = ({
  data,
  type,
  xKey,
  yKey,
  color = '#0ea5e9',
  height = 300,
  showGrid = true,
  showTooltip = true,
  showLegend = false
}) => {
  const CustomTooltip = ({ active, payload, label }: any) => {
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
    const commonProps = {
      data,
      margin: { top: 5, right: 30, left: 20, bottom: 5 }
    };

    switch (type) {
      case 'line':
        return (
          <LineChart {...commonProps}>
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
            <Line
              type="monotone"
              dataKey={yKey}
              stroke={color}
              strokeWidth={2}
              dot={{ fill: color, strokeWidth: 2, r: 4 }}
              activeDot={{ r: 6, stroke: color, strokeWidth: 2 }}
            />
          </LineChart>
        );
      
      case 'area':
        return (
          <AreaChart {...commonProps}>
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
            <Area
              type="monotone"
              dataKey={yKey}
              stroke={color}
              fill={color}
              fillOpacity={0.3}
              strokeWidth={2}
            />
          </AreaChart>
        );
      
      case 'bar':
        return (
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
        );

      case 'candlestick':
        const candlestickData = data.map(d => ({
          ...d,
          candleBody: [d.Open, d.Close],
          candleWick: [d.Low, d.High],
          isPositive: d.Close >= d.Open
        }));

        return (
          <ComposedChart data={candlestickData} margin={commonProps.margin}>
             {showGrid && <CartesianGrid strokeDasharray="3 3" stroke="#374151" vertical={false} />}
             <XAxis 
               dataKey={xKey} 
               stroke="#9ca3af"
               fontSize={10}
               tickLine={false}
               tickFormatter={(val) => {
                 try {
                   return val.split('-').slice(1).join('/'); // MM/DD
                 } catch (e) {
                   return val;
                 }
               }}
             />
             <YAxis 
               stroke="#9ca3af"
               fontSize={12}
               tickLine={false}
               domain={['auto', 'auto']}
             />
             {showTooltip && <Tooltip 
               contentStyle={{ backgroundColor: '#1f2937', border: '1px solid #4b5563', borderRadius: '8px' }}
               itemStyle={{ color: '#f3f4f6' }}
             />}
             <Bar dataKey="candleWick" fill="#6b7280" barSize={1} />
             <Bar dataKey="candleBody">
               {candlestickData.map((entry, index) => (
                 <Cell key={`cell-${index}`} fill={entry.isPositive ? '#10b981' : '#ef4444'} />
               ))}
             </Bar>
          </ComposedChart>
        );
      
      default:
        return null;
    }
  };

  return (
    <div style={{ height: `${height}px` }} className="w-full">
      <ResponsiveContainer width="100%" height="100%">
        {renderChart()}
      </ResponsiveContainer>
    </div>
  );
};

export default Chart;