# Integration Test Fixture and API Coverage Epic

**Date:** 2026-05-03
**Status:** Approved
**Scope:** `backend/tests/` — conftest overhaul, modular fixtures, endpoint tests for all Tier 1+2 routers

## Problem

The test suite uses SQLite which doesn't support JSONB, limiting integration testing. Only 3 of 13 API routers have any test coverage. No seed data fixtures exist for any model.

## Goals

1. **Regression safety net** — happy-path tests for every Tier 1+2 endpoint, ensuring they return correct status codes and response shapes
2. **Business logic validation** — deepen critical paths (scanner, universe) with filtering, sorting, and error case tests
3. **Realistic DB** — test against Postgres via testcontainers so JSONB, array types, and Postgres-specific behavior are covered

## Infrastructure

### Test Database (testcontainers)

Replace SQLite in `backend/tests/conftest.py` with a throwaway Postgres container:

```python
from testcontainers.postgres import PostgresContainer

@pytest.fixture(scope="session")
def postgres():
    with PostgresContainer("postgres:15-alpine") as pg:
        yield pg

@pytest.fixture(scope="session")
def db_engine(postgres):
    engine = create_engine(postgres.get_connection_url())
    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)
```

Container spins up once per session (~3-5s first run, ~1s cached). All tests share it with transaction rollback isolation. Requires Docker available (GitHub Actions has it by default).

Add `testcontainers` to `requirements.txt`.

### Fixture Architecture

Modular composable fixtures in separate files:

```
tests/
  conftest.py              -- engine, db session, client (testcontainers)
  fixtures/
    __init__.py
    core.py                -- seed_universes, seed_tickers, seed_scanner_configs
    scanner.py             -- seed_scanner_runs, seed_scanner_events
    journal.py             -- seed_trades
    alerts.py              -- seed_alert_rules
    outcomes.py            -- seed_outcomes
    system.py              -- seed_system_config
    providers.py           -- mock_polygon_provider, mock_news_provider, mock_futures_provider
```

Each fixture declares dependencies via pytest:

```python
@pytest.fixture
def seed_scanner_events(db, seed_universes, seed_scanner_configs):
    # creates events referencing the universes and configs
    ...
```

Seed data defined inline as ORM objects — type-checked, refactor-friendly, no external files.

### Test Organization

One test file per router group:

```
tests/api/
  test_health.py           -- existing, updated to use new conftest
  test_scanner.py          -- results, configs, history, scan-status-block, events CRUD
  test_universe.py         -- list, create, update, delete, stocks, quality
  test_journal.py          -- trades CRUD
  test_alerts.py           -- alert rules CRUD, delivery log
  test_outcomes.py         -- outcome snapshots, summaries
  test_system.py           -- system config get/update
  test_stocks.py           -- historical data (mocked Polygon)
  test_news.py             -- news articles (mocked Polygon)
  test_futures.py          -- futures data (mocked providers)
```

## Router Tiers

**Tier 1 — Pure DB, no external deps:**
scanner, universe, health, journal, outcomes, system, alerts

**Tier 2 — Needs mocked providers:**
stocks (Polygon), news (Polygon), futures (IBKR/Polygon)

**Tier 3 — WebSocket/streaming (out of scope):**
live_data, watchlist, auto_trading

## Sub-Issue Breakdown

| # | Title | Fixtures | Tests | Depends on |
|---|-------|----------|-------|------------|
| 1 | Testcontainers + core fixtures + scanner tests | `seed_universes`, `seed_tickers`, `seed_scanner_configs`, `seed_scanner_runs`, `seed_scanner_events` | `test_scanner.py` | -- |
| 2 | Universe endpoint tests | (uses core fixtures from #1) | `test_universe.py` | #1 |
| 3 | Journal fixtures + tests | `seed_trades` | `test_journal.py` | #1 |
| 4 | Alerts fixtures + tests | `seed_alert_rules` | `test_alerts.py` | #1 |
| 5 | Outcomes fixtures + tests | `seed_outcomes` | `test_outcomes.py` | #1 |
| 6 | System config tests | `seed_system_config` | `test_system.py` | #1 |
| 7 | Mocked Polygon + stocks tests | `mock_polygon_provider` | `test_stocks.py` | #1 |
| 8 | Mocked Polygon news + tests | `mock_news_provider` | `test_news.py` | #1 |
| 9 | Mocked futures providers + tests | `mock_futures_provider` | `test_futures.py` | #1 |

Issues 2-9 depend only on #1 and are independent of each other.

## Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Test DB | testcontainers (Postgres) | Realistic, no dev stack dependency, ~1s overhead |
| Seed data format | Python ORM fixtures | Type-checked, refactor-friendly, no drift |
| Fixture organization | Modular composable | Tests pull in only what they need |
| Factory library | No (plain fixtures) | Avoids extra dependency for this scale |
| Scope | Tier 1 + Tier 2 | Tier 3 (WebSocket) excluded — different testing approach needed |
| Coverage depth | Happy path first, then critical error cases | Regression net across all endpoints, deeper on scanner/universe |
