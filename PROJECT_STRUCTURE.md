# Project Structure

```
MarketHawk/
├── backend/
│   ├── live_scanner/
│   │   ├── __init__.py
│   │   ├── main.py
│   │   ├── bar_aggregator.py
│   │   ├── conditions.py
│   │   └── publisher.py
│   ├── alembic/
│   │   ├── versions/
│   │   └── env.py
│   ├── app/
│   │   ├── exceptions.py
│   │   ├── core/
│   │   │   ├── config.py
│   │   │   ├── database.py
│   │   │   ├── celery_app.py
│   │   │   ├── error_tracking.py
│   │   │   ├── cache.py
│   │   │   └── tracing.py
│   │   ├── models/
│   │   │   ├── active_watchlist.py
│   │   │   ├── scanner_run.py
│   │   │   ├── scanner_event.py
│   │   │   ├── scanner_config.py
│   │   │   ├── stock_universe.py
│   │   │   ├── stock_universe_ticker.py # StockUniverseTicker — universe membership
│   │   │   ├── monitored_stock.py
│   │   │   ├── stock_aggregate.py
│   │   │   ├── stock_metric.py
│   │   │   ├── stock_split.py
│   │   │   ├── ticker_reference.py
│   │   │   ├── news_article.py
│   │   │   ├── news_preference.py
│   │   │   ├── futures_contract.py
│   │   │   ├── futures_aggregate.py
│   │   │   ├── futures_rollover.py
│   │   │   ├── market_holiday.py
│   │   │   ├── trade.py
│   │   │   ├── universe_quality_report.py # UniverseQualityReport — data quality audits
│   │   │   ├── signal_analysis_run.py
│   │   │   ├── signal_cluster.py
│   │   │   ├── signal_review.py
│   │   │   ├── monitored_account.py
│   │   │   ├── tweet_signal.py
│   │   │   ├── user.py
│   │   │   └── __init__.py
│   │   ├── routers/
│   │   │   ├── auth.py
│   │   │   ├── scanner.py
│   │   │   ├── universe.py
│   │   │   ├── stocks.py
│   │   │   ├── news.py
│   │   │   ├── live_data.py
│   │   │   ├── futures.py
│   │   │   ├── journal.py
│   │   │   ├── watchlist.py
│   │   │   ├── health.py
│   │   │   ├── outcomes.py
│   │   │   ├── system.py
│   │   │   ├── tweets.py
│   │   │   └── __init__.py
│   │   ├── schemas/
│   │   │   ├── active_watchlist.py
│   │   │   └── stock.py
│   │   ├── services/
│   │   │   ├── stock_data.py
│   │   │   ├── universe_stats.py
│   │   │   ├── scan_orchestrator.py
│   │   │   ├── scanner_query_service.py # ScannerQueryService: get_scan_status_block, get_signal_quality_distribution, get_review_stats
│   │   │   ├── system_service.py
│   │   │   ├── auto_trade_service.py
│   │   │   ├── pre_market_scan.py
│   │   │   ├── oversold_bounce_scan.py # Self-registers "oversold_bounce" in orchestrator
│   │   │   ├── pocket_pivot.py
│   │   │   ├── scanner.py
│   │   │   ├── discovery_service.py
│   │   │   ├── catalyst_parser.py
│   │   │   ├── futures_data.py
│   │   │   ├── chart_indicators.py
│   │   │   ├── journal_service.py
│   │   │   ├── websocket_manager.py
│   │   │   ├── normalization.py
│   │   │   ├── data_quality.py
│   │   │   ├── stats.py
│   │   │   ├── event_helpers.py
│   │   │   ├── statistical_discovery.py # Phase 2b: pure-Python statistical analysis (correlation, SHAP, K-means); no DB dependencies
│   │   │   ├── signal_ranker.py
│   │   │   ├── universe_orchestrator.py # Celery dispatch + Redis state for universe ops: discover_and_refresh, sync_missing_aggregates, sync_aggregates, queue_quality_analysis, queue_normalization
│   │   │   ├── universe_export.py
│   │   │   └── __init__.py
│   │   ├── providers/
│   │   │   ├── base.py
│   │   │   ├── massive.py
│   │   │   ├── ibkr.py
│   │   │   └── __init__.py
│   │   ├── main.py
│   │   └── tasks/
│   ├── tests/
│   │   ├── conftest.py
│   │   ├── api/
│   │   │   ├── conftest.py
│   │   │   ├── test_alerts.py
│   │   │   ├── test_auto_trading.py
│   │   │   ├── test_health.py
│   │   │   ├── test_journal.py
│   │   │   ├── test_outcomes.py
│   │   │   ├── test_scanner.py
│   │   │   ├── test_stocks.py
│   │   │   ├── test_universe.py
│   │   │   ├── test_watchlist.py
│   │   │   └── test_live_data.py
│   │   └── services/
│   │       ├── test_alert_service.py
│   │       ├── test_auto_trade_service.py
│   │       ├── test_chart_indicators.py
│   │       ├── test_data_quality_helpers.py # _score_to_grade, _grade_color, weekday counting
│   │       ├── test_discovery_service.py
│   │       ├── test_journal_service.py
│   │       ├── test_normalization_helpers.py # _parse_date, _to_date_str round-trips
│   │       ├── test_outcome_service.py
│   │       └── test_split_adjustment.py
│   ├── alembic.ini
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/
│   ├── src/
│   │   ├── api/
│   │   │   ├── client.ts
│   │   │   ├── scanner.ts
│   │   │   ├── stocks.ts
│   │   │   ├── news.ts
│   │   │   ├── system.ts
│   │   │   ├── watchlist.ts
│   │   │   └── analysis.ts
│   │   ├── components/
│   │   │   ├── UniverseFormModal.tsx
│   │   │   ├── UniverseDetailsModal.tsx # Universe detail view modal
│   │   │   ├── ScannerResults.tsx
│   │   │   └── ...
│   │   ├── pages/
│   │   │   ├── Dashboard.tsx
│   │   │   ├── Scanner/
│   │   │   │   ├── index.tsx
│   │   │   │   ├── ScanConfigPanel.tsx # Header, date controls, config grid, scan history
│   │   │   │   ├── ScanStatusCard.tsx
│   │   │   │   ├── LiveProgressPanel.tsx # In-flight WS progress display
│   │   │   │   └── ResultsPanel.tsx
│   │   │   ├── AutoTrading/
│   │   │   │   ├── index.tsx
│   │   │   │   ├── StrategyPanel.tsx
│   │   │   │   ├── OrdersPanel.tsx
│   │   │   │   ├── AccountPanel.tsx
│   │   │   │   ├── ConfigPanel.tsx
│   │   │   │   └── components.tsx
│   │   │   ├── Alerts/
│   │   │   │   ├── index.tsx
│   │   │   │   ├── AlertRulesPanel.tsx # Alert rule list card
│   │   │   │   ├── AlertRuleModal.tsx
│   │   │   │   ├── AlertLogsPanel.tsx
│   │   │   │   └── ChannelConfigPanel.tsx # Browser push registration card
│   │   │   ├── StockDetailPage/
│   │   │   │   ├── index.tsx
│   │   │   │   ├── ChartPanel.tsx
│   │   │   │   ├── MetadataPanel.tsx
│   │   │   │   └── ScannerHistoryPanel.tsx # Event history + force scan dialog
│   │   │   ├── ActiveWatchlist/
│   │   │   │   ├── index.tsx
│   │   │   │   ├── WatchlistTable.tsx
│   │   │   │   └── AlertBadges.tsx
│   │   │   ├── PreMarketMovers.tsx
│   │   │   ├── Universes.tsx
│   │   │   ├── EdgeExplorer.tsx
│   │   │   ├── Journal.tsx
│   │   │   └── Settings.tsx
│   │   ├── hooks/
│   │   ├── App.tsx
│   │   └── main.tsx
│   ├── package.json
│   ├── tsconfig.json
│   ├── vite.config.ts
│   └── Dockerfile
├── .agent/
│   └── skills/
│       ├── backend_tests/SKILL.md
│       ├── db_migrations/SKILL.md
│       ├── error_tracking/SKILL.md
│       ├── frontend_lint/SKILL.md
│       ├── massive_api_research/
│       │   ├── SKILL.md
│       │   └── scripts/query_api.py
│       └── bash/SKILL.md
├── monitoring/
│   └── prometheus/
│       └── prometheus.yml
├── grafana/
│   └── provisioning/
│       ├── datasources/
│       │   └── prometheus.yaml
│       ├── dashboards/
│       │   ├── dashboards.yaml
│       │   ├── api-overview.json
│       │   ├── scanner-performance.json # Scanner events/duration, Polygon calls, IBKR status
│       │   ├── celery-tasks.json
│       │   └── infrastructure.json
│       └── alerting/
│           ├── contact-points.yaml
│           ├── notification-policies.yaml # Default routing policy
│           └── rules.yaml
├── database-schema.sql
├── docker-compose.yml
├── .env.example
├── README.md
├── ARCHITECTURE.md
├── DEVELOPMENT.md
├── ENV_VARIABLES.md
├── POLYGON_RATE_LIMITS.md
├── PROJECT_STRUCTURE.md
└── CLAUDE.md
```

## Notes for Navigation

- **Start a scan manually**: `POST http://localhost:8000/api/scanner/run` or use the Scanner page in the UI.
- **Add a new model**: create it in `backend/app/models/`, add the import to `backend/app/models/__init__.py`, then run `alembic revision --autogenerate`.
- **Add a new API endpoint**: create or extend a router in `backend/app/routers/`, then register it in `backend/app/main.py`.
- **Add a new frontend page**: create the component in `frontend/src/pages/`, add the route in `frontend/src/App.tsx`.
- **All migrations** must be created after any SQLAlchemy model change. See `DEVELOPMENT.md` for the workflow.
- **`database-schema.sql`** is a legacy reference file. The canonical schema is defined by the Alembic migration history — do not apply the SQL file directly.
