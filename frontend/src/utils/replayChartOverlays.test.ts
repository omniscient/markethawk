import { describe, expect, it } from 'vitest';
import { buildReplayMarkers, buildReplayPriceLines } from './replayChartOverlays';
import type { ReplayTrade } from '../api/replay';

const baseTrade: ReplayTrade = {
  id: 1,
  ticker: 'AAPL',
  signal_date: '2026-01-02',
  entry_date: '2026-01-02T14:31:00Z',
  entry_price: 100,
  direction: 'long',
  stop_price: 95,
  target_price: 110,
  exit_date: '2026-01-03T16:00:00Z',
  exit_price: 110,
  exit_reason: 'target',
  return_pct: 10,
  return_r: 2,
  mfe_pct: 11,
  mae_pct: -1,
  bars_held: 390,
  regime_trend: 'bullish',
  regime_vol: 'normal',
  fill_source: 'intraday',
};

describe('replay chart overlays', () => {
  it('builds sorted signal, entry, and exit markers', () => {
    const markers = buildReplayMarkers(baseTrade);

    expect(markers).toHaveLength(3);
    expect(markers.map((marker) => marker.text)).toEqual(['Signal', 'Entry', 'target']);
    expect(markers[1].shape).toBe('arrowUp');
    expect(markers[2].color).toBe('#22c55e');
  });

  it('uses short entry and losing exit directions', () => {
    const markers = buildReplayMarkers({
      ...baseTrade,
      direction: 'short',
      return_r: -1,
      exit_reason: 'stop',
    });

    expect(markers[1].position).toBe('aboveBar');
    expect(markers[1].shape).toBe('arrowDown');
    expect(markers[2].color).toBe('#ef4444');
  });

  it('builds entry, stop, target, and exit price lines', () => {
    expect(buildReplayPriceLines(baseTrade)).toEqual([
      { value: 100, color: '#38bdf8', label: 'Entry' },
      { value: 95, color: '#ef4444', label: 'Stop' },
      { value: 110, color: '#22c55e', label: 'Target' },
      { value: 110, color: '#f59e0b', label: 'Exit' },
    ]);
  });
});
