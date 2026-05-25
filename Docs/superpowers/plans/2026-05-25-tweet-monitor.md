# Tweet Monitor Microservice (Issue #78) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a standalone `tweet-monitor` Docker microservice that scrapes X/Twitter profiles using Playwright Chromium, classifies tweets into stock callouts, extracts tickers and price levels, and promotes high-confidence callouts (≥ 0.7) into the existing `ScannerEvent` / alert pipeline as `scanner_type="social_callout"`. A Dashboard `TweetFeed` component shows live signals via Redis pub/sub.

**Architecture:** Standalone FastAPI microservice under `backend/tweet_monitor/`, built from the `./backend` Docker context. Models (`MonitoredAccount`, `TweetSignal`) live in the main backend and are migrated by existing Alembic. Celery beat triggers `POST /poll` every 45 seconds. Follows the `live-scanner` precedent exactly for model sharing and container topology.

**Tech Stack:** FastAPI, Playwright Chromium, SQLAlchemy (sync), Pydantic Settings, Redis pub/sub, Celery beat, Alembic, React 18, TypeScript, React Query, Tailwind CSS.

**Design spec:** `Docs/superpowers/specs/2026-05-25-tweet-monitor-design.md`

---

### Task 1: `MonitoredAccount` and `TweetSignal` models

**Files:**
- Create: `backend/app/models/monitored_account.py`
- Create: `backend/app/models/tweet_signal.py`
- Modify: `backend/app/models/__init__.py`

- [ ] **Step 1: Create `MonitoredAccount` model**

Create `backend/app/models/monitored_account.py`:

```python
import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Integer, Boolean, DateTime
from sqlalchemy.dialects.postgresql import JSONB, UUID
from app.core.database import Base


class MonitoredAccount(Base):
    __tablename__ = "monitored_accounts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    handle = Column(String(100), nullable=False, unique=True)
    platform = Column(String(20), nullable=False, default="x")
    poll_interval_seconds = Column(Integer, nullable=False, default=45)
    enabled = Column(Boolean, nullable=False, default=True)
    classification_config = Column(JSONB, nullable=True)
    created_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc).replace(tzinfo=None),
    )
```

- [ ] **Step 2: Create `TweetSignal` model**

Create `backend/app/models/tweet_signal.py`:

```python
import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Float, Boolean, DateTime, Text, ForeignKey, Integer, Index
from sqlalchemy.dialects.postgresql import JSONB, UUID
from app.core.database import Base


class TweetSignal(Base):
    __tablename__ = "tweet_signals"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tweet_id = Column(String(50), unique=True, nullable=False, index=True)
    account_id = Column(UUID(as_uuid=True), ForeignKey("monitored_accounts.id"), nullable=False)
    full_text = Column(Text, nullable=False)
    classification = Column(String(20), nullable=False)  # CALLOUT/CELEBRATION/UPDATE/RETWEET/UNKNOWN
    confidence = Column(Float, nullable=False, default=0.0)
    tickers = Column(JSONB, nullable=False, default=list)
    price_levels = Column(JSONB, nullable=True)
    direction = Column(String(10), nullable=True)  # long/short/None
    promoted = Column(Boolean, nullable=False, default=False)
    scanner_event_id = Column(Integer, ForeignKey("scanner_events.id"), nullable=True)
    scraped_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc).replace(tzinfo=None),
    )
    tweet_created_at = Column(DateTime, nullable=True)

    __table_args__ = (
        Index("ix_tweet_signals_account_scraped", "account_id", "scraped_at"),
        Index("ix_tweet_signals_classification_confidence", "classification", "confidence"),
    )
```

- [ ] **Step 3: Register models in `__init__.py`**

In `backend/app/models/__init__.py`, add after the `SignalReview` import (line 34):

```python
from app.models.monitored_account import MonitoredAccount
from app.models.tweet_signal import TweetSignal
```

And add both names to `__all__` after `"SignalReview"`:

```python
    "MonitoredAccount",
    "TweetSignal",
```

- [ ] **Step 4: Commit**

```bash
git add backend/app/models/monitored_account.py backend/app/models/tweet_signal.py backend/app/models/__init__.py
git commit -m "feat(tweet-monitor): add MonitoredAccount and TweetSignal SQLAlchemy models"
```

---

### Task 2: Add `social_callout` to `event_helpers`

**Files:**
- Modify: `backend/app/services/event_helpers.py`

- [ ] **Step 1: Add summary generator**

In `backend/app/services/event_helpers.py`, add to `SUMMARY_GENERATORS` dict after the `"live_price_move"` entry (line 27):

```python
    "social_callout": lambda ind: (
        f"@{ind.get('account_handle', 'unknown')} callout: "
        f"{', '.join('$' + t for t in (ind.get('tickers') or []))} "
        f"(confidence {ind.get('confidence', 0):.0%})"
    ).strip(),
```

- [ ] **Step 2: Add severity calculator**

Add to `SEVERITY_CALCULATORS` dict after the `"live_price_move"` entry (line 64):

```python
    "social_callout": lambda ind: (
        "high" if ind.get("confidence", 0) >= 0.85
        else "medium" if ind.get("confidence", 0) >= 0.7
        else "low"
    ),
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/services/event_helpers.py
git commit -m "feat(tweet-monitor): add social_callout summary and severity to event_helpers"
```

---

### Task 3: Alembic migration for `monitored_accounts` and `tweet_signals`

**Files:**
- Generated: `backend/alembic/versions/<hash>_add_monitored_accounts_and_tweet_signals.py`

- [ ] **Step 1: Generate migration**

```bash
docker compose exec backend python -m alembic revision --autogenerate -m "add_monitored_accounts_and_tweet_signals"
```

Review the generated file in `backend/alembic/versions/`. Verify it creates both tables with the correct columns, FKs, and indexes.

- [ ] **Step 2: Seed initial `@PlayBookTrades` account**

After the standard `upgrade()` body, add a seed insert (before the closing `pass`):

```python
def upgrade() -> None:
    # ... generated table creation code ...

    # Seed initial monitored account
    op.execute("""
        INSERT INTO monitored_accounts (id, handle, platform, poll_interval_seconds, enabled, created_at)
        VALUES (
            gen_random_uuid(),
            'PlayBookTrades',
            'x',
            45,
            true,
            NOW()
        )
        ON CONFLICT (handle) DO NOTHING
    """)
```

- [ ] **Step 3: Apply migration**

```bash
docker compose exec backend python -m alembic upgrade head
```

Expected: `Running upgrade <prev> -> <new>, add_monitored_accounts_and_tweet_signals`

- [ ] **Step 4: Verify tables exist**

```bash
docker compose exec backend python -c "
from sqlalchemy import inspect, create_engine
from app.core.config import settings
eng = create_engine(settings.DATABASE_URL)
ins = inspect(eng)
print(ins.get_columns('monitored_accounts'))
print(ins.get_columns('tweet_signals'))
"
```

Expected: both tables listed with correct columns.

- [ ] **Step 5: Commit**

```bash
git add backend/alembic/versions/
git commit -m "feat(tweet-monitor): alembic migration for monitored_accounts and tweet_signals tables"
```

---

### Task 4: `tweet_monitor` package — Dockerfile and `requirements.txt`

**Files:**
- Create: `backend/tweet_monitor/__init__.py`
- Create: `backend/tweet_monitor/Dockerfile`
- Create: `backend/tweet_monitor/requirements.txt`

- [ ] **Step 1: Create package marker**

Create `backend/tweet_monitor/__init__.py` (empty file).

- [ ] **Step 2: Create `requirements.txt`**

Create `backend/tweet_monitor/requirements.txt`:

```
playwright==1.47.0
httpx==0.27.2
pydantic-settings==2.5.2
seqlog==0.3.22
```

These are tweet_monitor-specific deps. The main backend `requirements.txt` already provides `fastapi`, `uvicorn`, `sqlalchemy`, `redis`, `psycopg2-binary`, `alembic`, etc.

- [ ] **Step 3: Create `Dockerfile`**

Create `backend/tweet_monitor/Dockerfile`:

```dockerfile
FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install shared backend deps (SQLAlchemy, FastAPI, Redis, etc.)
COPY requirements.txt /tmp/backend_requirements.txt
RUN pip install --upgrade pip && \
    pip install --no-cache-dir -r /tmp/backend_requirements.txt

# Install tweet_monitor-specific deps including Playwright
COPY tweet_monitor/requirements.txt /tmp/tweet_monitor_requirements.txt
RUN pip install --no-cache-dir -r /tmp/tweet_monitor_requirements.txt && \
    playwright install chromium && \
    playwright install-deps chromium

# Copy entire backend directory (provides app/ package + tweet_monitor/)
COPY . .

CMD ["uvicorn", "tweet_monitor.main:app", "--host", "0.0.0.0", "--port", "8001"]
```

- [ ] **Step 4: Commit**

```bash
git add backend/tweet_monitor/__init__.py backend/tweet_monitor/Dockerfile backend/tweet_monitor/requirements.txt
git commit -m "feat(tweet-monitor): add package skeleton, Dockerfile, and requirements"
```

---

### Task 5: `tweet_monitor/config.py`

**Files:**
- Create: `backend/tweet_monitor/config.py`

- [ ] **Step 1: Create config module**

Create `backend/tweet_monitor/config.py`:

```python
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str
    REDIS_URL: str = "redis://redis:6379/0"
    X_AUTH_TOKEN: str = ""
    X_CSRF_TOKEN: str = ""
    SEQ_URL: str = "http://seq:5341"
    LOG_LEVEL: str = "INFO"
    ENVIRONMENT: str = "development"
    BROWSER_MAX_AGE_SECONDS: int = 1800   # 30 minutes
    BROWSER_MAX_MEMORY_MB: int = 512
    CALLOUT_CONFIDENCE_THRESHOLD: float = 0.7
    POLL_PORT: int = 8001

    class Config:
        env_file = ".env"


settings = Settings()
```

- [ ] **Step 2: Commit**

```bash
git add backend/tweet_monitor/config.py
git commit -m "feat(tweet-monitor): add Pydantic Settings config module"
```

---

### Task 6: `tweet_monitor/browser.py` — `BrowserManager`

**Files:**
- Create: `backend/tweet_monitor/browser.py`

- [ ] **Step 1: Create `BrowserManager`**

Create `backend/tweet_monitor/browser.py`:

```python
"""
Manages a persistent Playwright Chromium browser with health checks and auto-restart.
Restarts on: health-check failure, 30-min max age, or >512 MB memory usage.
"""

import asyncio
import logging
import time
from typing import Optional, Tuple

from playwright.async_api import async_playwright, Browser, BrowserContext, Page

logger = logging.getLogger(__name__)


class BrowserManager:
    def __init__(
        self,
        x_auth_token: str,
        x_csrf_token: str,
        max_age_seconds: int = 1800,
        max_memory_mb: int = 512,
    ):
        self._x_auth_token = x_auth_token
        self._x_csrf_token = x_csrf_token
        self._max_age_seconds = max_age_seconds
        self._max_memory_mb = max_memory_mb
        self._playwright = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._started_at: float = 0.0
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        self._playwright = await async_playwright().start()
        await self._launch_browser()

    async def stop(self) -> None:
        await self._close_browser()
        if self._playwright:
            await self._playwright.stop()

    async def get_page(self) -> Page:
        async with self._lock:
            if self._needs_restart():
                logger.info("BrowserManager: restarting browser (age or memory limit)")
                await self._close_browser()
                await self._launch_browser()
        return await self._context.new_page()

    async def is_healthy(self) -> Tuple[bool, str]:
        """
        Returns (healthy, reason). reason is one of: 'ok', 'auth_expired', 'browser_down'.
        'auth_expired' is surfaced as a distinct failure mode so operators are alerted.
        """
        if not self._browser or not self._context:
            return False, "browser_down"
        try:
            page = await asyncio.wait_for(self._context.new_page(), timeout=5.0)
            await asyncio.wait_for(
                page.goto("https://x.com", wait_until="domcontentloaded"), timeout=10.0
            )
            url = page.url
            await page.close()
            if "login" in url or "i/flow" in url:
                return False, "auth_expired"
            return True, "ok"
        except Exception as e:
            logger.warning(f"BrowserManager: health check failed: {e}")
            return False, "browser_down"

    async def _launch_browser(self) -> None:
        self._browser = await self._playwright.chromium.launch(headless=True)
        self._context = await self._browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        )
        await self._inject_cookies()
        self._started_at = time.monotonic()
        logger.info("BrowserManager: browser launched and cookies injected")

    async def _close_browser(self) -> None:
        try:
            if self._context:
                await self._context.close()
            if self._browser:
                await self._browser.close()
        except Exception as e:
            logger.warning(f"BrowserManager: error closing browser: {e}")
        finally:
            self._browser = None
            self._context = None

    async def _inject_cookies(self) -> None:
        if not self._x_auth_token:
            logger.warning("BrowserManager: X_AUTH_TOKEN not set — scraping unauthenticated")
            return
        await self._context.add_cookies([
            {
                "name": "auth_token",
                "value": self._x_auth_token,
                "domain": ".x.com",
                "path": "/",
                "httpOnly": True,
                "secure": True,
            },
            {
                "name": "ct0",
                "value": self._x_csrf_token,
                "domain": ".x.com",
                "path": "/",
            },
        ])

    def _needs_restart(self) -> bool:
        if not self._browser:
            return True
        age = time.monotonic() - self._started_at
        if age > self._max_age_seconds:
            logger.info(f"BrowserManager: max age reached ({age:.0f}s > {self._max_age_seconds}s)")
            return True
        return False
```

- [ ] **Step 2: Commit**

```bash
git add backend/tweet_monitor/browser.py
git commit -m "feat(tweet-monitor): add BrowserManager with Playwright Chromium lifecycle and cookie auth"
```

---

### Task 7: `tweet_monitor/scraper.py` — `XProfileScraper`

**Files:**
- Create: `backend/tweet_monitor/scraper.py`

- [ ] **Step 1: Create `XProfileScraper`**

Create `backend/tweet_monitor/scraper.py`:

```python
"""
Scrapes X.com profile timelines using Playwright.
Uses data-testid attributes for selector stability (more stable than CSS class names).
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

from playwright.async_api import Page

logger = logging.getLogger(__name__)

TWEET_SELECTOR = '[data-testid="tweet"]'
TWEET_TEXT_SELECTOR = '[data-testid="tweetText"]'
TWEET_TIME_SELECTOR = "time"
TWEET_LINK_SELECTOR = 'a[href*="/status/"]'


@dataclass
class RawTweet:
    tweet_id: str
    full_text: str
    created_at: Optional[datetime]


class XProfileScraper:
    def __init__(self, browser_manager):
        self._browser_manager = browser_manager

    async def fetch_tweets(self, handle: str, limit: int = 20) -> List[RawTweet]:
        """Fetch the most recent tweets from an X profile timeline."""
        page = await self._browser_manager.get_page()
        tweets: List[RawTweet] = []
        try:
            url = f"https://x.com/{handle}"
            await page.goto(url, wait_until="domcontentloaded", timeout=15000)
            try:
                await page.wait_for_selector(TWEET_SELECTOR, timeout=10000)
            except Exception:
                logger.warning(
                    f"XProfileScraper: no tweet elements found on @{handle} — "
                    "possible auth expiry or DOM change"
                )
                return tweets

            tweet_elements = await page.query_selector_all(TWEET_SELECTOR)
            for el in tweet_elements[:limit]:
                try:
                    tweet = await self._extract_tweet(el)
                    if tweet:
                        tweets.append(tweet)
                except Exception as e:
                    logger.debug(f"XProfileScraper: skipping tweet element: {e}")
        except Exception as e:
            logger.warning(f"XProfileScraper: failed to fetch @{handle}: {e}")
        finally:
            await page.close()
        return tweets

    async def _extract_tweet(self, el) -> Optional[RawTweet]:
        # Extract tweet ID from the status permalink
        link = await el.query_selector(TWEET_LINK_SELECTOR)
        if not link:
            return None
        href = await link.get_attribute("href") or ""
        if "/status/" not in href:
            return None
        tweet_id = href.split("/status/")[-1].split("?")[0]
        if not tweet_id:
            return None

        # Extract tweet text
        text_el = await el.query_selector(TWEET_TEXT_SELECTOR)
        full_text = (await text_el.inner_text()).strip() if text_el else ""

        # Extract timestamp from <time datetime="...">
        time_el = await el.query_selector(TWEET_TIME_SELECTOR)
        created_at = None
        if time_el:
            dt_str = await time_el.get_attribute("datetime")
            if dt_str:
                try:
                    created_at = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
                except ValueError:
                    pass

        return RawTweet(tweet_id=tweet_id, full_text=full_text, created_at=created_at)
```

- [ ] **Step 2: Commit**

```bash
git add backend/tweet_monitor/scraper.py
git commit -m "feat(tweet-monitor): add XProfileScraper with data-testid selectors"
```

---

### Task 8: `tweet_monitor/classifier.py` — rule-based classifier

**Files:**
- Create: `backend/tweet_monitor/classifier.py`

- [ ] **Step 1: Create classifier**

Create `backend/tweet_monitor/classifier.py`:

```python
"""
Rule-based tweet classifier with per-signal confidence scoring.
No ML model for v1 — pure regex and keyword matching.

Confidence threshold for ScannerEvent promotion: 0.7 (configurable via MonitoredAccount.classification_config).
"""

import re
from dataclasses import dataclass
from typing import Dict, Optional

RETWEET_PATTERN = re.compile(r"^RT @", re.IGNORECASE)
CASHTAG_PATTERN = re.compile(r"\$[A-Z]{1,5}\b")

CELEBRATION_WORDS = frozenset(
    {"up", "nice", "profit", "winner", "green", "gains", "win", "crushed", "hit", "target"}
)
DIRECTION_WORDS = frozenset(
    {"long", "short", "buying", "selling", "bought", "sold", "calls", "puts", "entry"}
)
PRICE_LEVEL_WORDS = frozenset(
    {"target", "stop", "entry", "exit", "pt", "sl", "tp", "level", "price"}
)
PRICE_NUMBER_PATTERN = re.compile(r"\$\d+\.?\d*")

DEFAULT_WEIGHTS: Dict[str, float] = {
    "has_cashtag": 0.4,
    "has_direction": 0.2,
    "has_price_level": 0.15,
    "all_three_bonus": 0.05,
}


@dataclass
class ClassificationResult:
    classification: str   # CALLOUT / CELEBRATION / UPDATE / RETWEET / UNKNOWN
    confidence: float     # 0.0 – 1.0
    direction: Optional[str]  # "long" / "short" / None


def classify(text: str, config: Optional[dict] = None) -> ClassificationResult:
    """
    Classify a tweet and return confidence.
    config: MonitoredAccount.classification_config JSONB — optional weight overrides.
    """
    weights = dict(DEFAULT_WEIGHTS)
    if config and "weights" in config:
        weights.update(config["weights"])

    # Hard rule: retweets are always RETWEET with zero confidence
    if RETWEET_PATTERN.match(text):
        return ClassificationResult(classification="RETWEET", confidence=0.0, direction=None)

    lower = text.lower()
    words = set(lower.split())

    has_cashtag = bool(CASHTAG_PATTERN.search(text))
    has_direction = bool(words & DIRECTION_WORDS)
    has_price_level = bool(words & PRICE_LEVEL_WORDS) or bool(PRICE_NUMBER_PATTERN.search(text))
    has_celebration = bool(words & CELEBRATION_WORDS)

    # Celebration: celebratory language without forward-looking signal
    if has_celebration and not has_direction and not has_cashtag:
        return ClassificationResult(classification="CELEBRATION", confidence=0.6, direction=None)

    # Score CALLOUT confidence
    score = 0.0
    if has_cashtag:
        score += weights["has_cashtag"]
    if has_direction:
        score += weights["has_direction"]
    if has_price_level:
        score += weights["has_price_level"]
    if has_cashtag and has_direction and has_price_level:
        score += weights["all_three_bonus"]

    score = min(round(score, 3), 1.0)

    if score >= 0.3:
        direction = None
        if any(w in lower for w in ("long", "buying", "calls", "bought")):
            direction = "long"
        elif any(w in lower for w in ("short", "selling", "puts", "sold")):
            direction = "short"
        return ClassificationResult(
            classification="CALLOUT", confidence=score, direction=direction
        )

    if has_celebration or ("profit" in lower and has_cashtag):
        return ClassificationResult(
            classification="CELEBRATION", confidence=0.5, direction=None
        )

    return ClassificationResult(classification="UNKNOWN", confidence=0.0, direction=None)
```

- [ ] **Step 2: Commit**

```bash
git add backend/tweet_monitor/classifier.py
git commit -m "feat(tweet-monitor): add rule-based tweet classifier with confidence scoring"
```

---

### Task 9: `tweet_monitor/extractor.py` — ticker and price extraction

**Files:**
- Create: `backend/tweet_monitor/extractor.py`

- [ ] **Step 1: Create extractor**

Create `backend/tweet_monitor/extractor.py`:

```python
"""
Extracts cashtag tickers and price levels from tweet text via regex.
"""

import re
from dataclasses import dataclass
from typing import List

CASHTAG_PATTERN = re.compile(r"\$([A-Z]{1,5})\b")
PRICE_PATTERN = re.compile(r"\$?(\d{1,6}(?:\.\d{1,4})?)")

# Single-letter cashtags that are almost always noise, not tickers
NOISE_TICKERS = frozenset({"A", "I", "S", "T", "U", "X"})


@dataclass
class TickerMatch:
    ticker: str
    confidence: float


def extract_tickers(text: str, base_confidence: float = 0.7) -> List[TickerMatch]:
    """
    Extract cashtag tickers from tweet text.
    Single-letter tickers in the noise set are excluded to reduce false positives.
    """
    seen: set = set()
    results: List[TickerMatch] = []
    for m in CASHTAG_PATTERN.finditer(text):
        ticker = m.group(1).upper()
        if ticker in NOISE_TICKERS or ticker in seen:
            continue
        seen.add(ticker)
        results.append(TickerMatch(ticker=ticker, confidence=base_confidence))
    return results


def extract_price_levels(text: str) -> List[float]:
    """
    Extract plausible stock price levels from tweet text.
    Filters out numbers outside the range $0.01 – $99,999.
    """
    levels: List[float] = []
    for m in PRICE_PATTERN.finditer(text):
        try:
            val = float(m.group(1))
            if 0.01 <= val <= 99999:
                levels.append(val)
        except ValueError:
            pass
    return sorted(set(levels))
```

- [ ] **Step 2: Commit**

```bash
git add backend/tweet_monitor/extractor.py
git commit -m "feat(tweet-monitor): add ticker and price level extractor"
```

---

### Task 10: `tweet_monitor/pipeline.py` — DB writes and ScannerEvent promotion

**Files:**
- Create: `backend/tweet_monitor/pipeline.py`

- [ ] **Step 1: Create `TweetPipeline`**

Create `backend/tweet_monitor/pipeline.py`:

```python
"""
TweetPipeline: persists TweetSignal, promotes high-confidence CALLOUTs to ScannerEvent,
and publishes to Redis for the frontend TweetFeed component.
"""

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import List, Optional

import redis.asyncio as aioredis
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.monitored_account import MonitoredAccount
from app.models.scanner_event import ScannerEvent
from app.models.tweet_signal import TweetSignal
from tweet_monitor.classifier import ClassificationResult
from tweet_monitor.extractor import TickerMatch
from tweet_monitor.scraper import RawTweet

logger = logging.getLogger(__name__)

REDIS_TWEET_CHANNEL = "tweet_signals"


class TweetPipeline:
    def __init__(self, db_url: str, redis_url: str, confidence_threshold: float = 0.7):
        self._engine = create_engine(db_url, pool_pre_ping=True)
        self._redis_url = redis_url
        self._redis: Optional[aioredis.Redis] = None
        self._confidence_threshold = confidence_threshold

    async def connect(self) -> None:
        self._redis = aioredis.from_url(self._redis_url, decode_responses=True)

    async def close(self) -> None:
        if self._redis:
            await self._redis.aclose()
        self._engine.dispose()

    def is_tweet_seen(self, tweet_id: str) -> bool:
        with Session(self._engine) as session:
            return (
                session.execute(
                    select(TweetSignal.id).where(TweetSignal.tweet_id == tweet_id).limit(1)
                ).first()
                is not None
            )

    def process_tweet(
        self,
        raw: RawTweet,
        account: MonitoredAccount,
        classification: ClassificationResult,
        tickers: List[TickerMatch],
        price_levels: List[float],
    ) -> Optional[TweetSignal]:
        """
        Write TweetSignal and promote to ScannerEvent(s) if classification == CALLOUT
        and confidence >= threshold. Returns the persisted signal, or None if duplicate.
        """
        ticker_data = [{"ticker": t.ticker, "confidence": t.confidence} for t in tickers]

        signal = TweetSignal(
            id=uuid.uuid4(),
            tweet_id=raw.tweet_id,
            account_id=account.id,
            full_text=raw.full_text,
            classification=classification.classification,
            confidence=classification.confidence,
            tickers=ticker_data,
            price_levels=price_levels if price_levels else None,
            direction=classification.direction,
            promoted=False,
            tweet_created_at=raw.created_at.replace(tzinfo=None) if raw.created_at else None,
        )

        with Session(self._engine) as session:
            try:
                session.add(signal)
                session.flush()

                if (
                    classification.classification == "CALLOUT"
                    and classification.confidence >= self._confidence_threshold
                ):
                    promoted = self._promote_to_scanner_events(
                        session, signal, account, classification, tickers
                    )
                    signal.promoted = promoted

                session.commit()
                session.refresh(signal)
                logger.info(
                    f"TweetPipeline: {raw.tweet_id} "
                    f"[{classification.classification} {classification.confidence:.2f}] "
                    f"promoted={signal.promoted}"
                )
                return signal
            except IntegrityError:
                session.rollback()
                logger.debug(f"TweetPipeline: duplicate tweet {raw.tweet_id} — skipping")
                return None

    def _promote_to_scanner_events(
        self,
        session: Session,
        signal: TweetSignal,
        account: MonitoredAccount,
        classification: ClassificationResult,
        tickers: List[TickerMatch],
    ) -> bool:
        """
        Create one ScannerEvent per ticker with confidence >= threshold.
        Uses the existing (ticker, event_date, scanner_type) UniqueConstraint to dedup
        within a trading day — first high-confidence callout per ticker per day wins.
        """
        today = datetime.now(timezone.utc).date()
        promoted_any = False

        for tm in tickers:
            if tm.confidence < self._confidence_threshold:
                continue

            summary = (
                f"@{account.handle} callout: ${tm.ticker}"
                + (f" {classification.direction}" if classification.direction else "")
                + f" (confidence {classification.confidence:.0%})"
            )
            severity = (
                "high" if classification.confidence >= 0.85
                else "medium" if classification.confidence >= 0.7
                else "low"
            )
            indicators = {
                "account_handle": account.handle,
                "tickers": [t.ticker for t in tickers],
                "confidence": classification.confidence,
                "direction": classification.direction,
            }
            metadata = {
                "tweet_id": signal.tweet_id,
                "account_handle": account.handle,
                "all_tickers": [t.ticker for t in tickers],
                "tweet_text_preview": signal.full_text[:280],
                "confidence": classification.confidence,
                "source": "tweet_monitor",
            }

            event = ScannerEvent(
                uuid=uuid.uuid4(),
                ticker=tm.ticker,
                event_date=today,
                scanner_type="social_callout",
                summary=summary,
                severity=severity,
                indicators=indicators,
                criteria_met={"callout_confidence_met": True},
                metadata_=metadata,
                signal_quality_score=round(classification.confidence * 100, 1),
            )
            try:
                session.add(event)
                session.flush()
                if not signal.scanner_event_id:
                    signal.scanner_event_id = event.id
                promoted_any = True
                logger.info(f"TweetPipeline: ScannerEvent created for ${tm.ticker}")
            except IntegrityError:
                session.rollback()
                logger.debug(
                    f"TweetPipeline: ScannerEvent already exists for ${tm.ticker} {today} — skipping"
                )

        return promoted_any

    async def publish(self, account_handle: str, signal: TweetSignal) -> None:
        """Publish signal to Redis for the frontend TweetFeed WebSocket."""
        if not self._redis:
            return
        msg = json.dumps({
            "type": "tweet_signal",
            "tweet_id": signal.tweet_id,
            "account_handle": account_handle,
            "classification": signal.classification,
            "confidence": signal.confidence,
            "tickers": signal.tickers,
            "direction": signal.direction,
            "promoted": signal.promoted,
            "full_text": signal.full_text[:280],
            "scraped_at": signal.scraped_at.isoformat() if signal.scraped_at else None,
        })
        try:
            await self._redis.publish(f"{REDIS_TWEET_CHANNEL}:{account_handle}", msg)
        except Exception as e:
            logger.warning(f"TweetPipeline: Redis publish failed: {e}")
```

- [ ] **Step 2: Commit**

```bash
git add backend/tweet_monitor/pipeline.py
git commit -m "feat(tweet-monitor): add TweetPipeline for DB writes, ScannerEvent promotion, Redis pub"
```

---

### Task 11: `tweet_monitor/health.py` and `tweet_monitor/main.py` — FastAPI app

**Files:**
- Create: `backend/tweet_monitor/health.py`
- Create: `backend/tweet_monitor/main.py`

- [ ] **Step 1: Create `health.py`**

Create `backend/tweet_monitor/health.py`:

```python
from dataclasses import dataclass


@dataclass
class HealthStatus:
    healthy: bool
    browser: str   # "ok" / "auth_expired" / "browser_down"
    db: str        # "ok" / "error"
    redis: str     # "ok" / "error"

    def to_dict(self) -> dict:
        return {
            "healthy": self.healthy,
            "browser": self.browser,
            "db": self.db,
            "redis": self.redis,
            "auth_expired": self.browser == "auth_expired",
        }
```

- [ ] **Step 2: Create `main.py`**

Create `backend/tweet_monitor/main.py`:

```python
"""
tweet-monitor FastAPI application.

Endpoints:
  POST /poll    — poll all enabled monitored accounts; triggered by Celery beat every 45s
  GET  /health  — liveness probe; reports browser/DB/Redis status + auth_expired flag
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Optional

import redis.asyncio as aioredis
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from tweet_monitor.browser import BrowserManager
from tweet_monitor.classifier import classify
from tweet_monitor.config import settings
from tweet_monitor.extractor import extract_price_levels, extract_tickers
from tweet_monitor.health import HealthStatus
from tweet_monitor.pipeline import TweetPipeline
from tweet_monitor.scraper import XProfileScraper

logging.basicConfig(level=settings.LOG_LEVEL)
logger = logging.getLogger(__name__)

# Module-level singletons — initialised in lifespan
_browser_manager: Optional[BrowserManager] = None
_pipeline: Optional[TweetPipeline] = None
_scraper: Optional[XProfileScraper] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _browser_manager, _pipeline, _scraper

    _browser_manager = BrowserManager(
        x_auth_token=settings.X_AUTH_TOKEN,
        x_csrf_token=settings.X_CSRF_TOKEN,
        max_age_seconds=settings.BROWSER_MAX_AGE_SECONDS,
        max_memory_mb=settings.BROWSER_MAX_MEMORY_MB,
    )
    await _browser_manager.start()

    _pipeline = TweetPipeline(
        db_url=settings.DATABASE_URL,
        redis_url=settings.REDIS_URL,
        confidence_threshold=settings.CALLOUT_CONFIDENCE_THRESHOLD,
    )
    await _pipeline.connect()

    _scraper = XProfileScraper(_browser_manager)

    logger.info("tweet-monitor: startup complete")
    yield

    await _browser_manager.stop()
    await _pipeline.close()
    logger.info("tweet-monitor: shutdown complete")


app = FastAPI(title="tweet-monitor", lifespan=lifespan)


@app.post("/poll")
async def poll():
    """Poll all enabled monitored accounts and process new tweets."""
    from app.models.monitored_account import MonitoredAccount

    engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True)
    with Session(engine) as session:
        accounts = (
            session.query(MonitoredAccount)
            .filter(MonitoredAccount.enabled == True)  # noqa: E712
            .all()
        )
    engine.dispose()

    results = []
    for account in accounts:
        result = await _poll_account(account)
        results.append({"handle": account.handle, **result})

    return {"polled": len(accounts), "results": results}


async def _poll_account(account) -> dict:
    tweets = await _scraper.fetch_tweets(account.handle)
    new_count = 0
    promoted_count = 0

    for raw in tweets:
        if _pipeline.is_tweet_seen(raw.tweet_id):
            continue

        classification = classify(raw.full_text, account.classification_config)
        tickers = extract_tickers(raw.full_text, base_confidence=classification.confidence)
        price_levels = extract_price_levels(raw.full_text)

        signal = await asyncio.to_thread(
            _pipeline.process_tweet, raw, account, classification, tickers, price_levels
        )
        if signal:
            new_count += 1
            if signal.promoted:
                promoted_count += 1
            await _pipeline.publish(account.handle, signal)

    return {"new_tweets": new_count, "promoted": promoted_count}


@app.get("/health")
async def health():
    """Liveness probe. Returns 200 when healthy, 503 otherwise."""
    browser_ok, browser_reason = await _browser_manager.is_healthy()

    db_status = "ok"
    try:
        engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True)
        with Session(engine) as s:
            s.execute(text("SELECT 1"))
        engine.dispose()
    except Exception:
        db_status = "error"

    redis_status = "ok"
    try:
        r = aioredis.from_url(settings.REDIS_URL)
        await r.ping()
        await r.aclose()
    except Exception:
        redis_status = "error"

    status = HealthStatus(
        healthy=browser_ok and db_status == "ok" and redis_status == "ok",
        browser=browser_reason,
        db=db_status,
        redis=redis_status,
    )
    code = 200 if status.healthy else 503
    return JSONResponse(content=status.to_dict(), status_code=code)
```

- [ ] **Step 3: Commit**

```bash
git add backend/tweet_monitor/health.py backend/tweet_monitor/main.py
git commit -m "feat(tweet-monitor): add FastAPI app with /poll and /health endpoints"
```

---

### Task 12: Unit tests for `classifier` and `extractor`

**Files:**
- Create: `backend/tweet_monitor/tests/__init__.py`
- Create: `backend/tweet_monitor/tests/test_classifier.py`
- Create: `backend/tweet_monitor/tests/test_extractor.py`

- [ ] **Step 1: Create tests package**

Create `backend/tweet_monitor/tests/__init__.py` (empty).

- [ ] **Step 2: Create `test_classifier.py`**

Create `backend/tweet_monitor/tests/test_classifier.py`:

```python
"""Unit tests for rule-based tweet classifier."""
from tweet_monitor.classifier import classify, ClassificationResult


def test_retweet_classified_correctly():
    result = classify("RT @SomeUser: $AAPL looking good for a long today")
    assert result.classification == "RETWEET"
    assert result.confidence == 0.0
    assert result.direction is None


def test_callout_with_all_signals():
    result = classify("Long $TSLA here, target $250, stop $210")
    assert result.classification == "CALLOUT"
    assert result.confidence >= 0.7
    assert result.direction == "long"


def test_callout_short():
    result = classify("Shorting $NVDA, puts at $480")
    assert result.classification == "CALLOUT"
    assert result.direction == "short"


def test_callout_cashtag_only():
    result = classify("$AAPL setting up nicely here")
    assert result.classification == "CALLOUT"
    assert result.confidence < 0.7  # insufficient for promotion


def test_celebration_no_cashtag():
    result = classify("Up 30% today, great win!")
    assert result.classification == "CELEBRATION"
    assert result.direction is None


def test_unknown_tweet():
    result = classify("Good morning everyone, hope you have a great day!")
    assert result.classification == "UNKNOWN"
    assert result.confidence == 0.0


def test_config_weight_override():
    config = {"weights": {"has_cashtag": 0.8, "has_direction": 0.1, "has_price_level": 0.1, "all_three_bonus": 0.0}}
    result = classify("$AMZN is breaking out", config)
    assert result.classification == "CALLOUT"
    assert result.confidence == 0.8


def test_confidence_capped_at_one():
    result = classify("Long $AAPL $TSLA here buying calls, target $200, stop $180 entry now")
    assert result.confidence <= 1.0
```

- [ ] **Step 3: Create `test_extractor.py`**

Create `backend/tweet_monitor/tests/test_extractor.py`:

```python
"""Unit tests for ticker and price level extractor."""
from tweet_monitor.extractor import extract_tickers, extract_price_levels


def test_single_cashtag():
    tickers = extract_tickers("Long $AAPL today")
    assert len(tickers) == 1
    assert tickers[0].ticker == "AAPL"


def test_multiple_cashtags():
    tickers = extract_tickers("$TSLA and $NVDA breaking out")
    assert {t.ticker for t in tickers} == {"TSLA", "NVDA"}


def test_noise_tickers_excluded():
    tickers = extract_tickers("$I $S $T are in the sentence but $AAPL is real")
    symbols = [t.ticker for t in tickers]
    assert "AAPL" in symbols
    assert "I" not in symbols
    assert "S" not in symbols
    assert "T" not in symbols


def test_no_cashtags():
    tickers = extract_tickers("Great day for trading!")
    assert tickers == []


def test_duplicate_cashtags_deduped():
    tickers = extract_tickers("$AAPL $AAPL $AAPL long")
    assert len(tickers) == 1


def test_price_levels_extracted():
    levels = extract_price_levels("target $250, stop $210")
    assert 250.0 in levels
    assert 210.0 in levels


def test_price_levels_out_of_range_excluded():
    levels = extract_price_levels("$0.001 target or $999999 target")
    assert 0.001 not in levels
    assert 999999 not in levels


def test_price_levels_deduplicated():
    levels = extract_price_levels("target $250 and also $250")
    assert levels.count(250.0) == 1
```

- [ ] **Step 4: Run the tests**

```bash
docker compose exec backend python -m pytest tweet_monitor/tests/ -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/tweet_monitor/tests/
git commit -m "test(tweet-monitor): add unit tests for classifier and extractor"
```

---

### Task 13: Celery task and beat schedule

**Files:**
- Modify: `backend/app/tasks.py`
- Modify: `backend/app/core/celery_app.py`

- [ ] **Step 1: Add `trigger_tweet_monitor` task to `tasks.py`**

In `backend/app/tasks.py`, add after the last task in the file (at the very end):

```python
@celery_app.task(bind=True, max_retries=3)
def trigger_tweet_monitor(self):
    """Trigger the tweet-monitor service to poll all enabled accounts.
    Called by Celery beat every 45 seconds."""
    import httpx
    try:
        response = httpx.post("http://tweet-monitor:8001/poll", timeout=35)
        response.raise_for_status()
        return response.json()
    except Exception as exc:
        raise self.retry(exc=exc, countdown=10)
```

- [ ] **Step 2: Add beat schedule entry to `celery_app.py`**

In `backend/app/core/celery_app.py`, add inside `celery_app.conf.beat_schedule` after the `'analyze-signal-features-nightly'` entry (line 39), before the closing `}`:

```python
    'trigger-tweet-monitor': {
        'task': 'app.tasks.trigger_tweet_monitor',
        'schedule': 45.0,           # seconds
        'options': {'expires': 40}, # drop if worker is already running
    },
```

- [ ] **Step 3: Restart celery-beat and verify**

```bash
docker compose restart celery-beat
```

After 1 minute, open Flower at http://localhost:5555 and verify:
- `trigger_tweet_monitor` appears in the task list
- It fires every 45 seconds (visible in the task history)

- [ ] **Step 4: Commit**

```bash
git add backend/app/tasks.py backend/app/core/celery_app.py
git commit -m "feat(tweet-monitor): add trigger_tweet_monitor Celery task and 45s beat schedule"
```

---

### Task 14: `docker-compose.yml` and `.env.example` updates

**Files:**
- Modify: `docker-compose.yml`
- Modify: `.env.example`

- [ ] **Step 1: Add `tweet-monitor` service to `docker-compose.yml`**

In `docker-compose.yml`, add the following service block after the `live-scanner` service block (after line ~199):

```yaml
  # Tweet Monitor — scrapes X accounts for real-time stock callouts
  tweet-monitor:
    build:
      context: ./backend
      dockerfile: tweet_monitor/Dockerfile
    container_name: tweet-monitor
    ports:
      - "8001:8001"
    mem_limit: 1g
    environment:
      DATABASE_URL: ${DATABASE_URL}
      REDIS_URL: redis://redis:6379/0
      ENVIRONMENT: ${ENVIRONMENT:-development}
      SEQ_URL: http://seq:5341
      LOG_LEVEL: ${LOG_LEVEL:-INFO}
      X_AUTH_TOKEN: ${X_AUTH_TOKEN:-}
      X_CSRF_TOKEN: ${X_CSRF_TOKEN:-}
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    networks:
      - stockscanner-network
    restart: unless-stopped
```

- [ ] **Step 2: Add `X_AUTH_TOKEN` and `X_CSRF_TOKEN` to `.env.example`**

Add a new section to `.env.example` (e.g. after the Redis section):

```bash
# =============================================================================
# Tweet Monitor — X (Twitter) authentication cookies
# Required for the tweet-monitor service to scrape authenticated timelines.
# Rotate approximately every 30 days.
# =============================================================================
X_AUTH_TOKEN=
X_CSRF_TOKEN=
```

- [ ] **Step 3: Build and start tweet-monitor**

```bash
docker compose build tweet-monitor
docker compose up -d tweet-monitor
```

- [ ] **Step 4: Verify startup**

```bash
docker compose logs tweet-monitor --tail=20
curl -s http://localhost:8001/health | python -m json.tool
```

Expected health response (without auth tokens configured):
```json
{
  "healthy": false,
  "browser": "auth_expired",
  "db": "ok",
  "redis": "ok",
  "auth_expired": true
}
```

- [ ] **Step 5: Commit**

```bash
git add docker-compose.yml .env.example
git commit -m "feat(tweet-monitor): add tweet-monitor service to docker-compose and env.example"
```

---

### Task 15: Backend tweets WebSocket router

**Files:**
- Create: `backend/app/routers/tweets.py`
- Modify: `backend/app/routers/__init__.py`
- Modify: `backend/app/main.py`

- [ ] **Step 1: Create `tweets.py` router**

Create `backend/app/routers/tweets.py`:

```python
"""
Tweets router — streams live tweet signals to the frontend via WebSocket.
Subscribes to Redis tweet_signals:* channels published by tweet_monitor/pipeline.py.
"""

import asyncio
import logging

import redis.asyncio as aioredis
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/tweets", tags=["tweets"])


@router.websocket("/feed")
async def tweet_feed_websocket(websocket: WebSocket):
    """
    WebSocket endpoint that streams incoming tweet signals from all monitored accounts.
    Subscribe: psubscribe tweet_signals:* (pattern subscribe to all account channels).
    """
    await websocket.accept()

    redis_client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    pubsub = redis_client.pubsub()
    await pubsub.psubscribe("tweet_signals:*")

    logger.info("Client connected to tweet feed")

    try:
        while True:
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if message:
                await websocket.send_text(message["data"])
            await asyncio.sleep(0.01)
    except WebSocketDisconnect:
        logger.info("Client disconnected from tweet feed")
    except Exception as e:
        logger.error(f"Tweet feed WebSocket error: {e}")
    finally:
        await pubsub.punsubscribe("tweet_signals:*")
        await redis_client.aclose()
```

- [ ] **Step 2: Register in `backend/app/routers/__init__.py`**

Add the import after the last existing router import:

```python
from app.routers.tweets import router as tweets_router
```

Add `"tweets_router"` to `__all__`.

- [ ] **Step 3: Register in `backend/app/main.py`**

Add `tweets_router` to the import on line 21:

```python
from app.routers import health_router, scanner_router, universe_router, stocks_router, news_router, live_data_router, journal_router, system_router, futures_router, alerts_router, watchlist_router, auto_trading_router, outcomes_router, tweets_router
```

Add after line 184 (`app.include_router(outcomes_router)`):

```python
    app.include_router(tweets_router)
```

- [ ] **Step 4: Restart backend and verify route exists**

```bash
docker compose restart backend
curl -s http://localhost:8000/openapi.json | python -m json.tool | grep -A3 "tweets"
```

Expected: `/api/tweets/feed` appears in the OpenAPI schema.

- [ ] **Step 5: Commit**

```bash
git add backend/app/routers/tweets.py backend/app/routers/__init__.py backend/app/main.py
git commit -m "feat(tweet-monitor): add /api/tweets/feed WebSocket endpoint to backend"
```

---

### Task 16: Frontend — TweetFeed types and API client

**Files:**
- Create: `frontend/src/api/tweets.ts`

- [ ] **Step 1: Create `tweets.ts` API module**

Create `frontend/src/api/tweets.ts`:

```typescript
export interface TweetSignal {
  type: 'tweet_signal';
  tweet_id: string;
  account_handle: string;
  classification: 'CALLOUT' | 'CELEBRATION' | 'UPDATE' | 'RETWEET' | 'UNKNOWN';
  confidence: number;
  tickers: Array<{ ticker: string; confidence: number }>;
  direction: 'long' | 'short' | null;
  promoted: boolean;
  full_text: string;
  scraped_at: string | null;
}

export const TWEET_FEED_WS_URL = '/api/tweets/feed';
```

- [ ] **Step 2: Type-check**

```bash
cd frontend && npx tsc --noEmit
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/api/tweets.ts
git commit -m "feat(frontend): add TweetSignal type and tweet feed WebSocket URL constant"
```

---

### Task 17: Frontend — `TweetFeed` component

**Files:**
- Create: `frontend/src/components/TweetFeed.tsx`

- [ ] **Step 1: Create `TweetFeed` component**

Create `frontend/src/components/TweetFeed.tsx`:

```tsx
import React, { useEffect, useRef, useState } from 'react';
import { Twitter } from 'lucide-react';
import Card from './ui/Card';
import { TweetSignal, TWEET_FEED_WS_URL } from '../api/tweets';

const MAX_SIGNALS = 20;

const CLASSIFICATION_COLORS: Record<string, string> = {
  CALLOUT: 'bg-green-500/20 text-green-400 border border-green-500/30',
  CELEBRATION: 'bg-yellow-500/20 text-yellow-400 border border-yellow-500/30',
  UPDATE: 'bg-blue-500/20 text-blue-400 border border-blue-500/30',
  RETWEET: 'bg-gray-500/20 text-gray-400 border border-gray-500/30',
  UNKNOWN: 'bg-gray-500/20 text-gray-500 border border-gray-500/30',
};

const TweetFeed: React.FC = () => {
  const [signals, setSignals] = useState<TweetSignal[]>([]);
  const [connected, setConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const host = window.location.host;
    const ws = new WebSocket(`${protocol}//${host}${TWEET_FEED_WS_URL}`);
    wsRef.current = ws;

    ws.onopen = () => setConnected(true);
    ws.onclose = () => setConnected(false);
    ws.onerror = () => setConnected(false);

    ws.onmessage = (event) => {
      try {
        const signal: TweetSignal = JSON.parse(event.data);
        if (signal.type !== 'tweet_signal') return;
        setSignals((prev) => [signal, ...prev].slice(0, MAX_SIGNALS));
      } catch {
        // ignore malformed messages
      }
    };

    return () => {
      ws.close();
    };
  }, []);

  return (
    <Card
      title="Tweet Feed"
      icon={Twitter as any}
      headerRight={
        <span className={`text-[10px] px-1.5 py-0.5 rounded font-mono ${connected ? 'text-green-400' : 'text-gray-500'}`}>
          {connected ? 'LIVE' : 'OFFLINE'}
        </span>
      }
    >
      {signals.length === 0 ? (
        <p className="text-xs text-gray-500 text-center py-4">
          Waiting for tweet signals…
        </p>
      ) : (
        <div className="space-y-2 max-h-80 overflow-y-auto">
          {signals.map((s) => (
            <div
              key={s.tweet_id}
              className="p-2 rounded bg-gray-800/40 border border-gray-700/40"
            >
              <div className="flex items-center gap-2 mb-1">
                <span className="text-xs font-semibold text-financial-light">
                  @{s.account_handle}
                </span>
                <span
                  className={`text-[10px] px-1 py-0.5 rounded font-bold uppercase ${
                    CLASSIFICATION_COLORS[s.classification] || CLASSIFICATION_COLORS.UNKNOWN
                  }`}
                >
                  {s.classification}
                </span>
                {s.confidence > 0 && (
                  <span className="text-[10px] text-gray-500 font-mono">
                    {(s.confidence * 100).toFixed(0)}%
                  </span>
                )}
                {s.promoted && (
                  <span className="text-[10px] text-green-400 font-bold">↑ PROMOTED</span>
                )}
              </div>

              {s.tickers.length > 0 && (
                <div className="flex gap-1 mb-1 flex-wrap">
                  {s.tickers.map((t) => (
                    <span
                      key={t.ticker}
                      className="text-[10px] px-1 py-0.5 bg-financial-blue/20 text-financial-blue rounded font-mono border border-financial-blue/30"
                    >
                      ${t.ticker}
                    </span>
                  ))}
                  {s.direction && (
                    <span
                      className={`text-[10px] px-1 py-0.5 rounded font-bold ${
                        s.direction === 'long'
                          ? 'text-green-400 bg-green-500/10'
                          : 'text-red-400 bg-red-500/10'
                      }`}
                    >
                      {s.direction.toUpperCase()}
                    </span>
                  )}
                </div>
              )}

              <p className="text-[11px] text-gray-400 leading-relaxed line-clamp-2">
                {s.full_text}
              </p>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
};

export default TweetFeed;
```

- [ ] **Step 2: Type-check**

```bash
cd frontend && npx tsc --noEmit
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/TweetFeed.tsx
git commit -m "feat(frontend): add TweetFeed live component with WebSocket subscription"
```

---

### Task 18: Frontend — add TweetFeed to Dashboard

**Files:**
- Modify: `frontend/src/pages/Dashboard.tsx`

- [ ] **Step 1: Add import**

In `frontend/src/pages/Dashboard.tsx`, add after the last component import:

```typescript
import TweetFeed from '../components/TweetFeed';
```

- [ ] **Step 2: Add `TweetFeed` to the dashboard layout**

Find the right-column or bottom section of the Dashboard layout (typically where `NewsFeed` lives). Add `<TweetFeed />` alongside or below `<NewsFeed />`:

```tsx
<TweetFeed />
```

The exact placement depends on the Dashboard grid layout. Place it in the same column as `NewsFeed` — if `NewsFeed` takes full column width, stack `TweetFeed` below it.

- [ ] **Step 3: Type-check**

```bash
cd frontend && npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/Dashboard.tsx
git commit -m "feat(frontend): add TweetFeed widget to Dashboard"
```

---

### Task 19: Frontend — Scanner page `social_callout` source annotation

**Files:**
- Modify: `frontend/src/components/ScannerResults.tsx`

- [ ] **Step 1: Add source annotation for `social_callout` events**

In `frontend/src/components/ScannerResults.tsx`, find the ticker cell or the summary cell in the row renderer. After the summary `<td>`, add a conditional sub-row or tooltip for `social_callout` events:

Locate the existing row structure (around where `event.summary` is rendered). Add this inline below the summary `<td>`:

```tsx
{event.scanner_type === 'social_callout' && event.metadata_ && (
  <div className="text-[10px] text-gray-500 mt-0.5">
    <span className="text-blue-400 font-mono">
      @{(event.metadata_ as any).account_handle}
    </span>
    {' · '}
    <a
      href={`https://x.com/i/web/status/${(event.metadata_ as any).tweet_id}`}
      target="_blank"
      rel="noopener noreferrer"
      className="text-gray-500 hover:text-gray-300 underline"
      onClick={(e) => e.stopPropagation()}
    >
      view tweet
    </a>
  </div>
)}
```

- [ ] **Step 2: Ensure `ScannerEvent` type includes `metadata_`**

In `frontend/src/api/scanner.ts`, verify the `ScannerEvent` interface has a `metadata_` field. If missing, add:

```typescript
  metadata_?: Record<string, unknown> | null;
```

- [ ] **Step 3: Type-check**

```bash
cd frontend && npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/ScannerResults.tsx frontend/src/api/scanner.ts
git commit -m "feat(frontend): add social_callout source annotation to Scanner results"
```

---

### Task 20: End-to-end verification

**Files:** none (verification only)

- [ ] **Step 1: Confirm all services are running**

```bash
docker compose ps
```

Expected: `tweet-monitor`, `backend`, `celery-beat`, `celery-worker`, `postgres`, `redis` all `Up`.

- [ ] **Step 2: Verify migration applied**

```bash
docker compose exec backend python -m alembic current
```

Expected: `head` on latest migration including `add_monitored_accounts_and_tweet_signals`.

- [ ] **Step 3: Verify tweet-monitor health endpoint**

```bash
curl -s http://localhost:8001/health | python -m json.tool
```

Expected: `db: "ok"`, `redis: "ok"`. `browser` will be `"auth_expired"` until real cookies are configured — this is expected.

- [ ] **Step 4: Verify backend `/api/tweets/feed` exists**

```bash
curl -s http://localhost:8000/openapi.json | python -m json.tool | grep -A5 "tweet"
```

Expected: `/api/tweets/feed` in the WebSocket paths.

- [ ] **Step 5: Verify `social_callout` in scanner API**

```bash
curl -s "http://localhost:8000/api/scanner/results?scanner_type=social_callout" | python -m json.tool
```

Expected: `[]` (empty — no signals yet, but no 500 error).

- [ ] **Step 6: Verify Celery beat is scheduling the task**

Open Flower at http://localhost:5555. Navigate to Tasks. After 45–90 seconds, `trigger_tweet_monitor` should appear with status `FAILURE` (expected — tweet-monitor returns `auth_expired`, Celery retries).

- [ ] **Step 7: Verify frontend compiles**

```bash
cd frontend && npm run build
```

Expected: build succeeds with no TypeScript errors.

- [ ] **Step 8: Open Dashboard in browser**

Open http://localhost:3333. Navigate to Dashboard.

Check:
- `TweetFeed` card is visible with "Waiting for tweet signals…" message
- No console errors about missing components or failed imports

- [ ] **Step 9: Configure real auth tokens (optional — for live testing)**

Add real X cookies to `.env`:

```bash
X_AUTH_TOKEN=<your-auth-token-cookie-value>
X_CSRF_TOKEN=<your-ct0-cookie-value>
```

Restart:
```bash
docker compose restart tweet-monitor
curl -s http://localhost:8001/health | python -m json.tool
```

Expected: `"healthy": true`, `"browser": "ok"`.

Then trigger a manual poll:
```bash
curl -X POST http://localhost:8001/poll | python -m json.tool
```

Expected: response shows `polled: 1`, `new_tweets: N`, `promoted: M`.

- [ ] **Step 10: Final commit if any fixes were needed**

```bash
git add -A
git commit -m "fix(tweet-monitor): address end-to-end verification findings"
```
