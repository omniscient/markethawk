"""
XProfileScraper: navigate X profile pages and extract tweet data from the DOM.

Uses data-testid selectors for stability. Each extracted tweet is a dict with:
  tweet_id, text, posted_at (ISO), media_urls, is_retweet, is_reply
"""
import logging
import re
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import urlparse

from playwright.async_api import Page

from app.browser import browser_manager

logger = logging.getLogger(__name__)

# X DOM selectors (data-testid — more stable than class names)
_TWEET_ARTICLE = 'article[data-testid="tweet"]'
_TWEET_TEXT = '[data-testid="tweetText"]'
_TWEET_TIME = "time"
_TWEET_MEDIA = '[data-testid="tweetPhoto"] img, [data-testid="videoPlayer"] video'
_RETWEET_MARKER = '[data-testid="socialContext"]'

_PROFILE_URL = "https://x.com/{handle}"
_LOAD_TIMEOUT_MS = 15_000
_SCROLL_PAUSE_MS = 1_000

# Tweet ID extracted from status URL: /status/1234567890
_TWEET_ID_RE = re.compile(r"/status/(\d+)")


class XProfileScraper:
    async def scrape(self, handle: str, since_tweet_id: Optional[str] = None) -> list[dict[str, Any]]:
        """Scrape the profile timeline for `handle` and return new tweets."""
        page: Optional[Page] = None
        try:
            page = await browser_manager.new_page()
            url = _PROFILE_URL.format(handle=handle)
            await page.goto(url, timeout=_LOAD_TIMEOUT_MS, wait_until="domcontentloaded")
            await page.wait_for_selector(_TWEET_ARTICLE, timeout=_LOAD_TIMEOUT_MS)
            raw = await self._extract_tweets(page)
        except Exception as exc:
            logger.error(f"Scrape failed for @{handle}: {exc}")
            return []
        finally:
            if page:
                await page.close()

        tweets = [t for t in raw if t]
        if since_tweet_id:
            tweets = [t for t in tweets if int(t["tweet_id"]) > int(since_tweet_id)]

        logger.info(f"@{handle}: scraped {len(raw)} tweets, {len(tweets)} new since {since_tweet_id}")
        return tweets

    async def _extract_tweets(self, page: Page) -> list[dict[str, Any]]:
        articles = await page.query_selector_all(_TWEET_ARTICLE)
        results = []
        for article in articles:
            try:
                tweet = await self._extract_one(article)
                if tweet:
                    results.append(tweet)
            except Exception as exc:
                logger.debug(f"Failed to extract tweet: {exc}")
        return results

    async def _extract_one(self, article) -> Optional[dict[str, Any]]:
        # Tweet URL / ID
        link = await article.query_selector('a[href*="/status/"]')
        if not link:
            return None
        href = await link.get_attribute("href") or ""
        m = _TWEET_ID_RE.search(href)
        if not m:
            return None
        tweet_id = m.group(1)
        tweet_url = f"https://x.com{href}"

        # Text
        text_el = await article.query_selector(_TWEET_TEXT)
        text = await text_el.inner_text() if text_el else ""

        # Timestamp
        time_el = await article.query_selector(_TWEET_TIME)
        posted_at_raw = await time_el.get_attribute("datetime") if time_el else None
        posted_at = posted_at_raw or datetime.now(timezone.utc).isoformat()

        # Media
        media_els = await article.query_selector_all(_TWEET_MEDIA)
        media_urls = []
        for el in media_els:
            src = await el.get_attribute("src") or ""
            if src and src not in media_urls:
                media_urls.append(src)

        # Retweet / reply detection
        social_ctx = await article.query_selector(_RETWEET_MARKER)
        is_retweet = bool(social_ctx)
        is_reply = text.startswith("@")

        return {
            "tweet_id": tweet_id,
            "tweet_url": tweet_url,
            "text": text.strip(),
            "posted_at": posted_at,
            "media_urls": media_urls,
            "is_retweet": is_retweet,
            "is_reply": is_reply,
        }
