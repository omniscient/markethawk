# API Versioning — Design Spec

## Overview

MarketHawk's REST API has no versioning strategy. All 15 routers are registered at `/api/{resource}` with no version prefix, giving clients no migration path when response shapes or endpoint signatures change. This spec defines the versioning approach and the complete implementation plan for adding v1 versioning.

## Problem Statement

Any breaking change — renamed field, removed endpoint, changed response shape — immediately affects all clients with no migration path. This is a prerequisite for exposing the API to third-party consumers and reduces operational risk during frontend-backend releases.

## Requirements

1. All 13 application API routers move to `/api/v1/{resource}` prefix
2. Auth (`/api/auth/`) and health (`/api/health`) remain at current unversioned paths
3. WebSocket endpoints move alongside their REST siblings to `/api/v1/...`
4. Frontend is updated in the same PR — hard cut, no dual routing
5. A versioning policy ADR is written documenting when to bump versions and the deprecation timeline
6. No deprecation middleware in this PR — deferred to the PR that introduces v2

## Architecture / Approach

### Backend: In-place prefix update

The 13 application routers have their prefix strings updated inside each router file. The two infrastructure routers (auth, health) are left unchanged. `main.py` `EXEMPT_PREFIXES` requires no update because auth and health remain at their current paths.

**Routers to update (13):**

| File | Current prefix | New prefix |
|------|---------------|------------|
| `routers/scanner.py` | `/api/scanner` | `/api/v1/scanner` |
| `routers/universe.py` | `/api/universe` | `/api/v1/universe` |
| `routers/stocks.py` | `/api/stocks` | `/api/v1/stocks` |
| `routers/news.py` | `/api/news` | `/api/v1/news` |
| `routers/live_data.py` | `/api/live` | `/api/v1/live` |
| `routers/journal.py` | `/api/journal` | `/api/v1/journal` |
| `routers/system.py` | `/api/system` | `/api/v1/system` |
| `routers/futures.py` | `/api/futures` | `/api/v1/futures` |
| `routers/alerts.py` | `/api/alerts` | `/api/v1/alerts` |
| `routers/watchlist.py` | `/api/watchlist` | `/api/v1/watchlist` |
| `routers/auto_trading.py` | `/api/trading` | `/api/v1/trading` |
| `routers/outcomes.py` | `/api/outcomes` | `/api/v1/outcomes` |
| `routers/tweets.py` | `/api/tweets` | `/api/v1/tweets` |

**Routers NOT changed (2):**

| File | Prefix | Reason |
|------|--------|--------|
| `routers/health.py` | `/api` | Infrastructure health signal; Docker and monitoring tools use this path |
| `routers/auth.py` | `/api/auth` | Auth is orthogonal to resource versioning; tokens should work across all API versions |

**`main.py` changes:** None required. `EXEMPT_PREFIXES = ("/api/auth/", "/api/health", ...)` continues to match correctly since auth and health remain at their existing paths.

### Frontend: Base URL and WebSocket updates

**REST client** (`frontend/src/api/client.ts`): Change the fallback default from `'/api'` to `'/api/v1'`:

```ts
// Before
const API_BASE = import.meta.env.VITE_API_BASE_URL ?? '/api';
// After
const API_BASE = import.meta.env.VITE_API_BASE_URL ?? '/api/v1';
```

All 12 REST API modules (`scanner.ts`, `stocks.ts`, `news.ts`, etc.) use `apiClient` with relative paths and automatically inherit the updated base URL. No changes needed to individual API modules.

**WebSocket consumers** (4 files with hardcoded URL strings):

| File | Current path | New path |
|------|-------------|---------|
| `hooks/useLiveStockData.ts` | `/api/live/ws/...` | `/api/v1/live/ws/...` |
| `hooks/useWatchlistLive.ts` | `/api/live/ws/watchlist` | `/api/v1/live/ws/watchlist` |
| `hooks/useScanTask.ts` | `/api/live/ws/scan-task/...` | `/api/v1/live/ws/scan-task/...` |
| `api/scanner.ts` | `/api/scanner/ws/runs/...` | `/api/v1/scanner/ws/runs/...` |

WebSocket URLs are constructed using `window.location.host` and are outside the `VITE_API_BASE_URL`/axios path, so each string must be updated individually.

**Environment:** Update `VITE_API_BASE_URL` default in `.env.example` to `/api/v1`. Existing `.env` files in deployed environments must be updated before the backend is restarted.

### Policy documentation

New ADR at `docs/adr/NNNN-api-versioning.md` documenting:

- **When to bump**: Breaking changes only — removed fields, type changes, renamed or removed endpoints. Non-breaking additions (new fields, new endpoints) do not require a version bump.
- **Deprecation window**: 90 days minimum from Sunset announcement to removal.
- **Sunset mechanism**: A FastAPI middleware that injects the RFC 8594 `Sunset` header on deprecated version paths will be introduced in the PR that creates `/api/v2/`. It is not implemented now because there are no deprecated paths to annotate.
- **How to introduce v2**: Add a new set of routers with `/api/v2/` prefix. Keep `/api/v1/` alive for the 90-day deprecation window, activate the Sunset middleware pointing at the retirement date.

## Alternatives Considered

### A. Prefix at `include_router()` in `main.py`
Strip `/api` from each application router file, add `prefix="/api/v1"` at each `include_router()` call site in `main.py`. Cleaner architectural separation (routers don't encode the mount point), but requires coordinated changes across 13 router files plus `main.py` and adds no runtime benefit. The in-place prefix update achieves the same result with a simpler change surface.

### B. Header-based versioning (`Accept-Version: v1`)
Cleaner URLs but requires rewriting the auth middleware path-matching logic and adds complexity to every frontend API call. Only MarketHawk's own React frontend consumes the API, so the URL-cleanliness benefit has no current audience. Ruled out.

### C. Backward-compatible redirect layer
Keep `/api/{resource}` routes alive, returning 301 redirects to `/api/v1/{resource}`. The only consumer is the frontend, which is updated in the same PR. A redirect layer ships dead code with no consumer and leaves a maintenance liability. Ruled out.

## Open Questions (non-blocking)

1. Do any Celery tasks or the live-scanner service call the FastAPI backend over HTTP internally? If so, those call sites would also need path updates. Assumed: no — workers and live-scanner communicate via PostgreSQL and Redis, not HTTP.
2. Is there a Nginx or reverse-proxy layer in front of the backend that matches on `/api/`? If so, rewrite rules may need updating. Not observed in the current `docker-compose.yml`.

## Assumptions

- **[Assumed]** No external API consumers exist other than the React frontend. If third-party clients are discovered, they must be identified and given advance notice before the hard cut.
- **[Assumed]** `VITE_API_BASE_URL` is currently unset in `.env` (falling back to `'/api'`). If it is explicitly set, it must be updated in addition to the fallback default.
- **[Assumed]** `live-scanner` and `celery-worker` containers do not call the FastAPI backend over HTTP. If any `httpx`/`requests` calls exist in `tasks/` or the live-scanner pointing at `http://backend:8000/api/...`, those are out of scope for this spec and must be audited separately.
