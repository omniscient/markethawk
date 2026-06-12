# Swagger / openapi.json / metrics authentication hardening

**Date:** 2026-06-12
**Issue:** #369
**Status:** Spec

---

## Problem

The global pure-ASGI `AuthMiddleware` in `backend/app/main.py` is deny-by-default, but
four prefixes in `EXEMPT_PREFIXES` (lines 266–275) are permanently whitelisted:

```
/docs      /redoc      /openapi.json      /metrics
```

`openapi.json` is a full API schema — a turnkey reconnaissance map of every route,
parameter, and model. `/metrics` exposes Prometheus data: request volumes, WebSocket
connection counts, and internal timing. Both are accessible to any unauthenticated
client that can reach port 8000.

Security review finding: OWASP A05:2021 Security Misconfiguration, CWE-200.

---

## Requirements

1. In production, FastAPI must not serve Swagger UI, ReDoc, or `openapi.json` — they
   must return 404.
2. The three doc prefixes must be removed from `EXEMPT_PREFIXES` when docs are
   disabled (they would 404 anyway, but explicit exclusion removes the whitelist entry).
3. `/metrics` must remain accessible to Prometheus on the internal Docker network.
4. `/metrics` must not be reachable via the external reverse proxy (Caddy).
5. The local development experience must be unchanged: docs available at `/docs`
   and `/metrics` open for local Prometheus scraping.
6. No environment-variable gymnastics required by developers — the override file
   handles it automatically.

---

## Architecture / Approach

### 1. New `DOCS_ENABLED` setting in `backend/app/core/config.py`

Follow the `COOKIE_SECURE` pattern (a dedicated boolean field rather than deriving from
`ENVIRONMENT`): a dedicated flag is independently overridable, defaults secure, and avoids
coupling docs visibility to the overloaded `ENVIRONMENT` string (which also accepts
`"debug"` and is used for the stack-trace gate at `main.py:438`).

```python
# config.py — add after COOKIE_SECURE
DOCS_ENABLED: bool = False  # Swagger/ReDoc/openapi.json — disabled by default in production
```

No validator is needed; Pydantic coerces `"true"` / `"false"` strings automatically.

### 2. Conditional FastAPI URLs in `create_app()`

Replace the bare `FastAPI(title=..., ...)` call with conditional URL arguments:

```python
_docs_url = "/docs" if settings.DOCS_ENABLED else None
app = FastAPI(
    title=settings.APP_NAME,
    description="Professional stock scanning and alert system",
    version=settings.APP_VERSION,
    lifespan=lifespan,
    docs_url=_docs_url,
    redoc_url=_docs_url,
    openapi_url="/openapi.json" if settings.DOCS_ENABLED else None,
)
```

When `docs_url=None`, FastAPI registers no routes for those paths and returns 404.

### 3. Dynamic `EXEMPT_PREFIXES` construction

Replace the hard-coded tuple with a conditional build:

```python
_base_exempt = (
    "/api/auth/",
    "/api/health",
    "/api/ready",
    "/metrics",
    "/api/alerts/infrastructure",
)
_doc_prefixes = ("/docs", "/redoc", "/openapi.json") if settings.DOCS_ENABLED else ()
EXEMPT_PREFIXES = _base_exempt + _doc_prefixes
```

`/metrics` stays in the base exempt tuple at all times (see §4 below).

### 4. `/metrics` — Caddyfile deny (defense-in-depth)

Prometheus scrapes `backend:8000/metrics` directly over the internal Docker network;
it never goes through Caddy. The existing Caddyfile already only forwards `/api/*` to
the backend and routes everything else to the frontend, so an external HTTPS request to
`/metrics` already reaches the frontend SPA — not Prometheus data. Adding an explicit
deny makes this protection visible and intentional:

```
# caddy/Caddyfile — inside the {$DOMAIN:localhost} block, before handle /api/*
handle /metrics {
    respond "Not found" 404
}
```

`/metrics` therefore stays permanently in `EXEMPT_PREFIXES` (backend auth middleware
never sees external `/metrics` requests). Prometheus scraping is unaffected.

> **Note for operators:** If backend port 8000 is published directly to the host
> (e.g. `8000:8000` in docker-compose.yml), Prometheus metrics remain accessible
> on that port regardless of Caddy. The production compose must not publish port 8000
> externally. This is an infra concern documented in deployment-guide.md (see §5).

### 5. `docker-compose.override.yml` — enable docs for local dev

Add one line to the `backend` environment block, alongside the existing `COOKIE_SECURE`
override:

```yaml
environment:
  COOKIE_SECURE: "false"
  DOCS_ENABLED: "true"
```

No changes required for existing dev workflows.

### 6. `deployment-guide.md` update

Add a section under "Production Hardening" explaining:
- `DOCS_ENABLED` defaults `False` — never set it `True` in production
- `/metrics` is internal-network only; the backend container must not publish
  port 8000 to the host in production compose

---

## Alternatives Considered

### A) Gate on `ENVIRONMENT == "development"`
The issue's code snippet uses this pattern, which is already used for stack-trace
exposure at `main.py:438`. Rejected: `ENVIRONMENT` is overloaded (`"development"`,
`"debug"`, `"production"`), coupling docs visibility to it is brittle (a staging
environment running `ENVIRONMENT=staging` would silently disable docs), and the
`COOKIE_SECURE` pattern already established the precedent for a dedicated boolean.

### B) METRICS_BEARER_TOKEN
Add a static bearer token that Prometheus passes with `bearer_token:`. Rejected for
size S: bearer-token auth for inbound requests has no existing codebase precedent, a
long-lived static secret is its own security smell, and the Caddyfile already blocks
external access. Adding bearer-token support to `AuthMiddleware` would be a non-trivial
change that this ticket doesn't warrant.

### C) `METRICS_PUBLIC: bool = False` with runtime gating
Remove `/metrics` from `EXEMPT_PREFIXES` in production. Rejected: Prometheus has no
mechanism to send a JWT cookie, so this would break all metric scraping in production
without a corresponding bearer-token implementation (see B). Network isolation is the
correct defence for the Prometheus scrape endpoint.

---

## Open Questions

- Should the Caddy `/metrics` deny be applied to `tweet-monitor:8000/metrics` as well?
  The `prometheus.yml` also scrapes that service. Caddy doesn't proxy to `tweet-monitor`
  at all, so no change needed — noting for completeness.

---

## Assumptions

- `DOCS_ENABLED` default `False` is correct for the existing `ENVIRONMENT: str = "production"` default.
- `docker-compose.override.yml` is applied automatically in local dev checkouts
  (confirmed by `docker-compose up -d` auto-merge behaviour documented in CLAUDE.md).
- Backend port 8000 is not published to the host in production Docker Compose.
  If it is, the Caddyfile deny is not sufficient and the port-mapping must be removed.
