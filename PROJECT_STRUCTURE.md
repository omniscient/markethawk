# Project Structure

```
MarketHawk/
├── backend/
│   ├── live_scanner/                   # Live scanner — standalone asyncio process (separate Docker service)
│   │   ├── __init__.py
│   │   ├── main.py                     # Entry point: connects to IB Gateway, runs sync + process loops
│   │   ├── bar_aggregator.py           # BarAggregator: 5 s bars → 1 m MinuteBar; session/volume tracking
│   │   ├── conditions.py               # Alert conditions: live_volume_spike, live_price_move
│   │   └── publisher.py                # LivePublisher: Redis publish (quote/tick/minute_bar/alert) + DB writes
│   ├── alembic/                        # Alembic migration framework
│   │   ├── versions/                   # Migration scripts (one file per schema change)
│   │   └── env.py                      # Alembic runtime config; imports models for autogenerate
│   ├── app/
│   │   ├── exceptions.py               # Domain exception hierarchy: MarketHawkError base + ScanError, DataFetchError, ProviderError subclasses; is_retryable flag drives Celery retry logic
│   │   ├── core/
│   │   │   ├── config.py               # Settings class; all env vars with typed defaults
│   │   │   ├── database.py             # Async SQLAlchemy engine and session factory
│   │   │   ├── celery_app.py           # Celery instance and beat schedule definitions
│   │   │   └── error_tracking.py       # ErrorTracker protocol; Seq + stdout implementations
│   │   ├── models/
│   │   │   ├── active_watchlist.py     # ActiveWatchlist — manually curated live-observation list (soft limit 50)
│   │   │   ├── scanner_run.py          # ScannerRun — one row per scan execution; failed_tickers JSONB for per-ticker domain failures
│   │   │   ├── scanner_event.py        # ScannerEvent — tickers that passed criteria; carries signal_quality_score (Float, indexed DESC NULLS LAST)
│   │   │   ├── scanner_config.py       # ScannerConfig — saved parameter sets
│   │   │   ├── stock_universe.py       # StockUniverse — named ticker groups
│   │   │   ├── stock_universe_ticker.py # StockUniverseTicker — universe membership
│   │   │   ├── monitored_stock.py      # MonitoredStock — per-ticker tracking state
│   │   │   ├── stock_aggregate.py      # StockAggregate — cached OHLCV bars
│   │   │   ├── stock_metric.py         # StockMetric — computed daily metrics
│   │   │   ├── stock_split.py          # StockSplit — split history
│   │   │   ├── ticker_reference.py     # TickerReference — Polygon metadata cache
│   │   │   ├── news_article.py         # NewsArticle — cached news for catalyst analysis
│   │   │   ├── news_preference.py      # NewsPreference — user news preferences
│   │   │   ├── futures_contract.py     # FuturesContract — contract specs
│   │   │   ├── futures_aggregate.py    # FuturesAggregate — futures OHLCV bars
│   │   │   ├── futures_rollover.py     # FuturesRollover — roll dates
│   │   │   ├── market_holiday.py       # MarketHoliday — NYSE/NASDAQ holiday calendar
│   │   │   ├── trade.py                # Trade — journal entries
│   │   │   ├── universe_quality_report.py # UniverseQualityReport — data quality audits
│   │   │   ├── signal_analysis_run.py  # SignalAnalysisRun — Phase 2b analysis execution anchor; stores correlation_matrix + feature_weights as JSONB
│   │   │   ├── signal_cluster.py       # SignalCluster — K-means cluster archetype per analysis run; centroid + return_profile
│   │   │   ├── signal_review.py        # SignalReview — user verdict (confirmed/rejected/enhanced/uncertain) on a ScannerEvent; latest_review @property exposed via ScannerEvent
│   │   │   ├── monitored_account.py    # MonitoredAccount — X accounts tracked by tweet-monitor; handle, platform, poll_interval_seconds, last_tweet_id, classification_config JSONB
│   │   │   ├── tweet_signal.py         # TweetSignal — one row per scraped tweet; classification, confidence, tickers/price_levels JSONB, promoted flag, FK → scanner_events
│   │   │   └── __init__.py             # Re-exports all models (required for Alembic autogenerate)
│   │   ├── routers/
│   │   │   ├── scanner.py              # /api/scanner/* — run, results (eager-loads reviews), history, signal-quality-distribution; review endpoints: POST /events/{uuid}/review, GET /events/reviews, GET /reviews/stats
│   │   │   ├── universe.py             # /api/universe/* — CRUD for universes
│   │   │   ├── stocks.py               # /api/stocks/* — historical data, ticker search
│   │   │   ├── news.py                 # /api/news/* — news articles and preferences
│   │   │   ├── live_data.py            # /api/live/ws/{ticker}/{resolution} — per-symbol WS; /api/live/ws/watchlist — watchlist-wide WS
│   │   │   ├── futures.py              # /api/futures/* — history, contracts, rollovers, download (catalog refresh)
│   │   │   ├── journal.py              # /api/journal/* — trade journal CRUD
│   │   │   ├── watchlist.py            # /api/watchlist/* — active watchlist CRUD
│   │   │   ├── health.py               # GET /health — liveness probe
│   │   │   ├── outcomes.py             # /api/outcomes/* — scorecard, signals, backfill; Phase 2b: analyze, correlations, analysis/latest
│   │   │   ├── system.py               # /api/system/* — configuration and status
│   │   │   ├── tweets.py               # GET /api/tweets/recent — TweetSignals; WS /api/tweets/feed — live Redis pub/sub stream
│   │   │   └── __init__.py
│   │   ├── schemas/
│   │   │   ├── active_watchlist.py     # ActiveWatchlistAdd / ActiveWatchlistUpdate / ActiveWatchlistItem
│   │   │   └── stock.py                # Pydantic request/response models
│   │   ├── services/
│   │   │   ├── stock_data.py           # OHLCV fetch, gap calculation, session flags; is_futures_ticker(); get_historical_enriched() (coercion + indicators + guardrails)
│   │   │   ├── universe_stats.py       # UniverseStatsService.compute() — universe aggregate stats (ticker count, bar count, date range, timespans)
│   │   │   ├── scan_orchestrator.py    # Scanner registry (ScannerDescriptor, _REGISTRY, register, get_all, run); single dispatch entry point
│   │   │   ├── pre_market_scan.py      # Self-registers "pre_market_volume_spike" in orchestrator
│   │   │   ├── oversold_bounce_scan.py # Self-registers "oversold_bounce" in orchestrator
│   │   │   ├── scanner.py              # ScannerService; calculate_day_metrics; _save_event delegates to alert_service.save_event
│   │   │   ├── stock_data.py           # OHLCV fetch, gap calculation, session flags
│   │   │   ├── discovery_service.py    # Bulk ticker sync from Polygon; rate-limit-aware paging
│   │   │   ├── catalyst_parser.py      # Batch 72-hour news analysis; returns latest_article_utc for recency enrichment
│   │   │   ├── futures_data.py         # 2-method public interface: get_continuous_series, sync_contracts; private write-path helpers
│   │   │   ├── chart_indicators.py     # Technical indicators (VWAP, MAs) for chart endpoints
│   │   │   ├── journal_service.py      # Trade journal CRUD
│   │   │   ├── websocket_manager.py    # WebSocket connection pool and broadcast
│   │   │   ├── normalization.py        # Price/volume normalization, split adjustments
│   │   │   ├── data_quality.py         # Quality checks; UniverseQualityReport generation
│   │   │   ├── stats.py                # Aggregate statistics for dashboard metrics
│   │   │   ├── event_helpers.py        # ScannerEvent construction and querying utilities
│   │   │   ├── statistical_discovery.py # Phase 2b: pure-Python statistical analysis (correlation, SHAP, K-means); no DB dependencies
│   │   │   ├── signal_ranker.py        # Phase 2c: compute_signal_quality_score() + load_ranker_config(); weights from SystemConfig
│   │   │   ├── universe_orchestrator.py # Celery dispatch + Redis state for universe ops: discover_and_refresh, sync_missing_aggregates, sync_aggregates, queue_quality_analysis, queue_normalization
│   │   │   ├── universe_export.py      # ZIP streaming for universe aggregate exports; no Celery/Redis; duck-typed request
│   │   │   └── __init__.py
│   │   ├── providers/
│   │   │   ├── base.py                 # BaseDataProvider sync abstract interface: get_bars, get_snapshots, get_ticker_details
│   │   │   ├── massive.py              # Polygon.io provider: get_bars (paginated), get_snapshots (normalised), bulk sync/backfill
│   │   │   ├── ibkr.py                 # ib_insync Interactive Brokers provider (futures-only; get_bars/get_snapshots are no-op stubs)
│   │   │   └── __init__.py
│   │   ├── main.py                     # FastAPI app factory; global error handler; router mounts
│   │   └── tasks/                      # Celery task package (sync.py, scanning.py, trading.py, quality.py)
│   ├── tests/
│   │   ├── conftest.py                 # Session-scoped engine + function-scoped db fixture (SAVEPOINT isolation)
│   │   ├── api/                        # Router integration tests (DI override via tests/api/conftest.py)
│   │   │   ├── conftest.py             # Autouse fixture: app.dependency_overrides[get_db] = test session
│   │   │   ├── test_alerts.py          # Alert rule CRUD + delivery log endpoints
│   │   │   ├── test_auto_trading.py    # Strategy CRUD, order lifecycle, stats, config
│   │   │   ├── test_health.py          # /api/health liveness check
│   │   │   ├── test_journal.py         # Journal trade and entry endpoints
│   │   │   ├── test_outcomes.py        # Outcome scorecard and snapshot endpoints
│   │   │   ├── test_scanner.py         # Scanner run, results, history endpoints
│   │   │   ├── test_stocks.py          # Historical OHLCV endpoint
│   │   │   ├── test_universe.py        # Universe CRUD endpoints
│   │   │   ├── test_watchlist.py       # Active watchlist CRUD (soft-limit enforcement)
│   │   │   └── test_live_data.py       # Skipped (requires live IBKR)
│   │   └── services/                   # Service-layer unit / integration tests
│   │       ├── test_alert_service.py   # AlertRuleService: matching, cooldown
│   │       ├── test_auto_trade_service.py  # AutoTradeExecutor: position math, guards, paper/live paths
│   │       ├── test_chart_indicators.py    # ChartIndicatorsService: pure DataFrame transforms
│   │       ├── test_data_quality_helpers.py # _score_to_grade, _grade_color, weekday counting
│   │       ├── test_discovery_service.py   # DiscoveryService with mocked Polygon client
│   │       ├── test_journal_service.py     # JournalService CRUD operations
│   │       ├── test_normalization_helpers.py # _parse_date, _to_date_str round-trips
│   │       ├── test_outcome_service.py     # OutcomeService: snapshot creation and capture
│   │       └── test_split_adjustment.py    # SplitAdjustmentService: price-factor math
│   ├── alembic.ini                     # Alembic configuration (points to DATABASE_URL)
│   ├── requirements.txt                # Python dependencies
│   └── Dockerfile                      # Backend container image
├── frontend/
│   ├── src/
│   │   ├── api/
│   │   │   ├── client.ts               # Axios instance with error interceptor
│   │   │   ├── scanner.ts              # Scanner API calls
│   │   │   ├── stocks.ts               # Stocks and universe API calls
│   │   │   ├── news.ts                 # News API calls
│   │   │   ├── system.ts               # System/health API calls
│   │   │   ├── watchlist.ts            # Active watchlist CRUD + React Query hooks
│   │   │   └── analysis.ts             # Phase 2b: fetchCorrelations, fetchLatestAnalysis, triggerAnalysis
│   │   ├── components/
│   │   │   ├── UniverseFormModal.tsx   # Create/edit universe modal
│   │   │   ├── UniverseDetailsModal.tsx # Universe detail view modal
│   │   │   ├── ScannerResults.tsx      # Scanner results table/list
│   │   │   └── ...                     # Other reusable components
│   │   ├── pages/
│   │   │   ├── Dashboard.tsx           # System metrics, recent alerts, market status
│   │   │   ├── Scanner.tsx             # Run scans, view results, configure criteria
│   │   │   ├── PreMarketMovers.tsx     # Real-time pre-market volume leaders
│   │   │   ├── Universes.tsx           # Create and manage stock universes
│   │   │   ├── EdgeExplorer.tsx        # Historical scanner hit rates and outcome distributions
│   │   │   ├── ActiveWatchlist.tsx     # Live-monitored symbols; real-time price/session/alerts via WS
│   │   │   ├── Journal.tsx             # Trade journal entry and review
│   │   │   ├── Alerts.tsx              # Alert configuration and history
│   │   │   ├── StockDetailPage.tsx     # Per-ticker chart, metrics, and news
│   │   │   └── Settings.tsx            # System configuration
│   │   ├── hooks/                      # Custom React hooks
│   │   ├── App.tsx                     # Router and layout wrapper
│   │   └── main.tsx                    # React entry point
│   ├── package.json
│   ├── tsconfig.json
│   ├── vite.config.ts
│   └── Dockerfile                      # Frontend container image
├── .agent/
│   └── skills/
│       ├── backend_tests/SKILL.md      # How to run pytest
│       ├── db_migrations/SKILL.md      # How to create and apply Alembic migrations
│       ├── error_tracking/SKILL.md     # How to debug errors using Seq ErrorIds
│       ├── frontend_lint/SKILL.md      # How to run ESLint
│       ├── massive_api_research/       # Polygon.io query tool
│       │   ├── SKILL.md
│       │   └── scripts/query_api.py    # CLI for ad-hoc Polygon API calls
│       └── bash/SKILL.md               # Shell patterns for this environment
├── database-schema.sql                 # Legacy SQL reference schema — do not use directly; use Alembic
├── docker-compose.yml                  # Full stack orchestration (all services)
├── .env.example                        # Environment variable template — copy to .env
├── README.md                           # Project overview and quick start
├── ARCHITECTURE.md                     # System design, data flow, module map
├── DEVELOPMENT.md                      # Local dev setup, Docker commands, debugging
├── ENV_VARIABLES.md                    # Complete environment variable reference
├── POLYGON_RATE_LIMITS.md              # Polygon.io API reference and rate limit guidance
├── PROJECT_STRUCTURE.md                # This file
└── CLAUDE.md                           # Claude Code instructions for this repository
```

## Notes for Navigation

- **Start a scan manually**: `POST http://localhost:8000/api/scanner/run` or use the Scanner page in the UI.
- **Add a new model**: create it in `backend/app/models/`, add the import to `backend/app/models/__init__.py`, then run `alembic revision --autogenerate`.
- **Add a new API endpoint**: create or extend a router in `backend/app/routers/`, then register it in `backend/app/main.py`.
- **Add a new frontend page**: create the component in `frontend/src/pages/`, add the route in `frontend/src/App.tsx`.
- **All migrations** must be created after any SQLAlchemy model change. See `DEVELOPMENT.md` for the workflow.
- **`database-schema.sql`** is a legacy reference file. The canonical schema is defined by the Alembic migration history — do not apply the SQL file directly.
