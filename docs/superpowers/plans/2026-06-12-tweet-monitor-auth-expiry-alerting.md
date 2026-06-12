# Tweet-Monitor Cookie Auth Expiry Alerting — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement issue #290 — expiry monitoring for tweet-monitor X.com cookie auth. The scraper gains a typed `AuthExpiredError`, a `tweet_monitor_auth_ok` Prometheus gauge exposed on `/metrics`, a Grafana alert rule that fires within 2 minutes of sustained auth failure, a fixed `/health` `auth_expired` field, removal of stale `is_auth_expired()`, and a cookie rotation procedure in `DEVELOPMENT.md`.

**Architecture:** Runtime detection in Playwright (`/i/flow/login` URL check after `page.goto()`) → typed `AuthExpiredError` that propagates to `poll_all()` → module-level `app/state.py` shared bool (avoids circular import between `main.py` and `health.py`) → `prometheus_client` Gauge mounted on `/metrics` → Grafana alert rule on `tweet_monitor_auth_ok < 1` for ≥ 2 minutes, routing through the existing `markethawk-webhook` contact point.

**Tech Stack:** Python / FastAPI / Playwright (tweet-monitor); prometheus_client; Prometheus YAML; Grafana provisioning YAML.

**Spec:** `docs/superpowers/specs/2026-06-12-tweet-monitor-auth-expiry-alerting-design.md`

**Key facts the engineer must know (verified live 2026-06-12):**
- `scraper.py:44` — `except Exception` currently swallows ALL failures including auth failures; `AuthExpiredError` must be re-raised BEFORE this handler.
- `health.py:22` — `auth_expired = not settings.x_auth_token or not settings.x_csrf_token` is a static config check. An expired (but set) token always reports `auth_expired: false`. Replace with `state.auth_ok`.
- `browser.py:156-158` — `is_auth_expired()` returns `not settings.x_auth_token` — same dead-code static check. Remove it; no callers reference it beyond the method itself.
- `main.py` imports `check_health` from `health.py`; `health.py` cannot import from `main.py` — circular. Use `app/state.py` as the shared state carrier.
- Prometheus port: the existing backend scrapes `backend:8000/metrics`. Tweet-monitor internal container port is also `8000` (per `trigger_tweet_monitor` Celery task calling `http://tweet-monitor:8000/poll`).
- Grafana alert pattern: follow `ibkr-disconnected` exactly — same group (`markethawk-infrastructure`), same `for: 2m`, same two-refId data block structure (B = metric query, C = math expression `$B < 1`).
- Tests run from `services/tweet-monitor/` directory: `python -m pytest tests/` (or `pytest tests/` with path insert at top of test file as per existing tests).
- `prometheus_client` version: pin to `>=0.17` (no upper bound to avoid conflicts; matches backend's `prometheus-client==0.20.0`).

---

### Task 1: Add `AuthExpiredError` and login-redirect detection to `scraper.py`

**Files:**
- Modify: `services/tweet-monitor/app/scraper.py`
- Create: `services/tweet-monitor/tests/test_scraper.py`

- [ ] **Step 1: Write the failing tests**

Create `services/tweet-monitor/tests/test_scraper.py`:

```python
"""Unit tests for XProfileScraper — auth expiry detection."""
import asyncio
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unittest.mock import AsyncMock, MagicMock, patch

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


def _make_browser_manager(page):
    bm = AsyncMock()
    bm.new_page = AsyncMock(return_value=page)
    return bm


# ── AuthExpiredError ──────────────────────────────────────────────────────────

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
```

- [ ] **Step 2: Verify tests fail**

```bash
cd /workspace/markethawk/services/tweet-monitor
python -m pytest tests/test_scraper.py -v 2>&1 | head -30
```

Expected: `ImportError: cannot import name 'AuthExpiredError' from 'app.scraper'`

- [ ] **Step 3: Implement — add `AuthExpiredError` and URL check to `scraper.py`**

In `services/tweet-monitor/app/scraper.py`, after the module docstring and imports, add the error class and modify `scrape()`:

```python
class AuthExpiredError(Exception):
    """Raised when X.com redirects to the login flow (cookie expired)."""
```

Replace the `scrape()` method body:

```python
    async def scrape(self, handle: str, since_tweet_id: Optional[str] = None) -> list[dict[str, Any]]:
        """Scrape the profile timeline for `handle` and return new tweets."""
        page: Optional[Page] = None
        try:
            page = await browser_manager.new_page()
            url = _PROFILE_URL.format(handle=handle)
            await page.goto(url, timeout=_LOAD_TIMEOUT_MS, wait_until="domcontentloaded")

            if "/i/flow/login" in page.url:
                raise AuthExpiredError(f"X.com redirected to login for @{handle}")

            await page.wait_for_selector(_TWEET_ARTICLE, timeout=_LOAD_TIMEOUT_MS)
            raw = await self._extract_tweets(page)
        except AuthExpiredError:
            raise
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
```

Full resulting `scraper.py`:

```python
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


class AuthExpiredError(Exception):
    """Raised when X.com redirects to the login flow (cookie expired)."""


class XProfileScraper:
    async def scrape(self, handle: str, since_tweet_id: Optional[str] = None) -> list[dict[str, Any]]:
        """Scrape the profile timeline for `handle` and return new tweets."""
        page: Optional[Page] = None
        try:
            page = await browser_manager.new_page()
            url = _PROFILE_URL.format(handle=handle)
            await page.goto(url, timeout=_LOAD_TIMEOUT_MS, wait_until="domcontentloaded")

            if "/i/flow/login" in page.url:
                raise AuthExpiredError(f"X.com redirected to login for @{handle}")

            await page.wait_for_selector(_TWEET_ARTICLE, timeout=_LOAD_TIMEOUT_MS)
            raw = await self._extract_tweets(page)
        except AuthExpiredError:
            raise
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
```

- [ ] **Step 4: Verify tests pass**

```bash
cd /workspace/markethawk/services/tweet-monitor
python -m pytest tests/test_scraper.py -v
```

Expected output:
```
tests/test_scraper.py::test_auth_expired_error_is_exception PASSED
tests/test_scraper.py::test_scrape_raises_auth_expired_on_login_redirect PASSED
tests/test_scraper.py::test_scrape_raises_auth_expired_on_exact_login_path PASSED
tests/test_scraper.py::test_scrape_returns_empty_list_on_non_auth_error PASSED
tests/test_scraper.py::test_scrape_does_not_raise_on_non_login_url PASSED
5 passed
```

- [ ] **Step 5: Commit**

```bash
git add services/tweet-monitor/app/scraper.py services/tweet-monitor/tests/test_scraper.py
git commit -m "feat(#290): add AuthExpiredError and login-redirect detection to scraper"
```

---

### Task 2: Create `state.py` and update `health.py` to use runtime state

**Files:**
- Create: `services/tweet-monitor/app/state.py`
- Modify: `services/tweet-monitor/app/health.py`
- Create: `services/tweet-monitor/tests/test_health.py`

- [ ] **Step 1: Write the failing tests**

Create `services/tweet-monitor/tests/test_health.py`:

```python
"""Unit tests for check_health() — runtime auth state."""
import asyncio
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unittest.mock import patch, MagicMock

import app.state as state
from app.health import check_health


def _run(coro):
    return asyncio.run(coro)


def _mock_externals():
    """Patch DB and Redis so health check doesn't require live services."""
    return [
        patch("app.health._check_db", return_value=True),
        patch("app.health._check_redis", return_value=True),
        patch("app.health.browser_manager") ,
    ]


def test_auth_expired_false_when_state_auth_ok_true():
    state.auth_ok = True
    patches = _mock_externals()
    with patches[0], patches[1], patches[2] as mock_bm:
        mock_bm.is_running = True
        mock_bm.age_seconds = 10.0
        result = _run(check_health())
    assert result["auth_expired"] is False


def test_auth_expired_true_when_state_auth_ok_false():
    state.auth_ok = False
    patches = _mock_externals()
    with patches[0], patches[1], patches[2] as mock_bm:
        mock_bm.is_running = True
        mock_bm.age_seconds = 10.0
        result = _run(check_health())
    assert result["auth_expired"] is True
    assert result["healthy"] is False


def test_healthy_is_false_when_auth_expired():
    state.auth_ok = False
    patches = _mock_externals()
    with patches[0], patches[1], patches[2] as mock_bm:
        mock_bm.is_running = True
        mock_bm.age_seconds = 10.0
        result = _run(check_health())
    assert result["healthy"] is False


def test_healthy_is_true_when_all_ok():
    state.auth_ok = True
    patches = _mock_externals()
    with patches[0], patches[1], patches[2] as mock_bm:
        mock_bm.is_running = True
        mock_bm.age_seconds = 10.0
        result = _run(check_health())
    assert result["healthy"] is True
```

- [ ] **Step 2: Verify tests fail**

```bash
cd /workspace/markethawk/services/tweet-monitor
python -m pytest tests/test_health.py -v 2>&1 | head -20
```

Expected: `ModuleNotFoundError: No module named 'app.state'`

- [ ] **Step 3: Implement — create `state.py`**

Create `services/tweet-monitor/app/state.py`:

```python
auth_ok: bool = True  # False = login redirect detected on last poll cycle
```

- [ ] **Step 4: Implement — update `health.py` to use runtime state**

Replace `services/tweet-monitor/app/health.py`:

```python
"""
HealthChecker: aggregates browser, DB, and Redis liveness into a single status dict.
Reports auth_expired as a distinct failure mode.
"""
from __future__ import annotations

import logging

import redis
from sqlalchemy import create_engine, text

import app.state as state
from app.browser import browser_manager
from app.config import settings

logger = logging.getLogger(__name__)

_engine = create_engine(settings.database_url, pool_pre_ping=True)


async def check_health() -> dict:
    browser_ok = browser_manager.is_running
    auth_expired = not state.auth_ok

    db_ok = _check_db()
    redis_ok = _check_redis()

    healthy = browser_ok and db_ok and redis_ok and not auth_expired

    return {
        "healthy": healthy,
        "browser": browser_ok,
        "browser_age_seconds": round(browser_manager.age_seconds),
        "db": db_ok,
        "redis": redis_ok,
        "auth_expired": auth_expired,
    }


def _check_db() -> bool:
    try:
        with _engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception as exc:
        logger.warning(f"DB health check failed: {exc}")
        return False


def _check_redis() -> bool:
    try:
        r = redis.from_url(settings.redis_url)
        r.ping()
        return True
    except Exception as exc:
        logger.warning(f"Redis health check failed: {exc}")
        return False
```

- [ ] **Step 5: Verify tests pass**

```bash
cd /workspace/markethawk/services/tweet-monitor
python -m pytest tests/test_health.py -v
```

Expected output:
```
tests/test_health.py::test_auth_expired_false_when_state_auth_ok_true PASSED
tests/test_health.py::test_auth_expired_true_when_state_auth_ok_false PASSED
tests/test_health.py::test_healthy_is_false_when_auth_expired PASSED
tests/test_health.py::test_healthy_is_true_when_all_ok PASSED
4 passed
```

- [ ] **Step 6: Commit**

```bash
git add services/tweet-monitor/app/state.py services/tweet-monitor/app/health.py services/tweet-monitor/tests/test_health.py
git commit -m "feat(#290): add shared state.py and wire health.py to runtime auth state"
```

---

### Task 3: Remove stale `browser.py:is_auth_expired()`

**Files:**
- Modify: `services/tweet-monitor/app/browser.py`

- [ ] **Step 1: Verify no callers**

```bash
grep -rn "is_auth_expired" /workspace/markethawk/services/tweet-monitor/
```

Expected: Only `app/browser.py` line 156 (the method definition itself). No callers.

- [ ] **Step 2: Implement — remove `is_auth_expired()` from `browser.py`**

Remove lines 156–158 from `services/tweet-monitor/app/browser.py`:

```python
    def is_auth_expired(self) -> bool:
        """Detect if X returned a login redirect (auth_expired)."""
        return not settings.x_auth_token
```

The `BrowserManager` class after removal has `age_seconds` and `is_running` as its only remaining properties after `_health_check`.

- [ ] **Step 3: Verify all existing tests still pass**

```bash
cd /workspace/markethawk/services/tweet-monitor
python -m pytest tests/ -v
```

Expected: All tests pass (scraper + health + classifier + extractor).

- [ ] **Step 4: Commit**

```bash
git add services/tweet-monitor/app/browser.py
git commit -m "feat(#290): remove stale browser.py:is_auth_expired() static env-var check"
```

---

### Task 4: Add Prometheus gauge to `main.py` and wire `state.auth_ok`

**Files:**
- Modify: `services/tweet-monitor/app/main.py`

- [ ] **Step 1: Add `prometheus_client` imports and module-level gauge**

At the top of `services/tweet-monitor/app/main.py`, add the prometheus import after the existing imports:

```python
from prometheus_client import Gauge, make_asgi_app
```

After the `app = FastAPI(title="Tweet Monitor", lifespan=lifespan)` line, add:

```python
import app.state as state

TWEET_MONITOR_AUTH_OK = Gauge(
    "tweet_monitor_auth_ok",
    "1 = X.com cookie auth healthy, 0 = auth expired or login redirect detected",
)
TWEET_MONITOR_AUTH_OK.set(1)  # assume healthy at startup

metrics_app = make_asgi_app()
app.mount("/metrics", metrics_app)
```

- [ ] **Step 2: Update `poll_all()` to catch `AuthExpiredError` and update state + gauge**

Add `AuthExpiredError` to the imports from `app.scraper`:

```python
from app.scraper import AuthExpiredError, XProfileScraper
```

Replace the `poll_all()` function:

```python
@app.post("/poll", response_model=PollSummary)
async def poll_all():
    """Scrape all enabled accounts and process new tweets."""
    start = time.perf_counter()
    state.auth_ok = True  # optimistic reset each cycle
    with _SessionLocal() as db:
        accounts = db.query(MonitoredAccount).filter(MonitoredAccount.enabled == True).all()

    summary = PollSummary(
        accounts_polled=0, tweets_found=0, tweets_new=0, tweets_promoted=0, duration_ms=0
    )
    errors: list[str] = []

    for account in accounts:
        try:
            promoted = await _poll_account(account, summary)
            summary.accounts_polled += 1
            summary.tweets_promoted += promoted
        except AuthExpiredError as exc:
            state.auth_ok = False
            msg = f"@{account.handle}: auth expired — {exc}"
            logger.error(msg)
            errors.append(msg)
        except Exception as exc:
            msg = f"@{account.handle}: {exc}"
            logger.error(msg)
            errors.append(msg)

    TWEET_MONITOR_AUTH_OK.set(1 if state.auth_ok else 0)
    summary.duration_ms = round((time.perf_counter() - start) * 1000, 1)
    summary.errors = errors
    return summary
```

Full resulting `main.py` for reference:

```python
"""
Tweet-monitor FastAPI application.

Endpoints:
  POST /poll              — Triggered by Celery beat every 45s
  GET  /health            — Browser + DB + Redis liveness
  GET  /status            — Operational metrics
  GET  /accounts          — List monitored accounts
  POST /accounts          — Create/update a monitored account
  POST /poll/{account_id} — Manual single-account trigger (debugging)
  GET  /metrics           — Prometheus metrics
"""
import asyncio
import logging
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

import redis as redis_lib
from fastapi import FastAPI, HTTPException
from prometheus_client import Gauge, make_asgi_app
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.state as state
from app.browser import browser_manager
from app.classifier import TweetClassifier
from app.config import settings
from app.extractor import PriceLevelExtractor, TickerExtractor
from app.health import check_health
from app.models import MonitoredAccount, TweetSignal
from app.pipeline import SignalPipeline
from app.schemas import (
    AccountCreate, AccountStatus, HealthResponse, PollSummary, StatusResponse,
)
from app.scraper import AuthExpiredError, XProfileScraper

logging.basicConfig(level=settings.log_level.upper())
logger = logging.getLogger(__name__)

_engine = create_engine(settings.database_url, pool_pre_ping=True)
_SessionLocal = sessionmaker(bind=_engine, autoflush=False, autocommit=False)
_redis = redis_lib.from_url(settings.redis_url, decode_responses=True)

_classifier = TweetClassifier()
_ticker_extractor = TickerExtractor()
_price_extractor = PriceLevelExtractor()
_pipeline = SignalPipeline()
_scraper = XProfileScraper()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await browser_manager.start()
    logger.info("Tweet-monitor started")
    yield
    await browser_manager.stop()
    logger.info("Tweet-monitor stopped")


app = FastAPI(title="Tweet Monitor", lifespan=lifespan)

TWEET_MONITOR_AUTH_OK = Gauge(
    "tweet_monitor_auth_ok",
    "1 = X.com cookie auth healthy, 0 = auth expired or login redirect detected",
)
TWEET_MONITOR_AUTH_OK.set(1)  # assume healthy at startup

metrics_app = make_asgi_app()
app.mount("/metrics", metrics_app)


@app.post("/poll", response_model=PollSummary)
async def poll_all():
    """Scrape all enabled accounts and process new tweets."""
    start = time.perf_counter()
    state.auth_ok = True  # optimistic reset each cycle
    with _SessionLocal() as db:
        accounts = db.query(MonitoredAccount).filter(MonitoredAccount.enabled == True).all()

    summary = PollSummary(
        accounts_polled=0, tweets_found=0, tweets_new=0, tweets_promoted=0, duration_ms=0
    )
    errors: list[str] = []

    for account in accounts:
        try:
            promoted = await _poll_account(account, summary)
            summary.accounts_polled += 1
            summary.tweets_promoted += promoted
        except AuthExpiredError as exc:
            state.auth_ok = False
            msg = f"@{account.handle}: auth expired — {exc}"
            logger.error(msg)
            errors.append(msg)
        except Exception as exc:
            msg = f"@{account.handle}: {exc}"
            logger.error(msg)
            errors.append(msg)

    TWEET_MONITOR_AUTH_OK.set(1 if state.auth_ok else 0)
    summary.duration_ms = round((time.perf_counter() - start) * 1000, 1)
    summary.errors = errors
    return summary


@app.post("/poll/{account_id}", response_model=PollSummary)
async def poll_one(account_id: int):
    """Manually trigger a poll for a single account."""
    with _SessionLocal() as db:
        account = db.query(MonitoredAccount).filter(MonitoredAccount.id == account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    start = time.perf_counter()
    summary = PollSummary(
        accounts_polled=1, tweets_found=0, tweets_new=0, tweets_promoted=0, duration_ms=0
    )
    promoted = await _poll_account(account, summary)
    summary.tweets_promoted = promoted
    summary.duration_ms = round((time.perf_counter() - start) * 1000, 1)
    return summary


async def _poll_account(account: MonitoredAccount, summary: PollSummary) -> int:
    """Scrape one account and process new tweets. Returns number promoted."""
    redis_key = f"tweet_monitor:last_seen:{account.id}"
    last_id: str | None = _redis.get(redis_key) or account.last_tweet_id

    tweets = await _scraper.scrape(account.handle, since_tweet_id=last_id)
    summary.tweets_found += len(tweets)

    promoted = 0
    newest_id: str | None = last_id

    for raw in tweets:
        raw["handle"] = account.handle
        tickers = _ticker_extractor.extract(raw["text"])
        price_levels = _price_extractor.extract(raw["text"], tickers)

        try:
            posted_at = datetime.fromisoformat(raw["posted_at"].replace("Z", "+00:00"))
        except Exception:
            posted_at = datetime.now(timezone.utc)

        result = _classifier.classify(
            text=raw["text"],
            posted_at=posted_at,
            is_retweet=raw.get("is_retweet", False),
            is_reply=raw.get("is_reply", False),
            tickers=tickers,
            price_levels=price_levels,
            account_config=account.classification_config or {},
        )

        signal = _pipeline.process(
            account=account,
            raw=raw,
            classification=result.classification,
            confidence=result.confidence,
            tickers=result.tickers,
            price_levels=result.price_levels,
            direction=result.direction,
        )
        if signal:
            summary.tweets_new += 1
            if signal.promoted:
                promoted += 1
            if newest_id is None or int(raw["tweet_id"]) > int(newest_id):
                newest_id = raw["tweet_id"]

    if newest_id and newest_id != last_id:
        _redis.set(redis_key, newest_id)
        with _SessionLocal() as db:
            acc = db.query(MonitoredAccount).filter(MonitoredAccount.id == account.id).first()
            if acc:
                acc.last_tweet_id = newest_id
                acc.last_poll_at = datetime.now(timezone.utc).replace(tzinfo=None)
                db.commit()

    return promoted


@app.get("/health", response_model=HealthResponse)
async def health():
    result = await check_health()
    if not result["healthy"]:
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=503, content=result)
    return result


@app.get("/status", response_model=StatusResponse)
async def status():
    health_data = await check_health()
    with _SessionLocal() as db:
        accounts = db.query(MonitoredAccount).all()
    return StatusResponse(
        accounts=[
            AccountStatus(
                id=a.id,
                handle=a.handle,
                display_name=a.display_name,
                platform=a.platform,
                enabled=a.enabled,
                last_poll_at=a.last_poll_at,
                last_tweet_id=a.last_tweet_id,
                poll_interval_seconds=a.poll_interval_seconds,
            )
            for a in accounts
        ],
        health=HealthResponse(**health_data),
    )


@app.get("/accounts", response_model=list[AccountStatus])
async def list_accounts():
    with _SessionLocal() as db:
        accounts = db.query(MonitoredAccount).all()
    return [
        AccountStatus(
            id=a.id,
            handle=a.handle,
            display_name=a.display_name,
            platform=a.platform,
            enabled=a.enabled,
            last_poll_at=a.last_poll_at,
            last_tweet_id=a.last_tweet_id,
            poll_interval_seconds=a.poll_interval_seconds,
        )
        for a in accounts
    ]


@app.post("/accounts", response_model=AccountStatus, status_code=201)
async def create_account(body: AccountCreate):
    with _SessionLocal() as db:
        existing = db.query(MonitoredAccount).filter(
            MonitoredAccount.handle == body.handle,
            MonitoredAccount.platform == body.platform,
        ).first()
        if existing:
            for k, v in body.model_dump().items():
                setattr(existing, k, v)
            db.commit()
            db.refresh(existing)
            a = existing
        else:
            a = MonitoredAccount(**body.model_dump())
            db.add(a)
            db.commit()
            db.refresh(a)
    return AccountStatus(
        id=a.id,
        handle=a.handle,
        display_name=a.display_name,
        platform=a.platform,
        enabled=a.enabled,
        last_poll_at=a.last_poll_at,
        last_tweet_id=a.last_tweet_id,
        poll_interval_seconds=a.poll_interval_seconds,
    )
```

- [ ] **Step 3: Verify all tests pass**

```bash
cd /workspace/markethawk/services/tweet-monitor
python -m pytest tests/ -v
```

Expected: All tests pass.

- [ ] **Step 4: Commit**

```bash
git add services/tweet-monitor/app/main.py
git commit -m "feat(#290): add TWEET_MONITOR_AUTH_OK Prometheus gauge and /metrics endpoint"
```

---

### Task 5: Add `prometheus_client` to `requirements.txt`

**Files:**
- Modify: `services/tweet-monitor/requirements.txt`

- [ ] **Step 1: Implement**

Add to `services/tweet-monitor/requirements.txt`:

```
prometheus_client>=0.17
```

Full resulting `requirements.txt`:

```
fastapi==0.115.0
uvicorn[standard]==0.30.6
playwright==1.47.0
sqlalchemy==2.0.35
psycopg2-binary==2.9.9
redis==5.1.0
httpx==0.27.2
pydantic-settings==2.5.2
seqlog==0.3.24
psutil==6.0.0
prometheus_client>=0.17
```

- [ ] **Step 2: Verify**

```bash
grep "prometheus_client" /workspace/markethawk/services/tweet-monitor/requirements.txt
```

Expected: `prometheus_client>=0.17`

- [ ] **Step 3: Commit**

```bash
git add services/tweet-monitor/requirements.txt
git commit -m "feat(#290): add prometheus_client to tweet-monitor requirements"
```

---

### Task 6: Add Prometheus scrape job for tweet-monitor

**Files:**
- Modify: `monitoring/prometheus/prometheus.yml`

- [ ] **Step 1: Implement**

Add the new scrape job to `monitoring/prometheus/prometheus.yml`:

```yaml
global:
  scrape_interval: 15s
  evaluation_interval: 15s

scrape_configs:
  - job_name: markethawk_backend
    static_configs:
      - targets: ["backend:8000"]
    metrics_path: /metrics

  - job_name: tweet_monitor
    static_configs:
      - targets: ["tweet-monitor:8000"]
    metrics_path: /metrics
```

- [ ] **Step 2: Verify**

```bash
grep -A3 "tweet_monitor" /workspace/markethawk/monitoring/prometheus/prometheus.yml
```

Expected:
```yaml
  - job_name: tweet_monitor
    static_configs:
      - targets: ["tweet-monitor:8000"]
    metrics_path: /metrics
```

- [ ] **Step 3: Commit**

```bash
git add monitoring/prometheus/prometheus.yml
git commit -m "feat(#290): add tweet-monitor Prometheus scrape job"
```

---

### Task 7: Add Grafana alert rule `tweet-monitor-auth-expired`

**Files:**
- Modify: `grafana/provisioning/alerting/rules.yaml`

- [ ] **Step 1: Implement**

Add the new alert rule to the `markethawk-infrastructure` group in `grafana/provisioning/alerting/rules.yaml`, after the `high-api-error-rate` rule:

```yaml
      - uid: tweet-monitor-auth-expired
        title: Tweet-Monitor Auth Expired
        condition: C
        for: 2m
        annotations:
          summary: >
            Tweet-monitor X.com cookie auth has been failing for 2+ minutes.
            Rotate X_AUTH_TOKEN and X_CSRF_TOKEN in .env and restart tweet-monitor.
        labels:
          severity: warning
        data:
          - refId: B
            relativeTimeRange:
              from: 300
              to: 0
            datasourceUid: prometheus
            model:
              expr: tweet_monitor_auth_ok
              refId: B
          - refId: C
            relativeTimeRange:
              from: 300
              to: 0
            datasourceUid: "-- Grafana --"
            model:
              type: math
              expression: $B < 1
```

Full resulting `rules.yaml`:

```yaml
apiVersion: 1

groups:
  - orgId: 1
    name: markethawk-infrastructure
    folder: MarketHawk
    interval: 1m
    rules:
      - uid: ibkr-disconnected
        title: IBKR Disconnected
        condition: C
        for: 2m
        annotations:
          summary: IBKR Gateway has been disconnected for more than 2 minutes
        labels:
          severity: critical
        data:
          - refId: B
            relativeTimeRange:
              from: 300
              to: 0
            datasourceUid: prometheus
            model:
              expr: ibkr_connection_status
              refId: B
          - refId: C
            relativeTimeRange:
              from: 300
              to: 0
            datasourceUid: "-- Grafana --"
            model:
              type: math
              expression: $B < 1

      - uid: high-celery-failure-rate
        title: High Celery Task Failure Rate
        condition: C
        for: 5m
        annotations:
          summary: Celery task failure rate exceeds 10% over the last 5 minutes
        labels:
          severity: warning
        data:
          - refId: B
            relativeTimeRange:
              from: 600
              to: 0
            datasourceUid: prometheus
            model:
              expr: >
                sum(rate(celery_tasks_total{status="failure"}[5m]))
                /
                sum(rate(celery_tasks_total[5m]))
              refId: B
          - refId: C
            relativeTimeRange:
              from: 600
              to: 0
            datasourceUid: "-- Grafana --"
            model:
              type: math
              expression: $B > 0.1

      - uid: db-pool-overflow
        title: DB Pool Overflow
        condition: C
        for: 5m
        annotations:
          summary: SQLAlchemy connection pool overflow is non-zero for more than 5 minutes
        labels:
          severity: warning
        data:
          - refId: B
            relativeTimeRange:
              from: 600
              to: 0
            datasourceUid: prometheus
            model:
              expr: db_pool_overflow
              refId: B
          - refId: C
            relativeTimeRange:
              from: 600
              to: 0
            datasourceUid: "-- Grafana --"
            model:
              type: math
              expression: $B > 0

      - uid: high-api-error-rate
        title: High API Error Rate
        condition: C
        for: 5m
        annotations:
          summary: HTTP 5xx error rate exceeds 5 errors/min
        labels:
          severity: warning
        data:
          - refId: B
            relativeTimeRange:
              from: 600
              to: 0
            datasourceUid: prometheus
            model:
              expr: sum(rate(http_requests_total{status_code=~"5.."}[1m])) * 60
              refId: B
          - refId: C
            relativeTimeRange:
              from: 600
              to: 0
            datasourceUid: "-- Grafana --"
            model:
              type: math
              expression: $B > 5

      - uid: tweet-monitor-auth-expired
        title: Tweet-Monitor Auth Expired
        condition: C
        for: 2m
        annotations:
          summary: >
            Tweet-monitor X.com cookie auth has been failing for 2+ minutes.
            Rotate X_AUTH_TOKEN and X_CSRF_TOKEN in .env and restart tweet-monitor.
        labels:
          severity: warning
        data:
          - refId: B
            relativeTimeRange:
              from: 300
              to: 0
            datasourceUid: prometheus
            model:
              expr: tweet_monitor_auth_ok
              refId: B
          - refId: C
            relativeTimeRange:
              from: 300
              to: 0
            datasourceUid: "-- Grafana --"
            model:
              type: math
              expression: $B < 1
```

- [ ] **Step 2: Verify**

```bash
grep -A5 "tweet-monitor-auth-expired" /workspace/markethawk/grafana/provisioning/alerting/rules.yaml
```

Expected:
```yaml
      - uid: tweet-monitor-auth-expired
        title: Tweet-Monitor Auth Expired
        condition: C
        for: 2m
```

- [ ] **Step 3: Commit**

```bash
git add grafana/provisioning/alerting/rules.yaml
git commit -m "feat(#290): add tweet-monitor-auth-expired Grafana alert rule"
```

---

### Task 8: Document X.com cookie rotation in `DEVELOPMENT.md`

**Files:**
- Modify: `DEVELOPMENT.md`

- [ ] **Step 1: Implement**

Add a new section "### Tweet-Monitor: X.com Cookie Rotation" under the `## Troubleshooting` section, after the "### ENV changes not reflected" subsection (line ~385):

```markdown
### Tweet-Monitor: X.com Cookie Rotation

`X_AUTH_TOKEN` and `X_CSRF_TOKEN` are X.com session cookies that expire roughly every 30 days. When they expire, the tweet-monitor detects the `/i/flow/login` redirect and raises `AuthExpiredError`, setting `tweet_monitor_auth_ok = 0`.

**Alert signature:**
- Grafana alert `Tweet-Monitor Auth Expired` fires in the `MarketHawk / Infrastructure` panel
- Seq error log: `Auth expired for @<handle>: X.com redirected to login for @<handle>`
- `/health` endpoint returns `"auth_expired": true, "healthy": false`

**To rotate cookies:**

1. Log in to X.com in Chrome (use the account the scraper monitors)
2. Open DevTools → Application → Cookies → `https://x.com`
3. Copy the value of `auth_token` → this is `X_AUTH_TOKEN`
4. Copy the value of `ct0` → this is `X_CSRF_TOKEN`
5. Update `.env`:
   ```
   X_AUTH_TOKEN=<new_auth_token>
   X_CSRF_TOKEN=<new_ct0_value>
   ```
6. Restart the tweet-monitor container:
   ```bash
   docker-compose restart tweet-monitor
   ```
7. Verify recovery: `curl http://localhost:8001/health` should return `"auth_expired": false, "healthy": true`

The `tweet_monitor_auth_ok` gauge returns to `1` on the next poll cycle (within 45 seconds) after a successful restart.
```

- [ ] **Step 2: Verify**

```bash
grep -A5 "X.com Cookie Rotation" /workspace/markethawk/DEVELOPMENT.md
```

Expected: The section heading and body appear.

- [ ] **Step 3: Commit**

```bash
git add DEVELOPMENT.md
git commit -m "docs(#290): add X.com cookie rotation procedure to DEVELOPMENT.md"
```

---

### Task 9: Run full test suite and validate

- [ ] **Step 1: Run all tweet-monitor tests**

```bash
cd /workspace/markethawk/services/tweet-monitor
python -m pytest tests/ -v
```

Expected: 9+ tests passing (classifier + extractor + scraper + health).

- [ ] **Step 2: Validate the running service exposes /metrics**

```bash
# After docker-compose restart tweet-monitor
curl -s http://localhost:8001/metrics | grep tweet_monitor_auth_ok
```

Expected:
```
# HELP tweet_monitor_auth_ok 1 = X.com cookie auth healthy, 0 = auth expired or login redirect detected
# TYPE tweet_monitor_auth_ok gauge
tweet_monitor_auth_ok 1.0
```

- [ ] **Step 3: Validate /health reflects runtime state**

```bash
curl -s http://localhost:8001/health | python -m json.tool
```

Expected: `"auth_expired": false` (assuming valid cookies in .env).

- [ ] **Step 4: Commit (if any cleanup needed)**

```bash
git add -p  # review any remaining changes
git commit -m "feat(#290): finalize tweet-monitor auth expiry alerting"
```
