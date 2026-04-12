"""
Catalyst Parser Service - NLP/Regex driven analysis for scanning news and matching catalysts.
"""

import re
from typing import Dict, Any, List
from datetime import datetime, timedelta, date
from sqlalchemy.orm import Session
from app.models.news_article import NewsArticle

class CatalystParser:
    
    # Define RegEx patterns for key catalyst types
    PATTERNS = {
        "dilution_warning": re.compile(r'\b(offering|direct offering|public offering|shelf|atm|at-the-market|s-1|s-3|secondary|placement|warrants?)\b', re.IGNORECASE),
        "earnings_beat": re.compile(r'\b(beats?|exceeds?|tops?|surpasses?)\s+(eps|estimates|expectations|revenue|guidance)\b', re.IGNORECASE),
        "earnings_miss": re.compile(r'\b(missed?|misses?|cuts?|lowers?|reduces?)\s+(eps|estimates|expectations|guidance|forecast)\b', re.IGNORECASE),
        "fda_news": re.compile(r'\b(fda|approval|pdufa|fast track|orphan drug|clinical trial|phase [123]|ind|nda)\b', re.IGNORECASE),
        "merger_acquisition": re.compile(r'\b(merger|acquisition|acquires?|buyout|merges?|tender offer)\b', re.IGNORECASE),
        "analyst_upgrade": re.compile(r'\b(upgrades?|upgraded?)\b', re.IGNORECASE),
        "analyst_downgrade": re.compile(r'\b(downgrades?|downgraded?)\b', re.IGNORECASE),
        "contract_won": re.compile(r'\b(awarded?|wins?|secures?)\b.*\b(contract|grant|award)\b', re.IGNORECASE)
    }

    @staticmethod
    def analyze(ticker: str, event_date: date, db: Session) -> Dict[str, Any]:
        """
        Scan recent news (within 72 hours of the event_date) for the given ticker,
        and apply regex rules to categorize catalysts.
        """
        results = CatalystParser.batch_analyze([ticker], event_date, db)
        return results.get(ticker.upper(), {"tags": [], "summary": None})

    @staticmethod
    def batch_analyze(tickers: List[str], event_date: date, db: Session) -> Dict[str, Dict[str, Any]]:
        """
        Analyze catalysts for multiple tickers in a single pass.
        Avoids N+1 query overhead by fetching all relevant articles once.
        """
        # Event date timeline bounds (72 hrs prior)
        end_time = datetime.combine(event_date, datetime.max.time())
        start_time = end_time - timedelta(hours=72)
        
        # Single query for all articles in the window. 
        # In a real high-volume system, we'd add .filter(NewsArticle.tickers.overlap(tickers))
        # but SQLAlchemy JSONB overlap depends on specific schema mapping. 
        # For now, fetching the 72h window is still 100x faster than N queries.
        articles = db.query(NewsArticle).filter(
            NewsArticle.published_utc >= start_time,
            NewsArticle.published_utc <= end_time
        ).all()
        
        results = {t.upper(): {"tags": [], "summary": None} for t in tickers}
        ticker_set = set(t.upper() for t in tickers)
        
        # Map articles to tickers
        ticker_news = {t: [] for t in ticker_set}
        for a in articles:
            if a.tickers:
                for t in a.tickers:
                    t_upper = t.upper()
                    if t_upper in ticker_news:
                        ticker_news[t_upper].append(a)
        
        # Analyze each ticker
        for ticker, recent_news in ticker_news.items():
            if not recent_news:
                continue
                
            tags = set()
            matched_summaries = []
            
            # Sort news so that the most recent are processed first
            recent_news.sort(key=lambda x: x.published_utc, reverse=True)
            
            for article in recent_news:
                content = f"{article.title} {article.description or ''}"
                
                # Simple fallback for generic earnings tag
                if "earnings" in content.lower() and "earnings_beat" not in tags and "earnings_miss" not in tags:
                    tags.add("earnings")
                    
                for tag, pattern in CatalystParser.PATTERNS.items():
                    if pattern.search(content):
                        tags.add(tag)
                        if len(matched_summaries) < 1:  # Keep the most relevant headline
                            matched_summaries.append(article.title)
                            
            # Prefer the headline that triggered a tag, otherwise the most recent headline
            summary = matched_summaries[0] if matched_summaries else recent_news[0].title
            
            results[ticker] = {
                "tags": list(tags),
                "summary": summary
            }
            
        return results
