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
│   │   │   ├── ws_limits.py
│   │   │   └── tracing.py
│   │   ├── models/
│   │   │   ├── backtest_run.py
│   │   │   ├── backtest_trade.py
│   │   │   ├── active_watchlist.py
│   │   │   ├── scanner_run.py
│   │   │   ├── scanner_event.py
│   │   │   ├── scanner_config.py
│   │   │   ├── stock_universe.py
│   │   │   ├── stock_universe_ticker.py
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
│   │   │   ├── universe_quality_report.py
│   │   │   ├── signal_analysis_run.py
│   │   │   ├── signal_cluster.py
│   │   │   ├── signal_review.py
│   │   │   ├── monitored_account.py
│   │   │   ├── tweet_signal.py
│   │   │   ├── regime_model.py     (RegimeModel — serialised GaussianHMM + state label mapping)
│   │   │   ├── user.py
│   │   │   └── __init__.py
│   │   ├── routers/
│   │   │   ├── backtest.py
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
│   │   │   ├── data_quality.py
│   │   │   └── __init__.py
│   │   ├── schemas/
│   │   │   ├── active_watchlist.py
│   │   │   └── stock.py
│   │   ├── services/
│   │   │   ├── backtest_service.py (daily-bar replay engine — _simulate_trade, run_backtest_logic)
│   │   │   ├── stock_data.py
│   │   │   ├── universe_stats.py
│   │   │   ├── scan_orchestrator.py
│   │   │   ├── scanner_query_service.py
│   │   │   ├── system_service.py
│   │   │   ├── auto_trade_service.py
│   │   │   ├── pre_market_scan.py
│   │   │   ├── oversold_bounce_scan.py
│   │   │   ├── pocket_pivot.py
│   │   │   ├── trend_pullback_scan.py
│   │   │   ├── scanner.py          (facade — scan bodies in sibling modules)
│   │   │   ├── session_metrics.py  (calculate_day_metrics* — extracted from scanner.py)
│   │   │   ├── scan_enrichment.py  (_get_batch_enrichment_data* — extracted from scanner.py)
│   │   │   ├── discovery_service.py
│   │   │   ├── stock_screener.py   (StockScreener — self-registers as "stocks" screener adapter)
│   │   │   ├── futures_screener.py (FuturesScreener — self-registers as "futures" screener adapter)
│   │   │   ├── catalyst_parser.py
│   │   │   ├── futures_data.py         (facade — impl in sibling modules)
│   │   │   ├── futures_contracts.py    (SYMBOL_EXCHANGE_MAP, FuturesContractService)
│   │   │   ├── futures_aggregates.py   (FuturesAggregatesService — download/gap-fill)
│   │   │   ├── futures_rollovers.py    (FuturesRolloversService, _build_time_slices)
│   │   │   ├── futures_series.py       (FutureSeriesService — continuous series assembly)
│   │   │   ├── chart_indicators.py
│   │   │   ├── journal_service.py
│   │   │   ├── websocket_manager.py
│   │   │   ├── normalization.py
│   │   │   ├── data_quality.py
│   │   │   ├── stats.py
│   │   │   ├── event_helpers.py
│   │   │   ├── regime_service.py   (RegimeService — HMM train/persist/query; Redis regime cache)
│   │   │   ├── statistical_discovery.py
│   │   │   ├── signal_ranker.py
│   │   │   ├── universe_orchestrator.py
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
│   │   │   ├── test_outcomes_regime.py
│   │   │   ├── test_scanner.py
│   │   │   ├── test_stocks.py
│   │   │   ├── test_universe.py
│   │   │   ├── test_watchlist.py
│   │   │   └── test_live_data.py
│   │   └── services/
│   │       ├── test_alert_service.py
│   │       ├── test_auto_trade_service.py
│   │       ├── test_chart_indicators.py
│   │       ├── test_data_quality_helpers.py
│   │       ├── test_discovery_service.py
│   │       ├── test_journal_service.py
│   │       ├── test_normalization_helpers.py
│   │       ├── test_outcome_service.py
│   │       ├── test_regime_service.py
│   │       └── test_split_adjustment.py
│   ├── alembic.ini
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/
│   ├── src/
│   │   ├── api/
│   │   │   ├── client.ts
│   │   │   ├── scanner/         ← facade index + sub-modules (types, runs, results, configs, reviews, ws, misc)
│   │   │   ├── universe.ts      ← StockUniverse, QualityReport CRUD (extracted from scanner)
│   │   │   ├── stocks.ts
│   │   │   ├── news.ts
│   │   │   ├── system.ts
│   │   │   ├── watchlist.ts
│   │   │   └── analysis.ts
│   │   ├── components/
│   │   │   ├── UniverseFormModal.tsx
│   │   │   ├── UniverseDetailsModal.tsx
│   │   │   ├── ScannerResults.tsx
│   │   │   └── ...
│   │   ├── pages/
│   │   │   ├── Dashboard.tsx
│   │   │   ├── Scanner/
│   │   │   │   ├── index.tsx
│   │   │   │   ├── ScanConfigPanel.tsx
│   │   │   │   ├── ScanStatusCard.tsx
│   │   │   │   ├── LiveProgressPanel.tsx
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
│   │   │   │   ├── AlertRulesPanel.tsx
│   │   │   │   ├── AlertRuleModal.tsx
│   │   │   │   ├── AlertLogsPanel.tsx
│   │   │   │   └── ChannelConfigPanel.tsx
│   │   │   ├── StockDetailPage/
│   │   │   │   ├── index.tsx
│   │   │   │   ├── ChartPanel.tsx
│   │   │   │   ├── MetadataPanel.tsx
│   │   │   │   └── ScannerHistoryPanel.tsx
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
│       │   ├── scanner-performance.json
│       │   ├── celery-tasks.json
│       │   └── infrastructure.json
│       └── alerting/
│           ├── contact-points.yaml
│           ├── notification-policies.yaml
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
