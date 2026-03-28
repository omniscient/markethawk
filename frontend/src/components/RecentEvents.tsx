import React from 'react';
import { TrendingUp, TrendingDown, Activity, ChevronUp, ChevronDown } from 'lucide-react';
import { format } from 'date-fns';
import { Link } from 'react-router-dom';

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
  sortBy?: string;
  sortOrder?: 'asc' | 'desc';
  onSort?: (column: string) => void;
}

const RecentEvents: React.FC<RecentEventsProps> = ({ 
  events, 
  maxItems = 10,
  sortBy,
  sortOrder,
  onSort
}) => {
  const displayEvents = events.slice(0, maxItems);

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
        <SortableGridHeader 
          label="Ticker" 
          sortKey="ticker" 
          currentSort={sortBy} 
          currentOrder={sortOrder} 
          onSort={onSort} 
          className="col-span-2"
        />
        <SortableGridHeader 
          label="Date" 
          sortKey="event_date" 
          currentSort={sortBy} 
          currentOrder={sortOrder} 
          onSort={onSort} 
          className="col-span-2"
        />
        <SortableGridHeader 
          label="Volume Spike" 
          sortKey="volume_spike_ratio" 
          currentSort={sortBy} 
          currentOrder={sortOrder} 
          onSort={onSort} 
          className="col-span-2"
        />
        <SortableGridHeader 
          label="Rel Volume" 
          sortKey="relative_volume" 
          currentSort={sortBy} 
          currentOrder={sortOrder} 
          onSort={onSort} 
          className="col-span-2"
        />
        <SortableGridHeader 
          label="Gap %" 
          sortKey="price_gap_pct" 
          currentSort={sortBy} 
          currentOrder={sortOrder} 
          onSort={onSort} 
          className="col-span-2"
        />
        <div className="col-span-2">Status</div>
      </div>

      {displayEvents.map((event) => (
        <div
          key={event.id}
          className="grid grid-cols-12 gap-4 px-4 py-3 bg-gray-800 rounded-lg hover:bg-gray-700 transition-colors cursor-pointer"
        >
          <div className="col-span-2">
            <Link 
              to={`/stock/${event.ticker}`}
              className="font-medium text-financial-blue hover:text-blue-400 transition-colors"
            >
              {event.ticker}
            </Link>
          </div>

          <div className="col-span-2 text-sm text-gray-400">
            {format(new Date(event.event_date), 'MMM d')}
          </div>

          <div className="col-span-2">
            <div className="flex items-center space-x-1">
              <TrendingUp className="h-4 w-4 text-positive" />
              <span className="text-positive font-medium">
                {event.volume_spike_ratio ?? 0}x
              </span>
            </div>
          </div>

          <div className="col-span-2">
            <span className="text-financial-light font-medium">
              {(event.relative_volume ?? 0).toFixed(1)}x
            </span>
          </div>

          <div className="col-span-2">
            {(event.price_gap_pct ?? 0) > 0 ? (
              <div className="flex items-center space-x-1">
                <TrendingUp className="h-4 w-4 text-positive" />
                <span className="text-positive font-medium">
                  +{(event.price_gap_pct ?? 0).toFixed(1)}%
                </span>
              </div>
            ) : (
              <div className="flex items-center space-x-1">
                <TrendingDown className="h-4 w-4 text-negative" />
                <span className="text-negative font-medium">
                  {(event.price_gap_pct ?? 0).toFixed(1)}%
                </span>
              </div>
            )}
          </div>

          <div className="col-span-2">
            <span className={`px-2 py-1 rounded text-xs font-medium ${Object.values(event.criteria_met || {}).every(Boolean)
                ? 'bg-green-500/20 text-green-400'
                : 'bg-yellow-500/20 text-yellow-400'
              }`}>
              {Object.values(event.criteria_met || {}).every(Boolean) ? 'All Met' : 'Partial'}
            </span>
          </div>
        </div>
      ))}
    </div>
  );
};

interface SortableGridHeaderProps {
  label: string;
  sortKey: string;
  currentSort?: string;
  currentOrder?: 'asc' | 'desc';
  onSort?: (key: string) => void;
  className?: string;
}

const SortableGridHeader: React.FC<SortableGridHeaderProps> = ({ 
  label, 
  sortKey, 
  currentSort, 
  currentOrder, 
  onSort,
  className = ""
}) => {
  const isActive = currentSort === sortKey;
  
  return (
    <div 
      className={`${className} cursor-pointer hover:text-financial-light transition-colors group select-none`}
      onClick={() => onSort?.(sortKey)}
    >
      <div className="flex items-center space-x-1">
        <span>{label}</span>
        <div className="flex flex-col">
          <ChevronUp 
            className={`h-2.5 w-2.5 -mb-0.5 ${isActive && currentOrder === 'asc' ? 'text-financial-blue' : 'text-gray-600 group-hover:text-gray-400'}`} 
          />
          <ChevronDown 
            className={`h-2.5 w-2.5 ${isActive && currentOrder === 'desc' ? 'text-financial-blue' : 'text-gray-600 group-hover:text-gray-400'}`} 
          />
        </div>
      </div>
    </div>
  );
};

export default RecentEvents;