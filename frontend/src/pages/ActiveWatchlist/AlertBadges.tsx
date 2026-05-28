
import type { LiveAlert } from '../../hooks/useWatchlistLive';

export function AlertBadge({ alert }: { alert: LiveAlert | null }) {
  if (!alert) return null;

  const age = Date.now() - new Date(alert.timestamp).getTime();
  if (age > 3_600_000) return null; // hide alerts older than 1 hour

  const color =
    alert.severity === 'high' ? 'bg-red-900/60 text-red-300 border-red-700'
    : alert.severity === 'medium' ? 'bg-yellow-900/50 text-yellow-300 border-yellow-700'
    : 'bg-gray-800 text-gray-400 border-gray-600';

  return (
    <span className={`inline-block text-xs px-1.5 py-0.5 rounded border ${color}`} title={alert.summary}>
      {alert.scanner_type === 'live_volume_spike' ? 'VOL' : 'MOVE'}
    </span>
  );
}
