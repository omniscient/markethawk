import { describe, it, expect } from 'vitest';
import { calculateDoubleSuperTrend } from './indicators';

// Minimal OHLCV helpers for atrPeriod=1 deterministic tests.
// Hand-computed expected values are documented inline for each case.
const B0 = { High: 10, Low: 8, Open: 9, Close: 9, time: 1000 };
const B1 = { High: 12, Low: 10, Open: 10.5, Close: 11, time: 2000 };
const B2 = { High: 5, Low: 1, Open: 4, Close: 1, time: 3000 }; // close drops below tUp → trend -1
const B3 = { High: 20, Low: 18, Open: 19, Close: 20, time: 4000 }; // close rises above tDown → trend +1

function makeBar(v: number, time: number) {
  return { High: v + 1, Low: v - 1, Open: v, Close: v, time };
}

describe('calculateDoubleSuperTrend — guard clauses', () => {
  it('returns [] for empty input', () => {
    expect(calculateDoubleSuperTrend([])).toEqual([]);
  });

  it('returns [] when data.length < atrPeriod (default 12)', () => {
    const data = Array.from({ length: 11 }, (_, i) => makeBar(10, i));
    expect(calculateDoubleSuperTrend(data)).toEqual([]);
  });

  it('returns [] when data.length === atrPeriod - 1', () => {
    const data = Array.from({ length: 2 }, (_, i) => makeBar(10, i));
    expect(calculateDoubleSuperTrend(data, 3, 3)).toEqual([]);
  });
});

describe('calculateDoubleSuperTrend — length invariant', () => {
  it('returns data.length results when data.length === atrPeriod', () => {
    const data = Array.from({ length: 12 }, (_, i) => makeBar(10 + i, i));
    expect(calculateDoubleSuperTrend(data)).toHaveLength(12);
  });

  it('returns data.length results when data.length > atrPeriod', () => {
    const data = Array.from({ length: 20 }, (_, i) => makeBar(10 + i, i));
    expect(calculateDoubleSuperTrend(data)).toHaveLength(20);
  });

  it('returns 1 result for a single bar when atrPeriod=1', () => {
    expect(calculateDoubleSuperTrend([B0], 3, 1)).toHaveLength(1);
  });
});

describe('calculateDoubleSuperTrend — time passthrough', () => {
  it('carries input time values to output unchanged', () => {
    const data = [B0, B1, B2, B3];
    const result = calculateDoubleSuperTrend(data, 3, 1);
    expect(result.map((r) => r.time)).toEqual([1000, 2000, 3000, 4000]);
  });
});

describe('calculateDoubleSuperTrend — first bar (atrPeriod=1, factor=3)', () => {
  // B0: H=10, L=8, O=9, C=9
  // tr = max(10-8, |10-9|, |8-9|) = max(2,1,1) = 2
  // atr = 2 (i=0 branch)
  // hl2 = 9; up = 9 - 3*2 = 3; dn = 9 + 3*2 = 15
  // tUp = 3, tDown = 15 (no recursion at i=0)
  // prevTDown initialises to 0, Close(9) > 0 → trend = 1
  // tsl1 = tUp = 3, tsl2 = tDown = 15
  it('produces correct tsl1/tsl2/trend for the first bar', () => {
    const [p] = calculateDoubleSuperTrend([B0], 3, 1);
    expect(p.tsl1).toBe(3);
    expect(p.tsl2).toBe(15);
    expect(p.trend).toBe(1);
  });
});

describe('calculateDoubleSuperTrend — second bar RMA and recursive bands (atrPeriod=1, factor=3)', () => {
  // B1: H=12, L=10, O=10.5, C=11  (prev=B0: C=9)
  // tr = max(12-10, |12-9|, |10-9|) = max(2,3,1) = 3
  // RMA (atrPeriod=1): atr = (prevATR*0 + 3)/1 = 3
  // hl2=11; up=11-9=2; dn=11+9=20
  // prev.Close(9) > prevTUp(3) → tUp = max(2,3) = 3
  // prev.Close(9) < prevTDown(15) → tDown = min(20,15) = 15
  // Close(11) not > 15, not < 3 → trend = prevTrend = 1
  // tsl1=3, tsl2=15
  it('produces correct values for the second bar', () => {
    const [, p] = calculateDoubleSuperTrend([B0, B1], 3, 1);
    expect(p.tsl1).toBe(3);
    expect(p.tsl2).toBe(15);
    expect(p.trend).toBe(1);
  });
});

describe('calculateDoubleSuperTrend — trend direction changes', () => {
  // After B0+B1: prevTUp=3, prevTDown=15, prevTrend=1
  // B2: H=5, L=1, O=4, C=1
  // tr = max(4, |5-11|, |1-11|) = max(4,6,10) = 10
  // RMA(1): atr=10; hl2=3; up=3-30=-27; dn=3+30=33
  // prev.Close(11) > prevTUp(3) → tUp = max(-27,3) = 3
  // prev.Close(11) < prevTDown(15) → tDown = min(33,15) = 15
  // Close(1) < prevTUp(3) → trend = -1
  // tsl1 = tDown = 15, tsl2 = tUp = 3
  it('trend flips to -1 when close drops below prevTUp', () => {
    const result = calculateDoubleSuperTrend([B0, B1, B2], 3, 1);
    expect(result[2].trend).toBe(-1);
    expect(result[2].tsl1).toBe(15);
    expect(result[2].tsl2).toBe(3);
  });

  // After B2: prevTUp=3, prevTDown=15, prevTrend=-1
  // B3: H=20, L=18, O=19, C=20
  // tr = max(2, |20-1|, |18-1|) = max(2,19,17) = 19
  // RMA(1): atr=19; hl2=19; up=19-57=-38; dn=19+57=76
  // prev.Close(1) > prevTUp(3)? No → tUp = up = -38
  // prev.Close(1) < prevTDown(15)? Yes → tDown = min(76,15) = 15
  // Close(20) > prevTDown(15) → trend = 1
  // tsl1 = tUp = -38, tsl2 = tDown = 15
  it('trend flips back to +1 when close rises above prevTDown', () => {
    const result = calculateDoubleSuperTrend([B0, B1, B2, B3], 3, 1);
    expect(result[3].trend).toBe(1);
    expect(result[3].tsl1).toBe(-38);
    expect(result[3].tsl2).toBe(15);
  });
});

describe('calculateDoubleSuperTrend — structural invariants', () => {
  it('trend is always 1 or -1', () => {
    const data = Array.from({ length: 30 }, (_, i) => ({
      High: 10 + Math.sin(i) * 3,
      Low: 10 + Math.sin(i) * 3 - 2,
      Open: 10,
      Close: 10 + Math.sin(i) * 3 - 1,
      time: i,
    }));
    const result = calculateDoubleSuperTrend(data, 3, 5);
    for (const p of result) {
      expect(p.trend === 1 || p.trend === -1).toBe(true);
    }
  });

  it('tsl1 and tsl2 are always finite', () => {
    const data = Array.from({ length: 30 }, (_, i) => makeBar(10 + i, i));
    const result = calculateDoubleSuperTrend(data, 3, 5);
    for (const p of result) {
      expect(isFinite(p.tsl1)).toBe(true);
      expect(isFinite(p.tsl2)).toBe(true);
    }
  });
});

describe('calculateDoubleSuperTrend — custom parameters', () => {
  it('factor=2 produces narrower ATR bands than factor=3', () => {
    const data = [B0];
    // factor=3: tsl1=3, tsl2=15  (band width 6 each side)
    // factor=2: atr=2, up=9-4=5, dn=9+4=13
    const [p2] = calculateDoubleSuperTrend(data, 2, 1);
    const [p3] = calculateDoubleSuperTrend(data, 3, 1);
    expect(p2.tsl1).toBe(5);
    expect(p2.tsl2).toBe(13);
    expect(p2.tsl1).toBeGreaterThan(p3.tsl1); // narrower lower band
    expect(p2.tsl2).toBeLessThan(p3.tsl2);    // narrower upper band
  });

  it('atrPeriod=3 requires at least 3 bars', () => {
    const two = [B0, B1];
    const three = [B0, B1, B2];
    expect(calculateDoubleSuperTrend(two, 3, 3)).toEqual([]);
    expect(calculateDoubleSuperTrend(three, 3, 3)).toHaveLength(3);
  });
});
