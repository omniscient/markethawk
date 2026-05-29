import { useState, useEffect, useRef } from 'react';

export interface LiveTick {
  type: 'tick';
  symbol: string;
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  wap: number;
}

export interface LiveMinuteBar {
  type: 'minute_bar';
  symbol: string;
  minute_ts: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  vwap: number;
  session: string;
  session_volume: number;
  minutes_elapsed: number;
  prior_close: number;
  price_change_pct: number;
}

export interface LiveQuote {
  type: 'quote';
  symbol: string;
  last: number;
  bid: number | null;
  ask: number | null;
  time: number;
}

export interface LiveAlert {
  type: 'alert';
  symbol: string;
  scanner_type: string;
  summary: string;
  severity: string;
  indicators: Record<string, unknown>;
  timestamp: string;
}

export type LiveMessage = LiveTick | LiveQuote | LiveMinuteBar | LiveAlert;

export interface SymbolLiveData {
  price: number;
  priceChangePct: number | null;
  session: string | null;
  sessionVolume: number | null;
  lastTickAt: number;
  alert: LiveAlert | null;
}

export function useWatchlistLive() {
  const [liveData, setLiveData] = useState<Record<string, SymbolLiveData>>({});
  const [connected, setConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    let destroyed = false;

    function connect() {
      if (destroyed) return;

      const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws';
      const ws = new WebSocket(`${protocol}://${window.location.host}/api/v1/live/ws/watchlist`);
      wsRef.current = ws;

      ws.onopen = () => {
        if (destroyed) { ws.close(); return; }
        setConnected(true);
      };

      ws.onmessage = (evt) => {
        if (destroyed) return;
        try {
          const msg: LiveMessage = JSON.parse(evt.data);
          if (msg.type === 'quote') {
            setLiveData((prev) => ({
              ...prev,
              [msg.symbol]: {
                ...prev[msg.symbol],
                price: msg.last,
                lastTickAt: Date.now(),
                alert: prev[msg.symbol]?.alert ?? null,
                priceChangePct: prev[msg.symbol]?.priceChangePct ?? null,
                session: prev[msg.symbol]?.session ?? null,
                sessionVolume: prev[msg.symbol]?.sessionVolume ?? null,
              },
            }));
          } else if (msg.type === 'tick') {
            setLiveData((prev) => ({
              ...prev,
              [msg.symbol]: {
                ...prev[msg.symbol],
                price: prev[msg.symbol]?.price || msg.close,
                lastTickAt: Date.now(),
                alert: prev[msg.symbol]?.alert ?? null,
                priceChangePct: prev[msg.symbol]?.priceChangePct ?? null,
                session: prev[msg.symbol]?.session ?? null,
                sessionVolume: prev[msg.symbol]?.sessionVolume ?? null,
              },
            }));
          } else if (msg.type === 'minute_bar') {
            setLiveData((prev) => ({
              ...prev,
              [msg.symbol]: {
                ...prev[msg.symbol],
                price: msg.close,
                priceChangePct: msg.price_change_pct,
                session: msg.session,
                sessionVolume: msg.session_volume,
                lastTickAt: Date.now(),
                alert: prev[msg.symbol]?.alert ?? null,
              },
            }));
          } else if (msg.type === 'alert') {
            setLiveData((prev) => ({
              ...prev,
              [msg.symbol]: {
                ...prev[msg.symbol],
                alert: msg,
                lastTickAt: prev[msg.symbol]?.lastTickAt ?? Date.now(),
                price: prev[msg.symbol]?.price ?? 0,
                priceChangePct: prev[msg.symbol]?.priceChangePct ?? null,
                session: prev[msg.symbol]?.session ?? null,
                sessionVolume: prev[msg.symbol]?.sessionVolume ?? null,
              },
            }));
          }
        } catch {
          // ignore parse errors
        }
      };

      ws.onclose = () => {
        if (destroyed) return;
        setConnected(false);
        reconnectTimer.current = setTimeout(connect, 3000);
      };

      ws.onerror = () => ws.close();
    }

    connect();

    return () => {
      destroyed = true;
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current);
      const ws = wsRef.current;
      // Only close if handshake is done — closing a CONNECTING socket triggers a spurious warning.
      if (ws && ws.readyState !== WebSocket.CONNECTING) ws.close();
    };
  }, []);

  return { liveData, connected };
}
