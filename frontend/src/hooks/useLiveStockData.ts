import { useState, useEffect, useRef } from 'react';

export interface LiveStockData {
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
}

export const useLiveStockData = (symbol: string | undefined) => {
  const [liveData, setLiveData] = useState<LiveStockData | null>(null);
  const [isConnected, setIsConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    if (!symbol) return;

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const host = window.location.host;
    
    // Use the proxied URL (/api/...) on the same host (3000)
    // Now that ws: true is in vite.config.ts, this is the most reliable path.
    const wsUrl = `${protocol}//${host}/api/live/ws/${symbol.toUpperCase()}`;

    console.log(`Connecting to live updates: ${wsUrl}`);
    
    let reconnectTimer: number;

    const connect = () => {
      // Close existing if any
      if (wsRef.current) {
        wsRef.current.close();
      }

      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;

      ws.onopen = () => {
        console.log(`WebSocket OPEN for ${symbol}`);
        setIsConnected(true);
      };

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data) as LiveStockData;
          setLiveData(data);
        } catch (err) {
          console.error('Error parsing live data:', err);
        }
      };

      ws.onerror = (err) => {
        // Only log error if not self-closed or connecting
        if (ws.readyState !== WebSocket.CLOSED && ws.readyState !== WebSocket.CLOSING) {
          console.error('WebSocket error:', err);
        }
        setIsConnected(false);
      };

      ws.onclose = (event) => {
        setIsConnected(false);
        // Don't reconnect if it was a clean close from our end
        if (!event.wasClean && wsRef.current === ws) {
          console.log(`Disconnected from live updates for ${symbol}, reconnecting...`);
          reconnectTimer = window.setTimeout(connect, 3000);
        }
      };
    };

    connect();

    return () => {
      console.log(`Cleaning up WebSocket for ${symbol}`);
      const ws = wsRef.current;
      if (ws) {
        // Remove listeners before closing to avoid "closed while connecting" logs
        ws.onopen = null;
        ws.onmessage = null;
        ws.onerror = null;
        ws.onclose = null;
        
        if (ws.readyState === WebSocket.CONNECTING || ws.readyState === WebSocket.OPEN) {
          ws.close();
        }
        wsRef.current = null;
      }
      if (reconnectTimer) {
        clearTimeout(reconnectTimer);
      }
    };
  }, [symbol]);

  return { liveData, isConnected };
};
