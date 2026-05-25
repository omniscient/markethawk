# Tweet Monitor Microservice Design

**Date**: 2026-05-25  
**Status**: Draft  
**Scope**: Standalone Docker service that monitors Twitter/X accounts for real-time stock callouts and feeds them into MarketHawk's scanner/alert pipeline.

---

## Overview

A dedicated microservice that uses Playwright (headless Chromium) to scrape Twitter/X profiles at regular intervals, classifies tweets as stock callouts, extracts tickers and price levels, and promotes high-confidence signals into the existing ScannerEvent → Alert → Trade pipeline.

The service is isolated from the main backend to keep Chromium dependencies out of Celery worker containers.

## Architecture

```
Celery Beat (every 45s)
  → HTTP POST http://tweet-monitor:8000/poll
    → Playwright scrapes enabled account profiles
    → Diffs against last_seen_tweet_id (Redis)
    → Classifies new tweets (CALLOUT/CELEBRATION/UPDATE/RETWEET/UNKNOWN)
    → Extracts tickers + price levels + direction
    → Writes TweetSignal to PostgreSQL
    → Promotes high-confidence CALLOUTs → ScannerEvent
    → Publishes to Redis channels for frontend
```

### Approach Chosen

**FastAPI microservice + Celery Beat HTTP trigger** (same pattern as `live-scanner`). Celery beat provides scheduler control and Flower visibility. The service owns its own browser lifecycle independently of Celery's task model.

---

## Service Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/poll` | Triggered by Celery beat. Scrapes all enabled accounts, returns summary. |
| `GET` | `/health` | Liveness — browser responsive + DB connected. |
| `GET` | `/status` | Last poll time, tweets processed, browser age, account stats. |
| `POST` | `/accounts` | Create/update monitored accounts. |
| `GET` | `/accounts` | List all monitored accounts with status. |
| `POST` | `/poll/{account_id}` | Manual single-account trigger (debugging). |

---

## Playwright Browser Lifecycle

- **Startup**: Headless Chromium launched at container start.
- **Persistence**: Browser context (with cookies) kept alive between polls for speed.
- **Health check**: Before each scrape, verify DOM loads within 5s on a known URL.
- **Force restart conditions**:
  - Health check fails
  - Session age > 30 minutes
  - Memory usage > 512MB
- **Shutdown**: Graceful close on SIGTERM (Docker stop).

### Poll Flow (per account)

1. Navigate to `https://x.com/{handle}` (or refresh if already on page)
2. Wait for tweet timeline to render (`article[data-testid="tweet"]`)
3. Extract all visible tweets: text, timestamp, tweet ID, media presence
4. Compare tweet IDs against `last_seen_id` (Redis key: `tweet_monitor:last_seen:{account_id}`)
5. For each new tweet: classify → write TweetSignal → conditionally promote
6. Update `last_seen_id` in Redis + `last_poll_at` in DB

### Deduplication

Tweet IDs are globally unique integers (monotonically increasing). Any tweet with ID > last_seen is new. Redis provides fast lookup; the DB column is a fallback if Redis is flushed.

---

## Data Models

### MonitoredAccount

```python
class MonitoredAccount(Base):
    __tablename__ = "monitored_accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    handle: Mapped[str] = mapped_column(String(50))           # "PlayBookTrades"
    display_name: Mapped[str] = mapped_column(String(100))    # "PlayBook Trades"
    platform: Mapped[str] = mapped_column(String(20))         # "x"
    poll_interval_seconds: Mapped[int] = mapped_column(default=45)
    enabled: Mapped[bool] = mapped_column(default=True)
    classification_config: Mapped[dict] = mapped_column(JSONB, default={})
    last_poll_at: Mapped[datetime | None]
    last_tweet_id: Mapped[str | None] = mapped_column(String(30))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())
```

### TweetSignal

```python
class TweetSignal(Base):
    __tablename__ = "tweet_signals"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("monitored_accounts.id"))
    tweet_id: Mapped[str] = mapped_column(String(30), unique=True)
    tweet_url: Mapped[str] = mapped_column(String(200))
    posted_at: Mapped[datetime]
    scraped_at: Mapped[datetime] = mapped_column(server_default=func.now())

    # Content
    full_text: Mapped[str] = mapped_column(Text)
    media_urls: Mapped[list] = mapped_column(JSONB, default=[])

    # Classification
    classification: Mapped[str] = mapped_column(String(20))   # CALLOUT|CELEBRATION|UPDATE|RETWEET|UNKNOWN
    confidence: Mapped[float]                                  # 0.0 - 1.0

    # Extraction
    tickers: Mapped[list] = mapped_column(JSONB, default=[])
    price_levels: Mapped[dict] = mapped_column(JSONB, default={})
    direction: Mapped[str | None] = mapped_column(String(10)) # "long"|"short"|None

    # Pipeline
    promoted: Mapped[bool] = mapped_column(default=False)
    scanner_event_id: Mapped[int | None] = mapped_column(ForeignKey("scanner_events.id"))
    promotion_reason: Mapped[str | None] = mapped_column(String(30))

    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
```

### Indexes

- `tweet_signals(tweet_id)` — unique, dedup lookups
- `tweet_signals(account_id, posted_at DESC)` — timeline queries
- `tweet_signals(classification, confidence)` — filter by type + quality
- `tweet_signals(promoted, classification)` — find un-promoted callouts
- `monitored_accounts(handle, platform)` — unique composite

### ScannerEvent Promotion

When a CALLOUT tweet is promoted, a `ScannerEvent` is created with:

```python
ScannerEvent(
    ticker=primary_ticker,
    event_date=tweet_posted_at.date(),
    scanner_type="social_callout",
    severity="medium",  # escalate to "high" if confidence > 0.9
    indicators={
        "confidence": 0.85,
        "source_account": "PlayBookTrades",
        "direction": "long",
        "price_entry": 185.50,
        "price_target": 195.00,
    },
    criteria_met={
        "has_cashtag": True,
        "has_price_level": True,
        "pre_market": True,
        "above_confidence_threshold": True,
    },
    metadata_={
        "tweet_id": "2057727807904772410",
        "tweet_url": "https://x.com/PlayBookTrades/status/...",
        "full_text": "...",
        "tweet_signal_id": 42,
    }
)
```

After creation, `evaluate_scanner_alerts` Celery task is dispatched (same as all other scanners).

---

## Classification Engine

Rule-based classifier — deterministic, inspectable, no ML dependency.

### Pipeline

```
Input: (tweet_text, media_present, is_retweet, is_reply, posted_at)
  → Step 1: Ticker extraction
  → Step 2: Price level extraction
  → Step 3: Classification + confidence scoring
  → Step 4: Direction detection
Output: (classification, confidence, tickers[], price_levels{}, direction)
```

### Step 1: Ticker Extraction

1. Regex `\$([A-Z]{1,5})` for cashtags
2. Uppercase word matching against `stock_universe_tickers` table
3. Exclusion list (configurable): `$USD`, `$DXY`, `$SPX`, `$VIX`, `$ES`, `$NQ`

### Step 2: Price Level Extraction

Pattern: `(entry|target|stop|above|below|break|trigger|pivot)\s*(?:at|@|:)?\s*\$?(\d+\.?\d*)`

Associates each price with the nearest ticker mention in the text. Output:

```json
{"AAPL": {"entry": 185.50, "target": 195.00, "stop": 180.00}}
```

### Step 3: Classification Rules

Evaluated in order, first match wins:

| Classification | Primary Keywords | Anti-Keywords |
|---|---|---|
| **CALLOUT** | watch, setup, trigger, pivot, entry, break above/below, setting up, looking at, eyes on, stalking, top watch, morning watch | gave you, told you, congrats, nailed it |
| **CELEBRATION** | gave you, told you, congrats, nailed it, runners, profit, cashed, beautiful move | watch, setup, entry |
| **UPDATE** | still holding, added, trimmed, stopped out, took half, scaling | (none) |
| **RETWEET** | (is_retweet=True without original commentary) | — |
| **UNKNOWN** | (no keywords match) | — |

### Confidence Scoring

Base: `0.5`

| Factor | Adjustment |
|--------|-----------|
| Exact keyword match from primary list | +0.2 |
| Contains cashtag ($TICKER) | +0.1 |
| Contains price level | +0.1 |
| Pre-market timing (4:00-9:30 AM ET) | +0.1 |
| Multiple conflicting signals | -0.2 |
| Very short text (<20 chars) | -0.1 |

### Promotion Threshold

Default: `0.7` (configurable per account in `classification_config.promotion_threshold`)

Only tweets classified as `CALLOUT` with `confidence >= threshold` are auto-promoted to ScannerEvent.

### Direction Detection

- **Long**: "calls", "break above", "long", "buy", "bull", "upside"
- **Short**: "puts", "break below", "short", "sell", "bear", "downside"
- **None**: ambiguous or no directional language

---

## Pipeline Integration

### Redis Pub/Sub Channels

| Channel | Payload | Consumer |
|---------|---------|----------|
| `tweet_signals:{ticker}` | TweetSignal summary (on CALLOUT promotion) | Frontend ticker detail page |
| `tweet_signals:all` | All new tweets (any classification) | Frontend tweet feed widget |

### Celery Integration

**New beat task** (added to `celery_app.py`):

```python
"trigger-tweet-monitor": {
    "task": "trigger_tweet_monitor",
    "schedule": 45.0,
    "options": {"expires": 40}  # Prevent pile-up if service is slow
}
```

**Trigger task** (in `tasks.py`):

```python
@celery_app.task(bind=True, max_retries=2)
def trigger_tweet_monitor(self):
    """HTTP trigger for the tweet-monitor microservice."""
    try:
        response = httpx.post(
            "http://tweet-monitor:8000/poll",
            timeout=30.0
        )
        response.raise_for_status()
        return response.json()
    except Exception as exc:
        logger.warning(f"Tweet monitor poll failed: {exc}")
        raise self.retry(exc=exc, countdown=10)
```

### Alert Pipeline Reuse

Promoted signals flow through the existing pipeline:
1. `ScannerEvent` created with `scanner_type="social_callout"`
2. `evaluate_scanner_alerts` task dispatched
3. `AlertRuleService.get_matching_rules()` filters by scanner_type + severity
4. `NotificationDispatcher.dispatch()` sends to configured channels
5. Optional: `execute_auto_trade` if rule has `auto_trade=True`

Users configure alert rules for `social_callout` the same way they configure rules for `pre_market_volume_spike` — no new alert infrastructure needed.

---

## Docker Deployment

### docker-compose.yml Addition

```yaml
tweet-monitor:
  build:
    context: ./services/tweet-monitor
    dockerfile: Dockerfile
  container_name: markethawk-tweet-monitor
  restart: unless-stopped
  ports:
    - "8001:8000"
  environment:
    - DATABASE_URL=${DATABASE_URL}
    - REDIS_URL=${REDIS_URL}
    - TWEET_MONITOR_LOG_LEVEL=INFO
    - SEQ_URL=http://seq:5341
    - PROMOTION_THRESHOLD=0.7
    - BROWSER_MAX_AGE_MINUTES=30
    - BROWSER_MAX_MEMORY_MB=512
  depends_on:
    postgres:
      condition: service_healthy
    redis:
      condition: service_healthy
  networks:
    - stockscanner-network
  deploy:
    resources:
      limits:
        memory: 1G
```

### Dockerfile

```dockerfile
FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 \
    libxkbcommon0 libxcomposite1 libxdamage1 libxrandr2 libgbm1 \
    libpango-1.0-0 libcairo2 libasound2 libxshmfence1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && playwright install chromium --with-deps

COPY . .
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### File Structure

```
services/tweet-monitor/
├── Dockerfile
├── requirements.txt          # fastapi, uvicorn, playwright, sqlalchemy, redis, httpx, seqlog
├── app/
│   ├── __init__.py
│   ├── main.py               # FastAPI app + lifespan (browser startup/shutdown)
│   ├── config.py             # Pydantic Settings (env vars)
│   ├── browser.py            # BrowserManager: launch, health-check, restart
│   ├── scraper.py            # XProfileScraper: navigate, extract tweets
│   ├── classifier.py         # TweetClassifier: classify, score confidence
│   ├── extractor.py          # TickerExtractor + PriceLevelExtractor
│   ├── pipeline.py           # SignalPipeline: write DB, promote, publish Redis
│   ├── models.py             # SQLAlchemy: TweetSignal, MonitoredAccount
│   ├── schemas.py            # Pydantic request/response models
│   └── health.py             # HealthChecker: browser + DB + Redis
└── tests/
    ├── test_classifier.py    # Unit tests with sample tweet texts
    ├── test_extractor.py     # Ticker + price extraction edge cases
    └── test_scraper.py       # Mock DOM extraction tests
```

---

## Error Handling & Resilience

| Failure Mode | Response |
|---|---|
| X rate-limits/blocks | Exponential backoff per account (2x delay, max 10 min). Alert via Seq. |
| Browser crash | Auto-restart, skip current poll cycle, resume next. |
| DB unreachable | Buffer new tweets in Redis list (`tweet_monitor:buffer`), flush on reconnection. |
| Celery beat stops | Optional internal fallback timer (disabled by default, enable via env var). |
| X DOM changes | Scraper uses data-testid selectors (stable). If extraction returns 0 tweets 3x in a row, alert via Seq. |
| Account suspended/deleted | Mark account as `enabled=False`, alert via Seq. |

---

## Observability

- **Seq logging**: Structured JSON with fields: `account_handle`, `tweet_id`, `classification`, `confidence`, `promoted`, `scrape_duration_ms`, `tweets_found`, `tweets_new`
- **Health endpoint**: Consumed by Docker healthcheck + external monitoring
- **Status endpoint**: Exposes operational metrics for the frontend Settings page
- **Flower**: Celery beat trigger task visible in Flower with success/failure history

---

## Configuration

All configurable via environment variables (with sane defaults):

| Variable | Default | Purpose |
|----------|---------|---------|
| `PROMOTION_THRESHOLD` | `0.7` | Min confidence for CALLOUT→ScannerEvent |
| `BROWSER_MAX_AGE_MINUTES` | `30` | Force browser restart interval |
| `BROWSER_MAX_MEMORY_MB` | `512` | Memory limit before restart |
| `POLL_TIMEOUT_SECONDS` | `25` | Max time for a single poll cycle |
| `BACKOFF_INITIAL_SECONDS` | `90` | First backoff delay on rate limit |
| `BACKOFF_MAX_SECONDS` | `600` | Maximum backoff ceiling |
| `FALLBACK_TIMER_ENABLED` | `false` | Internal scheduler if beat goes down |
| `FALLBACK_TIMER_SECONDS` | `60` | Internal poll interval |

---

## Multi-Account Support

The system is designed for N accounts from day one:

- Each account has independent `poll_interval_seconds` and `classification_config`
- The `/poll` endpoint iterates all enabled accounts sequentially (or parallel via asyncio if needed later)
- Per-account `last_seen_id` prevents cross-contamination
- The `classification_config` JSONB field allows per-account keyword overrides (some accounts may use different terminology)

### Initial Seed

```sql
INSERT INTO monitored_accounts (handle, display_name, platform, poll_interval_seconds, enabled)
VALUES ('PlayBookTrades', 'PlayBook Trades', 'x', 45, true);
```

---

## Future Considerations (Not In Scope)

- LLM-based classification (upgrade path from rules when patterns get complex)
- Discord/StockTwits scraping (same architecture, different scraper module)
- Backtesting engine (replay historical TweetSignals against price data)
- Frontend tweet feed widget (separate frontend ticket)
- Auto-trade confidence weighting (higher confidence → larger position)
