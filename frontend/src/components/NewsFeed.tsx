/// <reference types="vite/client" />
import React, { useEffect, useState, useRef } from 'react';
import { Newspaper, ExternalLink, Clock } from 'lucide-react';
import { formatDistanceToNow } from 'date-fns';
import { fetchRecentNews, NewsArticle } from '../api/news';

const NewsFeed: React.FC = () => {
    const [articles, setArticles] = useState<NewsArticle[]>([]);
    const ws = useRef<WebSocket | null>(null);

    useEffect(() => {
        // Fetch initial history
        fetchRecentNews()
            .then(data => setArticles(data))
            .catch(err => console.error("Failed to fetch initial news history:", err));

        // Establish WebSocket Connection
        // Assuming backend runs on 8000, and we either hit it directly or via proxy
        const WS_URL = import.meta.env.VITE_WS_URL || 'ws://localhost:8000/api/news/ws';

        const connectWs = () => {
            ws.current = new WebSocket(WS_URL);

            ws.current.onmessage = (event) => {
                const newArticle = JSON.parse(event.data);
                setArticles(prev => {
                    // Check for duplicates
                    if (prev.find(a => a.id === newArticle.id)) return prev;
                    // Prepend new article and optionally cap at 50 to avoid memory leak
                    return [newArticle, ...prev].slice(0, 50);
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

    return (
        <div className="space-y-4">
            <div className="flex items-center justify-between mb-4">
                <h3 className="text-lg font-semibold text-financial-light flex items-center">
                    <Newspaper className="h-5 w-5 mr-2 text-financial-blue" />
                    Live News Feed
                </h3>
                <span className="flex items-center text-xs text-positive bg-positive/10 px-2 py-1 rounded border border-positive/20">
                    <span className="relative flex h-2 w-2 mr-2">
                        <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-positive opacity-75"></span>
                        <span className="relative inline-flex rounded-full h-2 w-2 bg-positive"></span>
                    </span>
                    Live
                </span>
            </div>

            <div className="max-h-[500px] overflow-y-auto space-y-3 pr-2 custom-scrollbar">
                {articles.length === 0 ? (
                    <div className="text-center py-8 text-gray-400 text-sm">
                        Waiting for news updates...
                    </div>
                ) : (
                    articles.map((article) => (
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
                                    {formatDistanceToNow(new Date(article.published_utc), { addSuffix: true })}
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
                    ))
                )}
            </div>
        </div>
    );
};

export default NewsFeed;
