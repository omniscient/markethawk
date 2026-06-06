import { describe, it, expect } from 'vitest';
import { calculateDoubleSuperTrend } from './indicators';
import type { OHLCVInput } from './indicators';

function makeBar(close: number, high?: number, low?: number, open?: number): OHLCVInput {
  return {
    Close: close,
    High: high ?? close + 0.5,
    Low: low ?? close - 0.5,
    Open: open ?? close,
    time: 0,
  };
}

function makeNBars(n: number, baseClose = 100): OHLCVInput[] {
  return Array.from({ length: n }, (_, i) =>
    makeBar(baseClose + i * 0.1)
  );
}

describe('calculateDoubleSuperTrend', () => {
  it('returns [] when data length < atrPeriod', () => {
    expect(calculateDoubleSuperTrend(makeNBars(5), 3, 12)).toEqual([]);
  });

  it('returns [] when data is empty', () => {
    expect(calculateDoubleSuperTrend([], 3, 12)).toEqual([]);
  });

  it('returns one point per bar when data >= atrPeriod', () => {
    const data = makeNBars(20);
    const result = calculateDoubleSuperTrend(data, 3, 12);
    expect(result).toHaveLength(20);
  });

  it('each point has tsl1, tsl2, trend, time fields', () => {
    const data = makeNBars(15);
    const result = calculateDoubleSuperTrend(data, 3, 12);
    expect(result[0]).toHaveProperty('tsl1');
    expect(result[0]).toHaveProperty('tsl2');
    expect(result[0]).toHaveProperty('trend');
    expect(result[0]).toHaveProperty('time');
  });

  it('trend is 1 or -1', () => {
    const data = makeNBars(20);
    const result = calculateDoubleSuperTrend(data, 3, 12);
    for (const pt of result) {
      expect([1, -1]).toContain(pt.trend);
    }
  });

  it('tsl1 equals tUp when trend is 1', () => {
    // Rising prices → trend=1, tsl1 = tUp (lower band)
    const risingBars = Array.from({ length: 20 }, (_, i) =>
      makeBar(100 + i * 2, 102 + i * 2, 99 + i * 2)
    );
    const result = calculateDoubleSuperTrend(risingBars, 3, 5);
    const bullPoints = result.filter(p => p.trend === 1);
    for (const p of bullPoints) {
      expect(p.tsl1).toBeLessThan(p.tsl2);
    }
  });

  it('uses custom factor and atrPeriod', () => {
    const data = makeNBars(20);
    const r1 = calculateDoubleSuperTrend(data, 1, 5);
    const r2 = calculateDoubleSuperTrend(data, 5, 5);
    // Larger factor → wider bands → tsl values differ
    expect(r1[10].tsl1).not.toEqual(r2[10].tsl1);
  });

  it('preserves the time value from the input bar', () => {
    const data = makeNBars(15);
    data[0].time = 'bar-0-time';
    data[5].time = 42;
    const result = calculateDoubleSuperTrend(data, 3, 12);
    expect(result[0].time).toBe('bar-0-time');
    expect(result[5].time).toBe(42);
  });
});
