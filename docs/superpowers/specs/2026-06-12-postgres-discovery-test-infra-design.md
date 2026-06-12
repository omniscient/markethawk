# Postgres Discovery — First-Class Test Infrastructure

**Date:** 2026-06-12
**Issue:** [#360](https://github.com/omniscient/markethawk/issues/360)
**Status:** Pending review

## Problem

In Docker environments where the socket proxy blocks `exec` calls (`EXEC:0`),
testcontainers cannot run health checks and `_testcontainers_url()` cannot spin
up a test PostgreSQL. Issue #288 fixed this inline by adding `_probe_running_postgres()`
directly in `backend/tests/conftest.py`. The function works, but living as a
private helper inside conftest it is not reusable, not tested, and signals "temporary
workaround" rather than "owned infrastructure."

## Requirements

1. The discovery logic must be extractable — importable from a stable, named module.
2. `conftest.py`'s `_testcontainers_url()` must continue to call the discovery function exactly as today; no change to fixture behaviour.
3. The extracted module must have unit tests covering all four probe branches.
4. No new runtime dependencies; no behaviour change.
5. `TEST_DATABASE_URL` override must remain the highest-priority escape hatch.

## Approach

**Minimal extraction with unit tests.** Extract `_probe_running_postgres()` from
`conftest.py` into a new `backend/tests/utils/pg_discovery.py` module, rename it
to the public `probe_running_postgres()`, and have `_testcontainers_url()` import
and call it. Add `backend/tests/utils/__init__.py` so the package is importable.
Write unit tests at `backend/tests/utils/test_pg_discovery.py`.

No changes to the probe logic itself — behavior is preserved as-is.

## Changes

### 1. New file: `backend/tests/utils/__init__.py`
Empty package marker.

### 2. New file: `backend/tests/utils/pg_discovery.py`

```python
"""Postgres discovery helpers for the test infrastructure.

Locates a running PostgreSQL instance in environments where testcontainers
exec is blocked (e.g. docker-socket-proxy with EXEC:0).
"""
import os


def probe_running_postgres() -> str | None:
    """Return a postgres URL if a running instance is reachable, else None.

    Priority:
    1. TEST_DATABASE_URL env var (explicit override)
    2. Docker API scan via DOCKER_HOST (factory/DinD environments)
    3. Well-known hostnames (postgres, stockscanner-db, localhost)

    For each candidate host the function tries common_creds in order and
    returns on the first successful psycopg2.connect().
    """
    import psycopg2
    import requests

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

### 3. Modified: `backend/tests/conftest.py`

Remove lines 30–88 (the `_probe_running_postgres` function body) and replace with:

```python
from tests.utils.pg_discovery import probe_running_postgres
```

Update `_testcontainers_url()` to call `probe_running_postgres()` instead of `_probe_running_postgres()`.

### 4. New file: `backend/tests/utils/test_pg_discovery.py`

Five test cases, all using `unittest.mock.patch` (no new test dependencies):

| Test | What it asserts |
|------|-----------------|
| `test_explicit_env_var` | `TEST_DATABASE_URL` set → returned immediately; `psycopg2` and `requests` never called |
| `test_docker_api_ip_discovery` | `DOCKER_HOST=tcp://…`; `requests.get` returns a container with a postgres image and an IP; that IP is tried first; successful `psycopg2.connect` → correct URL returned |
| `test_docker_api_failure_falls_through` | `requests.get` raises → hostname list is still tried; matching `psycopg2.connect` → URL returned |
| `test_credential_iteration` | Multiple (host, cred) combos tried in order; only the third succeeds; asserts `.close()` was called on the successful connection |
| `test_all_fail_returns_none` | All `psycopg2.connect` calls raise; function returns `None` |

Mock targets: `tests.utils.pg_discovery.psycopg2` and `tests.utils.pg_discovery.requests`
(point-of-use patch, matching the repo convention from `tests/fixtures/providers.py`).

## Alternatives Considered

**B — Also extract `_testcontainers_url()` into the new module.** That context manager
is tightly coupled to `PostgresContainer(POSTGRES_IMAGE)` and the `db_engine` session
lifecycle, all of which belong in conftest. Moving it would expand scope without
adding reuse value. Rejected.

**C — Improve probe logic during extraction** (more credentials via env var, additional
Docker network patterns). The issue explicitly calls this out-of-scope ("scope
spillover… scope enforcement"). The existing logic works; the defect is structural.
Rejected.

## Assumptions

- `backend/tests/__init__.py` exists and `tests` is an importable package (confirmed).
- `backend/tests/utils/` does not yet exist and must be created.
- `psycopg2` and `requests` are already available in the test environment (both are
  used today in conftest.py, so they are either direct or transitive test deps).

## Open Questions

None blocking implementation.
