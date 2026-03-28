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
  HistogramSeries
} from 'lightweight-charts';

interface StockChartProps {
  data: any[];
  type: 'candlestick' | 'area' | 'line';
  height?: number;
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
  height = 400,
  colors = {}
}) => {
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<any> | null>(null);
  const volumeSeriesRef = useRef<ISeriesApi<'Histogram'> | null>(null);

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
    } else {
      const lineSeries = chart.addSeries(LineSeries, {
        color: '#8b5cf6',
        lineWidth: 2,
      });
      seriesRef.current = lineSeries;
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
        .map(d => ({
          time: (new Date(d.Date).getTime() / 1000) as Time,
          open: d.Open,
          high: d.High,
          low: d.Low,
          close: d.Close,
        }))
        .sort((a, b) => (a.time as number) - (b.time as number));

      seriesRef.current.setData(formattedData);

      if (volumeSeriesRef.current) {
        const volumeData = data
          .filter(d => d.Date && d.Volume != null)
          .map(d => ({
            time: (new Date(d.Date).getTime() / 1000) as Time,
            value: d.Volume,
            color: d.Close >= d.Open ? 'rgba(16, 185, 129, 0.5)' : 'rgba(239, 68, 68, 0.5)',
          }))
          .sort((a, b) => (a.time as number) - (b.time as number));
        
        volumeSeriesRef.current.setData(volumeData);
      }
    } else {
      const xKey = data[0].event_date ? 'event_date' : 'Date';
      const yKey = data[0].relative_volume ? 'relative_volume' : 'Close';

      const formattedData: (LineData | AreaData)[] = data
        .filter(d => d[xKey] && d[yKey] != null)
        .map(d => ({
          time: (new Date(d[xKey]).getTime() / 1000) as Time,
          value: d[yKey],
        }))
        .sort((a, b) => (a.time as number) - (b.time as number));

      // Filter out duplicate times (lightweight-charts requirement)
      const uniqueData = formattedData.filter((item, index, self) =>
        index === self.findIndex((t) => t.time === item.time)
      );

      seriesRef.current.setData(uniqueData);
    }

    chartRef.current?.timeScale().fitContent();
  }, [data, type]);

  return (
    <div className="w-full relative group">
      <div ref={chartContainerRef} className="w-full" />
    </div>
  );
};

export default StockChart;
