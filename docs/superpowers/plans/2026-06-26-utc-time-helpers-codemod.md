# Plan: UTC Time Helpers — Extend `app/utils/time.py` and Codemod Remaining Sites

**Issue:** #632
**Spec:** `docs/superpowers/specs/2026-06-26-utc-time-helpers-codemod-design.md`
**Date:** 2026-06-26
**Branch:** `refine/issue-632-architecture-v4--extract-app-utils-time-`

## Goal

Extend the existing `backend/app/utils/time.py` with one new function (`ensure_utc`) and codemod the remaining ~24 raw UTC-stamping patterns in `backend/app/` that were not covered by the prior issue #286 work. Add a `TestEnsureUtc` test class and wire a DTZ ruff lint guard to prevent regression.

## Architecture

The `backend/app/utils/time.py` module already exists with `utc_now()` (returns naive datetime) and `to_utc_naive()` (aware→naive conversion). The new `ensure_utc(dt)` fills the missing tz-aware stamping use case: it stamps a naive datetime with UTC tzinfo (idempotent — no-op if already aware). This creates a complete set:

| Helper | Input | Output | Replaces |
|---|---|---|---|
| `utc_now()` | — | naive UTC now | `datetime.now(timezone.utc).replace(tzinfo=None)` |
| `to_utc_naive(dt)` | any aware | naive UTC | `.astimezone(timezone.utc).replace(tzinfo=None)` |
| `ensure_utc(dt)` | naive or aware | tz-aware (UTC stamp) | `.replace(tzinfo=timezone.utc)` |

## File Structure

| File | Change |
|---|---|
| `backend/app/utils/time.py` | Add `ensure_utc(dt)` |
| `backend/tests/test_time_utils.py` | Add `TestEnsureUtc` class |
| `backend/app/tasks/scanning.py` | Patterns 1, 2, 3 — 3 replacements (Tasks 2 + 3, sequential) |
| `backend/app/tasks/quality.py` | Pattern 2 — 1 replacement |
| `backend/app/services/regime_service.py` | Pattern 2 + new import — 1 replacement |
| `backend/app/routers/scanner.py` | Pattern 3 — 2 replacements |
| `backend/app/routers/system.py` | Pattern 3 + remove unused `timezone` — 1 replacement |
| `backend/app/services/system_service.py` | Pattern 3 — 1 replacement |
| `backend/app/services/scanner_query_service.py` | Pattern 3 + remove unused `timezone` — 2 replacements |
| `backend/app/services/futures_aggregates.py` | Pattern 3 + new import — 1 replacement |
| `backend/app/services/liquidity_hunt.py` | Pattern 3 + new import — 1 replacement |
| `backend/app/services/quality_gate_evidence.py` | Pattern 3 + new import — 1 replacement |
| `backend/app/services/pre_market_scan.py` | Pattern 3 — 4 replacements |
| `backend/app/providers/ibkr.py` | Pattern 3 + new import — 4 replacements |
| `backend/app/utils/session.py` | Pattern 3 + new import + remove unused `timezone` — 1 replacement |
| `backend/pyproject.toml` | Add `DTZ003` + `DTZ004` to ruff select; add per-file ignores |

---

## Task 1: TDD — Add `ensure_utc` to `time.py` and `TestEnsureUtc` to tests

**Files:** `backend/tests/test_time_utils.py`, `backend/app/utils/time.py`

### Step 1.1 — Write failing tests

Add `TestEnsureUtc` class to `backend/tests/test_time_utils.py` immediately after `TestToUtcNaive`:

```python
class TestEnsureUtc:
    def test_naive_becomes_utc_aware(self):
        from datetime import datetime, timezone

        naive = datetime(2024, 1, 15, 10, 30, 0)
        result = ensure_utc(naive)
        assert result.tzinfo == timezone.utc
        assert result.replace(tzinfo=None) == naive  # value preserved

    def test_already_aware_passthrough(self):
        from datetime import datetime, timezone

        aware = datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
        assert ensure_utc(aware) is aware  # identity preserved (idempotent)

    def test_non_utc_aware_preserved(self):
        import zoneinfo
        from datetime import datetime

        et = zoneinfo.ZoneInfo("America/New_York")
        aware_et = datetime(2024, 1, 15, 10, 30, 0, tzinfo=et)
        result = ensure_utc(aware_et)
        # Stamps only naive datetimes; non-UTC aware datetimes pass through unchanged
        assert result is aware_et
```

Also update the import line at the top of the test file (currently `from app.utils.time import to_utc_naive, utc_now`):

```python
from app.utils.time import ensure_utc, to_utc_naive, utc_now
```

### Step 1.2 — Verify tests fail

```bash
docker-compose exec backend python -m pytest backend/tests/test_time_utils.py -x -q
```

Expected: `ImportError: cannot import name 'ensure_utc'` or `AttributeError`. Tests must fail before implementation.

### Step 1.3 — Implement `ensure_utc`

Extend `backend/app/utils/time.py` by appending `ensure_utc` after `to_utc_naive`:

```python
from datetime import datetime, timezone


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def to_utc_naive(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def ensure_utc(dt: datetime) -> datetime:
    """Stamp a naive datetime with UTC tzinfo. No-op if already tz-aware."""
    if dt.tzinfo is not None:
        return dt
    return dt.replace(tzinfo=timezone.utc)
```

### Step 1.4 — Verify tests pass

```bash
docker-compose exec backend python -m pytest backend/tests/test_time_utils.py -x -q
```

Expected output: `3 passed` in `TestEnsureUtc`, all existing tests still passing.

### Step 1.5 — Commit

```bash
git add backend/app/utils/time.py backend/tests/test_time_utils.py
git commit -m "feat(time): add ensure_utc() — idempotent tz-aware stamp helper (#632)"
```

---

## Task 2: Codemod `datetime.utcnow()` and `datetime.now(timezone.utc).replace(tzinfo=None)` → `utc_now()`

**Files:** `backend/app/tasks/scanning.py`, `backend/app/tasks/quality.py`, `backend/app/services/regime_service.py`

These replacements target Pattern 1 (deprecated `utcnow()`) and Pattern 2 (inline `utc_now()` equivalent). All three target files either already import `utc_now` or will after this task.

### Step 2.1 — Baseline grep (verify old patterns exist)

```bash
grep -rn "datetime\.utcnow()\|datetime\.now(timezone\.utc)\.replace(tzinfo=None)" backend/app/
```

Expected: 3 matches (scanning.py:518, scanning.py:188, quality.py:90, regime_service.py:192 — 4 total).

### Step 2.2 — Apply replacements

**`backend/app/tasks/scanning.py:518`** — replace `datetime.utcnow()` → `utc_now()`:

Old:
```python
{"task_ids": [task_id], "started_at": datetime.utcnow().isoformat()}
```
New:
```python
{"task_ids": [task_id], "started_at": utc_now().isoformat()}
```

This file already imports `utc_now` at line 17. No import change needed. After this edit, `datetime` may become unused at line 5 — run `ruff check --select F401 backend/app/tasks/scanning.py` to confirm whether `datetime` can be removed from the import (it's also used elsewhere in scanning.py, so likely stays).

**`backend/app/tasks/scanning.py:188`** — replace `.now(timezone.utc).replace(tzinfo=None)`:

Old:
```python
        now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
```
New:
```python
        now_utc = utc_now()
```

**`backend/app/tasks/quality.py:90`** — same pattern:

Old:
```python
    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
```
New:
```python
    now_utc = utc_now()
```

This file already imports `utc_now`. After edit, check if `timezone` is still used elsewhere in `quality.py`:
```bash
grep -n "timezone" backend/app/tasks/quality.py
```
Remove `timezone` from `from datetime import datetime, timezone` if F401 shows it unused.

**`backend/app/services/regime_service.py:192`** — add import and replace:

The file currently imports `from datetime import datetime, timedelta, timezone` with no `app.utils.time` import. Add:
```python
from app.utils.time import utc_now
```
(Place with other `app.*` imports, after `from app.models.regime_model import RegimeModel`.)

Old:
```python
        trained_at = datetime.now(timezone.utc).replace(tzinfo=None)
```
New:
```python
        trained_at = utc_now()
```

After edit, check `timezone` usage in regime_service.py:
```bash
grep -n "timezone" backend/app/services/regime_service.py
```
There are 4 `timezone` occurrences; we replaced one. Keep `timezone` in the import (3 remaining uses).

### Step 2.3 — Verify: grep shows 0 matches, tests pass

```bash
grep -rn "datetime\.utcnow()\|datetime\.now(timezone\.utc)\.replace(tzinfo=None)" backend/app/
# Expected: 0 results (backend/app/utils/time.py itself is excluded — it defines utc_now internally)
grep "datetime\.now(timezone\.utc)\.replace" backend/app/utils/time.py
# Expected: 1 match (the internal definition of utc_now — this is intentional, not a target)
```

```bash
docker-compose exec backend python -m pytest backend/tests/ -x -q --tb=short
```

Expected: no new failures.

### Step 2.4 — Commit

```bash
git add backend/app/tasks/scanning.py backend/app/tasks/quality.py backend/app/services/regime_service.py
git commit -m "refactor(time): codemod utcnow/now-replace-None → utc_now() in tasks + regime_service (#632)"
```

---

## Task 3: Codemod `.replace(tzinfo=timezone.utc)` in `routers/` and `tasks/scanning.py`

**Files:** `backend/app/tasks/scanning.py`, `backend/app/routers/scanner.py`, `backend/app/routers/system.py`

### Step 3.1 — Baseline grep

```bash
grep -n "\.replace(tzinfo=timezone\.utc)" backend/app/tasks/scanning.py backend/app/routers/scanner.py backend/app/routers/system.py
```

Expected matches:
- `scanning.py:356`
- `routers/scanner.py:165`
- `routers/scanner.py:206`
- `routers/system.py:59`

### Step 3.2 — Apply replacements

**`backend/app/tasks/scanning.py:356`** — `scanning.py` already imports `utc_now`; add `ensure_utc`:

Update the import on line 17 (currently `from app.utils.time import utc_now`):
```python
from app.utils.time import ensure_utc, utc_now
```

Old (line ~356):
```python
            "started_at": started_at.replace(tzinfo=timezone.utc).isoformat(),
```
New:
```python
            "started_at": ensure_utc(started_at).isoformat(),
```

After this edit (combined with Task 2's changes), check if `timezone` is still used in `scanning.py`:
```bash
grep -n "\btimezone\b" backend/app/tasks/scanning.py
```
Remove `timezone` from the datetime import if F401 confirms it's unused.

**`backend/app/routers/scanner.py:165` and `scanner.py:206`** — the file already imports `utc_now` at line 53; add `ensure_utc`:

```python
# Old (line 53):
from app.utils.time import utc_now
# New:
from app.utils.time import ensure_utc, utc_now
```

Old (line 165):
```python
        started_at = started_at.replace(tzinfo=timezone.utc)
```
New:
```python
        started_at = ensure_utc(started_at)
```

Old (line 206):
```python
        started_at = started_at.replace(tzinfo=timezone.utc)
```
New:
```python
        started_at = ensure_utc(started_at)
```

After edits, check `timezone` usage in `routers/scanner.py`:
```bash
grep -n "\btimezone\b" backend/app/routers/scanner.py
```
`scanner.py` imports `from datetime import date, datetime, timedelta, timezone` — if `timezone` only appears in these 2 now-replaced lines, remove it; otherwise keep.

**`backend/app/routers/system.py:59`** — add `ensure_utc` import (file currently has only `from datetime import timezone`):

Add after `from datetime import timezone`:
```python
from app.utils.time import ensure_utc
```

Old (line 59):
```python
                ts = ts.replace(tzinfo=timezone.utc)
```
New:
```python
                ts = ensure_utc(ts)
```

After edit, check if `timezone` is the last consumer in `routers/system.py`:
```bash
grep -n "\btimezone\b" backend/app/routers/system.py
```
If the only occurrence was line 59, remove `from datetime import timezone` entirely.

### Step 3.3 — Verify

```bash
grep -n "\.replace(tzinfo=timezone\.utc)" backend/app/tasks/scanning.py backend/app/routers/scanner.py backend/app/routers/system.py
# Expected: 0 matches
docker-compose exec backend python -m pytest backend/tests/ -x -q --tb=short
```

### Step 3.4 — Commit

```bash
git add backend/app/tasks/scanning.py backend/app/routers/scanner.py backend/app/routers/system.py
git commit -m "refactor(time): codemod .replace(tzinfo=timezone.utc) → ensure_utc() in routers + scanning (#632)"
```

---

## Task 4: Codemod `.replace(tzinfo=timezone.utc)` in `services/`

**Files:** `backend/app/services/system_service.py`, `backend/app/services/scanner_query_service.py`, `backend/app/services/futures_aggregates.py`, `backend/app/services/liquidity_hunt.py`, `backend/app/services/quality_gate_evidence.py`, `backend/app/services/pre_market_scan.py`

### Step 4.1 — Baseline grep

```bash
grep -n "\.replace(tzinfo=timezone\.utc)" \
  backend/app/services/system_service.py \
  backend/app/services/scanner_query_service.py \
  backend/app/services/futures_aggregates.py \
  backend/app/services/liquidity_hunt.py \
  backend/app/services/quality_gate_evidence.py \
  backend/app/services/pre_market_scan.py
```

Expected: 10 matches (1 + 2 + 1 + 1 + 1 + 4).

### Step 4.2 — `backend/app/services/system_service.py`

File already imports `utc_now`; extend:
```python
# Old:
from app.utils.time import utc_now
# New:
from app.utils.time import ensure_utc, utc_now
```

Old (line ~152):
```python
                started = datetime.fromisoformat(ts_str).replace(tzinfo=timezone.utc)
```
New:
```python
                started = ensure_utc(datetime.fromisoformat(ts_str))
```

After edit, **keep `timezone` in the import**. Line 153 uses `datetime.now(timezone.utc) - started` — a bare tz-aware call intentionally preserved per Requirement 9 (not a codemod target). Do not remove `timezone` from `from datetime import datetime, timedelta, timezone`.

### Step 4.3 — `backend/app/services/scanner_query_service.py`

File currently imports `from datetime import timezone` with no `app.utils.time` import. Replace that import:

```python
# Old:
from datetime import timezone
# New:
from app.utils.time import ensure_utc
```

(Remove the `datetime import timezone` line entirely; `ensure_utc` covers both patterns here.)

Old (line 35):
```python
                ts = ts.replace(tzinfo=timezone.utc)
```
New:
```python
                ts = ensure_utc(ts)
```

Old (line 58):
```python
                    r.created_at.replace(tzinfo=timezone.utc).isoformat()
```
New:
```python
                    ensure_utc(r.created_at).isoformat()
```

### Step 4.4 — `backend/app/services/futures_aggregates.py`

File imports `from datetime import datetime, timedelta, timezone` with no `app.utils.time` import. Add:
```python
from app.utils.time import ensure_utc
```
(Place with other `app.*` imports after the `from app.services.*` block.)

Old (line 261):
```python
                datetime.strptime(to_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
```
New:
```python
                ensure_utc(datetime.strptime(to_date, "%Y-%m-%d"))
```

After edit, `futures_aggregates.py` uses `timezone` at lines 70, 73, 84, 256, 258, 273, 277 for other patterns — keep `timezone` in the datetime import.

### Step 4.5 — `backend/app/services/liquidity_hunt.py`

File already imports `from app.utils.time import to_utc_naive` at line 38. Extend it:
```python
# Old (line 38):
from app.utils.time import to_utc_naive
# New:
from app.utils.time import ensure_utc, to_utc_naive
```

Old (line ~309):
```python
        ts_et = r.timestamp.replace(tzinfo=timezone.utc).astimezone(_ET)
```
New:
```python
        ts_et = ensure_utc(r.timestamp).astimezone(_ET)
```

`liquidity_hunt.py` uses `timezone` extensively for other things — keep `timezone` in the import.

### Step 4.6 — `backend/app/services/quality_gate_evidence.py`

File imports `from datetime import datetime, timezone` with no `app.utils.time` import. Add:
```python
from app.utils.time import ensure_utc
```

Old (line ~243):
```python
        ts = ts.replace(tzinfo=timezone.utc)
```
New:
```python
        ts = ensure_utc(ts)
```

After edit, check remaining `timezone` usage:
```bash
grep -n "\btimezone\b" backend/app/services/quality_gate_evidence.py
```
If `timezone` is no longer used after the replacement (the other occurrences are in function names/comments/string literals, not as `timezone.utc`), remove it from the import. Confirm with `ruff check --select F401`.

### Step 4.7 — `backend/app/services/pre_market_scan.py`

File imports `from app.utils.time import to_utc_naive`; extend:
```python
# Old:
from app.utils.time import to_utc_naive
# New:
from app.utils.time import ensure_utc, to_utc_naive
```

Four replacements:

Old (line ~197):
```python
            bar_ts = bar_ts.replace(tzinfo=timezone.utc)
```
New:
```python
            bar_ts = ensure_utc(bar_ts)
```

Old (line ~231):
```python
            ref_ts = ref_ts.replace(tzinfo=timezone.utc)
```
New:
```python
            ref_ts = ensure_utc(ref_ts)
```

Old (line ~233):
```python
            cat_latest = cat_latest.replace(tzinfo=timezone.utc)
```
New:
```python
            cat_latest = ensure_utc(cat_latest)
```

Old (line ~586):
```python
                else _max_bar_ts.replace(tzinfo=timezone.utc)
```
New:
```python
                else ensure_utc(_max_bar_ts)
```

After edits, check `timezone` usage in `pre_market_scan.py`:
```bash
grep -n "\btimezone\b" backend/app/services/pre_market_scan.py
```
`pre_market_scan.py` imports `from datetime import date, datetime, time, timedelta, timezone` — if `timezone` remains used elsewhere (e.g. in `ZoneInfo` calls or other expressions), keep it; otherwise remove.

### Step 4.8 — Verify

```bash
grep -n "\.replace(tzinfo=timezone\.utc)" \
  backend/app/services/system_service.py \
  backend/app/services/scanner_query_service.py \
  backend/app/services/futures_aggregates.py \
  backend/app/services/liquidity_hunt.py \
  backend/app/services/quality_gate_evidence.py \
  backend/app/services/pre_market_scan.py
# Expected: 0 matches

docker-compose exec backend python -m pytest backend/tests/ -x -q --tb=short
```

Also run ruff to catch any unused imports:
```bash
docker-compose exec backend ruff check --select F401 backend/app/services/
```

### Step 4.9 — Commit

```bash
git add \
  backend/app/services/system_service.py \
  backend/app/services/scanner_query_service.py \
  backend/app/services/futures_aggregates.py \
  backend/app/services/liquidity_hunt.py \
  backend/app/services/quality_gate_evidence.py \
  backend/app/services/pre_market_scan.py
git commit -m "refactor(time): codemod .replace(tzinfo=timezone.utc) → ensure_utc() in services/ (#632)"
```

---

## Task 5: Codemod `.replace(tzinfo=timezone.utc)` in `providers/` and `utils/`

**Files:** `backend/app/providers/ibkr.py`, `backend/app/utils/session.py`

### Step 5.1 — Baseline grep

```bash
grep -n "\.replace(tzinfo=timezone\.utc)" backend/app/providers/ibkr.py backend/app/utils/session.py
```

Expected: 5 matches (4 in ibkr.py, 1 in session.py).

### Step 5.2 — `backend/app/providers/ibkr.py`

File imports `from datetime import datetime, timedelta, timezone` with no `app.utils.time` import. Add:
```python
from app.utils.time import ensure_utc
```
(Place with other `app.*` imports, e.g., after `from app.exceptions import ProviderError`.)

Four replacements:

Old (line ~572):
```python
                datetime.strptime(to_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
```
New:
```python
                ensure_utc(datetime.strptime(to_date, "%Y-%m-%d"))
```

Old (line ~580):
```python
            datetime.strptime(from_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
```
New:
```python
            ensure_utc(datetime.strptime(from_date, "%Y-%m-%d"))
```

Old (line ~741):
```python
                return bar_date.replace(tzinfo=timezone.utc)
```
New:
```python
                return ensure_utc(bar_date)
```

Old (line ~749):
```python
                return dt.replace(tzinfo=timezone.utc)
```
New:
```python
                return ensure_utc(dt)
```

After edits, check `timezone` usage in `ibkr.py`:
```bash
grep -n "\btimezone\b" backend/app/providers/ibkr.py
```
`ibkr.py` uses `timezone` extensively for other purposes (IBKR TWS API calls use timezone-aware datetimes) — keep `timezone` in the import.

### Step 5.3 — `backend/app/utils/session.py`

File imports `from datetime import date, datetime, timezone`. Add:
```python
from app.utils.time import ensure_utc
```
(Place after the `from datetime` import.)

Old (line ~18):
```python
        ts = ts.replace(tzinfo=timezone.utc)
```
New:
```python
        ts = ensure_utc(ts)
```

After edit, check `timezone` usage in `session.py`:
```bash
grep -n "\btimezone\b" backend/app/utils/session.py
```
The next line (`et = ts.astimezone(_ET)`) does not reference `timezone` directly. If this was the only `timezone` usage, remove it from `from datetime import date, datetime, timezone` → `from datetime import date, datetime`.

### Step 5.4 — Verify

```bash
grep -n "\.replace(tzinfo=timezone\.utc)" backend/app/providers/ibkr.py backend/app/utils/session.py
# Expected: 0 matches

docker-compose exec backend python -m pytest backend/tests/ -x -q --tb=short
```

Final global check — no raw patterns should remain in `backend/app/` (except `time.py`'s internal definition of `utc_now`):
```bash
grep -rn "\.replace(tzinfo=timezone\.utc)\|datetime\.utcnow()\|datetime\.now(timezone\.utc)\.replace(tzinfo=None)" backend/app/ | grep -v "backend/app/utils/time.py"
# Expected: 0 matches
```

### Step 5.5 — Commit

```bash
git add backend/app/providers/ibkr.py backend/app/utils/session.py
git commit -m "refactor(time): codemod .replace(tzinfo=timezone.utc) → ensure_utc() in providers/ + utils/ (#632)"
```

---

## Task 6: Wire DTZ ruff lint guard in `pyproject.toml`

**File:** `backend/pyproject.toml`

### Step 6.1 — Baseline: confirm current ruff config

```bash
grep -A 15 "\[tool.ruff.lint\]" backend/pyproject.toml
```

Expected current `select`:
```toml
select = ["E", "W", "F", "I"]
```

### Step 6.2 — Apply DTZ rule additions

In `backend/pyproject.toml`, update `[tool.ruff.lint]` `select` line:

```toml
# Old:
select = ["E", "W", "F", "I"]

# New:
select = ["E", "W", "F", "I", "DTZ003", "DTZ004"]
```

> **Why `DTZ003` + `DTZ004` only (not full `DTZ`):** Per the spec, start with the narrow set targeting only deprecated patterns (`utcnow()` and `utcfromtimestamp()`). The full `DTZ` ruleset includes DTZ007 which flags `datetime.strptime()` calls (producing naive datetimes) — several legitimate sites in ibkr.py and futures_aggregates.py use `strptime` followed by `ensure_utc()` which is correct. Starting narrow avoids noise while guarding the specific patterns codemoded in this issue.

In `[tool.ruff.lint.per-file-ignores]`, add two new entries:

```toml
"app/utils/time.py" = ["DTZ"]           # internals use raw timezone.utc by design
"**/tests/**" = ["DTZ003", "DTZ004"]    # test files keep raw patterns (pragmatism)
```

Full updated `[tool.ruff.lint.per-file-ignores]` block after changes:

```toml
[tool.ruff.lint.per-file-ignores]
"**/__init__.py" = ["F401"]
# Tests import app modules after sys.path manipulation (E402); fixtures are redefined per-test
# (F811 is intentional pytest pattern); unused vars in tests are intermediate assertions (F841)
"**/tests/**/*.py" = ["E402", "F811", "F841"]
# Scripts use star imports for schema reflection and import after path setup
"**/scripts/**/*.py" = ["E402", "F403", "W291", "W293"]
# time.py internals deliberately use raw timezone.utc to build the utc_now/ensure_utc helpers
"app/utils/time.py" = ["DTZ"]
# Tests keep raw datetime patterns (test pragmatism; no .replace(tzinfo=...) targets anyway)
"**/tests/**" = ["DTZ003", "DTZ004"]
```

### Step 6.3 — Verify ruff passes on all codemoded files

```bash
docker-compose exec backend ruff check --select DTZ003,DTZ004 backend/app/
```

Expected output: no violations. If any file is flagged, add a `# noqa: DTZ003` or `# noqa: DTZ004` inline comment at the specific site and document why it is intentional.

### Step 6.4 — Verify full ruff + pytest suite

```bash
docker-compose exec backend ruff check backend/
docker-compose exec backend python -m pytest backend/tests/ -q --tb=short
```

Expected: 0 ruff violations, 0 test failures.

### Step 6.5 — Commit

```bash
git add backend/pyproject.toml
git commit -m "chore(lint): add DTZ003+DTZ004 ruff guard to prevent utcnow() re-accumulation (#632)"
```

---

## Summary

| Task | Files | Steps | Commit message |
|---|---|---|---|
| 1 | `utils/time.py`, `tests/test_time_utils.py` | TDD: write tests → implement `ensure_utc` | `feat(time): add ensure_utc()` |
| 2 | `tasks/scanning.py`, `tasks/quality.py`, `services/regime_service.py` | Codemod patterns 1 + 2 (4 sites) | `refactor(time): codemod utcnow/now-replace-None` |
| 3 | `tasks/scanning.py`, `routers/scanner.py`, `routers/system.py` | Codemod pattern 3 (4 sites) | `refactor(time): codemod .replace() in routers + scanning` |
| 4 | 6 service files | Codemod pattern 3 (10 sites) | `refactor(time): codemod .replace() in services/` |
| 5 | `providers/ibkr.py`, `utils/session.py` | Codemod pattern 3 (5 sites) | `refactor(time): codemod .replace() in providers/ + utils/` |
| 6 | `pyproject.toml` | Wire DTZ003+DTZ004 ruff guard | `chore(lint): add DTZ lint guard` |

**Total:** ~24 codemod edits across 15 files, 1 new function, 1 test class, 1 lint rule.
