# Plan: pg_discovery Docker API Response Hardening

**Date:** 2026-06-20
**Issue:** #429
**Spec:** [docs/superpowers/specs/2026-06-14-pg-discovery-docker-api-hardening-design.md](../specs/2026-06-14-pg-discovery-docker-api-hardening-design.md)

## Goal

Harden `probe_running_postgres()` in `backend/tests/utils/pg_discovery.py` against three silent Docker API failure modes: missing `raise_for_status()` check (HTTP error bodies decoded as container JSON), missing `isinstance(containers, list)` guard (`AttributeError` on error-dict responses swallowed by broad except), and absent diagnostic logging. Add one behavioral test for the non-list fallthrough path. The `str | None` return contract and discovery priority order are unchanged.

## Architecture

Test-infrastructure utility only — no backend routes, models, migrations, Celery tasks, or frontend changes. Two files in `backend/tests/utils/` are the complete scope.

## Tech Stack

- Python standard `logging` module — module-level `getLogger(__name__)`
- `requests.HTTPError` (already imported via the `requests` package)
- `pytest` + `monkeypatch` + `unittest.mock` for the new test

## Files

| File | Change |
|------|--------|
| `backend/tests/utils/pg_discovery.py` | Add `import logging`, module-level `logger`, `r.raise_for_status()`, specific `except requests.HTTPError` handler, `isinstance(containers, list)` guard, and three `logger.debug()` calls |
| `backend/tests/utils/test_pg_discovery.py` | Add `import requests` and one new test method |

---

## Task 1: Add failing test for non-list Docker API response

### Files
- `backend/tests/utils/test_pg_discovery.py`

### TDD Steps

**Step 1 — Add `import requests` to the test file imports**

In `backend/tests/utils/test_pg_discovery.py`, add `import requests` at the top of the file alongside the existing imports:

```python
"""Unit tests for the pg_discovery module."""

import requests
from unittest.mock import MagicMock, patch

from tests.utils.pg_discovery import probe_running_postgres
```

**Step 2 — Add the new test method to `TestProbeRunningPostgres`**

Append `test_docker_api_non_list_response_falls_through_to_hostname` as the final method in the class:

```python
    def test_docker_api_non_list_response_falls_through_to_hostname(self, monkeypatch):
        """When Docker API returns a non-list (e.g. error dict), falls through to well-known hostnames."""
        monkeypatch.delenv("TEST_DATABASE_URL", raising=False)
        monkeypatch.setenv("DOCKER_HOST", "tcp://docker:2375")

        mock_response = MagicMock()
        mock_response.json.return_value = {"message": "authorization failed"}
        mock_response.raise_for_status.return_value = None  # 200 OK, but non-list body
        mock_conn = MagicMock()

        with (
            patch("tests.utils.pg_discovery.requests") as mock_requests,
            patch("tests.utils.pg_discovery.psycopg2") as mock_psycopg2,
        ):
            mock_requests.get.return_value = mock_response
            mock_requests.HTTPError = requests.HTTPError

            def connect_side_effect(*args, **kwargs):
                if kwargs.get("host") == "postgres":
                    return mock_conn
                raise Exception("unreachable")

            mock_psycopg2.connect.side_effect = connect_side_effect
            result = probe_running_postgres()

        assert result is not None
        assert "postgres" in result  # proves fallthrough — no Docker IP contributed
```

**Step 3 — Verify the test fails (red)**

```bash
docker-compose exec backend python -m pytest backend/tests/utils/test_pg_discovery.py::TestProbeRunningPostgres::test_docker_api_non_list_response_falls_through_to_hostname -v 2>&1 | tail -20
```

Expected: `FAILED` — the current production code executes `for c in r.json()` which iterates dict keys (strings), and `c.get("Image", "")` raises `AttributeError: 'str' object has no attribute 'get'`. This error is swallowed by the broad `except Exception: pass`, so candidate_ips stays empty and the test may actually _pass_ by coincidence (falls through to hostname). Confirm the test captures the right baseline by temporarily removing the `isinstance` guard assertion from your mental model and verifying test behaviour.

> **Note:** If the test passes at this step due to the broad `except` swallowing the AttributeError, record that and proceed — the failing test step is a TDD gate for the HTTP error case (no `raise_for_status`). The non-list test may already pass before implementation because the current broad except masks the failure. The value of Task 1 is establishing the test in the suite; the guard makes the path explicit and logged rather than silently swallowed.

---

## Task 2: Implement guards and diagnostic logging in pg_discovery.py

### Files
- `backend/tests/utils/pg_discovery.py`

### TDD Steps

**Step 1 — Replace pg_discovery.py with the hardened implementation**

Replace the full contents of `backend/tests/utils/pg_discovery.py`:

```python
"""Postgres discovery helpers for the test infrastructure.

Locates a running PostgreSQL instance in environments where testcontainers
exec is blocked (e.g. docker-socket-proxy with EXEC:0).
"""

import logging
import os

import psycopg2
import requests

logger = logging.getLogger(__name__)


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
            r.raise_for_status()
            containers = r.json()
            if not isinstance(containers, list):
                logger.debug(
                    "Docker API returned non-list (%s), expected container array; "
                    "falling through to hostname probing",
                    type(containers).__name__,
                )
            else:
                for c in containers:
                    if "postgres" not in c.get("Image", "").lower():
                        continue
                    for net_info in (
                        c.get("NetworkSettings", {}).get("Networks", {}).values()
                    ):
                        ip = net_info.get("IPAddress", "")
                        if ip:
                            candidate_ips.append(ip)
        except requests.HTTPError as exc:
            logger.debug(
                "Docker API probe failed (HTTP %s) for %s; falling through to hostname probing",
                exc.response.status_code,
                docker_host[6:],
            )
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

    logger.debug(
        "No reachable postgres found after trying %d candidate host(s)",
        len(candidate_ips),
    )
    return None
```

**Key changes relative to current code:**
- `import logging` added
- `logger = logging.getLogger(__name__)` added at module level
- `r.raise_for_status()` called immediately after `requests.get()` — raises `requests.HTTPError` on 4xx/5xx
- `except requests.HTTPError as exc:` handler inserted before the broad `except Exception: pass` — logs status code and host, then falls through
- `isinstance(containers, list)` guard replaces direct iteration — logs type name on non-list, skips to hostname probing
- `for c in containers:` now lives in the `else:` branch of the isinstance check
- `logger.debug(...)` for no-host-found added before `return None`

**Step 2 — Run the full test suite for pg_discovery**

```bash
docker-compose exec backend python -m pytest backend/tests/utils/test_pg_discovery.py -v 2>&1 | tail -15
```

Expected output:
```
PASSED tests/utils/test_pg_discovery.py::TestProbeRunningPostgres::test_explicit_env_var_returns_immediately
PASSED tests/utils/test_pg_discovery.py::TestProbeRunningPostgres::test_docker_api_ip_discovery
PASSED tests/utils/test_pg_discovery.py::TestProbeRunningPostgres::test_docker_api_failure_falls_through_to_hostname
PASSED tests/utils/test_pg_discovery.py::TestProbeRunningPostgres::test_credential_iteration_order
PASSED tests/utils/test_pg_discovery.py::TestProbeRunningPostgres::test_all_fail_returns_none
PASSED tests/utils/test_pg_discovery.py::TestProbeRunningPostgres::test_docker_api_non_list_response_falls_through_to_hostname

6 passed in Xs
```

Note on existing tests: the existing `test_docker_api_ip_discovery` test already has a `MagicMock()` for `mock_response`, so `mock_response.raise_for_status()` returns another MagicMock without raising — no modification needed. The `test_docker_api_failure_falls_through_to_hostname` test sets `mock_requests.get.side_effect = Exception(...)`, so `raise_for_status()` is never reached — no modification needed.

**Step 3 — Commit both files**

```bash
git add backend/tests/utils/pg_discovery.py backend/tests/utils/test_pg_discovery.py
git commit -m "fix(pg_discovery): add raise_for_status, isinstance guard, and debug logging (#429)"
```

Expected:
```
[refine/issue-429-...] fix(pg_discovery): add raise_for_status, isinstance guard, and debug logging (#429)
 2 files changed, 21 insertions(+), 4 deletions(-)
```
