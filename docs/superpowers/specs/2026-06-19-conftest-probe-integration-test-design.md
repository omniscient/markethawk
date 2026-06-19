# Conftest Probe Integration Test Design

**Date:** 2026-06-19
**Issue:** #503 (scope spillover from #360)
**Status:** Pending review

## Overview

`_testcontainers_url()` in `backend/tests/conftest.py` calls `probe_running_postgres()` unconditionally before falling through to `PostgresContainer`. This is spec requirement #2 of issue #360 — the probe must run without any env-var gate (e.g. `POSTGRES_DISCOVERY_ENABLED`). There is existing unit coverage for the probe helper itself (`tests/utils/test_pg_discovery.py`), but no test pins the conftest *wiring*: that the probe is called, that a successful probe URL is yielded, and that a `None` probe result correctly falls through to the container. This spec covers a new integration test that closes that gap.

## Requirements

1. **Test file**: `backend/tests/utils/test_conftest_probe_integration.py`
2. **Three test scenarios** covering the full `_testcontainers_url()` contract:
   - **Probe returns `None` → fallthrough**: `probe_running_postgres` patched to return `None`; assert it is called exactly once, assert `PostgresContainer` is constructed and entered, assert the yielded URL equals `container.get_connection_url()`.
   - **No env gate (POSTGRES_DISCOVERY_ENABLED unset)**: `monkeypatch.delenv("POSTGRES_DISCOVERY_ENABLED", raising=False)` present so the test's intent is explicit; probe still called exactly once (same fixture as scenario 1 can cover this).
   - **Probe returns a URL → short-circuit**: `probe_running_postgres` patched to return a non-`None` URL string; assert the yielded value equals that URL, assert `PostgresContainer` is never constructed.
3. **No live dependencies**: both `tests.conftest.probe_running_postgres` and `tests.conftest.PostgresContainer` are patched for every test — no real Docker daemon or real postgres required.
4. **Standard pytest collection**: the test must be collected by the standard `pytest backend/` run without special markers or fixtures.
5. **No production code changes**: `_testcontainers_url()` and `probe_running_postgres()` are left untouched.

## Architecture

### Import approach

`_testcontainers_url()` is a private `@contextmanager` defined in `tests/conftest.py`. Import it directly:

```python
from tests.conftest import _testcontainers_url
```

`tests/conftest.py` is a plain importable module (the package `__init__.py` exists), so direct import is valid. Importing test-infrastructure internals for infra-level verification is an established pattern in this codebase (see `test_pg_discovery.py` patching `tests.utils.pg_discovery.requests`).

### Patch targets

Both names must be patched on the `tests.conftest` namespace, where `_testcontainers_url` resolves them:

| Name | Patch target |
|------|-------------|
| `probe_running_postgres` | `tests.conftest.probe_running_postgres` |
| `PostgresContainer` | `tests.conftest.PostgresContainer` |

### Context manager usage

Because `_testcontainers_url` is a `@contextmanager`, the test must enter it to trigger the body:

```python
with _testcontainers_url() as url:
    assert url == expected
```

`PostgresContainer` is used as a context manager inside `_testcontainers_url`, so the mock must satisfy `__enter__`/`__exit__`. A `MagicMock()` satisfies this automatically; configure `mock_container.__enter__.return_value = mock_container` and `mock_container.get_connection_url.return_value = "postgresql://..."` to control the yielded URL.

### Environment variable handling

- `monkeypatch.delenv("POSTGRES_DISCOVERY_ENABLED", raising=False)` — makes test intent explicit (no env gate) without affecting mock invocation (the mock replaces the entire function, so `TEST_DATABASE_URL` inside the real probe is never read).
- `TEST_DATABASE_URL` — not relevant; it gates the `db_engine` fixture's choice between `_env_url()` and `_testcontainers_url()`, not anything inside `_testcontainers_url()` itself.

### File location

`backend/tests/utils/test_conftest_probe_integration.py` — the `utils/` directory already owns `pg_discovery.py` and `test_pg_discovery.py`. This test validates the integration between `tests.conftest` and that module, so it sits naturally alongside its sibling. `tests/utils/__init__.py` exists (empty), so pytest collects it automatically.

## Alternatives Considered

### A: Rely on existing unit coverage only

`test_pg_discovery.py` already covers probe helper behaviour thoroughly. We could argue there is no gap. **Rejected** — it does not test the conftest wiring. A future developer could add `if os.environ.get("POSTGRES_DISCOVERY_ENABLED"):` around the probe call in `_testcontainers_url()` and no existing test would catch it. The [AVOID] memory entry for issue #360 identified exactly this risk.

### B: Test via the `db_engine` session fixture

Exercise the conftest wiring indirectly by having a session-scoped test that patches `probe_running_postgres` at `db_engine` fixture setup time. **Rejected** — `db_engine` is session-scoped; patching it from a function-scoped test is awkward and creates ordering dependencies. Directly importing and calling `_testcontainers_url()` is simpler and avoids fixture scope coupling.

## Open Questions

None blocking.

## Assumptions

- `pytest` can import from `tests.conftest` without pytest's own conftest machinery interfering (the import happens at module level, before any fixture collection — this is safe and used elsewhere in the test suite).
- The `MagicMock` auto-spec of `PostgresContainer` as a context manager is sufficient; `testcontainers.postgres.PostgresContainer` does not define `__enter__`/`__exit__` in a way that requires `spec=` to be set.
