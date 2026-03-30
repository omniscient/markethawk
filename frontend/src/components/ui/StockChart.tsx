import React, { useEffect, useRef } from 'react';
import { 
  createChart, 
  ColorType, 
  IChartApi, 
  ISeriesApi, 
  CandlestickData, 
  LineData, 
  AreaData,
  Time,
  CandlestickSeries,
  AreaSeries,
  LineSeries,
  HistogramSeries,
  createSeriesMarkers
} from 'lightweight-charts';

interface StockChartProps {
  data: any[];
  type: 'candlestick' | 'area' | 'line';
  timespan?: string;
  height?: number;
  events?: any[];
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
  colors = {}
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
  const seriesRef = useRef<ISeriesApi<any> | null>(null);
  const volumeSeriesRef = useRef<ISeriesApi<'Histogram'> | null>(null);
  const markersPluginRef = useRef<any | null>(null);

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

    } else if (type === 'area') {
      const areaSeries = chart.addSeries(AreaSeries, {
        lineColor: '#0ea5e9',
        topColor: 'rgba(14, 165, 233, 0.4)',
        bottomColor: 'rgba(14, 165, 233, 0.0)',
        lineWidth: 2,
      });
      seriesRef.current = areaSeries;
      markersPluginRef.current = createSeriesMarkers(areaSeries, []);
    } else {
      const lineSeries = chart.addSeries(LineSeries, {
        color: '#8b5cf6',
        lineWidth: 2,
      });
      seriesRef.current = lineSeries;
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
  }, [type, height, background, text, upColor, downColor]);

  useEffect(() => {
    if (!seriesRef.current || !data.length) return;

    // Transform data
    // Expects: { Date: string, Open: number, High: number, Low: number, Close: number, Volume: number }
    // Or: { event_date: string, relative_volume: number }
    
    if (type === 'candlestick') {
      const formattedData: CandlestickData[] = data
        .filter(d => d.Date && d.Open != null)
        .map(d => {
          // Normalize time: YYYY-MM-DD for daily, Unix timestamp for intraday
          let timeValue: Time;
          if (timespan === 'day') {
            timeValue = d.Date.split('T')[0] as Time;
          } else {
            // Robust ISO parsing for intraday
            const dt = new Date(d.Date);
            timeValue = toLocalTime(dt.getTime() / 1000) as Time;
          }

          return {
            time: timeValue,
            open: d.Open,
            high: d.High,
            low: d.Low,
            close: d.Close,
          };
        })
        .sort((a, b) => {
          if (typeof a.time === 'number' && typeof b.time === 'number') return a.time - b.time;
          return String(a.time).localeCompare(String(b.time));
        });

      // Deduplicate by time (lightweight-charts requirement)
      const uniqueFormattedData = formattedData.filter((item, index, self) =>
        index === self.findIndex((t) => t.time === item.time)
      );

      seriesRef.current.setData(uniqueFormattedData);

      if (volumeSeriesRef.current) {
        const volumeData = data
          .filter(d => d.Date && d.Volume != null)
          .map(d => {
            let timeValue: Time;
            if (timespan === 'day') {
              timeValue = d.Date.split('T')[0] as Time;
            } else {
              const dt = new Date(d.Date);
              timeValue = toLocalTime(dt.getTime() / 1000) as Time;
            }
            return {
              time: timeValue,
              value: d.Volume,
              color: d.Close >= d.Open ? 'rgba(16, 185, 129, 0.5)' : 'rgba(239, 68, 68, 0.5)',
            };
          })
          .sort((a, b) => {
            if (typeof a.time === 'number' && typeof b.time === 'number') return a.time - b.time;
            return String(a.time).localeCompare(String(b.time));
          });
        
        // Deduplicate volume by time
        const uniqueVolumeData = volumeData.filter((item, index, self) =>
          index === self.findIndex((t) => t.time === item.time)
        );

        volumeSeriesRef.current.setData(uniqueVolumeData);
      }

      // Add markers for scanner events
      if (events && events.length > 0 && markersPluginRef.current) {
        const markers = events
          .filter(e => e.event_date)
          .map(e => {
            let timeValue: Time;
            if (timespan === 'day') {
              timeValue = e.event_date.split('T')[0] as Time;
            } else {
              const dt = new Date(e.event_date);
              timeValue = toLocalTime(dt.getTime() / 1000) as Time;
            }
            return {
              time: timeValue,
              position: 'belowBar' as const,
              color: '#fbbf24', // yellow-400
              shape: 'circle' as const,
              size: 1,
              text: '', // No text as requested
            };
          })
          .sort((a, b) => {
            if (typeof a.time === 'number' && typeof b.time === 'number') return a.time - b.time;
            return String(a.time).localeCompare(String(b.time));
          });
        
        // Filter markers to only those that have a corresponding candle in the current data
        const dataTimes = new Set(uniqueFormattedData.map(d => String(d.time)));
        const validMarkers = markers.filter(m => dataTimes.has(m.time as string));
        
        // Use v5 createSeriesMarkers plugin API
        markersPluginRef.current.setMarkers(validMarkers);
      } else if (markersPluginRef.current) {
        markersPluginRef.current.setMarkers([]);
      }
    } else {
      const xKey = data[0].event_date ? 'event_date' : 'Date';
      const yKey = data[0].relative_volume ? 'relative_volume' : 'Close';

      const formattedData: (LineData | AreaData)[] = data
        .filter(d => d[xKey] && d[yKey] != null)
        .map(d => {
          const timeValue = String(d[xKey]).includes('T') || String(d[xKey]).includes(':') 
            ? toLocalTime(new Date(d[xKey]).getTime() / 1000) as Time
            : d[xKey].split('T')[0] as Time;
          
          return {
            time: timeValue,
            value: d[yKey],
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

      seriesRef.current.setData(uniqueData);
    }

    chartRef.current?.timeScale().fitContent();
  }, [data, type, events, timespan]);

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
      // For intraday charts, use Unix timestamp in seconds (shifted for local display)
      timeValue = toLocalTime(liveData.s / 1000) as Time;
    }

    if (type === 'candlestick') {
      seriesRef.current.update({
        time: timeValue,
        open: liveData.o,
        high: liveData.h,
        low: liveData.l,
        close: liveData.c,
      });

      if (volumeSeriesRef.current) {
        volumeSeriesRef.current.update({
          time: timeValue,
          value: liveData.v,
          color: liveData.c >= liveData.o ? 'rgba(16, 185, 129, 0.5)' : 'rgba(239, 68, 68, 0.5)',
        });
      }
    } else {
      seriesRef.current.update({
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
        ? (new Date(data[1].Date || data[1].event_date).getTime() - new Date(data[0].Date || data[0].event_date).getTime()) / 1000
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
