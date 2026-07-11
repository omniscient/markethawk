# Foundation Backlog Trio Design

**Date:** 2026-07-10
**Issues:** #425, #503, #632
**Status:** approved for implementation

## Goal

Ship three independent, low-blast-radius backlog improvements: eliminate concurrent
refresh-token rotation races, lock the PostgreSQL discovery fallback behind a
regression test, and consolidate the remaining UTC-normalization idioms.

## Decisions

### #425: single-flight refresh

Keep refresh coordination in `frontend/src/api/client.ts`. A module-scoped
`refreshPromise` represents the only in-flight `POST /api/auth/refresh` call.
The first eligible 401 creates it; concurrent eligible 401s await it; every
request retries once after it resolves. The promise is cleared in `finally` so
a later token expiry can start a fresh refresh. Failed refreshes retain the
current redirect-to-login behavior.

This is frontend-only. The backend's single-use rotation remains a security
property rather than being weakened with a grace window.

### #503: testcontainers discovery contract

Add one focused test at
`backend/tests/utils/test_conftest_probe_integration.py`. It patches the
discovery probe and `PostgresContainer`, invokes `_testcontainers_url()`, and
asserts that the probe is called once before the fallback container supplies a
connection URL. The test exercises the real context manager without needing a
database.

### #632: bounded UTC helper consolidation

ADR-0009 requires database `DateTime` values to be **naive UTC**. Extend the
existing `app.utils.time` module with `ensure_utc(dt)`, which adds UTC tzinfo
only to naive datetimes and returns already-aware datetimes unchanged.

Use `utc_now()` for direct naive-UTC generation and `ensure_utc()` for direct
`.replace(tzinfo=timezone.utc)` calls. Do not replace intentionally-aware
`datetime.now(timezone.utc)`, `datetime.fromtimestamp(..., tz=timezone.utc)`,
or test fixtures. The codemod is limited to the current production matches and
is protected by the narrow Ruff `DTZ003`/`DTZ004` checks.

## Verification

- The refresh regression test holds two 401 handlers behind one deferred
  refresh and proves that only one refresh request is issued.
- The PostgreSQL test proves the probe executes before a container fallback.
- Time helper tests prove naive stamping, aware passthrough, and storage
  conversion semantics; Ruff verifies the targeted deprecated UTC calls stay
  absent.
