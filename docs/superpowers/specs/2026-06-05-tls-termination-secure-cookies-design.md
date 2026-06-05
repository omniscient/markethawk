# TLS Termination and Secure Cookie Enforcement — Design Spec

**Date:** 2026-06-05
**Status:** Approved (brainstorming) → ready for implementation plan
**Issue:** #202 — [arch-v2][MED] Enforce secure cookies + TLS termination
**Author:** Refinement Pipeline (brainstorming session)

## Overview

Session cookies are set with `secure=is_prod` where `is_prod = ENVIRONMENT == "production"` (`backend/app/routers/auth.py:34`). Because `docker-compose.yml` defaults `ENVIRONMENT=development`, cookies travel over plaintext HTTP in the as-shipped stack. There is no TLS termination anywhere in the service topology and `deploy.yml` does raw `docker compose up` with no proxy or certificate.

This spec closes three acceptance criteria from Architecture Quality Report v2 (risk R12):
1. Add a Caddy reverse proxy to the deployment topology with auto-HTTPS.
2. Decouple the cookie `secure` flag from `ENVIRONMENT` via a dedicated `COOKIE_SECURE` setting.
3. Change all `0.0.0.0` port bindings to `127.0.0.1` for defense-in-depth.

## Requirements

| ID | Requirement |
|----|-------------|
| REQ-1 | A `caddy` service is added to `docker-compose.yml`, gated behind `profiles: ["tls"]`, so it does not start in local dev checkouts unless explicitly requested. |
| REQ-2 | `COOKIE_SECURE: bool = True` is added to `Settings` in `config.py`. Default is `True` (secure-by-default, consistent with the existing `ENVIRONMENT: str = "production"` posture). |
| REQ-3 | `auth.py:_set_auth_cookies` uses `settings.COOKIE_SECURE` instead of `is_prod = ENVIRONMENT == "production"`. |
| REQ-4 | `docker-compose.override.yml` adds `COOKIE_SECURE: "false"` to the `backend` service so plain-HTTP local dev continues to work with no developer action. |
| REQ-5 | `SameSite` is changed from `"lax"` to `"strict"` in `_set_auth_cookies`. Safe because all browser traffic routes through the same-origin Caddy proxy in production, and there are no cross-site navigation or OAuth redirect flows in the app. |
| REQ-6 | A `caddy/Caddyfile` is added. Routes all `/api/*` traffic (including WebSocket paths) to `backend:8000` and all other traffic to `frontend:3333`. When `DOMAIN` env var is set, Caddy provisions a Let's Encrypt cert automatically; when unset, falls back to `localhost` with a locally-trusted cert. |
| REQ-7 | All `0.0.0.0` port bindings in `docker-compose.yml` are changed to `127.0.0.1`: `backend` (8000), `frontend` (3333), `prometheus` (9090), `grafana` (3001), `ib-gateway` (4004, 4003), `jaeger` OTLP (4317). The Jaeger UI port (16686) and all other ports are already `127.0.0.1`-bound. |
| REQ-8 | `deployment-guide.md` TLS section updated with concrete Caddy setup instructions. |
| REQ-9 | `ENV_VARIABLES.md` updated to document `COOKIE_SECURE` and `DOMAIN`. |
| REQ-10 | `deploy.yml` SSH deploy script opts into `--profile tls` so Caddy starts on deployed servers (consistent with the existing `--profile factory` / `--profile scheduler` pattern). |

## Architecture

### Cookie Hardening (backend)

**`backend/app/core/config.py`** — new field added to `Settings`:

```python
COOKIE_SECURE: bool = True
```

**`backend/app/routers/auth.py:_set_auth_cookies`** — replace the `is_prod` derivation:

```python
# Before
is_prod = settings.ENVIRONMENT == "production"
response.set_cookie(..., samesite="lax", secure=is_prod, ...)

# After
response.set_cookie(..., samesite="strict", secure=settings.COOKIE_SECURE, ...)
```

Both cookies (`access_token` and `refresh_token`) receive the same update.

**`docker-compose.override.yml`** — add `environment:` block to the `backend` service so local dev (plain HTTP) works without developer action:

```yaml
backend:
  environment:
    COOKIE_SECURE: "false"
  volumes: ...
  command: ...
```

Docker Compose merges `environment:` maps from base and override files, so this key is additive and does not disturb other env vars forwarded by `docker-compose.yml`.

### TLS Proxy (Caddy)

**New file `caddy/Caddyfile`**:

```
{$DOMAIN:localhost} {
    handle /api/* {
        reverse_proxy backend:8000
    }
    handle {
        reverse_proxy frontend:3333
    }
}
```

Caddy's `reverse_proxy` directive handles WebSocket upgrades transparently, covering `/api/v1/live/ws/*` without extra configuration.

**`docker-compose.yml` — new `caddy` service** (after existing services, before `volumes:`):

```yaml
caddy:
  image: caddy:2-alpine
  container_name: stockscanner-caddy
  ports:
    - "80:80"
    - "443:443"
    - "443:443/udp"   # HTTP/3 QUIC
  volumes:
    - ./caddy/Caddyfile:/etc/caddy/Caddyfile:ro
    - caddy_data:/data     # cert storage — must persist across restarts
    - caddy_config:/config
  networks:
    - stockscanner-network
  restart: unless-stopped
  profiles:
    - tls
```

Two new named volumes (`caddy_data`, `caddy_config`) added to the `volumes:` block. `caddy_data` must persist to avoid requesting new Let's Encrypt certs on every start (rate-limited at 5 issuances per domain per week).

### Port Binding Changes

All `0.0.0.0` bindings moved to `127.0.0.1`:

| Service | Before | After |
|---------|--------|-------|
| `backend` | `8000:8000` | `127.0.0.1:8000:8000` |
| `frontend` | `3333:3333` | `127.0.0.1:3333:3333` |
| `prometheus` | `9090:9090` | `127.0.0.1:9090:9090` |
| `grafana` | `3001:3000` | `127.0.0.1:3001:3000` |
| `ib-gateway` | `4004:4004` | `127.0.0.1:4004:4004` |
| `ib-gateway` | `4003:4003` | `127.0.0.1:4003:4003` |
| `jaeger` OTLP | `4317:4317` | `127.0.0.1:4317:4317` |

Services already on `127.0.0.1` (`postgres`, `redis`, `flower`, `pgadmin`, `seq`, `seq-gelf`, `tweet-monitor`, `jaeger` UI) are unchanged.

### Deploy Workflow

**`.github/workflows/deploy.yml`** — add `--profile tls` to the main `docker compose up -d` invocation in the SSH script, and note `DOMAIN` in the deployment prerequisites. No structural change to the workflow file is needed beyond the profile flag.

## Alternatives Considered

### Separate `docker-compose.tls.yml` overlay

Keeps the main file unchanged but requires also editing `deploy.yml` to pass `-f docker-compose.tls.yml`. Profile-gating achieves the same "Caddy absent in local dev" outcome while being correctly exercised by the as-written deploy workflow via `--profile tls`. The existing `factory` and `scheduler` profiles establish this exact pattern.

### `secure=True` always — no env var

Hardcoding `secure=True` unconditionally is simpler but breaks plain-HTTP local dev with no escape path — the browser silently drops the cookie and the developer cannot log in. A dedicated `COOKIE_SECURE` setting with a `True` default gives an explicit opt-out while defaulting to the secure posture.

### nginx instead of Caddy

nginx requires either manual cert provisioning (PEM files mounted as volumes) or a certbot sidecar container. For an autonomous `direct-to-pr` task, Caddy's automatic Let's Encrypt issuance from a five-line `Caddyfile` keyed on `DOMAIN` is operationally simpler and ships without secret pre-provisioning. There is no existing proxy in the codebase to be consistent with, so there is no incumbent advantage for nginx.

## Open Questions (non-blocking)

- **CORS_ORIGINS**: When running behind Caddy with `DOMAIN` set, `CORS_ORIGINS` in `.env` should list the HTTPS domain (e.g., `["https://markethawk.example.com"]`). This is an operator concern not a code change; document in `deployment-guide.md` alongside the Caddy setup.
- **Test suite**: `httpx`-based `TestClient` does not enforce the browser secure-cookie rule, so auth tests should pass with `COOKIE_SECURE=True`. Implement should confirm with a quick `pytest tests/api/test_auth*` run before committing the config change.
- **Caddy localhost self-signed**: When `DOMAIN` is unset and Caddy is started with `--profile tls`, Caddy generates a locally-trusted self-signed cert. Browsers and curl require trusting the Caddy CA (`caddy trust` or `--insecure`). This is intentional; developers use plain HTTP without the tls profile.

## Assumptions

- **[ASSUMPTION]** Docker Compose `environment:` keys in `docker-compose.override.yml` are merged additively with keys in `docker-compose.yml`, so `COOKIE_SECURE: "false"` in the override does not disturb other env vars set in the base file.
- **[ASSUMPTION]** Caddy v2's `{$DOMAIN:localhost}` env var syntax correctly substitutes the `DOMAIN` variable at startup; if `DOMAIN` is unset, it falls back to `localhost`.
- **[ASSUMPTION]** Caddy's `reverse_proxy` directive handles HTTP Upgrade (WebSocket) requests transparently — no `@websocket` matcher or extra headers required for `/api/v1/live/ws/*`.
- **[ASSUMPTION]** `caddy_data` is declared as an internal (non-external) named volume. Unlike `postgres_data` and `redis_data` (which are marked `external: true` and pre-created by an operator), cert storage does not need a pre-existing external volume.

## Files to Change

| File | Type | Change |
|------|------|--------|
| `backend/app/core/config.py` | Edit | Add `COOKIE_SECURE: bool = True` |
| `backend/app/routers/auth.py` | Edit | Use `settings.COOKIE_SECURE`; `samesite="strict"` |
| `docker-compose.yml` | Edit | Add `caddy` service (profile: tls); all `0.0.0.0` ports → `127.0.0.1`; add `caddy_data`/`caddy_config` volumes |
| `docker-compose.override.yml` | Edit | Add `environment: { COOKIE_SECURE: "false" }` to `backend` service |
| `caddy/Caddyfile` | New | Caddy reverse-proxy config |
| `deployment-guide.md` | Edit | Replace stub TLS section with Caddy setup instructions |
| `ENV_VARIABLES.md` | Edit | Document `COOKIE_SECURE` and `DOMAIN` variables |
| `.github/workflows/deploy.yml` | Edit | Add `--profile tls` to deploy commands |
