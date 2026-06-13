# Plan: Postgres Discovery — First-Class Test Infrastructure

**Date:** 2026-06-13
**Issue:** [#360](https://github.com/omniscient/markethawk/issues/360)
**Spec:** `docs/superpowers/specs/2026-06-12-postgres-discovery-test-infra-design.md`
**Branch:** `refine/issue-360-test-infra--add-postgres-discovery-fallb`

---

## Goal

Extract `_probe_running_postgres()` from `backend/tests/conftest.py` into a proper, importable
module at `backend/tests/utils/pg_discovery.py`. Rename it to the public API
`probe_running_postgres()`, add unit tests covering all five cases from the spec, and update
`conftest.py` to delegate to the new module. No behavior change; no new runtime dependencies.

## Architecture

Pure structural extraction — the probe logic is identical to the existing private helper. The
extraction makes the discovery mechanism importable, independently testable, and located in the
correct package (`backend/tests/utils/` for infrastructure helpers, not `backend/tests/fixtures/`
which is reserved for domain seed/mock helpers per the test directory layout pattern).

**Memory pattern applied:** `backend-patterns.md` `[PATTERN] backend/tests/fixtures/ is reserved
for domain seed/mock helpers … Infrastructure helpers … belong in backend/tests/utils/`.

## Tech Stack

- Python 3.12 / pytest
- `psycopg2` and `requests` (already available in the test environment — both imported in conftest.py today)
- `unittest.mock` — no new test dependencies

## File Structure

| File | Action | Description |
|------|--------|-------------|
| `backend/tests/utils/__init__.py` | Create | Empty package marker |
| `backend/tests/utils/pg_discovery.py` | Create | Public `probe_running_postgres()` with module-level imports |
| `backend/tests/utils/test_pg_discovery.py` | Create | 5 unit tests (TDD — written before implementation) |
| `backend/tests/conftest.py` | Modify | Remove `_probe_running_postgres()`, add import, update call site |

---

## Task 1: Create `utils` package and write failing tests

**Files:** `backend/tests/utils/__init__.py`, `backend/tests/utils/test_pg_discovery.py`

This task follows TDD: the test file is written before the implementation module exists. All five
tests will fail with `ModuleNotFoundError` until Task 2 creates the module.

### Step 1.1 — Create the empty package marker

```bash
touch backend/tests/utils/__init__.py
```

Content: empty file (just marks `utils/` as an importable package).

### Step 1.2 — Write the test file

Create `backend/tests/utils/test_pg_discovery.py`:

```python
from unittest.mock import MagicMock, patch


def test_explicit_env_var():
    """TEST_DATABASE_URL set → returned immediately; psycopg2 and requests never called."""
    with (
        patch.dict("os.environ", {"TEST_DATABASE_URL": "postgresql://u:p@host/db"}, clear=True),
        patch("tests.utils.pg_discovery.psycopg2") as mock_psycopg2,
        patch("tests.utils.pg_discovery.requests") as mock_requests,
    ):
        from tests.utils.pg_discovery import probe_running_postgres

        result = probe_running_postgres()

    assert result == "postgresql://u:p@host/db"
    mock_psycopg2.connect.assert_not_called()
    mock_requests.get.assert_not_called()


def test_docker_api_ip_discovery():
    """DOCKER_HOST=tcp://...; requests.get returns container with postgres image and IP;
    that IP is tried first; successful psycopg2.connect → correct URL returned."""
    container_json = [
        {
            "Image": "postgres:15-alpine",
            "NetworkSettings": {"Networks": {"bridge": {"IPAddress": "172.17.0.5"}}},
        }
    ]
    mock_response = MagicMock()
    mock_response.json.return_value = container_json
    mock_conn = MagicMock()

    with (
        patch.dict("os.environ", {"DOCKER_HOST": "tcp://docker-socket-proxy:2375"}, clear=True),
        patch("tests.utils.pg_discovery.psycopg2") as mock_psycopg2,
        patch("tests.utils.pg_discovery.requests") as mock_requests,
    ):
        mock_requests.get.return_value = mock_response
        mock_psycopg2.connect.return_value = mock_conn
        from tests.utils.pg_discovery import probe_running_postgres

        result = probe_running_postgres()

    assert result == "postgresql://postgres:postgres@172.17.0.5:5432/postgres"
    mock_requests.get.assert_called_once_with(
        "http://docker-socket-proxy:2375/containers/json", timeout=3
    )
    first_call = mock_psycopg2.connect.call_args_list[0]
    assert first_call.kwargs["host"] == "172.17.0.5"
    mock_conn.close.assert_called_once()


def test_docker_api_failure_falls_through():
    """requests.get raises → hostname list is still tried; matching psycopg2.connect → URL returned."""
    mock_conn = MagicMock()

    with (
        patch.dict("os.environ", {"DOCKER_HOST": "tcp://docker-socket-proxy:2375"}, clear=True),
        patch("tests.utils.pg_discovery.psycopg2") as mock_psycopg2,
        patch("tests.utils.pg_discovery.requests") as mock_requests,
    ):
        mock_requests.get.side_effect = ConnectionError("proxy blocked")
        mock_psycopg2.connect.return_value = mock_conn
        from tests.utils.pg_discovery import probe_running_postgres

        result = probe_running_postgres()

    assert result == "postgresql://postgres:postgres@postgres:5432/postgres"
    first_call = mock_psycopg2.connect.call_args_list[0]
    assert first_call.kwargs["host"] == "postgres"
    mock_conn.close.assert_called_once()


def test_credential_iteration():
    """Multiple (host, cred) combos tried in order; only third succeeds; .close() called."""
    mock_conn = MagicMock()

    def connect_side_effect(**kwargs):
        if kwargs.get("user") == "onecli":
            return mock_conn
        raise Exception("auth failed")

    with (
        patch.dict("os.environ", {}, clear=True),
        patch("tests.utils.pg_discovery.psycopg2") as mock_psycopg2,
        patch("tests.utils.pg_discovery.requests") as mock_requests,
    ):
        mock_psycopg2.connect.side_effect = connect_side_effect
        from tests.utils.pg_discovery import probe_running_postgres

        result = probe_running_postgres()

    # No DOCKER_HOST → only hostname list (postgres, stockscanner-db, localhost).
    # Credentials tried in order: postgres/postgres/postgres, postgres/postgres/stockscanner,
    # onecli/onecli/onecli. Third set succeeds on first hostname.
    assert result == "postgresql://onecli:onecli@postgres:5432/onecli"
    mock_conn.close.assert_called_once()
    mock_requests.get.assert_not_called()


def test_all_fail_returns_none():
    """All psycopg2.connect calls raise; function returns None."""
    with (
        patch.dict("os.environ", {}, clear=True),
        patch("tests.utils.pg_discovery.psycopg2") as mock_psycopg2,
        patch("tests.utils.pg_discovery.requests") as mock_requests,
    ):
        mock_psycopg2.connect.side_effect = Exception("connection refused")
        from tests.utils.pg_discovery import probe_running_postgres

        result = probe_running_postgres()

    assert result is None
```

**Note on patch targets:** `patch("tests.utils.pg_discovery.psycopg2")` and
`patch("tests.utils.pg_discovery.requests")` work because `pg_discovery.py` uses module-level
imports (Task 2). Module-level imports create named attributes on the module object that
`unittest.mock.patch` replaces for the duration of the test — this is the point-of-use patch
convention used throughout the repo (e.g. `tests/fixtures/providers.py`).

### Step 1.3 — Verify tests fail

```bash
cd /workspace/markethawk/backend
python -m pytest tests/utils/test_pg_discovery.py -v --no-cov 2>&1 | head -20
```

Expected output (all five tests fail):
```
ERROR tests/utils/test_pg_discovery.py - ModuleNotFoundError: No module named 'tests.utils.pg_discovery'
```

### Step 1.4 — Commit

```bash
git add backend/tests/utils/__init__.py backend/tests/utils/test_pg_discovery.py
git commit -m "test(#360): add failing unit tests for pg_discovery module"
```

---

## Task 2: Create `pg_discovery` module — make tests green

**Files:** `backend/tests/utils/pg_discovery.py`

### Step 2.1 — Write the module

Create `backend/tests/utils/pg_discovery.py`:

```python
"""Postgres discovery helpers for the test infrastructure.

Locates a running PostgreSQL instance in environments where testcontainers
exec is blocked (e.g. docker-socket-proxy with EXEC:0).
"""
import os

import psycopg2
import requests


def probe_running_postgres() -> str | None:
    """Return a postgres URL if a running instance is reachable, else None.

    Priority:
    1. TEST_DATABASE_URL env var (explicit override)
    2. Docker API scan via DOCKER_HOST (factory/DinD environments)
    3. Well-known hostnames (postgres, stockscanner-db, localhost)

    For each candidate host the function tries common_creds in order and
    returns on the first successful psycopg2.connect().
    """
    explicit = os.environ.get("TEST_DATABASE_URL")
    if explicit:
        return explicit

    candidate_ips: list[str] = []
    docker_host = os.environ.get("DOCKER_HOST", "")
    if docker_host.startswith("tcp://"):
        try:
            r = requests.get(
                f"http://{docker_host[6:]}/containers/json",
                timeout=3,
            )
            for c in r.json():
                if "postgres" not in c.get("Image", "").lower():
                    continue
                for net_info in (
                    c.get("NetworkSettings", {}).get("Networks", {}).values()
                ):
                    ip = net_info.get("IPAddress", "")
                    if ip:
                        candidate_ips.append(ip)
        except Exception:
            pass

    for hostname in ["postgres", "stockscanner-db", "localhost"]:
        candidate_ips.append(hostname)

    common_creds = [
        ("postgres", "postgres", "postgres"),
        ("postgres", "postgres", "stockscanner"),
        ("onecli", "onecli", "onecli"),
    ]
    for ip in candidate_ips:
        for user, pw, db in common_creds:
            try:
                psycopg2.connect(
                    host=ip,
                    port=5432,
                    user=user,
                    password=pw,
                    dbname=db,
                    connect_timeout=1,
                ).close()
                return f"postgresql://{user}:{pw}@{ip}:5432/{db}"
            except Exception:
                pass
    return None
```

**Implementation note:** `psycopg2` and `requests` are imported at module level (not inside the
function body as the spec's illustrative snippet shows). Module-level imports are required for
`patch("tests.utils.pg_discovery.psycopg2")` to find the attribute to replace. All probe logic is
identical to the existing `_probe_running_postgres()` in conftest.py — no behavior change.

### Step 2.2 — Verify tests pass

```bash
cd /workspace/markethawk/backend
python -m pytest tests/utils/test_pg_discovery.py -v --no-cov
```

Expected output:
```
tests/utils/test_pg_discovery.py::test_explicit_env_var PASSED
tests/utils/test_pg_discovery.py::test_docker_api_ip_discovery PASSED
tests/utils/test_pg_discovery.py::test_docker_api_failure_falls_through PASSED
tests/utils/test_pg_discovery.py::test_credential_iteration PASSED
tests/utils/test_pg_discovery.py::test_all_fail_returns_none PASSED

5 passed in 0.Xs
```

### Step 2.3 — Commit

```bash
git add backend/tests/utils/pg_discovery.py
git commit -m "feat(#360): add pg_discovery module as first-class test infrastructure"
```

---

## Task 3: Update `conftest.py` to delegate to `probe_running_postgres`

**Files:** `backend/tests/conftest.py`

### Step 3.1 — Remove the private function and add import

In `backend/tests/conftest.py`, remove lines 30–88 (the entire `_probe_running_postgres()`
function body — from `def _probe_running_postgres() -> str | None:` through the closing `return None`).

Add the following import after the existing standard imports (after line 26,
`_conftest_logger = _logging.getLogger(__name__)`):

```python
from tests.utils.pg_discovery import probe_running_postgres
```

The top of conftest.py after the change:

```python
import os

os.environ.setdefault("RATE_LIMITING_ENABLED", "false")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")
os.environ.setdefault("POLYGON_API_KEY", "test-key-for-unit-tests-only")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret-key-for-unit-tests-only-aaa")

import logging as _logging
from contextlib import contextmanager
from typing import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from testcontainers.postgres import PostgresContainer

from app.core.database import Base
from app.main import app
from tests.utils.pg_discovery import probe_running_postgres

_conftest_logger = _logging.getLogger(__name__)

POSTGRES_IMAGE = "postgres:15-alpine"
```

### Step 3.2 — Update the call site in `_testcontainers_url()`

Change the call from `_probe_running_postgres()` to `probe_running_postgres()`.

The resulting function (unchanged except for the call):

```python
@contextmanager
def _testcontainers_url():
    # When testcontainers' exec endpoint is blocked (e.g. docker-socket-proxy
    # with EXEC:0), fall back to a running postgres discovered via DNS probe.
    probe = probe_running_postgres()
    if probe:
        yield probe
        return
    with PostgresContainer(POSTGRES_IMAGE) as container:
        yield container.get_connection_url()
```

### Step 3.3 — Verify the full test suite runs without regressions

```bash
cd /workspace/markethawk/backend
python -m pytest tests/ -v --ignore=tests/live_scanner -x 2>&1 | tail -30
```

Expected: all previously-passing tests continue to pass, plus the 5 new `test_pg_discovery` tests.

### Step 3.4 — Commit

```bash
git add backend/tests/conftest.py
git commit -m "refactor(#360): replace _probe_running_postgres with imported probe_running_postgres"
```
