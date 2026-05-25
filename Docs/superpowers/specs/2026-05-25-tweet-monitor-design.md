# Tweet Monitor Microservice Design

**Date:** 2026-05-25

## Overview

MarketHawk currently surfaces stock signals from pre-market volume spikes, liquidity hunts, and technical scans. A significant class of high-conviction, time-sensitive signals originates on social media — specifically from credentialed traders who announce long/short setups in real time on X (Twitter). This design adds a standalone `tweet-monitor` Docker microservice that polls X profile timelines, classifies tweets as stock callouts, extracts ticker symbols and price levels, and promotes high-confidence callouts into the existing `ScannerEvent` / alert pipeline. The initial account is `@PlayBookTrades`.

## Requirements

### Functional
- Poll enabled X accounts every 45 seconds via a Celery beat task
- Scrape profile timelines using Playwright Chromium with cookie-based authentication
- Classify each new tweet into: `CALLOUT`, `CELEBRATION`, `UPDATE`, `RETWEET`, or `UNKNOWN`
- Assign a confidence score (0.0–1.0) to each classification using rule-based scoring
- Extract ticker symbols and price levels from tweet text via regex
- Persist every new tweet as a `TweetSignal` record (regardless of classification)
- Promote any `CALLOUT` tweet with confidence ≥ 0.7 to one `ScannerEvent` per ticker mentioned
- Store tweet context in `ScannerEvent.metadata_` (tweet_id, account handle, all_tickers, per-ticker confidence)
- Publish all incoming tweet signals to a Redis channel for live frontend delivery
- Expose `/health` endpoint that reports status of browser, DB, and Redis; detect `auth_expired` as a distinct failure mode when X returns 401/redirect
- Auto-restart the Playwright browser on health-check failure or after 30-minute max age
- Emit structured logs to Seq in CLEF format

### Non-Functional
- Memory limit: 1 GB (Playwright Chromium is the dominant consumer)
- Recovery: browser crashes must not crash the service process; restart and resume polling
- Redis buffering: if DB write fails, buffer to Redis and retry with exponential backoff
- Multi-account: architecture supports multiple monitored accounts from day one; initial config enables only `@PlayBookTrades`

### Out of Scope
- X API v2 integration (Playwright scraping is the chosen mechanism)
- Dedicated frontend page for tweet signals (covered by Scanner table + Dashboard widget)
- Trading automation triggered by tweet signals
- Sentiment scoring beyond classification confidence

## Architecture

### Service Placement

The tweet-monitor follows the `live-scanner` pattern exactly: it lives under `backend/tweet_monitor/`, is built from the `./backend` Docker context, and imports ORM models directly from `app.models`. The main backend owns `TweetSignal` and `MonitoredAccount` model definitions and their Alembic migrations.

```
backend/
├── app/
│   ├── models/
│   │   ├── tweet_signal.py         # NEW — TweetSignal ORM model
│   │   └── monitored_account.py    # NEW — MonitoredAccount ORM model
│   └── models/__init__.py          # Updated — import + export both new models
└── tweet_monitor/
    ├── Dockerfile                  # Python 3.11 + Playwright Chromium
    ├── requirements.txt            # fastapi, uvicorn, playwright, sqlalchemy, redis, httpx, seqlog
    ├── main.py                     # FastAPI app + lifespan (browser startup/shutdown)
    ├── config.py                   # Pydantic Settings from env vars
    ├── browser.py                  # BrowserManager: launch, health-check, restart
    ├── scraper.py                  # XProfileScraper: navigate X profile, extract tweets from DOM
    ├── classifier.py               # Rule-based classifier + confidence scoring
    ├── extractor.py                # Ticker + price level regex extraction
    ├── pipeline.py                 # DB writes, ScannerEvent promotion, Redis pub/sub
    ├── health.py                   # /health endpoint implementation
    └── tests/
        ├── test_classifier.py
        └── test_extractor.py
```

### Data Flow

```
Celery Beat (every 45s)
  → task: trigger_tweet_monitor (backend/app/tasks.py)
    → HTTP POST tweet-monitor:8001/poll
      → BrowserManager.get_page()          # Playwright Chromium, cookies injected
        → XProfileScraper.fetch_tweets()   # Navigate profile, extract DOM
          for each new tweet:
            → classifier.classify()        # → {classification, confidence}
            → extractor.extract_tickers()  # → [{ticker, confidence}]
            → TweetSignal written to DB
            → if classification == CALLOUT:
                for each ticker where confidence >= 0.7:
                  → ScannerEvent created (scanner_type="social_callout")
                  → metadata_ = {tweet_id, account, all_tickers, confidence}
                  → alert pipeline notified
            → Redis PUBLISH tweet_signals:{account}
```

### Authentication

Cookie-based X authentication. Two env vars are injected into the Playwright browser context at startup and after every browser restart:

| Env Var | Purpose |
|---------|---------|
| `X_AUTH_TOKEN` | X session auth token cookie |
| `X_CSRF_TOKEN` | X CSRF token cookie |

These are documented in `.env.example` and `ENV_VARIABLES.md`. The BrowserManager injects them as cookies before the first navigation. The `/health` endpoint detects an auth-expired condition when X returns an HTTP 401 or a redirect to the login page, and reports `{"auth_expired": true}` as a distinct health-check field so operators are alerted before scraping silently stops.

Cookie rotation is manual. Cookies expire approximately every 30 days. The operator replaces env vars and restarts the container.

### Data Models

**`monitored_accounts`** (new table):

| Column | Type | Notes |
|--------|------|-------|
| `id` | UUID PK | |
| `handle` | String | e.g. `PlayBookTrades` (no @) |
| `platform` | String | `"x"` (extensible) |
| `poll_interval_seconds` | Integer | default 45 |
| `enabled` | Boolean | default true |
| `classification_config` | JSONB | per-account classifier overrides (optional) |
| `created_at` | DateTime | |

**`tweet_signals`** (new table):

| Column | Type | Notes |
|--------|------|-------|
| `id` | UUID PK | |
| `tweet_id` | String UNIQUE | X's native tweet ID |
| `account_id` | UUID FK → monitored_accounts | |
| `full_text` | Text | raw tweet content |
| `classification` | String | `CALLOUT/CELEBRATION/UPDATE/RETWEET/UNKNOWN` |
| `confidence` | Float | 0.0–1.0 |
| `tickers` | JSONB | `[{ticker, confidence}]` |
| `price_levels` | JSONB | extracted price targets / stop levels |
| `direction` | String | `long/short/null` |
| `promoted` | Boolean | true if any ScannerEvent was created |
| `scanner_event_id` | UUID FK → scanner_events | nullable; first promoted event |
| `scraped_at` | DateTime | |
| `tweet_created_at` | DateTime | timestamp from X DOM |

Indexes: `tweet_id` (unique), `account_id + scraped_at DESC`, `classification + confidence`.

**`ScannerEvent` changes** (no schema change):
- `scanner_type = "social_callout"` identifies tweet-originated events
- `metadata_` JSONB carries `{tweet_id, account_handle, all_tickers, tweet_text_preview, confidence}`

### Frontend Integration

**Scanner page** (`frontend/src/pages/Scanner.tsx`):
- `social_callout` events appear in `ScannerResults` automatically (scanner_type badge renders as "social callout")
- A "Source" sub-row or tooltip is added to the event row for `social_callout` events, showing `@handle` and a link to the tweet (both from `metadata_`)

**Dashboard** (`frontend/src/pages/Dashboard.tsx`):
- New `TweetFeed` component, modeled on the existing `NewsFeed` component
- Opens a WebSocket or subscribes to the `tweet_signals` Redis pub/sub channel via the FastAPI backend
- Displays the last N raw `TweetSignal` records with: account handle, classification badge, confidence, extracted tickers, truncated tweet text
- Updates live as new signals arrive; no page reload needed

**Backend addition**: new `GET /api/tweets/feed` WebSocket endpoint (analogous to `/api/live/ws/watchlist`) that subscribes to Redis `tweet_signals:*` and forwards events to connected frontend clients.

### Docker Compose Changes

```yaml
tweet-monitor:
  build:
    context: ./backend
    dockerfile: tweet_monitor/Dockerfile
  container_name: tweet-monitor
  ports:
    - "8001:8001"
  mem_limit: 1g
  environment:
    - DATABASE_URL=${DATABASE_URL}
    - REDIS_URL=${REDIS_URL}
    - X_AUTH_TOKEN=${X_AUTH_TOKEN}
    - X_CSRF_TOKEN=${X_CSRF_TOKEN}
    - SEQ_URL=${SEQ_URL}
  depends_on:
    - postgres
    - redis
  restart: unless-stopped
  networks:
    - stockscanner-network
```

### Celery Integration

`backend/app/core/celery_app.py` gains one new beat entry:

```python
'trigger-tweet-monitor': {
    'task': 'app.tasks.trigger_tweet_monitor',
    'schedule': 45.0,   # seconds
    'options': {'expires': 40},  # drop if worker is already busy
},
```

`backend/app/tasks.py` gains:

```python
@celery_app.task(bind=True, max_retries=3)
def trigger_tweet_monitor(self):
    import httpx
    try:
        httpx.post("http://tweet-monitor:8001/poll", timeout=35)
    except Exception as exc:
        raise self.retry(exc=exc, countdown=10)
```

## Browser Lifecycle

The `BrowserManager` maintains one persistent Chromium browser process. It is replaced when:
1. `/health` is called and the browser is unresponsive (ping timeout > 5s)
2. Browser age exceeds 30 minutes (prevents memory leaks)
3. Memory usage exceeds 512 MB (measured via `/proc/self/status` inside the container)

Restart is sequential: close old browser → launch new browser → inject cookies → verify X navigation succeeds. The FastAPI lifespan hook starts the initial browser and shuts it down cleanly on container stop.

## Classifier Design

Rule-based scoring (no ML model required for v1):

| Signal | CALLOUT indicator | Score contribution |
|--------|------------------|--------------------|
| Contains cashtag (`$AAPL`) | yes | +0.4 |
| Contains direction word (`long`, `short`, `buying`, `selling`) | yes | +0.2 |
| Contains price level (`target`, `stop`, `entry`, number near ticker) | yes | +0.15 |
| Retweet prefix (`RT @`) | yes | forces RETWEET, confidence = 0 |
| Celebratory language (`up`, `nice`, `profit`) without forward direction | yes | forces CELEBRATION |
| Contains ticker + direction + price level | all three | confidence ≥ 0.75 |

Threshold for ScannerEvent promotion: confidence ≥ 0.7.

Per-account `classification_config` JSONB allows weight overrides without code changes.

## Alternatives Considered

### B: Playwright inside Celery worker
Run a Playwright browser as part of the Celery worker task. No separate service, no HTTP hop.

**Rejected:** Playwright Chromium consumes ~300–600 MB of RAM per browser instance. Embedding it in the Celery worker would bloat the worker pod and could crash the entire worker process on browser failure, blocking all other tasks. The 45-second poll cadence also means the browser would need to be started and stopped on every task invocation (too slow) or kept alive across tasks via a global singleton (brittle in Celery's forking model).

### C: Self-polling microservice (no Celery trigger)
The tweet-monitor service polls on its own internal timer without any Celery beat trigger. Simpler control flow, no HTTP dependency.

**Rejected:** The acceptance criteria explicitly require poll visibility in Flower. Celery beat is the established scheduling mechanism in this codebase and gives operators a single pane of glass for all background tasks. The HTTP POST is a single line and the failure mode (tweet-monitor down → task retries) is well-defined.

## Open Questions

- **Ticker disambiguation**: If a tweet mentions `$AI` (C3.ai), does the extractor check against `TickerReference` to validate it's a real ticker? The regex can generate false positives. A TickerReference lookup is recommended but not strictly required for v1.
- **Historical backfill**: On first startup, should the scraper fetch the last N tweets to populate `tweet_signals` retroactively, or only process tweets seen after first poll? Leave as configurable; default: no backfill.
- **Rate limiting**: X does not publish its scraping rate limits. The 45-second poll interval is a reasonable starting point; the `classification_config` allows per-account interval adjustment if blocks are observed.

## Assumptions

- **X profile pages remain publicly scrapeable with a logged-in session.** If X implements additional bot-detection (CAPTCHAs, fingerprinting) that Playwright cannot bypass, this service will require a different approach (e.g., Nitter mirror or X API v2 elevated access).
- **Cookie rotation is a manual operator task**, not an automated flow. The operator accepts this burden for v1.
- **`@PlayBookTrades` posts primarily in English** and the rule-based classifier is designed for English-language tweet patterns.
- **The tweet DOM structure on X is stable enough for Playwright CSS selectors.** X has historically changed its DOM; the scraper should use `data-testid` attributes (more stable than class names) and log a warning when the expected elements are not found rather than crashing.
- **Signal quality scoring (`signal_ranker.py`) is not applied to `social_callout` events.** These events carry an inherent confidence score from the classifier; layering the existing signal ranker would be confusing. The `signal_quality_score` column on `ScannerEvent` can default to the classifier confidence × 100 for UI consistency.
