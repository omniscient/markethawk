# Implementation Plan: Strict Data Quality Gate for Automated Trading (Issue #496)

**Date:** 2026-06-22  
**Issue:** #496 | **Parent Epic:** #491  
**Spec:** `docs/superpowers/specs/2026-06-19-strict-quality-gate-automated-trading-design.md`  
**Blocked by (assumed merged):** #492 (quality gate service), #494 (scanner_run_id FK)

---

## Goal

Insert a strict data-quality gate as Guard 2.5 in `AutoTradeExecutor.maybe_execute()`. Every automated order — live or paper — must pass `quality_gate_service.assess(..., policy=QualityGatePolicy.strict)` before sizing and submission. `warning`/`blocked` verdicts refuse orders; `skipped` can bypass via `QUALITY_GATE_SKIP_BYPASS` SystemConfig key; gate service exceptions fail-closed.

## Architecture

**Integration point:** `backend/app/services/auto_trade_service.py`, inserted between Guard 2 (idempotency, line ~150) and Guard 3 (Redis lock, line ~152).

**Universe resolution path:** `event.scanner_run_id → ScannerRun.universe_id` (nullable FK added by #494). Null result → `skipped` verdict, bypassable.

**Refusal pattern:** structured `logger.warning(...)` + `return None` — identical to all 11 existing guards. No `AutoTradeOrder` row is written on refusal (constraint: `uq_auto_trade_symbol_strategy_date` would block recovery if a refusal row existed).

## Tech Stack

Backend: FastAPI + SQLAlchemy 2.0 (sync) + PostgreSQL + Redis + Celery  
Quality gate: `app.services.quality_gate_service` (merged via #492)  
Testing: pytest + fakeredis + transaction-rollback `db` fixture from `conftest.py`

---

## File Structure

| File | Change |
|---|---|
| `backend/app/models/scanner_event.py` | Add `scanner_run_id` nullable FK (if #494 not merged) |
| `backend/app/alembic/versions/<hash>_add_scanner_run_id_to_scanner_events.py` | Migration for FK (if #494 not merged) |
| `backend/app/services/auto_trade_service.py` | Add Guard 2.5, `_resolve_universe_id`, `_gate_passes` |
| `backend/tests/services/test_auto_trade_service.py` | Add 6 new test cases for gate verdicts |

---

## ⚠️ Gating Preconditions (Check Before Starting)

This plan **cannot be executed** until both prerequisites are satisfied:

1. **#492 (quality gate service) must be merged.** Check:
   ```bash
   ls backend/app/services/quality_gate_service.py 2>/dev/null || echo "MISSING — stop here"
   ```
   If MISSING: post an issue comment that #492 must be merged first and exit. The gate service must provide `quality_gate_service.assess(universe_id, event, policy, db)` returning `QualityGateAssessment(verdict, issue_codes, warning_codes)` and export `QualityGatePolicy` with a `.strict` value.

   **Also verify the verdict type**: check whether `QualityGateAssessment.verdict` is a plain `str` or an enum. If enum, update all `assessment.verdict == "trusted"` comparisons in `_gate_passes` and all `_gate_assessment("trusted")` mock setups to use the enum values instead.

2. **#494 (scanner_run_id FK) must be merged (or Task 1b completes it).** Check:
   ```bash
   grep "scanner_run_id" backend/app/models/scanner_event.py || echo "MISSING — run Task 1b"
   ```

If both preconditions pass → proceed directly to Task 2.

---

## Task 1 — Verify Prerequisites

**Files:** (read-only checks, no edits)

### Steps

1. Run the two checks from the Gating Preconditions section above.

2. Check if `scanner_run_id` FK exists in `ScannerEvent`:
   ```bash
   grep "scanner_run_id" backend/app/models/scanner_event.py
   ```
   If present → skip to Task 2. If absent → proceed with Task 1b.

3. If quality gate service is missing → stop per Gating Preconditions. Otherwise proceed to Task 2 (or Task 1b if FK is missing).

---

## Task 1b — Add `scanner_run_id` FK to `ScannerEvent` (only if #494 not merged)

> Skip this task if `scanner_run_id` already exists in the model.

**Files:**
- `backend/app/models/scanner_event.py`
- `backend/app/alembic/versions/<hash>_add_scanner_run_id_to_scanner_events.py`

### TDD Steps

1. **Write failing test** — add to `backend/tests/services/test_auto_trade_service.py`:
   ```python
   def test_scanner_event_has_scanner_run_id_column(db: Session):
       """Verify the FK column exists on ScannerEvent."""
       from app.models.scanner_event import ScannerEvent
       assert hasattr(ScannerEvent, "scanner_run_id")
       ev = ScannerEvent(
           ticker="TSLA",
           event_date=date.today(),
           scanner_type="pre_market_volume_spike",
           indicators={"last_trade_price": 100.0},
           criteria_met={},
           metadata_={},
           scanner_run_id=None,
       )
       db.add(ev)
       db.flush()
       assert ev.id is not None
   ```

2. **Verify test fails:**
   ```bash
   docker-compose exec backend python -m pytest tests/services/test_auto_trade_service.py::test_scanner_event_has_scanner_run_id_column -x -q 2>&1 | tail -10
   ```
   Expected: `AttributeError` or column missing.

3. **Implement** — add the FK column to `backend/app/models/scanner_event.py` after the `signal_cluster_id` column:
   ```python
   scanner_run_id = Column(
       Integer, ForeignKey("scanner_runs.id"), nullable=True, index=True
   )
   ```
   The existing `ForeignKey` import at the top of the file already includes `ForeignKey`.

4. **Generate migration:**
   ```bash
   docker-compose exec backend python -m alembic revision --autogenerate \
     -m "add_scanner_run_id_to_scanner_events"
   ```
   Expected output: `Generating .../alembic/versions/<hash>_add_scanner_run_id_to_scanner_events.py ... done`

5. **Review the generated migration file** before applying — open it and confirm it only adds the `scanner_run_id` column and index. Autogenerate can emit unrelated drift from the live DB; revert any spurious operations.

6. **Apply migration:**
   ```bash
   docker-compose exec backend python -m alembic upgrade head
   ```
   Expected output: `Running upgrade <prev> -> <hash>, add_scanner_run_id_to_scanner_events`

7. **Verify test passes:**
   ```bash
   docker-compose exec backend python -m pytest tests/services/test_auto_trade_service.py::test_scanner_event_has_scanner_run_id_column -x -q 2>&1 | tail -5
   ```
   Expected: `1 passed`

8. **Commit:**
   ```bash
   git add backend/app/models/scanner_event.py backend/app/alembic/versions/
   git commit -m "feat: add scanner_run_id FK to scanner_events for quality gate universe resolution (#496)"
   ```

---

## Task 2 — Write Failing Tests for Quality Gate Guard

**Files:** `backend/tests/services/test_auto_trade_service.py`

Write all six tests before any implementation. Each test patches `quality_gate_service.assess` and `redis.from_url`. Tests use the transaction-rollback `db` fixture from `conftest.py` (not MagicMock DB).

### Steps

1. **Add `GATE_PATCH` constant** (after existing imports — it's a string literal, no import needed):
   ```python
   GATE_PATCH = "app.services.auto_trade_service.quality_gate_service.assess"
   ```

2. **Add a helper to build a mock assessment** — import `QualityGateAssessment` lazily inside the helper so the module import does not fail at collection time when `quality_gate_service.py` doesn't exist yet (pre-#492):
   ```python
   def _gate_assessment(verdict: str, issue_codes=None, warning_codes=None):
       from app.services.quality_gate_service import QualityGateAssessment
       a = MagicMock(spec=QualityGateAssessment)
       a.verdict = verdict
       a.issue_codes = issue_codes or []
       a.warning_codes = warning_codes or []
       return a
   ```

3. **Add a helper to build an event with scanner_run_id:**
   ```python
   def _event_with_run(db, ticker="AAPL", scanner_run_id=None):
       from app.models.scanner_run import ScannerRun
       from app.models.stock_universe import StockUniverse

       # criteria is NOT NULL on StockUniverse
       universe = StockUniverse(name="Test Universe", description="", criteria={}, is_active=True)
       db.add(universe)
       db.flush()

       run = ScannerRun(
           scanner_type="pre_market_volume_spike",
           universe_id=universe.id,
           status="completed",
       )
       db.add(run)
       db.flush()

       ev = ScannerEvent(
           ticker=ticker,
           event_date=date.today(),
           scanner_type="pre_market_volume_spike",
           indicators={"last_trade_price": 50.0},
           criteria_met={},
           metadata_={"session": "pre_market"},
           opening_price=Decimal("50.00"),
           scanner_run_id=run.id if scanner_run_id is None else scanner_run_id,
       )
       db.add(ev)
       db.flush()
       return ev
   ```

4. **Write the six gate tests:**

   ```python
   def test_quality_gate_trusted_allows_order(db: Session):
       """verdict=trusted → order created normally; gate called with policy=strict."""
       from app.services.quality_gate_service import QualityGatePolicy

       strategy = _strategy(db, max_concurrent_positions=10, max_trades_per_day=10)
       rule = _rule(db, strategy)
       event = _event_with_run(db)

       with (
           patch(REDIS_PATCH, return_value=_fake_redis()),
           patch(GATE_PATCH, return_value=_gate_assessment("trusted")) as mock_assess,
       ):
           order = AutoTradeExecutor().maybe_execute(rule, event, db)

       assert order is not None
       assert order.status == "submitted"
       # Spec req #2: must call under strict policy, not trusting advisory blob
       mock_assess.assert_called_once()
       assert mock_assess.call_args.kwargs.get("policy") == QualityGatePolicy.strict


   def test_quality_gate_warning_refuses_order(db: Session):
       """verdict=warning → no order created."""
       strategy = _strategy(db, max_concurrent_positions=10, max_trades_per_day=10)
       rule = _rule(db, strategy)
       event = _event_with_run(db)

       with (
           patch(REDIS_PATCH, return_value=_fake_redis()),
           patch(GATE_PATCH, return_value=_gate_assessment("warning", warning_codes=["W001"])),
       ):
           order = AutoTradeExecutor().maybe_execute(rule, event, db)

       assert order is None


   def test_quality_gate_blocked_refuses_order(db: Session):
       """verdict=blocked → no order created."""
       strategy = _strategy(db, max_concurrent_positions=10, max_trades_per_day=10)
       rule = _rule(db, strategy)
       event = _event_with_run(db)

       with (
           patch(REDIS_PATCH, return_value=_fake_redis()),
           patch(GATE_PATCH, return_value=_gate_assessment("blocked", issue_codes=["B001"])),
       ):
           order = AutoTradeExecutor().maybe_execute(rule, event, db)

       assert order is None


   def test_quality_gate_skipped_without_bypass_refuses_order(db: Session):
       """verdict=skipped and QUALITY_GATE_SKIP_BYPASS absent → no order created."""
       strategy = _strategy(db, max_concurrent_positions=10, max_trades_per_day=10)
       rule = _rule(db, strategy)
       event = _event_with_run(db)
       # No QUALITY_GATE_SKIP_BYPASS row in SystemConfig

       with (
           patch(REDIS_PATCH, return_value=_fake_redis()),
           patch(GATE_PATCH, return_value=_gate_assessment("skipped")),
       ):
           order = AutoTradeExecutor().maybe_execute(rule, event, db)

       assert order is None


   def test_quality_gate_skipped_with_bypass_allows_order(db: Session):
       """verdict=skipped + QUALITY_GATE_SKIP_BYPASS='true' → order created."""
       from app.models.system_config import SystemConfig

       db.add(SystemConfig(key="QUALITY_GATE_SKIP_BYPASS", value="true"))
       db.flush()

       strategy = _strategy(db, max_concurrent_positions=10, max_trades_per_day=10)
       rule = _rule(db, strategy)
       event = _event_with_run(db)

       with (
           patch(REDIS_PATCH, return_value=_fake_redis()),
           patch(GATE_PATCH, return_value=_gate_assessment("skipped")),
       ):
           order = AutoTradeExecutor().maybe_execute(rule, event, db)

       assert order is not None
       assert order.status == "submitted"


   def test_quality_gate_exception_fails_closed(db: Session):
       """Gate service raises → no order created (fail-closed)."""
       strategy = _strategy(db, max_concurrent_positions=10, max_trades_per_day=10)
       rule = _rule(db, strategy)
       event = _event_with_run(db)

       with (
           patch(REDIS_PATCH, return_value=_fake_redis()),
           patch(GATE_PATCH, side_effect=RuntimeError("gate unavailable")),
       ):
           order = AutoTradeExecutor().maybe_execute(rule, event, db)

       assert order is None
   ```

5. **Verify all six tests fail** (quality gate guard not yet implemented):
   ```bash
   docker-compose exec backend python -m pytest \
     tests/services/test_auto_trade_service.py \
     -k "quality_gate" -x -q 2>&1 | tail -15
   ```
   Expected: tests fail because the gate patch target doesn't exist yet or the guard is absent.

6. **Commit failing tests:**
   ```bash
   git add backend/tests/services/test_auto_trade_service.py
   git commit -m "test: quality gate guard scenarios for auto_trade_service — TDD scaffold (#496)"
   ```

---

## Task 3 — Implement Guard 2.5 in `auto_trade_service.py`

**Files:** `backend/app/services/auto_trade_service.py`

### Steps

1. **Add new imports** at the top of `auto_trade_service.py` (after existing imports, before `logger = ...`):
   ```python
   from app.models.scanner_run import ScannerRun
   from app.services import quality_gate_service
   from app.services.quality_gate_service import QualityGateAssessment, QualityGatePolicy
   ```

2. **Add `_resolve_universe_id` as a method on `AutoTradeExecutor`** (add after `_get_account_equity`, before the module-level singleton):
   ```python
   def _resolve_universe_id(self, event: ScannerEvent, db: Session) -> Optional[int]:
       """Canonical path: event.scanner_run_id → ScannerRun.universe_id.
       Returns None if the run linkage is absent or the run has no universe.
       A None result causes the gate to return verdict='skipped'.
       """
       if not event.scanner_run_id:
           return None
       run = db.query(ScannerRun).filter(ScannerRun.id == event.scanner_run_id).first()
       return run.universe_id if run else None
   ```

3. **Add `_gate_passes` as a method on `AutoTradeExecutor`** (add immediately after `_resolve_universe_id`):
   ```python
   def _gate_passes(self, assessment: QualityGateAssessment, db: Session) -> bool:
       if assessment.verdict == "trusted":
           return True
       if assessment.verdict == "skipped":
           cfg = (
               db.query(SystemConfig)
               .filter(SystemConfig.key == "QUALITY_GATE_SKIP_BYPASS")
               .first()
           )
           bypass_enabled = cfg and cfg.value.lower() == "true"
           return bypass_enabled
       # blocked or warning → always refuse
       return False
   ```

4. **Insert Guard 2.5** in `maybe_execute()`, between the idempotency check (`return None` at ~line 150) and the Redis lock (`redis_client = redis.from_url(...)` at ~line 152).

   Find the exact insertion point — the blank line between `return None` (end of Guard 2) and `# ── 3. Redis distributed lock` comment. Insert:
   ```python
           # ── 2.5. Data quality gate (strict policy) ───────────────────
           try:
               universe_id = self._resolve_universe_id(event, db)
               assessment = quality_gate_service.assess(
                   universe_id=universe_id,
                   event=event,
                   policy=QualityGatePolicy.strict,
                   db=db,
               )
           except Exception as exc:
               logger.warning(
                   "quality_gate_service_error: ticker=%s event=%s rule=%s error=%s"
                   " — failing closed",
                   event.ticker,
                   event.id,
                   rule.id,
                   exc,
               )
               return None

           gate_ok = self._gate_passes(assessment, db)
           bypass_used = assessment.verdict == "skipped" and gate_ok
           if not gate_ok:
               logger.warning(
                   "quality_gate_refused: ticker=%s event=%s rule=%s"
                   " verdict=%s issues=%s warnings=%s bypass_used=%s",
                   event.ticker,
                   event.id,
                   rule.id,
                   assessment.verdict,
                   assessment.issue_codes,
                   assessment.warning_codes,
                   bypass_used,  # always False here since gate_ok=False → bypass_used=False
               )
               return None
           if bypass_used:
               logger.warning(
                   "quality_gate_bypass_used: ticker=%s event=%s rule=%s"
                   " verdict=skipped",
                   event.ticker,
                   event.id,
                   rule.id,
               )
   ```

5. **Verify implementation compiles cleanly** (no syntax errors, no missing import errors):
   ```bash
   docker-compose exec backend python -c "from app.services.auto_trade_service import AutoTradeExecutor; print('OK')"
   ```
   Expected: `OK`

6. **Verify the six gate tests now pass:**
   ```bash
   docker-compose exec backend python -m pytest \
     tests/services/test_auto_trade_service.py \
     -k "quality_gate" -v 2>&1 | tail -20
   ```
   Expected: `6 passed`

7. **Run full auto-trade test suite** (no regressions):
   ```bash
   docker-compose exec backend python -m pytest \
     tests/services/test_auto_trade_service.py \
     -v 2>&1 | tail -20
   ```
   Expected: all tests pass.

8. **Commit implementation:**
   ```bash
   git add backend/app/services/auto_trade_service.py
   git commit -m "feat: add quality gate Guard 2.5 to AutoTradeExecutor.maybe_execute() (#496)"
   ```

---

## Task 4 — Add Seq Alert for Quality Gate Refusal Rate (Best-Effort / Manual)

> **Note:** This task requires a running Seq instance and a valid `SEQ_API_KEY`. It is best-effort — an autonomous runner should attempt it but may skip gracefully if `SEQ_API_KEY` is not set. The logging at WARNING severity (Task 3) satisfies the normative part of Req 8; the Seq alert is the monitoring configuration on top.

**Files:** (Seq configuration via API — no file changes needed in the codebase)

The structured `logger.warning("quality_gate_refused: ...")` emitted in Guard 2.5 is already routed to Seq by the existing `error_tracking.py` setup. Create a Seq alert that fires when the per-hour count exceeds 5.

### Steps

1. **Verify logs reach Seq** — trigger a test by temporarily patching the gate to return `blocked` for one event in the dev environment and check Seq (`http://localhost:5341`). Confirm log entries appear with `@MessageTemplate` containing `quality_gate_refused`.

2. **Create the Seq alert via the Seq API.** Replace `<SEQ_URL>` with the actual Seq base URL and `<API_KEY>` with a Seq admin API key (available from `SEQ_ADMIN_PASSWORD_HASH` in `.env`):

   ```bash
   # Create signal: "Quality Gate Refusals > 5/hr"
   curl -s -X POST "${SEQ_URL:-http://localhost:5341}/api/signals" \
     -H "Content-Type: application/json" \
     -H "X-Seq-ApiKey: ${SEQ_API_KEY}" \
     -d '{
       "Title": "Quality Gate Refusals > 5/hr",
       "Description": "Auto-trade orders refused by quality gate exceed 5 per hour — potential misconfigured gate or mass data-quality event",
       "Filters": [
         {
           "Description": "quality_gate_refused logs at Warning level",
           "Filter": "@Level = '\''Warning'\'' and @MessageTemplate like '\''quality_gate_refused%'\''",
           "FilterNonStrict": "@Level = '\''Warning'\'' and @MessageTemplate like '\''quality_gate_refused%'\''"
         }
       ],
       "IsRestricted": false,
       "OwnerId": null
     }' | python3 -m json.tool
   ```

   Alternatively, create via the Seq UI:
   - Navigate to `http://localhost:5341 → Signals → New Signal`
   - **Title:** `Quality Gate Refusals > 5/hr`
   - **Filter:** `@Level = 'Warning' and @MessageTemplate like 'quality_gate_refused%'`
   - Save. Then add an alert on this signal with threshold: count > 5, window: 1 hour.

3. **Document the Seq alert in DEVELOPMENT.md** under a "Monitoring" or "Alerts" section (if one exists) so operators know it's configured:
   ```
   **Quality Gate Refusal Rate** — Seq signal fires when `quality_gate_refused` WARNING logs exceed 5/hr.
   Indicates misconfigured gate or mass data-quality event. Review auto_trade_service logs.
   ```

4. **Commit the DEVELOPMENT.md update** (if edited):
   ```bash
   git add DEVELOPMENT.md
   git commit -m "docs: document Seq alert for quality gate refusal rate (#496)"
   ```

---

## Task 5 — End-to-End Validation

### Steps

1. **Restart backend** to pick up all changes:
   ```bash
   docker-compose restart backend celery-worker
   docker-compose logs backend --tail=10
   ```
   Expected: no import errors, backend starts cleanly.

2. **Verify backend reloads cleanly:**
   ```bash
   docker-compose logs backend --tail=5 | grep -E "Application startup complete|ERROR"
   ```
   Expected: `Application startup complete` with no ERROR lines.

3. **Run full backend test suite** to confirm no regressions:
   ```bash
   docker-compose exec backend python -m pytest tests/services/test_auto_trade_service.py -v 2>&1 | tail -30
   ```
   Expected: all tests pass.

4. **Smoke test via API** — verify `maybe_execute()` is reachable:
   ```bash
   curl -s http://localhost:8000/api/health | python3 -m json.tool
   ```
   Expected: `{"status": "ok", ...}`

5. **Confirm refusal log format** by checking that a paper-mode event with a mocked `blocked` verdict produces the expected structured log line format:
   ```
   quality_gate_refused: ticker=AAPL event=<id> rule=<id>
    verdict=blocked issues=['B001'] warnings=[] bypass_used=False
   ```

---

## Task 6 — Final Commit and Push

### Steps

1. **Check all changes are staged:**
   ```bash
   git status
   git diff --stat origin/main HEAD
   ```

2. **Run all affected tests one final time:**
   ```bash
   docker-compose exec backend python -m pytest \
     tests/services/test_auto_trade_service.py \
     tests/api/test_auto_trading.py \
     -v 2>&1 | tail -30
   ```
   Expected: all tests pass.

3. **Push branch** (only after user approval):
   ```bash
   git push origin refine/issue-496-apply-strict-data-quality-gate-to-automa
   ```

---

## Memory-Baked Constraints

The following cross-cutting constraints from accumulated memory are baked directly into each task:

- **[architecture.md AVOID]** No `AutoTradeOrder` row for gate refusals. Guard 2.5 uses `return None` only, matching all 11 existing guards. `uq_auto_trade_symbol_strategy_date` would block recovery.
- **[architecture.md PATTERN]** Gate is called with `policy=QualityGatePolicy.strict`, not reading `event.metadata_["quality_gate"]` advisory blob from #494. Advisory mode doesn't escalate blockers.
- **[architecture.md PATTERN]** Exception in gate service → fail-closed: block order, log at WARNING, `return None`.
- **[architecture.md AVOID]** No `scanner_type → ScannerConfig` fallback for universe resolution. `scanner_type` is not unique across configs; null `scanner_run_id` → `skipped` verdict.
- **[codebase-patterns.md AVOID]** Tests use the transaction-rollback `db` fixture from `conftest.py` — not MagicMock DB — so SQLAlchemy queries execute against real schema.
- **[backend-patterns.md]** `utc_now` from `app.utils.time` for any naive-UTC datetime needs (not used here, noted for awareness).
