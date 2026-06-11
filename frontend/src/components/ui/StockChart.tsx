import React, { useEffect, useRef } from 'react';
import {
  createChart,
  ColorType,
  IChartApi,
  ISeriesApi,
  ISeriesMarkersPluginApi,
  CandlestickData,
  LineData,
  AreaData,
  Time,
  CandlestickSeries,
  AreaSeries,
  LineSeries,
  HistogramSeries,
  createSeriesMarkers,
  SeriesMarker,
} from 'lightweight-charts';
import { calculateDoubleSuperTrend } from '../../utils/indicators';
import { ScannerEvent } from '../../api/scanner';

interface StyledCandleData extends CandlestickData {
  color?: string;
  borderColor?: string;
  wickColor?: string;
}

export interface StockBarRow {
  Date?: string;
  Open?: number;
  High?: number;
  Low?: number;
  Close?: number;
  Volume?: number | null;
  vwap?: number | null;
  vwap_intraday?: number | null;
  marker_type?: string | null;
  contract_month?: string | null;
  transactions?: number | null;
  // Used in line/area mode for relative volume charts
  event_date?: string;
  relative_volume?: number;
}

interface StockChartProps {
  data: StockBarRow[];
  type: 'candlestick' | 'area' | 'line';
  timespan?: string;
  height?: number;
  events?: ScannerEvent[];
  highlightDate?: string;
  symbol?: string; // Ticker symbol for live data filtering
  liveData?: {
    ev: string;
    sym: string;
    v: number;
    o: number;
    c: number;
    h: number;
    l: number;
    vw: number | null;
    s: number;
    e: number;
  } | null;
  colors?: {
    background?: string;
    text?: string;
    upColor?: string;
    downColor?: string;
    borderUpColor?: string;
    borderDownColor?: string;
    wickUpColor?: string;
    wickDownColor?: string;
  };
  showDoubleSuperTrend?: boolean;
}

const StockChart: React.FC<StockChartProps> = ({
  data,
  type,
  timespan = 'day',
  height = 400,
  events = [],
  highlightDate,
  symbol,
  liveData,
  colors = {},
  showDoubleSuperTrend = false
}) => {
  // Helper to shift UTC timestamps to match the browser's local time labels
  const toLocalTime = (utcSeconds: number): number => {
    const d = new Date(utcSeconds * 1000);
    return Date.UTC(
      d.getFullYear(),
      d.getMonth(),
      d.getDate(),
      d.getHours(),
      d.getMinutes(),
      d.getSeconds()
    ) / 1000;
  };

  const chartContainerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null);
  const volumeSeriesRef = useRef<ISeriesApi<'Histogram'> | null>(null);
  const vwapSeriesRef = useRef<ISeriesApi<'Line'> | null>(null);
  const stLine1SeriesRef = useRef<ISeriesApi<'Line'> | null>(null);
  const stLine2SeriesRef = useRef<ISeriesApi<'Line'> | null>(null);
  const stCloudSeriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null);
  const markersPluginRef = useRef<ISeriesMarkersPluginApi<Time> | null>(null);
  const prevDataLengthRef = useRef<number>(0);
  const currentBarRef = useRef<{
    time: Time;
    open: number;
    high: number;
    low: number;
    close: number;
  } | null>(null);

  const {
    background = '#0f172a',
    text = '#9ca3af',
    upColor = '#10b981',
    downColor = '#ef4444',
  } = colors;

  useEffect(() => {
    if (!chartContainerRef.current) return;

    // Create chart
    const chart = createChart(chartContainerRef.current, {
      layout: {
        background: { type: ColorType.Solid, color: background },
        textColor: text,
        fontSize: 12,
        fontFamily: 'Inter, system-ui, sans-serif',
      },
      width: chartContainerRef.current.clientWidth,
      height: height,
      grid: {
        vertLines: { color: '#1e293b' },
        horzLines: { color: '#1e293b' },
      },
      crosshair: {
        mode: 1, // Normal crosshair
        vertLine: {
          color: '#475569',
          width: 1,
          style: 3, // Dotted
          labelBackgroundColor: '#1e293b',
        },
        horzLine: {
          color: '#475569',
          width: 1,
          style: 3, // Dotted
          labelBackgroundColor: '#1e293b',
        },
      },
      timeScale: {
        borderColor: '#1e293b',
        timeVisible: true,
        secondsVisible: false,
      },
      handleScroll: true,
      handleScale: true,
    });

    chartRef.current = chart;

    // Add series based on type using v5 addSeries API
    if (type === 'candlestick') {
      const candlestickSeries = chart.addSeries(CandlestickSeries, {
        upColor: upColor,
        downColor: downColor,
        borderVisible: false,
        wickUpColor: upColor,
        wickDownColor: downColor,
      });
      seriesRef.current = candlestickSeries;
      
      // Initialize markers plugin for v5
      markersPluginRef.current = createSeriesMarkers(candlestickSeries, []);

      // Add volume histogram
      const volumeSeries = chart.addSeries(HistogramSeries, {
        color: '#1e293b',
        priceFormat: {
          type: 'volume',
        },
        priceScaleId: '', // Overlay over price
      });
      
      volumeSeries.priceScale().applyOptions({
        scaleMargins: {
          top: 0.8, // volume at bottom 20%
          bottom: 0,
        },
      });
      volumeSeriesRef.current = volumeSeries;

      // Add VWAP line
      const vwapSeries = chart.addSeries(LineSeries, {
        color: '#f97316', // orange-500
        lineWidth: 2,
        crosshairMarkerVisible: false,
        lastValueVisible: false,
        priceLineVisible: false,
      });
      vwapSeriesRef.current = vwapSeries;
      
      // Add Double SuperTrend Series (only visible if toggled)
      const stLine1 = chart.addSeries(LineSeries, {
        color: '#10b981',
        lineWidth: 1,
        crosshairMarkerVisible: false,
        lastValueVisible: false,
        priceLineVisible: false,
        visible: showDoubleSuperTrend,
      });
      stLine1SeriesRef.current = stLine1;

      const stLine2 = chart.addSeries(LineSeries, {
        color: '#10b981',
        lineWidth: 1,
        crosshairMarkerVisible: false,
        lastValueVisible: false,
        priceLineVisible: false,
        visible: showDoubleSuperTrend,
      });
      stLine2SeriesRef.current = stLine2;

      const stCloud = chart.addSeries(CandlestickSeries, {
        upColor: 'rgba(16, 185, 129, 0.2)',
        downColor: 'rgba(239, 68, 68, 0.2)',
        borderVisible: false,
        wickVisible: false,
        visible: showDoubleSuperTrend,
        priceLineVisible: false,
        lastValueVisible: false,
      });
      stCloudSeriesRef.current = stCloud;

    } else if (type === 'area') {
      const areaSeries = chart.addSeries(AreaSeries, {
        lineColor: '#0ea5e9',
        topColor: 'rgba(14, 165, 233, 0.4)',
        bottomColor: 'rgba(14, 165, 233, 0.0)',
        lineWidth: 2,
      });
      seriesRef.current = areaSeries as unknown as ISeriesApi<'Candlestick'>;
      markersPluginRef.current = createSeriesMarkers(areaSeries, []);
    } else {
      const lineSeries = chart.addSeries(LineSeries, {
        color: '#8b5cf6',
        lineWidth: 2,
      });
      seriesRef.current = lineSeries as unknown as ISeriesApi<'Candlestick'>;
      markersPluginRef.current = createSeriesMarkers(lineSeries, []);
    }

    // Handle responsiveness
    const handleResize = () => {
      if (chartContainerRef.current && chartRef.current) {
        chartRef.current.applyOptions({ width: chartContainerRef.current.clientWidth });
      }
    };

    window.addEventListener('resize', handleResize);

    return () => {
      window.removeEventListener('resize', handleResize);
      if (markersPluginRef.current) {
        markersPluginRef.current.detach();
      }
      chart.remove();
    };
  }, [type, height, background, text, upColor, downColor, showDoubleSuperTrend]);

  useEffect(() => {
    if (!seriesRef.current || !data.length) return;

    // Transform data
    // Expects: { Date: string, Open: number, High: number, Low: number, Close: number, Volume: number }
    // Or: { event_date: string, relative_volume: number }
    
    if (type === 'candlestick') {
      // Single-pass transformation: compute the time value once per bar and build
      // all three series (candles, volume, vwap) together.
      // The previous approach mapped + sorted + O(N²)-deduped three times separately.
      const candleData: CandlestickData[] = [];
      const volumeData: { time: Time; value: number; color: string }[] = [];
      const vwapData: { time: Time; value: number }[] = [];
      const seenTimes = new Set<number | string>();

      for (const d of data) {
        if (!d.Date || d.Open == null || d.High == null || d.Low == null || d.Close == null) continue;

        let timeValue: Time;
        if (timespan === 'day') {
          timeValue = d.Date.split('T')[0] as Time;
        } else {
          let ts = new Date(d.Date).getTime() / 1000;
          if (timespan === 'hour') ts = Math.floor(ts / 3600) * 3600;
          else if (timespan === 'minute') ts = Math.floor(ts / 60) * 60;
          timeValue = toLocalTime(ts) as Time;
        }

        // O(1) dedup — skip bars whose time was already seen
        const key = timeValue as number | string;
        if (seenTimes.has(key)) continue;
        seenTimes.add(key);

        candleData.push({ time: timeValue, open: d.Open, high: d.High, low: d.Low, close: d.Close });

        if (d.Volume != null) {
          volumeData.push({
            time: timeValue,
            value: d.Volume,
            color: d.Close >= d.Open ? 'rgba(16, 185, 129, 0.5)' : 'rgba(239, 68, 68, 0.5)',
          });
        }

        if (d.vwap_intraday != null) {
          vwapData.push({ time: timeValue, value: d.vwap_intraday });
        }
      }

      // Data arrives sorted from the backend — no client-side sort needed.
      seriesRef.current.setData(candleData);
      volumeSeriesRef.current?.setData(volumeData);
      vwapSeriesRef.current?.setData(vwapData);

      // SuperTrend Calculation
      if (showDoubleSuperTrend) {
        // Use deduplicated candleData but map lowercase to uppercase keys for the indicator utility
        const stInputData = candleData.map(c => ({
          ...c,
          High: c.high,
          Low: c.low,
          Open: c.open,
          Close: c.close
        }));

        const stData = calculateDoubleSuperTrend(stInputData, 3, 12);
        
        const line1Data = stData.map(d => ({ time: d.time as Time, value: d.tsl1 }));
        const line2Data = stData.map(d => ({ time: d.time as Time, value: d.tsl2 }));
        const cloudData: StyledCandleData[] = stData.map(d => ({
          time: d.time as Time,
          open: d.tsl1,
          close: d.tsl2,
          high: Math.max(d.tsl1, d.tsl2),
          low: Math.min(d.tsl1, d.tsl2),
          // We can't set color per bar in CandleSeries easily without using color property in data
          color: d.trend === 1 ? 'rgba(16, 185, 129, 0.2)' : 'rgba(239, 68, 68, 0.2)',
          borderColor: d.trend === 1 ? 'rgba(16, 185, 129, 0.2)' : 'rgba(239, 68, 68, 0.2)',
          wickColor: d.trend === 1 ? 'rgba(16, 185, 129, 0.2)' : 'rgba(239, 68, 68, 0.2)',
        }));
        
        // Update line colors based on trend for the last point or generally
        const currentTrend = stData.length > 0 ? stData[stData.length - 1].trend : 1;
        const trendColor = currentTrend === 1 ? '#10b981' : '#ef4444';
        
        stLine1SeriesRef.current?.applyOptions({ color: trendColor });
        stLine2SeriesRef.current?.applyOptions({ color: trendColor });
        
        stLine1SeriesRef.current?.setData(line1Data);
        stLine2SeriesRef.current?.setData(line2Data);
        stCloudSeriesRef.current?.setData(cloudData);
      }

      // Markers — events + inline indicators
      const allMarkers: SeriesMarker<Time>[] = [];

      if (events && events.length > 0) {
        for (const e of events) {
          if (!e.event_date) continue;
          let timeValue: Time;
          if (timespan === 'day') {
            timeValue = e.event_date.split('T')[0] as Time;
          } else {
            let ts = new Date(e.event_date).getTime() / 1000;
            if (timespan === 'hour') ts = Math.floor(ts / 3600) * 3600;
            else if (timespan === 'minute') ts = Math.floor(ts / 60) * 60;
            timeValue = toLocalTime(ts) as Time;
          }
          allMarkers.push({ time: timeValue, position: 'belowBar' as const, color: '#fbbf24', shape: 'circle' as const, size: 1, text: '' });
        }
      }

      for (const d of data) {
        if (!d.Date || d.marker_type == null) continue;
        let timeValue: Time;
        if (timespan === 'day') {
          timeValue = d.Date.split('T')[0] as Time;
        } else {
          let ts = new Date(d.Date).getTime() / 1000;
          if (timespan === 'hour') ts = Math.floor(ts / 3600) * 3600;
          else if (timespan === 'minute') ts = Math.floor(ts / 60) * 60;
          timeValue = toLocalTime(ts) as Time;
        }
        const isSwipe = d.marker_type === 'swipe';
        allMarkers.push({
          time: timeValue,
          position: isSwipe ? 'aboveBar' : 'belowBar' as const,
          color: isSwipe ? '#ef4444' : '#10b981',
          shape: isSwipe ? 'arrowDown' : 'arrowUp' as const,
          size: 1,
          text: '',
        });
      }

      if (markersPluginRef.current) {
        if (allMarkers.length > 0) {
          allMarkers.sort((a, b) =>
            typeof a.time === 'number' && typeof b.time === 'number'
              ? a.time - b.time
              : String(a.time).localeCompare(String(b.time))
          );
          const validMarkers = allMarkers.filter(m => seenTimes.has(m.time as number | string));
          markersPluginRef.current.setMarkers(validMarkers);
        } else {
          markersPluginRef.current.setMarkers([]);
        }
      }
    } else {
      const xKey = data[0].event_date ? 'event_date' : 'Date';
      const yKey = data[0].relative_volume ? 'relative_volume' : 'Close';

      const formattedData: (LineData | AreaData)[] = data
        .filter(d => d[xKey] && d[yKey] != null)
        .map(d => {
          const rawTime = d[xKey] as string;
          const timeValue = rawTime.includes('T') || rawTime.includes(':')
            ? toLocalTime(new Date(rawTime).getTime() / 1000) as Time
            : rawTime.split('T')[0] as Time;

          return {
            time: timeValue,
            value: d[yKey] as number,
          };
        })
        .sort((a, b) => {
          if (typeof a.time === 'number' && typeof b.time === 'number') return a.time - b.time;
          return String(a.time).localeCompare(String(b.time));
        });

      // Filter out duplicate times (lightweight-charts requirement)
      const uniqueData = formattedData.filter((item, index, self) =>
        index === self.findIndex((t) => t.time === item.time)
      );

      (seriesRef.current as unknown as ISeriesApi<'Line'>).setData(uniqueData as LineData[]);
    }
    
    // Only fit content on initial load or when data was previously empty
    // This prevents the chart from "jumping" when new historical data is backfilled
    if (data.length > 0 && prevDataLengthRef.current === 0) {
      chartRef.current?.timeScale().fitContent();
    }
    prevDataLengthRef.current = data.length;
  }, [data, type, events, timespan, symbol, showDoubleSuperTrend]);

  // Reset initialization flag when symbol or timespan changes to allow refitting
  useEffect(() => {
    prevDataLengthRef.current = 0;
  }, [symbol, timespan]);

  useEffect(() => {
    if (!seriesRef.current || !liveData || !symbol || liveData.sym !== symbol.toUpperCase()) return;

    let timeValue: Time;

    if (timespan === 'day') {
      // For daily charts, update the bar matching the current local date
      const localDate = new Date(liveData.s);
      const year = localDate.getFullYear();
      const month = String(localDate.getMonth() + 1).padStart(2, '0');
      const day = String(localDate.getDate()).padStart(2, '0');
      timeValue = `${year}-${month}-${day}` as Time;
    } else {
      // For intraday charts, round to the current timespan resolution
      let timestamp = liveData.s / 1000;
      
      if (timespan === 'hour') {
        // Round to nearest hour
        timestamp = Math.floor(timestamp / 3600) * 3600;
      } else if (timespan === 'minute') {
        // Round to nearest minute
        timestamp = Math.floor(timestamp / 60) * 60;
      }
      
      timeValue = toLocalTime(timestamp) as Time;
    }

    if (type === 'candlestick') {
      const isNewBar = !currentBarRef.current || currentBarRef.current.time !== timeValue;
      
      const open = isNewBar ? liveData.o : currentBarRef.current!.open;
      const high = isNewBar ? liveData.h : Math.max(currentBarRef.current!.high, liveData.h);
      const low = isNewBar ? liveData.l : Math.min(currentBarRef.current!.low, liveData.l);
      const close = liveData.c;

      const barData = {
        time: timeValue,
        open,
        high,
        low,
        close,
      };

      seriesRef.current.update(barData);
      currentBarRef.current = barData;

      if (volumeSeriesRef.current) {
        // For volume, we treat it as cumulative if it's the same bar, 
        // though Polygon's v in AM/A is already the aggregate for that slice.
        // If it's a new bar, we start fresh; if same bar, we'd ideally know total day volume 
        // but for a single candle detail, showing the latest slice volume is acceptable 
        // OR we accumulate it if we want the bar's total volume.
        // Actually, for intraday, usually you want the total bar volume. 
        // But Polygon's AM already is the total for the minute.
        // For 'A' updates into a 'minute' bar, we should accumulate.
        
        // Simplified: use the liveData volume which works well for AM->Minute 
        // and A->Second. For mixed (A->Minute), we'll just use the latest.
        volumeSeriesRef.current.update({
          time: timeValue,
          value: liveData.v,
          color: close >= open ? 'rgba(16, 185, 129, 0.5)' : 'rgba(239, 68, 68, 0.5)',
        });
      }
    } else {
      (seriesRef.current as unknown as ISeriesApi<'Line'>).update({
        time: timeValue,
        value: liveData.c,
      });
    }
  }, [liveData, type, symbol, timespan]);

  // Handle programmatic scrolling when highlightDate changes
  useEffect(() => {
    if (!chartRef.current || !highlightDate || !data.length) return;

    const timeScale = chartRef.current.timeScale();
    const dateStr = highlightDate.split('T')[0].split(' ')[0];
    
    if (type === 'candlestick') {
      // For daily charts using YYYY-MM-DD strings
      const targetDate = new Date(dateStr);
      
      // Calculate a 30-day window around the target date
      const fromDate = new Date(targetDate);
      fromDate.setDate(fromDate.getDate() - 30);
      const toDate = new Date(targetDate);
      toDate.setDate(toDate.getDate() + 30);
      
      timeScale.setVisibleRange({
        from: fromDate.toISOString().split('T')[0] as Time,
        to: toDate.toISOString().split('T')[0] as Time,
      });
    } else {
      // For intraday or other numeric time scales
      const targetTime = toLocalTime(new Date(highlightDate).getTime() / 1000) as Time;
      
      const dataFreqSeconds = data.length > 1
        ? (new Date((data[1].Date || data[1].event_date) as string).getTime() - new Date((data[0].Date || data[0].event_date) as string).getTime()) / 1000
        : 86400; // default 1 day

      const bufferBars = 30;
      const bufferSeconds = dataFreqSeconds * bufferBars;

      timeScale.setVisibleRange({
        from: (targetTime as number) - bufferSeconds as Time,
        to: (targetTime as number) + bufferSeconds as Time,
      });
    }

  }, [highlightDate, data, type]);

  return (
    <div className="w-full relative group">
      <div ref={chartContainerRef} className="w-full" />
    </div>
  );
};

export default StockChart;
