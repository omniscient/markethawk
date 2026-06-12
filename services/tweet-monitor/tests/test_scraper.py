"""Unit tests for XProfileScraper — auth expiry detection."""
import asyncio
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unittest.mock import AsyncMock, patch

import pytest

from app.scraper import AuthExpiredError, XProfileScraper


def _make_page(url="https://x.com/testhandle"):
    page = AsyncMock()
    page.url = url
    page.goto = AsyncMock()
    page.wait_for_selector = AsyncMock()
    page.query_selector_all = AsyncMock(return_value=[])
    page.close = AsyncMock()
    return page


def test_auth_expired_error_is_exception():
    err = AuthExpiredError("test")
    assert isinstance(err, Exception)


def test_scrape_raises_auth_expired_on_login_redirect():
    page = _make_page(url="https://x.com/i/flow/login?redirect_after_login=...")
    with patch("app.scraper.browser_manager") as mock_bm:
        mock_bm.new_page = AsyncMock(return_value=page)
        scraper = XProfileScraper()
        with pytest.raises(AuthExpiredError):
            asyncio.run(scraper.scrape("testhandle"))


def test_scrape_raises_auth_expired_on_exact_login_path():
    page = _make_page(url="https://x.com/i/flow/login")
    with patch("app.scraper.browser_manager") as mock_bm:
        mock_bm.new_page = AsyncMock(return_value=page)
        scraper = XProfileScraper()
        with pytest.raises(AuthExpiredError):
            asyncio.run(scraper.scrape("testhandle"))


def test_scrape_returns_empty_list_on_non_auth_error():
    page = _make_page(url="https://x.com/realDonaldTrump")
    page.wait_for_selector = AsyncMock(side_effect=Exception("timeout"))
    with patch("app.scraper.browser_manager") as mock_bm:
        mock_bm.new_page = AsyncMock(return_value=page)
        scraper = XProfileScraper()
        result = asyncio.run(scraper.scrape("realDonaldTrump"))
        assert result == []


def test_scrape_does_not_raise_on_non_login_url():
    page = _make_page(url="https://x.com/testhandle")
    page.wait_for_selector = AsyncMock()
    page.query_selector_all = AsyncMock(return_value=[])
    with patch("app.scraper.browser_manager") as mock_bm:
        mock_bm.new_page = AsyncMock(return_value=page)
        scraper = XProfileScraper()
        result = asyncio.run(scraper.scrape("testhandle"))
        assert isinstance(result, list)
