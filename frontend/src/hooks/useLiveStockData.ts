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

export const useLiveStockData = (symbol: string | undefined, resolution: 'minute' | 'second' = 'minute') => {
  const [liveData, setLiveData] = useState<LiveStockData | null>(null);
  const [isConnected, setIsConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    if (!symbol) return;

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const host = window.location.host;
    
    // Updated to include resolution in the path
    const wsUrl = `${protocol}//${host}/api/live/ws/${symbol.toUpperCase()}/${resolution}`;

    console.log(`Connecting to live updates: ${wsUrl}`);
    
    let reconnectTimer: number | undefined;
    let isMounted = true;

    const connect = () => {
      if (!isMounted) return;

      if (wsRef.current) {
        wsRef.current.close();
      }

      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;

      ws.onopen = () => {
        if (!isMounted) {
          ws.close();
          return;
        }
        console.log(`WebSocket OPEN for ${symbol}`);
        setIsConnected(true);
      };

      ws.onmessage = (event) => {
        if (!isMounted) return;
        try {
          const data = JSON.parse(event.data) as LiveStockData;
          setLiveData(data);
        } catch (err) {
          console.error('Error parsing live data:', err);
        }
      };

      ws.onerror = (err) => {
        if (!isMounted) return;
        // Only log error if not self-closed or connecting
        if (ws.readyState !== WebSocket.CLOSED && ws.readyState !== WebSocket.CLOSING) {
          console.error('WebSocket error:', err);
        }
        setIsConnected(false);
      };

      ws.onclose = (event) => {
        if (!isMounted) return;
        setIsConnected(false);
        // Don't reconnect if it was a clean close from our end
        if (!event.wasClean && wsRef.current === ws) {
          console.log(`Disconnected from live updates for ${symbol}, reconnecting...`);
          reconnectTimer = window.setTimeout(connect, 3000);
        }
      };
    };

    // Delay connection slightly to avoid "closed before established" warnings 
    // frequently caused by React Strict Mode double-renders in dev.
    const startTimer = window.setTimeout(() => {
      if (isMounted) connect();
    }, 50);

    return () => {
      console.log(`Cleaning up WebSocket for ${symbol}`);
      isMounted = false;
      window.clearTimeout(startTimer);
      if (reconnectTimer) window.clearTimeout(reconnectTimer);
      
      const ws = wsRef.current;
      if (ws) {
        // Remove listeners before closing to avoid "closed while connecting" logs
        ws.onopen = null;
        ws.onmessage = null;
        ws.onerror = null;
        ws.onclose = null;
        
        if (ws.readyState === WebSocket.OPEN) {
          ws.close();
        } else if (ws.readyState === WebSocket.CONNECTING) {
            // Force the socket to close immediately AFTER it connects 
            // to avoid the "closed before established" console warning.
            ws.onopen = () => ws.close();
        }
        wsRef.current = null;
      }
    };
  }, [symbol, resolution]);

  return { liveData, isConnected };
};
