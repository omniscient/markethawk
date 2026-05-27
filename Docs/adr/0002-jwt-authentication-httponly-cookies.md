# ADR-002: JWT Authentication via HttpOnly Cookies

**Date**: 2026-05-27  
**Status**: Accepted  
**Issue**: [#84 — Add authentication and restrict CORS origins](https://github.com/omniscient/markethawk/issues/84)

## Context

All 60+ API endpoints were publicly accessible with no authentication. Sensitive operations — auto-trade order submission, system configuration changes, scanner execution — were reachable by any HTTP client. The CORS configuration used a wildcard (`["*"]`), meaning any origin could call the API if it was network-accessible.

### Options Considered

**A. Static API key in `localStorage`** — Simple. One secret in `.env`, sent as `X-API-Key` header. Rejected: `localStorage` is readable by JavaScript; an XSS vulnerability exposes the key permanently.

**B. JWT in HttpOnly cookies** — Access token (short-lived JWT) + refresh token (long-lived opaque, Redis-backed) both set as `HttpOnly; SameSite=Lax` cookies. Not accessible to JavaScript. Supports instant session revocation via Redis key deletion.

**C. Session-based auth (Redis sessions)** — Same security properties as B, but adds stateful server-side session management without providing meaningful additional value over JWT + Redis refresh tokens.

**D. OAuth2 / external provider** — Over-engineered for a self-hosted single-operator tool.

## Decision

Option **B**: JWT access tokens in HttpOnly cookies, backed by Redis-stored refresh tokens.

### Parameters

| Setting | Value |
|---|---|
| Access token | 15-minute JWT, HttpOnly cookie, path `/` |
| Refresh token | 7-day opaque token (`secrets.token_hex(32)`), HttpOnly cookie, path `/api/auth/refresh`, key stored in Redis |
| Cookie flags | `HttpOnly; SameSite=Lax; Secure` (Secure omitted on localhost) |
| Signing | HS256, key from `JWT_SECRET_KEY` env var |
| Auth enforcement | ASGI middleware — validates `jwt.decode()` only, no DB lookup in hot path |
| Exempt paths | `/api/auth/`, `/api/health`, `/docs`, `/redoc`, `/openapi.json` |

### Bootstrap flow

`GET /api/auth/status` returns `{ bootstrapped: bool }`. When `false`, the login page shows a "Create account" form. `POST /api/auth/register` is only callable when the `users` table is empty; subsequent calls return 403. This eliminates the need for seed scripts or manual CLI setup.

### Why `localStorage` was rejected

`localStorage` is synchronously readable by any JavaScript running on the page. A single XSS vulnerability (injected script, malicious dependency, compromised CDN) exposes the secret permanently — the attacker can extract it and make authenticated API calls from any origin indefinitely. HttpOnly cookies are invisible to JavaScript by definition; even a full XSS compromise cannot extract the token.

### Multi-user path

The `User(id, username, password_hash, created_at, is_active)` model is the minimal schema needed for future multi-user support. Adding more users is additive (INSERT rows). Scoping data to users requires adding `user_id` foreign keys to the relevant tables — a mechanical migration, not an architectural rewrite.

## Consequences

- All API requests must include the `access_token` HttpOnly cookie (set automatically by the browser after login).
- Frontend Axios client sets `withCredentials: true` and auto-refreshes on 401 before redirecting to `/login`.
- `alerts.ts` and `trading.ts` were consolidated onto the shared `apiClient` (previously used standalone `axios.create()` instances that bypassed the auth interceptor).
- CORS `allow_credentials=True` is required and already set; `CORS_ORIGINS` must list explicit origins (no wildcard) — now driven by the `CORS_ORIGINS` env var, defaulting to `http://localhost:3333`.
- `JWT_SECRET_KEY` must be set in `.env` before first deployment. If unset, all non-exempt endpoints return 401 (fail-closed by empty-string key mismatch).
