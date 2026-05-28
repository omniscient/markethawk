from datetime import date, datetime
from unittest.mock import MagicMock

from app.models.news_article import NewsArticle
from app.services.catalyst_parser import CatalystParser


def _make_article(ticker, title, published_utc):
    a = NewsArticle()
    a.tickers = [ticker]
    a.title = title
    a.description = ""
    a.published_utc = published_utc
    return a


def test_batch_analyze_returns_latest_article_utc():
    pub_utc = datetime(2025, 3, 10, 8, 0, 0)
    article = _make_article("AAPL", "Apple acquires company", pub_utc)

    db = MagicMock()
    mq = MagicMock()
    mq.filter.return_value = mq
    mq.all.return_value = [article]
    db.query.return_value = mq

    result = CatalystParser.batch_analyze(["AAPL"], date(2025, 3, 10), db)
    assert "latest_article_utc" in result["AAPL"]
    assert result["AAPL"]["latest_article_utc"] == pub_utc


def test_batch_analyze_latest_article_utc_null_when_no_news():
    db = MagicMock()
    mq = MagicMock()
    mq.filter.return_value = mq
    mq.all.return_value = []
    db.query.return_value = mq

    result = CatalystParser.batch_analyze(["AAPL"], date(2025, 3, 10), db)
    assert result["AAPL"]["latest_article_utc"] is None
