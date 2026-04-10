import React from 'react';
import { Bell, TrendingUp, TrendingDown } from 'lucide-react';
import { format } from 'date-fns';
import { Link } from 'react-router-dom';
import Ticker from './Ticker';

interface Alert {
  id: string;
  ticker: string;
  type: 'volume_spike' | 'price_movement' | 'news';
  message: string;
  timestamp: string;
  severity: 'high' | 'medium' | 'low';
}

interface AlertListProps {
  alerts: Alert[];
  maxItems?: number;
}

const AlertList: React.FC<AlertListProps> = ({ alerts, maxItems = 5 }) => {
  const displayAlerts = alerts.slice(0, maxItems);

  const getSeverityColor = (severity: string) => {
    switch (severity) {
      case 'high':
        return 'bg-red-500/20 text-red-400 border-red-500/30';
      case 'medium':
        return 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30';
      case 'low':
        return 'bg-blue-500/20 text-blue-400 border-blue-500/30';
      default:
        return 'bg-gray-500/20 text-gray-400 border-gray-500/30';
    }
  };

  const getTypeIcon = (type: string) => {
    switch (type) {
      case 'volume_spike':
        return TrendingUp;
      case 'price_movement':
        return TrendingDown;
      default:
        return Bell;
    }
  };

  if (displayAlerts.length === 0) {
    return (
      <div className="text-center py-8">
        <Bell className="h-12 w-12 text-gray-600 mx-auto mb-2" />
        <p className="text-gray-400">No alerts at this time</p>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {displayAlerts.map((alert) => {
        const Icon = getTypeIcon(alert.type);
        return (
          <div
            key={alert.id}
            className={`p-3 rounded-lg border ${getSeverityColor(alert.severity)}`}
          >
            <div className="flex items-start space-x-3">
              <Icon className="h-4 w-4 mt-0.5 flex-shrink-0" />
              <div className="flex-1 min-w-0">
                <p className="text-sm">
                  <Ticker ticker={alert.ticker} size="sm" />
                </p>
                <p className="text-xs text-gray-300 mt-1">
                  {alert.message}
                </p>
                <p className="text-xs text-gray-500 mt-1">
                  {format(new Date(alert.timestamp), 'MMM d, h:mm a')}
                </p>
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
};

export default AlertList;