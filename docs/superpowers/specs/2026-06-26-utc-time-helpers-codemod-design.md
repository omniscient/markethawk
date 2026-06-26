# UTC Time Helpers — Extend `app/utils/time.py` and Codemod Remaining Sites

**Status:** design
**Date:** 2026-06-26
**Issue:** #632 (architecture-audit-v4 — R03 UTC normalization duplication)
**Predecessor:** Issue #286 (initial `utc_now`/`to_utc_naive` extraction)

## Problem

The v4 architecture review (R03-v4, Medium severity) flagged UTC-normalization patterns as duplicated across the codebase and worsening across reviews (96 sites in v3 → 287 raw `timezone.utc` references in v4). A shared helper module `backend/app/utils/time.py` already exists — introduced in issue #286 — and has been adopted at 55+ call sites for `utc_now()` and `to_utc_naive()`. However, a second class of raw UTC-stamping patterns (`.replace(tzinfo=timezone.utc)`) was not covered by those two functions, leaving ~24 additional duplicated sites in production code that suppress the Maintainability score.

The fix is bounded: add one new function (`ensure_utc`) to the existing module, codemod the remaining raw patterns, add a test class, and wire a ruff lint guard so the patterns cannot re-accumulate.

> **Important context for implementers**: The issue body describes adding `app/utils/time.py` as if it doesn't exist — it does. Do NOT recreate or replace the file. Extend it.

## Requirements

1. Add `ensure_utc(dt: datetime) -> datetime` to `backend/app/utils/time.py` — stamps a naive datetime with UTC tzinfo, idempotent (no-op if already tz-aware). Returns a **tz-aware** datetime (distinct from `to_utc_naive` which returns naive).
2. Codemod all `datetime.utcnow()` calls in `backend/app/` to `utc_now()` (deprecated Python function, ~1 site).
3. Codemod all `datetime.now(timezone.utc).replace(tzinfo=None)` inline duplicates in `backend/app/` to `utc_now()` (~4 sites).
4. Codemod all `.replace(tzinfo=timezone.utc)` patterns in `backend/app/` to `ensure_utc(...)` (~19 sites).
5. Add a `TestEnsureUtc` class to `backend/tests/test_time_utils.py` covering: idempotent no-op on already-aware datetime, naive input → tz-aware UTC output, and non-UTC aware input preserved.
6. Add `DTZ` ruff rules to `backend/pyproject.toml` with per-file ignores for `time.py` and `**/tests/**` so the codemod cannot silently regress.
7. **Do not** codemod `backend/tests/` — test files keep raw `datetime.now(timezone.utc)` patterns (test pragmatism; no `.replace(tzinfo=timezone.utc)` targets exist there anyway).
8. **Do not** replace `datetime.fromtimestamp(ts, tz=timezone.utc)` — epoch-to-aware conversions are already correct and readable; wrapping them would require a fourth unlisted function.
9. **Do not** replace bare `datetime.now(timezone.utc)` calls not followed by `.replace(tzinfo=None)` — these are intentionally tz-aware (used in `.date()`, `.isoformat()`, timedelta arithmetic, SQLAlchemy `default=` lambdas).
10. Keep `to_utc_naive` as-is (23 active call sites, established memory pattern). Do not rename it or introduce a `local_to_utc` alias — the `_naive` suffix correctly signals the return type distinction from `ensure_utc`.

## Architecture / Approach

### 1. Extend `backend/app/utils/time.py`

```python
from datetime import datetime, timezone


def utc_now() -> datetime:
    """Return current UTC time as a naive datetime (no tzinfo)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def to_utc_naive(dt: datetime) -> datetime:
    """Convert any aware datetime to a naive UTC datetime. Passthrough if already naive."""
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def ensure_utc(dt: datetime) -> datetime:
    """Stamp a naive datetime with UTC tzinfo. No-op if already tz-aware."""
    if dt.tzinfo is not None:
        return dt
    return dt.replace(tzinfo=timezone.utc)
```

> `ensure_utc` is idempotent: safe to call on a datetime that may or may not already carry tzinfo (e.g. `ibkr.py:739-742` branch logic).

### 2. Codemod targets (all in `backend/app/`)

| Pattern | Replacement | Est. sites |
|---|---|---|
| `datetime.utcnow()` | `utc_now()` | 1 |
| `datetime.now(timezone.utc).replace(tzinfo=None)` | `utc_now()` | 4 |
| `<expr>.replace(tzinfo=timezone.utc)` | `ensure_utc(<expr>)` | ~19 |

Total: ~24 edits. Files span `tasks/scanning.py`, `tasks/sync.py`, `tasks/quality.py`, `services/futures_aggregates.py`, `services/futures_contracts.py`, `services/universe_orchestrator.py`, `services/regime_service.py`, `providers/ibkr.py`, `routers/stocks.py`, and others.

Each edited file must add `from app.utils.time import ensure_utc` (or extend an existing import) and remove the now-unused `timezone` import if it's the last consumer in that file.

### 3. Test additions (`backend/tests/test_time_utils.py`)

Add a `TestEnsureUtc` class alongside the existing `TestUtcNow` and `TestToUtcNaive` classes:

```python
class TestEnsureUtc:
    def test_naive_becomes_utc_aware(self):
        naive = datetime(2024, 1, 15, 10, 30, 0)
        result = ensure_utc(naive)
        assert result.tzinfo == timezone.utc
        assert result.replace(tzinfo=None) == naive  # value preserved

    def test_already_aware_passthrough(self):
        aware = datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
        assert ensure_utc(aware) is aware  # identity preserved

    def test_non_utc_aware_preserved(self):
        import zoneinfo
        et = zoneinfo.ZoneInfo("America/New_York")
        aware_et = datetime(2024, 1, 15, 10, 30, 0, tzinfo=et)
        result = ensure_utc(aware_et)
        # Function stamps naive datetimes; non-UTC aware datetimes pass through unchanged
        assert result is aware_et
```

### 4. Ruff lint guard (`backend/pyproject.toml`)

Add `"DTZ"` to `[tool.ruff.lint] select` and configure per-file ignores:

```toml
[tool.ruff.lint]
select = ["E", "W", "F", "I", "DTZ"]

[tool.ruff.lint.per-file-ignores]
"app/utils/time.py" = ["DTZ"]           # helper internals use raw timezone.utc by design
"**/tests/**" = ["DTZ001", "DTZ003", "DTZ004", "DTZ005", "DTZ006", "DTZ007"]
```

If the full `DTZ` ruleset proves noisy (e.g. flags intentional `datetime.now(timezone.utc)` calls), narrow to `["DTZ003", "DTZ004"]` which target only `utcnow()` and `utcfromtimestamp()` — the specific deprecated patterns being codemoded.

## Alternatives Considered

### A. Rename `to_utc_naive` → `local_to_utc`

**Rejected.** `to_utc_naive` is the name specified in established memory pattern and documented in CLAUDE.md conventions. Renaming would churn 23 working call sites, break the pattern documentation, and lose the `_naive` suffix that signals the return type — especially important since `ensure_utc` returns tz-aware. The issue's `local_to_utc` name is satisfied by the existing function without a rename.

### B. Full codemod including `backend/tests/`

**Rejected.** `backend/tests/` has no `.replace(tzinfo=timezone.utc)` targets, and importing the helper being tested into test fixtures couples verification to implementation. ~30 raw `datetime.now(timezone.utc)` in tests are intentional and correct tz-aware values; converting them would add noise without reducing the architectural metric.

### C. Add `from_timestamp_utc(ts)` to cover `datetime.fromtimestamp(ts, tz=timezone.utc)` sites

**Rejected for this issue.** The epoch-to-UTC conversion pattern (1-2 sites in `ibkr.py`/`massive.py`) is already readable and correct. Adding a 4th helper for 2 sites is not justified by the issue's scope or the architectural observation.

## Open Questions

- If DTZ flags `datetime.now(timezone.utc)` calls without `.replace(tzinfo=None)` as violations, the implementer should choose between a `# noqa: DTZ005` suppression at each intentional site or narrowing the ruleset to `DTZ003`+`DTZ004` only. The spec prefers the narrower set as a starting point.

## Assumptions

- **[ASSUMPTION]** The v4 architecture review's "287 sites" count reflects all raw `timezone.utc` token occurrences across the codebase (including intentional tz-aware patterns and tests), not 287 duplicated helpers waiting to be replaced. The actual codemod target is ~24 edits in `backend/app/`.
- **[ASSUMPTION]** `ensure_utc` should be idempotent (no-op on already-aware input). This is consistent with the `to_utc_naive` passthrough-on-naive convention and is the safe default for call sites where the awareness state may vary (e.g. `ibkr.py` conditional branches).
- **[ASSUMPTION]** The `backend/pyproject.toml` ruff config uses `[tool.ruff.lint] select = ["E", "W", "F", "I"]` — this was verified in Q&A from codebase exploration.
