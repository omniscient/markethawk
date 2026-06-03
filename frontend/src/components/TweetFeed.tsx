/// <reference types="vite/client" />
import React, { useEffect, useState, useRef } from 'react';
import { Bird, ExternalLink, TrendingUp, TrendingDown, Zap } from 'lucide-react';
import { formatDistanceToNow } from 'date-fns';
import { fetchRecentTweets, TweetSignal } from '../api/tweets';

const CLASSIFICATION_COLORS: Record<string, string> = {
  CALLOUT: 'bg-financial-blue/20 text-financial-blue',
  CELEBRATION: 'bg-green-500/20 text-green-400',
  UPDATE: 'bg-yellow-500/20 text-yellow-400',
  RETWEET: 'bg-gray-500/20 text-gray-400',
  UNKNOWN: 'bg-gray-500/20 text-gray-500',
};

interface TweetFeedProps {
  limit?: number;
}

const TweetFeed: React.FC<TweetFeedProps> = ({ limit = 50 }) => {
  const [signals, setSignals] = useState<TweetSignal[]>([]);
  const ws = useRef<WebSocket | null>(null);

  useEffect(() => {
    fetchRecentTweets(limit)
      .then(data => setSignals(data))
      .catch(err => console.error('Failed to fetch tweet signals:', err));

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const host = window.location.host;
    const WS_URL = `${protocol}//${host}/api/v1/tweets/feed`;

    let reconnectTimer: number | undefined;
    let isMounted = true;

    const connectWs = () => {
      if (!isMounted) return;
      if (ws.current) ws.current.close();

      const currentWs = new WebSocket(WS_URL);
      ws.current = currentWs;

      currentWs.onmessage = (event) => {
        if (!isMounted) return;
        try {
          const signal: TweetSignal = JSON.parse(event.data);
          setSignals(prev => {
            if (prev.find(s => s.tweet_id === signal.tweet_id)) return prev;
            return [signal, ...prev].slice(0, limit);
          });
        } catch (err) {
          console.error('Error parsing tweet signal:', err);
        }
      };

      currentWs.onclose = (event) => {
        if (!isMounted) return;
        if (!event.wasClean && ws.current === currentWs) {
          reconnectTimer = window.setTimeout(connectWs, 3000);
        }
      };
    };

    const startTimer = window.setTimeout(() => {
      if (isMounted) connectWs();
    }, 50);

    return () => {
      isMounted = false;
      window.clearTimeout(startTimer);
      if (reconnectTimer) window.clearTimeout(reconnectTimer);
      const currentWs = ws.current;
      if (currentWs) {
        currentWs.onopen = null;
        currentWs.onmessage = null;
        currentWs.onclose = null;
        currentWs.onerror = null;
        if (currentWs.readyState === WebSocket.OPEN) {
          currentWs.close();
        } else if (currentWs.readyState === WebSocket.CONNECTING) {
          currentWs.onopen = () => currentWs.close();
        }
        ws.current = null;
      }
    };
  }, [limit]);

  const renderSignal = (signal: TweetSignal) => {
    const postedDate = signal.posted_at
      ? new Date(signal.posted_at.endsWith('Z') ? signal.posted_at : signal.posted_at + 'Z')
      : null;
    const timeAgo = postedDate ? formatDistanceToNow(postedDate, { addSuffix: true }) : '';
    const classColor = CLASSIFICATION_COLORS[signal.classification] || CLASSIFICATION_COLORS.UNKNOWN;

    return (
      <div
        key={signal.tweet_id}
        className="bg-gray-800/50 rounded-lg p-3 border border-gray-700 hover:border-gray-600 transition-colors animate-fade-in"
      >
        <div className="flex items-start justify-between gap-2 mb-1.5">
          <div className="flex items-center gap-1.5 flex-wrap min-w-0">
            {signal.tickers.slice(0, 3).map(t => (
              <span key={t} className="text-xs font-mono bg-financial-blue/20 text-financial-blue px-1.5 py-0.5 rounded">
                ${t}
              </span>
            ))}
            <span className={`text-xs font-medium px-1.5 py-0.5 rounded ${classColor}`}>
              {signal.classification}
            </span>
            {signal.promoted && (
              <span className="text-xs font-medium px-1.5 py-0.5 rounded bg-orange-500/20 text-orange-400 flex items-center gap-1">
                <Zap className="h-3 w-3" />
                Promoted
              </span>
            )}
          </div>
          <div className="flex items-center gap-1.5 shrink-0">
            {signal.direction === 'long' && <TrendingUp className="h-3.5 w-3.5 text-green-400" />}
            {signal.direction === 'short' && <TrendingDown className="h-3.5 w-3.5 text-red-400" />}
            <a
              href={signal.tweet_url}
              target="_blank"
              rel="noopener noreferrer"
              className="text-gray-500 hover:text-gray-300 transition-colors"
            >
              <ExternalLink className="h-3.5 w-3.5" />
            </a>
          </div>
        </div>

        <p className="text-sm text-gray-300 leading-snug line-clamp-3 mb-1.5">
          {signal.full_text}
        </p>

        <div className="flex items-center justify-between text-xs text-gray-500">
          <span className="flex items-center gap-1">
            <Bird className="h-3 w-3" />
            @{signal.handle ?? 'unknown'}
          </span>
          <div className="flex items-center gap-2">
            <span>conf {(signal.confidence * 100).toFixed(0)}%</span>
            {timeAgo && <span>{timeAgo}</span>}
          </div>
        </div>
      </div>
    );
  };

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center gap-2 mb-3">
        <Bird className="h-4 w-4 text-financial-blue" />
        <h3 className="text-sm font-semibold text-financial-light">Tweet Signals</h3>
        <span className="ml-auto text-xs text-gray-500">{signals.length} signals</span>
      </div>

      {signals.length === 0 ? (
        <div className="flex-1 flex items-center justify-center text-sm text-gray-500">
          Waiting for signals…
        </div>
      ) : (
        <div className="flex-1 overflow-y-auto space-y-2 pr-1">
          {signals.map(renderSignal)}
        </div>
      )}
    </div>
  );
};

export default TweetFeed;
