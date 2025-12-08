import React from 'react';
import { TrendingUp, TrendingDown, Activity } from 'lucide-react';
import { format } from 'date-fns';

interface Event {
  id: string;
  ticker: string;
  event_date: string;
  event_type: string;
  relative_volume: number;
  volume_spike_ratio: number;
  price_gap_pct: number;
  criteria_met: Record<string, any>;
}

interface RecentEventsProps {
  events: Event[];
  maxItems?: number;
}

const RecentEvents: React.FC<RecentEventsProps> = ({ events, maxItems = 10 }) => {
  const displayEvents = events.slice(0, maxItems);

  const formatVolume = (volume: number) => {
    if (volume >= 1000000) {
      return `${(volume / 1000000).toFixed(1)}M`;
    } else if (volume >= 1000) {
      return `${(volume / 1000).toFixed(1)}K`;
    }
    return volume.toString();
  };

  if (displayEvents.length === 0) {
    return (
      <div className="text-center py-8">
        <Activity className="h-12 w-12 text-gray-600 mx-auto mb-2" />
        <p className="text-gray-400">No recent events</p>
      </div>
    );
  }

  return (
    <div className="space-y-2">
      <div className="grid grid-cols-12 gap-4 px-4 py-2 text-xs font-medium text-gray-400 border-b border-gray-700">
        <div className="col-span-2">Ticker</div>
        <div className="col-span-2">Date</div>
        <div className="col-span-2">Volume Spike</div>
        <div className="col-span-2">Rel Volume</div>
        <div className="col-span-2">Gap %</div>
        <div className="col-span-2">Status</div>
      </div>
      
      {displayEvents.map((event) => (
        <div
          key={event.id}
          className="grid grid-cols-12 gap-4 px-4 py-3 bg-gray-800 rounded-lg hover:bg-gray-700 transition-colors cursor-pointer"
        >
          <div className="col-span-2">
            <span className="font-medium text-financial-light">{event.ticker}</span>
          </div>
          
          <div className="col-span-2 text-sm text-gray-400">
            {format(new Date(event.event_date), 'MMM d')}
          </div>
          
          <div className="col-span-2">
            <div className="flex items-center space-x-1">
              <TrendingUp className="h-4 w-4 text-positive" />
              <span className="text-positive font-medium">
                {event.volume_spike_ratio}x
              </span>
            </div>
          </div>
          
          <div className="col-span-2">
            <span className="text-financial-light font-medium">
              {event.relative_volume.toFixed(1)}x
            </span>
          </div>
          
          <div className="col-span-2">
            {event.price_gap_pct > 0 ? (
              <div className="flex items-center space-x-1">
                <TrendingUp className="h-4 w-4 text-positive" />
                <span className="text-positive font-medium">
                  +{event.price_gap_pct.toFixed(1)}%
                </span>
              </div>
            ) : (
              <div className="flex items-center space-x-1">
                <TrendingDown className="h-4 w-4 text-negative" />
                <span className="text-negative font-medium">
                  {event.price_gap_pct.toFixed(1)}%
                </span>
              </div>
            )}
          </div>
          
          <div className="col-span-2">
            <span className={`px-2 py-1 rounded text-xs font-medium ${
              Object.values(event.criteria_met).every(Boolean)
                ? 'bg-green-500/20 text-green-400'
                : 'bg-yellow-500/20 text-yellow-400'
            }`}>
              {Object.values(event.criteria_met).every(Boolean) ? 'All Met' : 'Partial'}
            </span>
          </div>
        </div>
      ))}
    </div>
  );
};

export default RecentEvents;