# ADR-010: API Versioning Policy

**Date**: 2026-05-29  
**Status**: Accepted  
**Issue**: [#105 — Add API versioning](https://github.com/omniscient/markethawk/issues/105)

## Context

All API endpoints were served at `/api/{resource}` with no version prefix. Any breaking change — renamed fields, removed endpoints, changed response shapes — would affect all clients simultaneously with no migration path.

The only current consumer is the React frontend. No external third-party clients exist.

Three versioning strategies were considered:

- **URL prefix** (`/api/v1/`) — visible, cache-friendly, works natively with FastAPI's router model
- **Header-based** (`Accept-Version: v1`) — cleaner URLs but adds middleware complexity; worth it only when third-party clients need stable-looking URLs
- **Query parameter** (`?version=1`) — least standard, poorest cache behaviour

## Decision

**URL prefix versioning** at `/api/v1/{resource}`.

All 13 application routers move from `/api/{resource}` to `/api/v1/{resource}` in a single hard-cut change. Auth (`/api/auth`) and health (`/api/health`) are explicitly excluded from versioning:

- **Auth** is infrastructure, not a versioned resource. Tokens must work across all API versions. A `/api/v1/auth` prefix would raise the question "do I need a v2 token for v2 endpoints?" Keeping auth unversioned avoids this permanently.
- **Health** is a platform contract consumed by Docker, load-balancers, and monitoring tools. It must remain stable regardless of API version evolution.

No backward-compatibility redirect layer is introduced. The only consumer (the React frontend) is updated in the same change. Dual routing would leave dead code with no runtime benefit.

### Versioning policy

| Trigger | Action |
|---|---|
| Additive change (new field, new endpoint) | No version bump — v1 stays current |
| Breaking change (renamed/removed field, changed response shape, removed endpoint) | Introduce `/api/v2/` alongside v1 |
| v1 sunset after v2 ships | 90-day deprecation window; `Sunset` response header on v1 endpoints during that period |

A breaking change is defined as any change that would require a client code update to continue working correctly.

### Sunset mechanism (deferred)

The `Sunset` header middleware described in issue #105 is deferred to the PR that introduces `/api/v2/`. Shipping it now would deploy code with no runtime effect — no old routes exist to sunset.

## Consequences

- All versioned API calls go to `/api/v1/{resource}`. Frontend `VITE_API_BASE_URL` defaults to `/api/v1`.
- Auth endpoints remain at `/api/auth/` and use a dedicated `unversionedClient` in the frontend.
- WebSocket endpoints version together with their REST siblings (`/api/v1/live/ws/`, `/api/v1/scanner/ws/`, `/api/v1/system/ws/`).
- Future breaking changes require introducing `/api/v2/` and running both versions in parallel for 90 days before removing v1.
- The `EXEMPT_PREFIXES` list in `main.py` requires no changes — auth and health middleware exemptions remain at their current paths.
