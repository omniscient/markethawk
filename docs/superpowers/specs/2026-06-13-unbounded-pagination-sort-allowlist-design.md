# F-INPUT-01: Unbounded Pagination + Reflective Sort Hardening

**Date:** 2026-06-13
**Issue:** #376
**Epic:** #372 (Defensive Security Review 2026-06-12)
**Status:** Spec

---

## Problem

Three API endpoints accept a `limit` query parameter with no upper bound, allowing a
single request to serialize an entire PostgreSQL table into memory (CWE-770). One of
those endpoints also resolves a sort column via `getattr(ScannerEvent, user_input)`,
widening the attack surface to unintended attribute/descriptor access (CWE-915).

**Affected endpoints:**
- `GET /api/v1/scanner/results` — unbounded `limit` + reflective `sort_by`
- `GET /api/v1/scanner/history` — unbounded `limit`
- `GET /api/v1/outcomes/signals/{scanner_type}` — unbounded `limit` (sort already safe)

**Attack scenarios:**
- `GET /api/v1/scanner/results?limit=10000000` → full `scanner_events` table serialized
- `GET /api/v1/scanner/results?sort_by=__class__` → reflective `getattr` probing

---

## Requirements

1. `limit` on all three affected endpoints must have a `ge=1, le=200` FastAPI `Query`
   constraint so invalid values are rejected with 422 before any DB query runs.
2. `sort_by` on `/scanner/results` must be validated against an explicit allowlist of
   known `ScannerEvent` column names; unknown values return 422.
3. The fix must not change default values (keeping current defaults intact preserves
   all existing frontend calls without modification).
4. Verification: `?limit=10000000` → 422; `?sort_by=__class__` → 422.
5. Tests cover both the limit cap and the sort allowlist rejection.

---

## Architecture / Approach

### Limit cap — use FastAPI `Query` with bounds

Follow the existing pattern in `routers/tweets.py:59`:
```python
limit: int = Query(50, ge=1, le=200)
```

Apply to all three endpoints, preserving their current defaults:

| Endpoint | Current default | New declaration |
|---|---|---|
| `GET /scanner/results` | `limit: int = 100` | `limit: int = Query(100, ge=1, le=200)` |
| `GET /scanner/history` | `limit: int = 20` | `limit: int = Query(20, ge=1, le=200)` |
| `GET /outcomes/signals` | `limit: int = 100` | `limit: int = Query(100, ge=1, le=200)` |

FastAPI enforces the constraint before the handler body runs; the client receives a
standard 422 Unprocessable Entity with a field-level validation error.

### Sort allowlist — replace reflective `getattr` with a column dict

**Only `/scanner/results`** has the reflective-sort issue. The current code
(`scanner.py:408-421`) does:
```python
sort_attr = getattr(ScannerEvent, sort_by, ScannerEvent.created_at)
```

The fallback masks bad input rather than rejecting it. Replace with an explicit dict:

```python
SCANNER_RESULTS_SORT_COLUMNS = {
    "signal_quality_score": ScannerEvent.signal_quality_score,
    "event_date": ScannerEvent.event_date,
    "ticker": ScannerEvent.ticker,
    "severity": ScannerEvent.severity,
    "created_at": ScannerEvent.created_at,
}
```

The allowlist covers every sort key the frontend sends (`useScannerState.ts:79`
defaults to `signal_quality_score`; `ScannerResults.tsx` exposes `event_date`,
`ticker`, `severity`, `signal_quality_score`).

Validation:
```python
if sort_by and sort_by not in SCANNER_RESULTS_SORT_COLUMNS:
    raise HTTPException(status_code=422, detail=f"Invalid sort field: {sort_by}")
sort_attr = SCANNER_RESULTS_SORT_COLUMNS.get(sort_by, ScannerEvent.signal_quality_score)
```

The surrounding `try/except Exception` block (which swallowed bad input silently) is
removed — the explicit guard makes it redundant.

**`/outcomes/signals`** delegates to `StatsService.get_signals()` which already uses
a `sort_col_map` dict with a safe `.get(sort_by, default)` fallback (`stats.py:463`).
No change needed there; only the `limit` cap is missing.

### No schema/migration changes

All changes are in router function signatures and the sorting block. No model changes,
no new tables, no Alembic migration required.

---

## Alternatives Considered

### A: Raise HTTPException on unknown sort, keep `getattr` for known fields
Would still require allowlist enumeration, adds indirection, and `getattr` on a
verified key is identical to a dict lookup. The dict approach (`StatsService` already
uses it) is the established project pattern.

### B: Clamp `limit` silently (min/max enforcement without rejection)
Silently capping to 200 is less correct — the caller would receive different data
than requested with no indication. FastAPI's `ge`/`le` constraints yield a 422 with a
descriptive error, matching the issue's verification requirement.

---

## Open Questions

- None blocking. The frontend's maximum displayed result count is 100 (hardcoded in
  `useScannerState.ts`), so `le=200` gives 2× headroom for any API-direct use.

---

## Assumptions

- `le=200` is sufficient for legitimate `/scanner/results` use. The frontend never
  requests more than 100 (`frontend/src/pages/Scanner/index.tsx:50`). The bulk export
  path (`syncUniverseAggregates`) hits a different endpoint and is unaffected.
- `/scanner/history` is low-impact (queries `scanner_runs`, a small table) but should
  be fixed consistently for completeness.
- The five allowlisted sort fields (`signal_quality_score`, `event_date`, `ticker`,
  `severity`, `created_at`) cover all frontend sort interactions. Adding new sort
  columns in the future requires an explicit allowlist entry — this is intentional.

---

## Implementation Checklist

- [ ] `backend/app/routers/scanner.py` — cap `limit` on `/history` and `/results`
- [ ] `backend/app/routers/scanner.py` — add `SCANNER_RESULTS_SORT_COLUMNS` dict,
  replace `getattr` + remove silent `try/except`, add 422 guard
- [ ] `backend/app/routers/outcomes.py` — cap `limit` on `/signals/{scanner_type}`
- [ ] `backend/tests/api/test_scanner.py` — add tests: `limit=10000000` → 422,
  `sort_by=__class__` → 422, `sort_by=signal_quality_score` → 200
- [ ] `backend/tests/api/test_outcomes.py` — add test: `limit=10000000` → 422
