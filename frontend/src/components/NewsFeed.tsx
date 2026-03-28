/// <reference types="vite/client" />
import React, { useEffect, useState, useRef } from 'react';
import { Newspaper, ExternalLink, Clock, RefreshCw } from 'lucide-react';
import { formatDistanceToNow } from 'date-fns';
import { fetchRecentNews, NewsArticle, triggerNewsRefresh } from '../api/news';

// Normalize a published_utc string to ensure consistent UTC parsing.
// The REST API may return "2026-03-23T15:30:00" (no Z) while WebSocket
// messages may include "Z". Without the Z suffix, new Date() interprets
// the string as local time, which breaks sort order.
const parsePublishedUtc = (dateStr: string): number =>
    new Date(dateStr.endsWith('Z') ? dateStr : dateStr + 'Z').getTime();

const NewsFeed: React.FC = () => {
    const [articles, setArticles] = useState<NewsArticle[]>([]);
    const [isRefreshing, setIsRefreshing] = useState(false);
    const ws = useRef<WebSocket | null>(null);

    const handleRefresh = async () => {
        setIsRefreshing(true);
        try {
            await triggerNewsRefresh();
            // We usually wait for WebSocket for the actual update, 
            // but we could also re-fetch here for immediate feedback.
            const data = await fetchRecentNews();
            data.sort((a, b) => parsePublishedUtc(b.published_utc) - parsePublishedUtc(a.published_utc));
            setArticles(data);
        } catch (err) {
            console.error("Manual news refresh failed:", err);
        } finally {
            setIsRefreshing(false);
        }
    };

    useEffect(() => {
        // Fetch initial history
        fetchRecentNews()
            .then(data => {
                data.sort((a, b) => parsePublishedUtc(b.published_utc) - parsePublishedUtc(a.published_utc));
                setArticles(data);
            })
            .catch(err => console.error("Failed to fetch initial news history:", err));

        // Establish WebSocket Connection
        // Assuming backend runs on 8000, and we either hit it directly or via proxy
        const WS_URL = import.meta.env.VITE_WS_URL || 'ws://localhost:8000/api/news/ws';

        const connectWs = () => {
            ws.current = new WebSocket(WS_URL);

            ws.current.onmessage = (event) => {
                const newArticle = JSON.parse(event.data);
                setArticles(prev => {
                    if (prev.find(a => a.id === newArticle.id)) return prev;

                    const combined = [newArticle, ...prev];
                    combined.sort((a, b) => parsePublishedUtc(b.published_utc) - parsePublishedUtc(a.published_utc));
                    return combined.slice(0, 50);
                });
            };

            ws.current.onclose = () => {
                // Reconnect after 3 seconds
                setTimeout(connectWs, 3000);
            };
        };

        connectWs();

        return () => {
            ws.current?.close();
        };
    }, []);

    const sortedArticles = articles
        .slice()
        .sort((a, b) => parsePublishedUtc(b.published_utc) - parsePublishedUtc(a.published_utc));

    const renderArticle = (article: NewsArticle) => (
        <div
            key={article.id}
            className="bg-gray-800/50 rounded-lg p-4 border border-gray-700 hover:border-gray-600 transition-colors animate-fade-in"
        >
            <div className="flex justify-between items-start mb-2">
                <div className="flex flex-wrap gap-1 mb-1">
                    {article.tickers?.slice(0, 3).map(t => (
                        <span key={t} className="text-xs font-mono bg-financial-blue/20 text-financial-blue px-1.5 rounded">
                            {t}
                        </span>
                    ))}
                    {article.tickers && article.tickers.length > 3 && (
                        <span className="text-xs font-mono bg-gray-700 text-gray-300 px-1.5 rounded">
                            +{article.tickers.length - 3}
                        </span>
                    )}
                </div>
                <div className="text-xs text-gray-400 flex items-center whitespace-nowrap ml-2">
                    <Clock className="w-3 h-3 mr-1" />
                    {formatDistanceToNow(parsePublishedUtc(article.published_utc), { addSuffix: true })}
                </div>
            </div>

            <a
                href={article.article_url}
                target="_blank"
                rel="noopener noreferrer"
                className="font-medium text-financial-light hover:text-white transition-colors group flex items-start"
            >
                <div className="flex-1">
                    <h4 className="leading-snug line-clamp-2">{article.title}</h4>
                    <p className="text-xs text-gray-400 mt-2 flex items-center">
                        <span className="truncate max-w-[150px] inline-block">{article.provider || article.author || 'Unknown source'}</span>
                        <ExternalLink className="w-3 h-3 ml-1 opacity-0 group-hover:opacity-100 transition-opacity" />
                    </p>
                </div>
                {article.image_url && (
                    <div className="ml-3 shrink-0">
                        <img
                            src={article.image_url}
                            alt=""
                            className="w-16 h-12 object-cover rounded shadow-sm border border-gray-700"
                        />
                    </div>
                )}
            </a>
        </div>
    );

    return (
        <div className="space-y-4">
            <div className="flex items-center justify-between mb-4">
                <div className="flex items-center space-x-4">
                    <h3 className="text-lg font-semibold text-financial-light flex items-center">
                        <Newspaper className="h-5 w-5 mr-2 text-financial-blue" />
                        Stock News
                    </h3>
                    <button
                        onClick={handleRefresh}
                        disabled={isRefreshing}
                        className={`flex items-center text-xs font-medium px-2 py-1 rounded border transition-colors ${
                            isRefreshing 
                                ? 'bg-gray-700/50 text-gray-400 border-gray-600' 
                                : 'bg-financial-blue/10 text-financial-blue border-financial-blue/20 hover:bg-financial-blue/20'
                        }`}
                        title="Force refresh news (bypasses weekend schedule)"
                    >
                        <RefreshCw className={`h-3 w-3 mr-1 ${isRefreshing ? 'animate-spin' : ''}`} />
                        {isRefreshing ? 'Refreshing...' : 'Refresh'}
                    </button>
                </div>
                <span className="flex items-center text-xs text-positive bg-positive/10 px-2 py-1 rounded border border-positive/20">
                    <span className="relative flex h-2 w-2 mr-2">
                        <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-positive opacity-75"></span>
                        <span className="relative inline-flex rounded-full h-2 w-2 bg-positive"></span>
                    </span>
                    Live
                </span>
            </div>

            <div className="max-h-[600px] overflow-y-auto space-y-3 pr-2 custom-scrollbar">
                {sortedArticles.length === 0 ? (
                    <div className="text-center py-8 text-gray-400 text-sm">
                        Waiting for stock news updates...
                    </div>
                ) : (
                    sortedArticles.map(renderArticle)
                )}
            </div>
        </div>
    );
};

export default NewsFeed;
