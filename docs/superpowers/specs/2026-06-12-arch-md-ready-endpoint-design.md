# ARCHITECTURE.md — Document /api/ready Readiness Endpoint

**Date:** 2026-06-12
**Issue:** #350 (scope spillover from #289)
**Status:** Draft

## Problem

Issue #289 implemented `GET /api/ready` (readiness probe: DB `SELECT 1` + Redis `PING`, HTTP 200/503) but the ARCHITECTURE.md router table was intentionally reverted to keep that PR's diff focused. This ticket tracks the documentation follow-up.

A subsequent PR (`readiness-probe-migration-gate`) added the core entry to ARCHITECTURE.md (line 225). However, it omits one item explicitly called out in the issue: "auth and rate-limit exempt" — a meaningful architectural property (the endpoint is outside the `/api/v1/` auth namespace and decorated with `@limiter.exempt`, making it safe to call from infrastructure tooling without credentials or rate-limit budget).

## Decision

Append `auth and rate-limit exempt;` to the existing `health.py` entry in ARCHITECTURE.md so the entry fully reflects the issue's stated scope.

**Before:**
```
`GET /api/health` — liveness probe; `GET /api/ready` — readiness probe (DB `SELECT 1` + Redis `PING`, HTTP 200/503 with per-probe latency; used by compose healthcheck and frontend `depends_on`)
```

**After:**
```
`GET /api/health` — liveness probe; `GET /api/ready` — readiness probe (DB `SELECT 1` + Redis `PING`, HTTP 200/503 with per-probe latency; auth and rate-limit exempt; used by compose healthcheck and frontend `depends_on`)
```

## Requirements

1. The `health.py` row in the Routers table in ARCHITECTURE.md must document `GET /api/ready`.
2. The entry must state it is the readiness probe, checks DB and Redis, returns 200/503, and is auth and rate-limit exempt.
3. No code changes — documentation only.

## Alternatives Considered

**Close as already done** — the existing entry covers all functionally significant details; "auth and rate-limit exempt" is implied by the unversioned `/api/` prefix and a code-level decorator. Rejected because the issue body explicitly lists this property and the doc update is a three-word addition with no risk.

## Assumptions

- No other sections of ARCHITECTURE.md reference `/api/ready` in a way that would become inconsistent with this change.
- The auth-exempt property is architectural (all infrastructure callers depend on it) and therefore worth documenting at the architecture level.

## Open Questions

None — this is a one-line doc fix.
