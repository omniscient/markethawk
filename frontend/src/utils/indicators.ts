
/**
 * Calculates the Double SuperTrend ATR indicator.
 * Translated from Pine Script:
 * Up=hl2-(Factor*atr(ATR))
 * Dn=hl2+(Factor*atr(ATR))
 * TUp=close[1]>TUp[1]? max(Up,TUp[1]) : Up
 * TDown=close[1]<TDown[1]? min(Dn,TDown[1]) : Dn
 * Trend = close > TDown[1] ? 1: close< TUp[1]? -1: nz(Trend[1],1)
 */
export function calculateDoubleSuperTrend(
  data: any[],
  factor: number = 3,
  atrPeriod: number = 12
) {
  if (data.length < atrPeriod) return [];

  const results = [];
  let prevATR = 0;
  let prevTUp = 0;
  let prevTDown = 0;
  let prevTrend = 1;

  for (let i = 0; i < data.length; i++) {
    const current = data[i];
    const prev = i > 0 ? data[i - 1] : current;

    // 1. Calculate True Range
    const tr = Math.max(
      current.High - current.Low,
      Math.abs(current.High - (prev.Close || current.Open)),
      Math.abs(current.Low - (prev.Close || current.Open))
    );

    // 2. Calculate ATR (RMA)
    let atr: number;
    if (i === 0) {
      atr = tr;
    } else if (i < atrPeriod) {
      // Warm up period (simple average for the first N bars)
      prevATR = (prevATR * i + tr) / (i + 1);
      atr = prevATR;
    } else {
      // RMA: (prevATR * (n - 1) + tr) / n
      atr = (prevATR * (atrPeriod - 1) + tr) / atrPeriod;
    }
    prevATR = atr;

    // 3. hl2
    const hl2 = (current.High + current.Low) / 2;

    // 4. Up / Dn
    const up = hl2 - factor * atr;
    const dn = hl2 + factor * atr;

    // 5. TUp / TDown (Recursive)
    let tUp = up;
    let tDown = dn;

    if (i > 0) {
      tUp = prev.Close > prevTUp ? Math.max(up, prevTUp) : up;
      tDown = prev.Close < prevTDown ? Math.min(dn, prevTDown) : dn;
    }

    // 6. Trend
    let trend = prevTrend;
    if (current.Close > prevTDown) {
      trend = 1;
    } else if (current.Close < prevTUp) {
      trend = -1;
    }

    // 7. Tsl1 / Tsl2
    const tsl1 = trend === 1 ? tUp : tDown;
    const tsl2 = trend === 1 ? tDown : tUp;

    results.push({
      time: current.time, // We'll pass the processed time from the chart
      tsl1,
      tsl2,
      trend,
    });

    prevTUp = tUp;
    prevTDown = tDown;
    prevTrend = trend;
  }

  return results;
}
