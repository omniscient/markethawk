# Auth Refresh Single-Flight Guard — Design

**Date:** 2026-06-14
**Status:** Spec — pending implementation plan
**Author:** Brainstormed with Claude (Opus 4.8)
**Issue:** #425

## Problem

When the 15-minute access token expires while multiple API calls are in flight simultaneously
(the dashboard fires many requests on load), every request that 401s independently triggers its
own `POST /api/auth/refresh`. The backend uses single-use token rotation — on each refresh it
deletes the old refresh token and issues a new one — so only the first concurrent refresh
succeeds. The remaining concurrent refreshes present the now-deleted token and receive 401.

The app mostly self-heals (the winning refresh sets a fresh access-token cookie, so subsequent
polls succeed), but the race produces:
- 401 log noise in Seq
- Transient failures of all but one of the competing requests
- A latent spurious-logout risk under high request bursts

Evidence from live logs (2026-06-13): five refresh attempts in a 265 ms burst — one 200, four
401s — leaving orphaned Redis keys from the losing races.

**Root cause (frontend):** `frontend/src/api/client.ts` response interceptor (~L38–47): every
401 independently calls `unversionedClient.post('/auth/refresh')`. No single-flight guard means
N concurrent 401s → N concurrent refreshes.

## Requirements

1. With the access token expired and ≥5 dashboard requests fired at once, exactly **one**
   `POST /api/auth/refresh` is issued; zero spurious `/auth/refresh` 401s result.
2. All originally-failed requests must **retry successfully** after the single refresh resolves.
3. A genuinely expired or invalid refresh token must still 401 and route the user to `/login`
   without a retry loop — the existing `!error.config.url?.includes('/auth/')` guard must be
   preserved.
4. After a successful or failed refresh cycle, subsequent token expiry events must be handled
   cleanly — the single-flight state must reset for the next cycle.
5. Tests in `frontend/src/api/client.test.ts` must cover:
   - (a) N concurrent 401s → exactly 1 refresh call
   - (b) All concurrent requests retry after the refresh succeeds
   - (c) A failed refresh → `window.location.href` redirected to `/login`

## Non-Goals (v1)

- Backend changes — Option B (grace window / Redis `prev_token → new_token` mapping) is
  explicitly out of scope. Option A eliminates the race structurally; Option B adds security
  surface (softens single-use rotation as a theft-detection signal) without benefit once A is
  shipped. Track as a separate follow-up only if load testing reveals a residual race after
  this fix is merged.
- Retry ordering guarantees — requests queued behind the single-flight refresh may complete
  concurrently in any order; the fix makes no ordering promise.
- Per-tab coordination — the single-flight guard is module-scoped within one browser tab;
  two tabs expiring at the same instant may both attempt a refresh. This is an acceptable
  edge case: the backend's single-use rotation already handles it gracefully (the losing tab
  gets a 401 on its second request and re-triggers the same interceptor path, which by then
  will find a valid cookie).

## Approach: Module-Level Single-Flight Promise (Option A)

Introduce a module-level `refreshPromise: Promise<void> | null` variable in
`frontend/src/api/client.ts`. The interceptor consults this variable before calling
`/auth/refresh`:

```
refreshPromise = null   (module-level)

interceptor (on 401):
  if _retried or url includes '/auth/' → reject (no-op, same as today)
  set _retried = true on error.config
  if refreshPromise is null:
    refreshPromise = unversionedClient.post('/auth/refresh')
                       .then(() => {})
                       .catch(() => { throw ... })
                       .finally(() => { refreshPromise = null })
  await refreshPromise
  → on resolve: return apiClient(error.config)   (retry original request)
  → on reject:  window.location.href = '/login'
```

Key invariants:
- **`_retried` flag** — remains per-request on `error.config`. Prevents infinite loops: if
  the retry also 401s (meaning the new token is also invalid), the interceptor does not
  attempt a second refresh.
- **`finally` cleanup** — `refreshPromise` is reset to `null` in a `finally` block, not in
  `.then` alone. This ensures a future expiry cycle (after the next 15 minutes) starts a
  fresh refresh rather than finding a stale rejected promise.
- **Error re-throw in `.catch`** — the promise stored in `refreshPromise` must reject (not
  resolve) when the refresh fails, so that all `await`ing requests enter their own `catch`
  block and redirect to login.
- **No new dependencies** — `vi.mock` from the existing Vitest 4.1.7 installation is
  sufficient for tests; do not add `axios-mock-adapter` or `msw`.

### Test requirements

All tests go in `frontend/src/api/client.test.ts`. Concurrent 401s must be fired via
`Promise.all([...])` over un-awaited promises — sequential awaiting would pass even against a
buggy implementation (each sequential 401 would start and finish its own refresh before the
next one began).

```
describe('single-flight refresh', () => {
  it('fires exactly one /auth/refresh when N requests 401 concurrently')
  it('retries all concurrent requests after refresh succeeds')
  it('redirects to /login when refresh fails')
})
```

## Alternatives Considered

### Option B — Backend refresh-reuse grace window

Store a `prev_token → new_token` mapping in Redis for a configurable window (a few seconds)
so near-simultaneous reuses of a rotated token succeed rather than 401ing.

**Rejected because:**
- Option A eliminates the race at its source (the frontend fires only one refresh); B mitigates
  a race that A prevents from occurring. B adds no value once A is shipped.
- Single-use rotation is a deliberate security property: reuse of a deleted refresh token is the
  signal used to detect refresh-token theft/replay. A grace window softens this detection window.
- B requires backend changes, Redis schema changes, env config additions (ENV_VARIABLES.md), and
  Seq structured logging for reuse-after-grace events — all out of the `size: M`, `frontend`
  ticket scope.

### Per-request `_retried` flag as sole guard (status quo)

Already in place but insufficient: each request checks its own `_retried` flag, which prevents
per-request retry loops but does nothing to prevent N concurrent requests from each starting
their own refresh.

## Assumptions

- [ASSUMPTION] The browser cookie jar is shared across all concurrent requests in the same tab,
  so after the winning refresh sets the `access_token` and `refresh_token` cookies, every
  retried request automatically carries the new cookies with no extra bookkeeping.
- [ASSUMPTION] `axios` config objects are distinct per request (not shared), so setting
  `error.config._retried = true` on one request does not affect others.
- [ASSUMPTION] The `refreshPromise` race (two requests check `refreshPromise === null` at the
  exact same microtask tick) cannot occur in browser JavaScript because the event loop is
  single-threaded; no mutex is needed.

## Open Questions (non-blocking)

- **Per-tab race:** if two browser tabs expire simultaneously, each tab's single-flight guard
  fires independently. In practice the backend handles this via token rotation (the losing
  tab's second request will re-enter the interceptor path and succeed). No action required for
  v1 but worth monitoring in Seq.
- **Test isolation for `window.location`:** `jsdom` makes `window.location.href` assignment
  observable. The implementer should verify the mocking strategy for redirect assertions works
  cleanly in the existing `jsdom` environment used by Vitest.

## Files Changed

| File | Change |
|---|---|
| `frontend/src/api/client.ts` | Add `refreshPromise` module var; update interceptor (~+10 lines) |
| `frontend/src/api/client.test.ts` | Add 3 single-flight interceptor test cases (~50 lines) |
