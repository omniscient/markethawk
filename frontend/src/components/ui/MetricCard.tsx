import React from 'react';
import { LucideIcon, TrendingUp, TrendingDown } from 'lucide-react';

interface MetricCardProps {
  title: string;
  value: string | number;
  change?: number;
  trend?: number;
  icon: LucideIcon;
  color?: 'blue' | 'green' | 'red' | 'yellow' | 'purple';
  subtitle?: string;
  valueColor?: string;
}

const MetricCard: React.FC<MetricCardProps> = ({
  title,
  value,
  change,
  trend,
  icon: Icon,
  color = 'blue',
  subtitle,
  valueColor,
}) => {
  const effectiveChange = change ?? trend;
  const colorClasses = {
    blue: 'bg-blue-500/10 text-blue-400',
    green: 'bg-green-500/10 text-green-400',
    red: 'bg-red-500/10 text-red-400',
    yellow: 'bg-yellow-500/10 text-yellow-400',
    purple: 'bg-purple-500/10 text-purple-400',
  };

  const isPositive = effectiveChange && effectiveChange > 0;

  return (
    <div className="bg-financial-gray rounded-lg border border-gray-700 p-6 shadow-lg">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-gray-400 text-sm font-medium">{title}</p>
          <p className={`text-2xl font-bold mt-1 ${valueColor ?? 'text-financial-light'}`}>
            {value}
          </p>
          {subtitle && (
            <p className="text-gray-500 text-xs mt-1">{subtitle}</p>
          )}
          {effectiveChange !== undefined && effectiveChange !== 0 && (
            <div className="flex items-center mt-2">
              {isPositive ? (
                <TrendingUp className="h-4 w-4 text-positive mr-1" />
              ) : (
                <TrendingDown className="h-4 w-4 text-negative mr-1" />
              )}
              <span className={`text-sm font-medium ${
                isPositive ? 'text-positive' : 'text-negative'
              }`}>
                {Math.abs(effectiveChange)}%
              </span>
              <span className="text-gray-400 text-sm ml-1">vs last period</span>
            </div>
          )}
        </div>
        <div className={`p-3 rounded-lg ${colorClasses[color]}`}>
          <Icon className="h-6 w-6" />
        </div>
      </div>
    </div>
  );
};

export default MetricCard;