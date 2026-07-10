# Foundation Backlog Trio Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> `superpowers:executing-plans` to implement this plan task-by-task. Steps use
> checkbox syntax for tracking.

**Goal:** Deliver #425, #503, and #632 as independently testable foundation
improvements.

**Architecture:** The frontend coordinates a single refresh promise at the
Axios boundary. Backend test infrastructure is protected with a direct context
manager test. UTC normalization stays in `app.utils.time`, preserving the
naive-UTC database contract from ADR-0009.

**Tech Stack:** React, TypeScript, Axios, Vitest, Python 3.12, pytest, Ruff.

## Global Constraints

- Preserve single-use server refresh-token rotation.
- Preserve ADR-0009: database datetimes are naive UTC.
- Each ticket has a red-green test cycle before its production change.
- Do not change API schemas, migrations, or intentional aware-UTC API values.

---

### Task 1: Single-flight refresh (#425)

**Files:**

- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/api/client.test.ts`

**Interfaces:**

- Produces: one module-scoped `Promise<void> | null` shared by eligible 401
  responses.
- Preserves: each Axios config's `_retried` guard and failed-refresh redirect.

- [ ] **Step 1: Add a failing concurrent-401 regression test.**

  Capture the response rejection interceptor, make `unversionedClient.post`
  return a deferred promise, invoke the handler with two distinct eligible
  401 errors, and assert the refresh spy has been called once before resolving
  the deferred promise. Resolve it and assert both original requests retry.

- [ ] **Step 2: Run the focused test.**

  Run: `npm test -- client.test.ts`

  Expected: the new test fails because both handlers call refresh separately.

- [ ] **Step 3: Add the minimal coordinator.**

  ```ts
  let refreshPromise: Promise<void> | null = null;

  function refreshAccessToken(): Promise<void> {
    if (!refreshPromise) {
      refreshPromise = unversionedClient.post('/auth/refresh')
        .then(() => undefined)
        .finally(() => { refreshPromise = null; });
    }
    return refreshPromise;
  }
  ```

  Replace the direct `unversionedClient.post` call in the interceptor with
  `await refreshAccessToken()`.

- [ ] **Step 4: Run the focused test and frontend type check.**

  Run: `npm test -- client.test.ts` then `npx tsc --noEmit`

### Task 2: Discovery-fallback regression test (#503)

**Files:**

- Create: `backend/tests/utils/test_conftest_probe_integration.py`

**Interfaces:**

- Consumes: `tests.conftest._testcontainers_url()` and
  `tests.conftest.probe_running_postgres`.
- Produces: a test that proves probe-first, container-second behavior.

- [ ] **Step 1: Add a failing probe-first test.**

  Patch `probe_running_postgres` to return `None`, patch
  `PostgresContainer` as a context manager whose container returns a known
  URL, enter `_testcontainers_url()`, and assert the URL, one probe call, and
  one container construction.

- [ ] **Step 2: Run the focused test.**

  Run: `python -m pytest tests/utils/test_conftest_probe_integration.py --no-cov -q`

  Expected: the test is collected and passes because the production probe is
  already unconditional; this ticket is a missing-regression-test completion.

### Task 3: UTC normalization helper and codemod (#632)

**Files:**

- Modify: `backend/app/utils/time.py`
- Modify: `backend/tests/test_time_utils.py`
- Modify: `backend/pyproject.toml`
- Modify: current production matches in `backend/app/providers/ibkr.py`,
  `backend/app/tasks/scanning.py`, `backend/app/tasks/quality.py`,
  `backend/app/tasks/sync.py`, `backend/app/routers/scanner.py`,
  `backend/app/routers/system.py`, `backend/app/services/futures_aggregates.py`,
  `backend/app/services/liquidity_hunt.py`, `backend/app/services/pre_market_scan.py`,
  `backend/app/services/quality_gate_evidence.py`,
  `backend/app/services/regime_service.py`,
  `backend/app/services/scanner_query_service.py`, and
  `backend/app/services/system_service.py`.

**Interfaces:**

- Produces: `ensure_utc(dt: datetime) -> datetime`.
- Preserves: `utc_now()` and `to_utc_naive()` semantics.

- [ ] **Step 1: Add failing `TestEnsureUtc` cases.**

  Test that a naive datetime gains `timezone.utc` without changing its clock
  value, and that UTC-aware and non-UTC-aware datetimes are returned by
  identity.

- [ ] **Step 2: Run the helper test.**

  Run: `python -m pytest tests/test_time_utils.py --no-cov -q`

  Expected: import failure because `ensure_utc` does not exist.

- [ ] **Step 3: Implement the helper and codemod only matching idioms.**

  ```python
  def ensure_utc(dt: datetime) -> datetime:
      if dt.tzinfo is not None:
          return dt
      return dt.replace(tzinfo=timezone.utc)
  ```

  Replace `datetime.utcnow()` with `utc_now()`, direct naive-UTC construction
  with `utc_now()`, and direct UTC stamping with `ensure_utc(...)`. Extend
  Ruff selection with `DTZ003` and `DTZ004`; do not touch tests or intentional
  aware-UTC operations.

- [ ] **Step 4: Run helper tests and lint.**

  Run: `python -m pytest tests/test_time_utils.py --no-cov -q` then
  `ruff check app`

### Task 4: Aggregate verification

- [ ] Run: `npm test`, `npx tsc --noEmit`, and the focused backend tests.
- [ ] Run `git diff --check` and inspect the final diff.
- [ ] Commit only the three ticket changes and their implementation records.
