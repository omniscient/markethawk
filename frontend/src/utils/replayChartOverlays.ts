import type { SeriesMarker, Time } from 'lightweight-charts';
import type { ReplayTrade } from '../api/replay';

export interface ReplayPriceLine {
  value: number;
  color: string;
  label: string;
}

const timeFromIso = (value: string | null): Time | null => {
  if (!value) return null;
  return value.split('T')[0].split(' ')[0] as Time;
};

export const buildReplayMarkers = (trade: ReplayTrade): SeriesMarker<Time>[] => {
  const markers: SeriesMarker<Time>[] = [];
  const signalTime = timeFromIso(trade.signal_date);
  const entryTime = timeFromIso(trade.entry_date);
  const exitTime = timeFromIso(trade.exit_date);

  if (signalTime) {
    markers.push({
      time: signalTime,
      position: 'belowBar',
      color: '#f59e0b',
      shape: 'circle',
      size: 1,
      text: 'Signal',
    });
  }

  if (entryTime) {
    markers.push({
      time: entryTime,
      position: trade.direction === 'short' ? 'aboveBar' : 'belowBar',
      color: '#38bdf8',
      shape: trade.direction === 'short' ? 'arrowDown' : 'arrowUp',
      size: 1,
      text: 'Entry',
    });
  }

  if (exitTime) {
    markers.push({
      time: exitTime,
      position: trade.return_r != null && trade.return_r < 0 ? 'belowBar' : 'aboveBar',
      color: trade.return_r != null && trade.return_r < 0 ? '#ef4444' : '#22c55e',
      shape: trade.return_r != null && trade.return_r < 0 ? 'arrowDown' : 'arrowUp',
      size: 1,
      text: trade.exit_reason ?? 'Exit',
    });
  }

  return markers.sort((a, b) =>
    typeof a.time === 'number' && typeof b.time === 'number'
      ? a.time - b.time
      : String(a.time).localeCompare(String(b.time)),
  );
};

export const buildReplayPriceLines = (trade: ReplayTrade): ReplayPriceLine[] => {
  const lines: ReplayPriceLine[] = [];

  if (trade.entry_price != null) {
    lines.push({ value: trade.entry_price, color: '#38bdf8', label: 'Entry' });
  }
  if (trade.stop_price != null) {
    lines.push({ value: trade.stop_price, color: '#ef4444', label: 'Stop' });
  }
  if (trade.target_price != null) {
    lines.push({ value: trade.target_price, color: '#22c55e', label: 'Target' });
  }
  if (trade.exit_price != null) {
    lines.push({ value: trade.exit_price, color: '#f59e0b', label: 'Exit' });
  }

  return lines;
};
