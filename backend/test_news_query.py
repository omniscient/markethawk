
import sys
import os

# Add backend to path
sys.path.append(os.getcwd())

from app.core.database import SessionLocal
from app.models.news_article import NewsArticle
from sqlalchemy import String, cast
import json

def test_query():
    db = SessionLocal()
    ticker = "ELAB"
    try:
        print(f"Testing query for ticker: {ticker}")
        query = db.query(NewsArticle)
        query = query.filter(cast(NewsArticle.tickers, String).contains(f'"{ticker.upper()}"'))
        articles = query.order_by(NewsArticle.published_utc.desc()).limit(1).all()
        print(f"Found {len(articles)} articles")
    except Exception as e:
        import traceback
        print(f"Error: {e}")
        traceback.print_exc()
    finally:
        db.close()

if __name__ == "__main__":
    test_query()
