# Testing Infrastructure: Coverage, CI, and Service Test Gaps

**Date:** 2026-05-24  
**Status:** Draft  
**Issue:** #72 — Testing Architecture Review: deepen test coverage and infrastructure  
**Scope:** `backend/tests/`, `backend/requirements.txt`, `backend/pyproject.toml`, `.github/workflows/ci.yml`

## Problem

The audit of the test suite (365 functions across 33 files) revealed four structural gaps:

1. Every API test function manually wires and clears the FastAPI DI override (`app.dependency_overrides[get_db] = lambda: db` / `app.dependency_overrides.clear()`) — two lines of boilerplate repeated in every test.
2. No coverage measurement, no CI pipeline. Zero visibility into what is tested; no regression gate on pull requests.
3. Six business-logic service modules have no tests: `auto_trade_service`, `alert_service`, `chart_indicators`, `discovery_service`, `journal_service`, `outcome_service`.
4. Three production routers have no API tests: `auto_trading`, `live_data`, `watchlist`.

Frontend testing (#5) and async-mode deepening (#6) from the original audit are explicitly **out of scope** — they carry additional setup cost and design uncertainty better addressed as a follow-on once the backend coverage baseline is established in CI.

## Requirements

1. A single autouse fixture absorbs the DI-override lifecycle for all API tests; individual test functions contain only request-and-assert logic.
2. `pytest-cov` is added to `backend/requirements.txt` and configured in `backend/pyproject.toml`; a 60% line-coverage gate enforced on `app/`.
3. A GitHub Actions workflow runs on every pull request targeting `main`, executes the full pytest suite, and fails the PR if coverage falls below 60%.
4. New test files exist for all six untested services.
5. New test files exist for `auto_trading` and `watchlist` routers.
6. `live_data.py` (100% WebSocket, no HTTP endpoints) is explicitly deferred; a placeholder test file documents the known gap.
7. `auto_trade_service` tests use `paper_mode=True` strategies and `fakeredis`; live IBKR paths are isolated with `unittest.mock.patch("app.providers.ibkr_orders.IBKROrderManager")`. No broker connection is required in CI.

## Architecture

### Candidate 1 — Autouse DI Override Fixture

Add `backend/tests/api/conftest.py` with a function-scoped autouse fixture that wires the DB override for every test in the `api/` subtree:

```python
import pytest
from app.main import app
from app.core.database import get_db

@pytest.fixture(autouse=True)
def override_get_db(db):
    app.dependency_overrides[get_db] = lambda: db
    yield
    app.dependency_overrides.clear()
```

The existing root `backend/tests/conftest.py` already provides the function-scoped `db` fixture with transactional rollback. The new `api/conftest.py` composes on top of it — no changes to the root conftest required. Tests in `backend/tests/services/` and `backend/tests/providers/` are unaffected.

**Before (per test):**
```python
app.dependency_overrides[get_db] = lambda: db
response = client.get("/api/scanner/results")
app.dependency_overrides.clear()
```

**After (per test):**
```python
response = client.get("/api/scanner/results")
```

### Candidate 2 — Coverage Reporting and CI Gate

**`backend/pyproject.toml`** (new file):
```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "--cov=app --cov-report=xml --cov-report=term-missing --cov-fail-under=60"

[tool.coverage.run]
source = ["app"]
omit = ["app/main.py", "app/migrations/*"]

[tool.coverage.report]
exclude_lines = [
    "pragma: no cover",
    "if TYPE_CHECKING:",
]
```

**`backend/requirements.txt`** — add `pytest-cov`.

**`.github/workflows/ci.yml`** (new file):
```yaml
name: Backend CI

on:
  pull_request:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:15-alpine
        env:
          POSTGRES_USER: test
          POSTGRES_PASSWORD: test
          POSTGRES_DB: markethawk_test
        options: >-
          --health-cmd pg_isready
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
        ports:
          - 5432:5432

    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip
          cache-dependency-path: backend/requirements.txt

      - name: Install dependencies
        run: pip install -r backend/requirements.txt

      - name: Run tests
        working-directory: backend
        env:
          TEST_DATABASE_URL: postgresql://test:test@localhost:5432/markethawk_test
        run: python -m pytest

      - name: Upload coverage report
        uses: actions/upload-artifact@v4
        with:
          name: coverage-xml
          path: backend/coverage.xml
```

The existing conftest already checks `TEST_DATABASE_URL` and uses it when set, falling back to testcontainers. Setting it in CI avoids Docker-in-Docker overhead on GitHub-hosted runners.

### Candidate 3 — Service Test Files

One file per untested service. All land in `backend/tests/services/`:

| File | Key test areas |
|------|---------------|
| `test_auto_trade_service.py` | Guard checks (insufficient equity, duplicate locks), position sizing math, side determination, paper_mode order path; patch `IBKROrderManager` for live paths; `fakeredis` for Redis lock |
| `test_alert_service.py` | Alert creation, deduplication, delivery log writes; mock SMTP and WebSocket broadcast |
| `test_chart_indicators.py` | VWAP, MA, and indicator computation correctness against synthetic OHLCV DataFrames — pure function tests, no DB |
| `test_discovery_service.py` | Paginated Polygon response handling, batch insert, rate-limit retry; mock Polygon HTTP responses with `respx` or `unittest.mock` |
| `test_journal_service.py` | Trade CRUD (create, read, update, delete) against the testcontainers DB via the `db` fixture |
| `test_outcome_service.py` | Outcome snapshot calculation, edge cases (no price data, expired window) |

### Candidate 4 — Router Test Files

| File | Scope |
|------|-------|
| `backend/tests/api/test_auto_trading.py` | Strategies CRUD, orders list, stats, config endpoints. Paper-mode fixture seeds a `paper_mode=True` strategy; broker-touching paths patch `IBKROrderManager`. |
| `backend/tests/api/test_watchlist.py` | Watchlist CRUD (create, list, add ticker, remove ticker, delete). |
| `backend/tests/api/test_live_data.py` | Placeholder file with `pytest.skip` and a comment noting that this router is 100% WebSocket; deferred to the future async/WebSocket work item. |

## Alternatives Considered

### A — All 6 candidates in one spec
Rejected. Frontend testing (Vitest setup, `@testing-library/react`, MSW) and async-mode deepening add greenfield infrastructure cost that would block CI stabilization. The "Strong" candidates are independently valuable and ship a measurable baseline first.

### B — Coverage gate at 70%
Rejected. Current service coverage is approximately 40%. Jumping to 70% would leave CI in a permanently red state until all new service tests from Candidate 3 land — making the gate a noise source rather than a signal. 60% is achievable once the new service and router tests ship.

### C — Use testcontainers in CI instead of GitHub Actions `services:`
Viable but rejected for CI. The existing conftest already falls back to testcontainers when `TEST_DATABASE_URL` is unset, so local development continues to use it. In CI, a native `services:` postgres is faster (no container-startup overhead inside the job) and avoids any Docker-in-Docker edge cases.

## Open Questions

- Whether to wire `codecov.io` for coverage diff comments on PRs (non-blocking; the uploaded `coverage.xml` artifact makes this a one-line addition later).
- Whether `live_data.py` WebSocket tests should be a separate GitHub issue or folded into the future async-deepening work item.

## Assumptions

- The GitHub Actions runner is `ubuntu-latest`, which has Docker available (used by testcontainers in local runs but not in CI for this spec).
- `fakeredis` is not yet in `requirements.txt`; it must be added alongside `pytest-cov`.
- `respx` (HTTP mock for httpx/HTTPX-based clients) or `responses` (for requests-based) is the right mock layer for `discovery_service` — this depends on which HTTP library Polygon calls use; implementation should verify and pick the matching library.
- The `watchlist` router uses standard HTTP REST endpoints (not WebSocket) based on its name and Tier 3 classification in the prior spec having been provisional.
