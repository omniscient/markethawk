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
        # Event date timeline bounds (72 hrs prior)
        end_time = datetime.combine(event_date, datetime.max.time())
        start_time = end_time - timedelta(hours=72)
        
        # Filter for our specific ticker in the recent window. 
        articles = db.query(NewsArticle).filter(
            NewsArticle.published_utc >= start_time,
            NewsArticle.published_utc <= end_time
        ).all()
        
        ticker_upper = ticker.upper()
        recent_news = []
        for a in articles:
            if a.tickers and ticker_upper in [t.upper() for t in a.tickers]:
                recent_news.append(a)
                
        if not recent_news:
            return {
                "tags": [],
                "summary": None
            }
            
        tags = set()
        matched_summaries = []
        
        # Sort news so that the most recent are processed first, or just linear.
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
        
        return {
            "tags": list(tags),
            "summary": summary
        }
