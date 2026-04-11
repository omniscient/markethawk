import React from 'react';
import { Activity, AlertCircle, Info, ShieldAlert } from 'lucide-react';
import { format } from 'date-fns';
import Ticker from './Ticker';
import { ScannerEvent } from '../api/scanner';

interface RecentEventsProps {
  events: ScannerEvent[];
  maxItems?: number;
  sortBy?: string;
  sortOrder?: 'asc' | 'desc';
  onSort?: (_column: string) => void;
  onEventClick?: (_event: ScannerEvent) => void;
}

const RecentEvents: React.FC<RecentEventsProps> = ({
  events,
  maxItems = 10,
  sortBy: _sortBy,
  sortOrder: _sortOrder,
  onSort: _onSort,
  onEventClick
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

  const getSeverityStyles = (severity: string) => {
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

  const getSeverityIcon = (severity: string) => {
    switch (severity) {
      case 'high':
        return <ShieldAlert className="h-3 w-3 mr-1" />;
      case 'medium':
        return <AlertCircle className="h-3 w-3 mr-1" />;
      default:
        return <Info className="h-3 w-3 mr-1" />;
    }
  };

  return (
    <div className="space-y-2">
      <div className="grid grid-cols-12 gap-4 px-4 py-2 text-xs font-medium text-gray-400 border-b border-gray-700">
        <div className="col-span-2">Ticker</div>
        <div className="col-span-2">Date</div>
        <div className="col-span-5">Summary</div>
        <div className="col-span-2">Severity</div>
        <div className="col-span-1">Details</div>
      </div>

      {displayEvents.map((event) => (
        <div
          key={event.id}
          onClick={() => onEventClick?.(event)}
          className="grid grid-cols-12 gap-4 px-4 py-3 bg-gray-800/50 rounded-lg hover:bg-gray-700/50 border border-gray-700/50 transition-all cursor-pointer items-center"
        >
          <div className="col-span-2">
            <Ticker ticker={event.ticker} />
          </div>

          <div className="col-span-2 text-sm text-gray-400">
            {format(new Date(event.event_date.includes('T') ? event.event_date : `${event.event_date}T00:00:00`), 'MMM d')}
          </div>

          <div className="col-span-5">
            <p className="text-sm text-gray-200 truncate" title={event.summary}>
              {event.summary || `${event.scanner_type.replace(/_/g, ' ')} detected`}
            </p>
          </div>

          <div className="col-span-2">
            <span className={`inline-flex items-center px-2 py-0.5 rounded text-[10px] font-bold uppercase border ${getSeverityStyles(event.severity)}`}>
              {getSeverityIcon(event.severity)}
              {event.severity}
            </span>
          </div>

          <div className="col-span-1 text-right">
            <span className={`px-1.5 py-0.5 rounded text-[10px] font-bold ${Object.values(event.criteria_met || {}).every(Boolean)
                ? 'text-positive'
                : 'text-yellow-400'
              }`}>
              {Object.values(event.criteria_met || {}).filter(Boolean).length}/
              {Object.values(event.criteria_met || {}).length}
            </span>
          </div>
        </div>
      ))}
    </div>
  );
};

export default RecentEvents;