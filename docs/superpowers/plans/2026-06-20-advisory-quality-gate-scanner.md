# Implementation Plan: Advisory Data Quality Gate for Scanner Runs

**Date:** 2026-06-20
**Issue:** [#494](https://github.com/omniscient/markethawk/issues/494) — Apply advisory data quality gate to scanner runs
**Spec:** [2026-06-19-advisory-quality-gate-scanner-design.md](../specs/2026-06-19-advisory-quality-gate-scanner-design.md)

---

## Goal

Wire `QualityGateService.assess()` (from #492) into `run_universe_scan` so that:
1. The gate runs once at scan start in advisory mode (never blocks)
2. The full assessment is persisted as JSONB on `ScannerRun.quality_gate`
3. Each new `ScannerEvent` is stamped with `metadata_["quality_gate"] = {tier, warnings, schema_version}`

## Architecture

Gate runs in `_run_universe_scan_logic` → result stored on `ScannerRun` → minimal `gate_metadata` dict threaded via `scan_orchestrator.run()` → each scanner's `_orchestrator_run` adapter → main run function → `save_event()`. All other call paths (nightly scheduled scans, live scanner, run_range_scan) are untouched.

## Tech Stack

- Backend: FastAPI + SQLAlchemy 2.0 (sync) + PostgreSQL + Alembic
- New service dependency: `app.services.quality_gate.QualityGateService` (added by #492)
- Testing: pytest + MagicMock (following `test_scanning_tasks.py` patterns)

---

## File Changes

| File | Change |
|------|--------|
| `backend/app/models/scanner_run.py` | Add `quality_gate = Column(JSONB, nullable=True)` |
| `backend/app/alembic/versions/<hash>_add_quality_gate_to_scanner_runs.py` | `ADD COLUMN quality_gate JSONB NULL` |
| `backend/app/services/alert_service.py` | Add `gate_metadata=None` to `save_event()`; merge into enrichment; guard upsert |
| `backend/app/services/scanner.py` | Add `gate_metadata=None` to `ScannerService._save_event()`; proxy to `save_event()` |
| `backend/app/services/scan_orchestrator.py` | Add `gate_metadata=None` to `run()`; pass to `descriptor.run()` |
| `backend/app/services/pre_market_scan.py` | Add `gate_metadata=None` to `_run()`, `run_pre_market_scan()`, `_persist()`; pass to `ScannerService._save_event()` |
| `backend/app/services/oversold_bounce_scan.py` | Add `gate_metadata=None` to `_run()`, `run_oversold_bounce_scan()`; pass to `ScannerService._save_event()` |
| `backend/app/services/pocket_pivot.py` | Add `gate_metadata=None` to `_orchestrator_run()`, `run_pocket_pivot_scan()`; pass to `_save_event()` |
| `backend/app/services/trend_pullback_scan.py` | Add `gate_metadata=None` to `_orchestrator_run()`, `run_trend_pullback_scan()`; pass to `_save_event()` |
| `backend/app/services/liquidity_hunt.py` | Add `gate_metadata=None` to `_orchestrator_run()`, `run_liquidity_hunt_scan()`; pass to both `_save_event()` calls |
| `backend/app/tasks/scanning.py` | Evaluate gate in `_run_universe_scan_logic`; persist; thread `gate_metadata` |
| `backend/tests/tasks/test_scanning_tasks.py` | Tests: gate called, warning result continues scan, events stamped |

---

## Task 1 — Add `quality_gate` column to `ScannerRun` model

**Files:** `backend/app/models/scanner_run.py`

### TDD

**1a. Write a failing import test** — add to `backend/tests/tasks/test_scanning_tasks.py`:

```python
def test_scanner_run_has_quality_gate_column():
    from app.models.scanner_run import ScannerRun
    assert hasattr(ScannerRun, "quality_gate")
```

**1b. Verify it fails** (column doesn't exist yet):
```bash
docker-compose exec backend python -m pytest backend/tests/tasks/test_scanning_tasks.py::test_scanner_run_has_quality_gate_column -x 2>&1 | tail -10
# Expected: AttributeError or AssertionError
```

**1c. Add the column to the model** — in `backend/app/models/scanner_run.py`, after the `failed_tickers` line:

```python
# Before:
    failed_tickers = Column(JSONB, nullable=True)
    created_at = Column(DateTime, default=utc_now)

# After:
    failed_tickers = Column(JSONB, nullable=True)
    quality_gate = Column(JSONB, nullable=True)
    created_at = Column(DateTime, default=utc_now)
```

**1d. Generate and apply the migration:**
```bash
docker-compose exec backend python -m alembic revision \
  --autogenerate \
  -m "add_quality_gate_to_scanner_runs"
# Expected output: Generating .../add_quality_gate_to_scanner_runs.py ...  done.

docker-compose exec backend python -m alembic upgrade head
# Expected: Running upgrade <prev> -> <hash>, OK
```

**1e. Verify test passes:**
```bash
docker-compose exec backend python -m pytest backend/tests/tasks/test_scanning_tasks.py::test_scanner_run_has_quality_gate_column -x
# Expected: 1 passed
```

**1f. Verify migration is correct** — check the generated migration file at `backend/app/alembic/versions/<hash>_add_quality_gate_to_scanner_runs.py`:

```python
# upgrade() should contain:
op.add_column('scanner_runs', sa.Column('quality_gate', postgresql.JSONB(astext_type=sa.Text()), nullable=True))

# downgrade() should contain:
op.drop_column('scanner_runs', 'quality_gate')
```

**1g. Commit** — replace `<hash>` with the actual generated revision ID (e.g. `a1b2c3d4e5f6`):
```bash
# First find the actual generated file:
ls backend/app/alembic/versions/ | grep add_quality_gate

git add backend/app/models/scanner_run.py \
        backend/app/alembic/versions/<actual-hash>_add_quality_gate_to_scanner_runs.py
git commit -m "feat: add quality_gate JSONB column to scanner_runs (#494)"
```

---

## Task 2 — Add `gate_metadata` to `alert_service.save_event()` with enrichment merge and upsert guard

**Files:** `backend/app/services/alert_service.py`

### TDD

**2a. Write failing tests** — add to `backend/tests/tasks/test_scanning_tasks.py`:

```python
def test_save_event_accepts_gate_metadata_param():
    """save_event signature must accept gate_metadata kwarg."""
    import inspect
    from app.services.alert_service import save_event
    sig = inspect.signature(save_event)
    assert "gate_metadata" in sig.parameters


def test_save_event_merges_gate_metadata_into_enrichment(monkeypatch):
    """New events get metadata_["quality_gate"] stamped from gate_metadata."""
    from unittest.mock import MagicMock, patch
    from datetime import date
    from app.services.alert_service import save_event

    db = MagicMock()
    # No existing event — upsert path not taken
    db.query.return_value.filter.return_value.first.return_value = None

    captured_event = {}
    OriginalScannerEvent = None

    def fake_add(obj):
        captured_event["obj"] = obj

    db.add = fake_add

    gate_meta = {"tier": "warning", "warnings": ["low_coverage"], "schema_version": "v1"}

    with patch("app.services.alert_service.generate_event_summary", return_value="summary"), \
         patch("app.services.alert_service.compute_event_severity", return_value="medium"), \
         patch("app.services.alert_service.RegimeService.get_regime_at_date", return_value=None), \
         patch("app.services.alert_service.trigger_scanner_alert"), \
         patch("app.services.alert_service.ScannerEvent") as MockEvent:
        MockEvent.return_value = MagicMock()
        save_event(
            db=db,
            ticker="AAPL",
            event_date=date(2026, 1, 2),
            scanner_type="pre_market_volume_spike",
            indicators={"vol_ratio": 5.0},
            criteria_met={"volume_threshold": True},
            enrichment={"sector": "tech"},
            gate_metadata=gate_meta,
        )
    # The ScannerEvent was constructed with metadata_ containing quality_gate
    call_kwargs = MockEvent.call_args[1]
    assert call_kwargs["metadata_"]["quality_gate"] == gate_meta
    assert call_kwargs["metadata_"]["sector"] == "tech"


def test_save_event_upsert_does_not_overwrite_existing_gate_stamp(monkeypatch):
    """On upsert, existing metadata_[quality_gate] is not overwritten."""
    from unittest.mock import MagicMock, patch
    from datetime import date
    from app.services.alert_service import save_event

    existing_event = MagicMock()
    existing_event.id = 42
    existing_event.metadata_ = {
        "sector": "tech",
        "quality_gate": {"tier": "trusted", "warnings": [], "schema_version": "v1"},
    }

    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = existing_event

    new_gate = {"tier": "warning", "warnings": ["low_coverage"], "schema_version": "v1"}

    with patch("app.services.alert_service.generate_event_summary", return_value="summary"), \
         patch("app.services.alert_service.compute_event_severity", return_value="medium"), \
         patch("app.services.alert_service.RegimeService.get_regime_at_date", return_value=None):
        save_event(
            db=db,
            ticker="AAPL",
            event_date=date(2026, 1, 2),
            scanner_type="pre_market_volume_spike",
            indicators={"vol_ratio": 5.0},
            criteria_met={"volume_threshold": True},
            enrichment={"sector": "consumer"},
            gate_metadata=new_gate,
        )

    # existing_event.metadata_ must still carry the OLD quality_gate (trusted)
    final_metadata = existing_event.metadata_
    assert final_metadata["quality_gate"]["tier"] == "trusted"
    # Other enrichment fields ARE updated
    assert final_metadata["sector"] == "consumer"
```

**2b. Verify tests fail:**
```bash
docker-compose exec backend python -m pytest backend/tests/tasks/test_scanning_tasks.py \
  -k "gate_metadata or upsert_gate" -x 2>&1 | tail -15
```

**2c. Implement changes** in `backend/app/services/alert_service.py`:

At line 372, after `ranker_config: Optional[Dict[str, Any]] = None,` add the new parameter:

```python
# Before:
def save_event(
    db: Session,
    ticker: str,
    event_date: date,
    scanner_type: str,
    indicators: Dict[str, Any],
    criteria_met: Dict[str, Any],
    enrichment: Dict[str, Any],
    previous_close: float = None,
    opening_price: float = None,
    closing_price: float = None,
    ranker_config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:

# After:
def save_event(
    db: Session,
    ticker: str,
    event_date: date,
    scanner_type: str,
    indicators: Dict[str, Any],
    criteria_met: Dict[str, Any],
    enrichment: Dict[str, Any],
    previous_close: float = None,
    opening_price: float = None,
    closing_price: float = None,
    ranker_config: Optional[Dict[str, Any]] = None,
    gate_metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
```

After the three `_validate_jsonb_dict(...)` calls (around line 391), add the gate_metadata merge:

```python
# After the three _validate_jsonb_dict calls, before building event_dict:
    if gate_metadata is not None:
        enrichment = {**enrichment, "quality_gate": gate_metadata}
```

Replace the `if existing:` block (current lines 433-438) to guard the quality_gate key:

```python
# Before:
    if existing:
        for key, value in event_dict.items():
            if key == "metadata":
                setattr(existing, "metadata_", value)
            else:
                setattr(existing, key, value)
        db.flush()
        event_dict["id"] = existing.id

# After:
    if existing:
        for key, value in event_dict.items():
            if key == "metadata" and gate_metadata is not None:
                # Do not overwrite a previously-stamped quality_gate on upsert
                merged_meta = dict(existing.metadata_ or {})
                new_meta = dict(value)
                new_meta.pop("quality_gate", None)
                merged_meta.update(new_meta)
                setattr(existing, "metadata_", merged_meta)
            elif key == "metadata":
                setattr(existing, "metadata_", value)
            else:
                setattr(existing, key, value)
        db.flush()
        event_dict["id"] = existing.id
```

**2d. Verify tests pass:**
```bash
docker-compose exec backend python -m pytest backend/tests/tasks/test_scanning_tasks.py \
  -k "gate_metadata or upsert_gate" -x
# Expected: 3 passed
```

**2e. Commit:**
```bash
git add backend/app/services/alert_service.py backend/tests/tasks/test_scanning_tasks.py
git commit -m "feat: add gate_metadata param to save_event with enrichment merge and upsert guard (#494)"
```

---

## Task 3 — Proxy `gate_metadata` through `ScannerService._save_event()`

**Files:** `backend/app/services/scanner.py`

### TDD

**3a. Write failing test:**

```python
def test_scanner_service_save_event_accepts_gate_metadata():
    import inspect
    from app.services.scanner import ScannerService
    sig = inspect.signature(ScannerService._save_event)
    assert "gate_metadata" in sig.parameters
```

**3b. Implement** — in `backend/app/services/scanner.py`, update `_save_event()`:

```python
# Before:
    @staticmethod
    def _save_event(
        db: Session,
        ticker: str,
        event_date: date,
        scanner_type: str,
        indicators: Dict[str, Any],
        criteria_met: Dict[str, Any],
        enrichment: Dict[str, Any],
        previous_close: float = None,
        opening_price: float = None,
        closing_price: float = None,
        ranker_config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        from app.services.alert_service import save_event

        return save_event(
            db=db,
            ticker=ticker,
            event_date=event_date,
            scanner_type=scanner_type,
            indicators=indicators,
            criteria_met=criteria_met,
            enrichment=enrichment,
            previous_close=previous_close,
            opening_price=opening_price,
            closing_price=closing_price,
            ranker_config=ranker_config,
        )

# After:
    @staticmethod
    def _save_event(
        db: Session,
        ticker: str,
        event_date: date,
        scanner_type: str,
        indicators: Dict[str, Any],
        criteria_met: Dict[str, Any],
        enrichment: Dict[str, Any],
        previous_close: float = None,
        opening_price: float = None,
        closing_price: float = None,
        ranker_config: Optional[Dict[str, Any]] = None,
        gate_metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        from app.services.alert_service import save_event

        return save_event(
            db=db,
            ticker=ticker,
            event_date=event_date,
            scanner_type=scanner_type,
            indicators=indicators,
            criteria_met=criteria_met,
            enrichment=enrichment,
            previous_close=previous_close,
            opening_price=opening_price,
            closing_price=closing_price,
            ranker_config=ranker_config,
            gate_metadata=gate_metadata,
        )
```

**3c. Verify test passes:**
```bash
docker-compose exec backend python -m pytest backend/tests/tasks/test_scanning_tasks.py \
  -k "scanner_service_save_event" -x
```

**3d. Commit:**
```bash
git add backend/app/services/scanner.py backend/tests/tasks/test_scanning_tasks.py
git commit -m "feat: proxy gate_metadata through ScannerService._save_event (#494)"
```

---

## Task 4 — Add `gate_metadata=None` to `scan_orchestrator.run()`

**Files:** `backend/app/services/scan_orchestrator.py`

### TDD

**4a. Write failing test:**

```python
def test_scan_orchestrator_run_accepts_gate_metadata():
    import inspect
    from app.services.scan_orchestrator import run
    sig = inspect.signature(run)
    assert "gate_metadata" in sig.parameters
```

**4b. Implement** — update `run()` in `backend/app/services/scan_orchestrator.py`:

```python
# Before:
async def run(
    scanner_type: str,
    tickers: list[str],
    db: Any,
    event_date: date,
    scanner_run: Optional[Any] = None,
) -> list[dict]:
    descriptor = _REGISTRY.get(scanner_type)
    if descriptor is None:
        raise ValueError(
            f"Unknown scanner type: {scanner_type!r}. Registered: {list(_REGISTRY)}"
        )
    return await descriptor.run(tickers, db, event_date, scanner_run=scanner_run)

# After:
async def run(
    scanner_type: str,
    tickers: list[str],
    db: Any,
    event_date: date,
    scanner_run: Optional[Any] = None,
    gate_metadata: Optional[Any] = None,
) -> list[dict]:
    descriptor = _REGISTRY.get(scanner_type)
    if descriptor is None:
        raise ValueError(
            f"Unknown scanner type: {scanner_type!r}. Registered: {list(_REGISTRY)}"
        )
    return await descriptor.run(
        tickers, db, event_date, scanner_run=scanner_run, gate_metadata=gate_metadata
    )
```

Also add `Optional` import if not already present — it already is (imported from `typing`).

**4c. Verify test passes:**
```bash
docker-compose exec backend python -m pytest backend/tests/tasks/test_scanning_tasks.py \
  -k "orchestrator_run" -x
```

**4d. Commit:**
```bash
git add backend/app/services/scan_orchestrator.py backend/tests/tasks/test_scanning_tasks.py
git commit -m "feat: thread gate_metadata through scan_orchestrator.run() (#494)"
```

---

## Task 5 — Thread `gate_metadata` through all 5 scanner adapters

**Files:** `pre_market_scan.py`, `oversold_bounce_scan.py`, `pocket_pivot.py`, `trend_pullback_scan.py`, `liquidity_hunt.py`

Each scanner requires three changes:
1. `_orchestrator_run`/`_run` adapter: add `gate_metadata=None`, pass to main run function
2. Main run function: add `gate_metadata=None`, pass to `_save_event()` call site(s)
3. `_persist()` helper (pre_market only): add `gate_metadata=None`, pass to `ScannerService._save_event()`

### 5a. `pre_market_scan.py`

**In `_run()` adapter** (line 593):
```python
# Before:
async def _run(
    tickers: list[str], db: Any, event_date: date, scanner_run: Optional[Any] = None
) -> list[dict]:
    return await run_pre_market_scan(
        tickers, db, event_date=event_date, scanner_run=scanner_run
    )

# After:
async def _run(
    tickers: list[str], db: Any, event_date: date, scanner_run: Optional[Any] = None,
    gate_metadata: Optional[Any] = None,
) -> list[dict]:
    return await run_pre_market_scan(
        tickers, db, event_date=event_date, scanner_run=scanner_run,
        gate_metadata=gate_metadata,
    )
```

**In `run_pre_market_scan()` signature** (line 445):
```python
# Before:
async def run_pre_market_scan(
    tickers: List[str],
    db: Session,
    event_date: date = None,
    scanner_run: Optional["ScannerRun"] = None,
) -> List[Dict[str, Any]]:

# After:
async def run_pre_market_scan(
    tickers: List[str],
    db: Session,
    event_date: date = None,
    scanner_run: Optional["ScannerRun"] = None,
    gate_metadata: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
```

**In `_persist()` call inside `run_pre_market_scan`** — find the `_persist(enriched, failed, db, event_date, ranker_config, scanner_run)` call and add `gate_metadata`:
```python
# Before:
        results = _persist(enriched, failed, db, event_date, ranker_config, scanner_run)

# After:
        results = _persist(enriched, failed, db, event_date, ranker_config, scanner_run, gate_metadata)
```

**In `_persist()` function signature** (line 405):
```python
# Before:
def _persist(
    enriched: list[EnrichedSignal],
    failed: list[Dict[str, Any]],
    db: Session,
    event_date: date,
    ranker_config: Optional[Dict[str, Any]],
    scanner_run: Optional[Any],
) -> list[Dict[str, Any]]:

# After:
def _persist(
    enriched: list[EnrichedSignal],
    failed: list[Dict[str, Any]],
    db: Session,
    event_date: date,
    ranker_config: Optional[Dict[str, Any]],
    scanner_run: Optional[Any],
    gate_metadata: Optional[Dict[str, Any]] = None,
) -> list[Dict[str, Any]]:
```

**In `_persist()` body**, update the `ScannerService._save_event()` call (line 417):
```python
# Before:
        event_dict = ScannerService._save_event(
            db=db,
            ticker=signal.raw.ticker,
            event_date=event_date,
            scanner_type="pre_market_volume_spike",
            indicators=signal.indicators,
            criteria_met=signal.raw.criteria_met,
            enrichment=signal.enrichment,
            previous_close=signal.raw.previous_close,
            opening_price=signal.day_metrics.get("opening_price", 0.0),
            closing_price=signal.day_metrics.get("closing_price"),
            ranker_config=ranker_config,
        )

# After:
        event_dict = ScannerService._save_event(
            db=db,
            ticker=signal.raw.ticker,
            event_date=event_date,
            scanner_type="pre_market_volume_spike",
            indicators=signal.indicators,
            criteria_met=signal.raw.criteria_met,
            enrichment=signal.enrichment,
            previous_close=signal.raw.previous_close,
            opening_price=signal.day_metrics.get("opening_price", 0.0),
            closing_price=signal.day_metrics.get("closing_price"),
            ranker_config=ranker_config,
            gate_metadata=gate_metadata,
        )
```

### 5b. `oversold_bounce_scan.py`

**In `_run()` adapter** (line 232):
```python
# Before:
async def _run(
    tickers: list[str], db: Any, event_date: date, scanner_run: Optional[Any] = None
) -> list[dict]:
    return await run_oversold_bounce_scan(
        tickers, db, event_date=event_date, scanner_run=scanner_run
    )

# After:
async def _run(
    tickers: list[str], db: Any, event_date: date, scanner_run: Optional[Any] = None,
    gate_metadata: Optional[Any] = None,
) -> list[dict]:
    return await run_oversold_bounce_scan(
        tickers, db, event_date=event_date, scanner_run=scanner_run,
        gate_metadata=gate_metadata,
    )
```

**In `run_oversold_bounce_scan()` signature** (line 27):
```python
# Before:
async def run_oversold_bounce_scan(
    tickers: list[str],
    db: Session,
    event_date: date = None,
    scanner_run: Optional["ScannerRun"] = None,
) -> list[dict]:

# After:
async def run_oversold_bounce_scan(
    tickers: list[str],
    db: Session,
    event_date: date = None,
    scanner_run: Optional["ScannerRun"] = None,
    gate_metadata: Optional[Dict[str, Any]] = None,
) -> list[dict]:
```

**In the `ScannerService._save_event()` call** (line 182):
```python
# Before:
                    event_dict = ScannerService._save_event(
                        db=db,
                        ticker=ticker,
                        event_date=event_date,
                        scanner_type="oversold_bounce",
                        indicators=indicators,
                        criteria_met=criteria_met,
                        enrichment=enrichment,
                        previous_close=float(today["prev_close"]),
                        opening_price=float(today["Open"]),
                        closing_price=float(today["Close"]),
                        ranker_config=ranker_config,
                    )

# After:
                    event_dict = ScannerService._save_event(
                        db=db,
                        ticker=ticker,
                        event_date=event_date,
                        scanner_type="oversold_bounce",
                        indicators=indicators,
                        criteria_met=criteria_met,
                        enrichment=enrichment,
                        previous_close=float(today["prev_close"]),
                        opening_price=float(today["Open"]),
                        closing_price=float(today["Close"]),
                        ranker_config=ranker_config,
                        gate_metadata=gate_metadata,
                    )
```

### 5c. `pocket_pivot.py`

**In `_orchestrator_run()` adapter** (line 398):
```python
# Before:
async def _orchestrator_run(
    tickers: list,
    db: Any,
    event_date: date,
    scanner_run: Optional[Any] = None,
) -> list[dict]:
    return await run_pocket_pivot_scan(
        tickers=tickers,
        db=db,
        start_date=event_date,
        end_date=event_date,
    )

# After:
async def _orchestrator_run(
    tickers: list,
    db: Any,
    event_date: date,
    scanner_run: Optional[Any] = None,
    gate_metadata: Optional[Any] = None,
) -> list[dict]:
    return await run_pocket_pivot_scan(
        tickers=tickers,
        db=db,
        start_date=event_date,
        end_date=event_date,
        gate_metadata=gate_metadata,
    )
```

**In `run_pocket_pivot_scan()` signature** (line 165):
```python
# Before:
async def run_pocket_pivot_scan(
    tickers: list[str],
    db: Session,
    start_date: date | None = None,
    end_date: date | None = None,
) -> list[dict[str, Any]]:

# After:
async def run_pocket_pivot_scan(
    tickers: list[str],
    db: Session,
    start_date: date | None = None,
    end_date: date | None = None,
    gate_metadata: Optional[Dict[str, Any]] = None,
) -> list[dict[str, Any]]:
```

**In the `_save_event()` call** (line 314):
```python
# Before:
                    event_dict = _save_event(
                        db=db,
                        ticker=ticker,
                        event_date=event_date,
                        scanner_type="pocket_pivot",
                        indicators=indicators,
                        criteria_met=criteria_met,
                        enrichment=enrichment,
                        previous_close=prior_close,
                        closing_price=today["close"],
                    )

# After:
                    event_dict = _save_event(
                        db=db,
                        ticker=ticker,
                        event_date=event_date,
                        scanner_type="pocket_pivot",
                        indicators=indicators,
                        criteria_met=criteria_met,
                        enrichment=enrichment,
                        previous_close=prior_close,
                        closing_price=today["close"],
                        gate_metadata=gate_metadata,
                    )
```

### 5d. `trend_pullback_scan.py`

**In `_orchestrator_run()` adapter** (line 408):
```python
# Before:
async def _orchestrator_run(
    tickers: list,
    db: Any,
    event_date: date,
    scanner_run: Optional[Any] = None,
) -> list[dict]:
    return await run_trend_pullback_scan(
        tickers=tickers,
        db=db,
        start_date=event_date,
        end_date=event_date,
    )

# After:
async def _orchestrator_run(
    tickers: list,
    db: Any,
    event_date: date,
    scanner_run: Optional[Any] = None,
    gate_metadata: Optional[Any] = None,
) -> list[dict]:
    return await run_trend_pullback_scan(
        tickers=tickers,
        db=db,
        start_date=event_date,
        end_date=event_date,
        gate_metadata=gate_metadata,
    )
```

**In `run_trend_pullback_scan()` signature** (line 264):
```python
# Before:
async def run_trend_pullback_scan(
    tickers: list[str],
    db: Session,
    start_date: date | None = None,
    end_date: date | None = None,
    config: dict | None = None,
    diagnostics_out: dict | None = None,
) -> list[dict[str, Any]]:

# After:
async def run_trend_pullback_scan(
    tickers: list[str],
    db: Session,
    start_date: date | None = None,
    end_date: date | None = None,
    config: dict | None = None,
    diagnostics_out: dict | None = None,
    gate_metadata: Optional[Dict[str, Any]] = None,
) -> list[dict[str, Any]]:
```

**In the `_save_event()` call** (line 329):
```python
# Before:
                    event_dict = _save_event(
                        db=db,
                        ticker=ticker,
                        event_date=event_date,
                        scanner_type="trend_pullback",
                        indicators=indicators,
                        criteria_met=criteria_met,
                        enrichment=enrichment,
                        previous_close=prior_close,
                    )

# After:
                    event_dict = _save_event(
                        db=db,
                        ticker=ticker,
                        event_date=event_date,
                        scanner_type="trend_pullback",
                        indicators=indicators,
                        criteria_met=criteria_met,
                        enrichment=enrichment,
                        previous_close=prior_close,
                        gate_metadata=gate_metadata,
                    )
```

### 5e. `liquidity_hunt.py`

**In `_orchestrator_run()` adapter** (line 672) — note: this adapter currently lacks both `scanner_run` and `gate_metadata`:
```python
# Before:
async def _orchestrator_run(tickers: list, db: Any, event_date: date) -> list[dict]:
    return await run_liquidity_hunt_scan(
        tickers=tickers,
        db=db,
        start_date=event_date,
        end_date=event_date,
    )

# After:
async def _orchestrator_run(
    tickers: list,
    db: Any,
    event_date: date,
    scanner_run: Optional[Any] = None,
    gate_metadata: Optional[Any] = None,
) -> list[dict]:
    return await run_liquidity_hunt_scan(
        tickers=tickers,
        db=db,
        start_date=event_date,
        end_date=event_date,
        gate_metadata=gate_metadata,
    )
```

Note: `scanner_run` is accepted in the signature (so the orchestrator's `descriptor.run(..., scanner_run=run, gate_metadata=gate_metadata)` call doesn't raise `TypeError`) but is not forwarded to `run_liquidity_hunt_scan` — that function does not use it and adding it would be out-of-scope. The `**kwargs`-style kwarg acceptance pattern (optional param with default) is the correct approach here.

**In `run_liquidity_hunt_scan()` signature** (line 422):
```python
# Before:
async def run_liquidity_hunt_scan(
    tickers: list[str],
    db: Session,
    start_date: date | None = None,
    end_date: date | None = None,
    config: dict | None = None,
) -> list[dict[str, Any]]:

# After:
async def run_liquidity_hunt_scan(
    tickers: list[str],
    db: Session,
    start_date: date | None = None,
    end_date: date | None = None,
    config: dict | None = None,
    gate_metadata: Optional[Dict[str, Any]] = None,
) -> list[dict[str, Any]]:
```

**In the first `_save_event()` call** (pre-market variant, line 543):
```python
# Before:
                        event_dict = _save_event(
                            db=db,
                            ticker=ticker,
                            event_date=event_date,
                            scanner_type="liquidity_hunt_pre",
                            indicators=indicators_pre,
                            criteria_met=criteria_pre,
                            enrichment=enrichment,
                            previous_close=prior_day_close,
                            opening_price=session_metrics["regular_open"],
                            closing_price=session_metrics["regular_close"],
                        )

# After:
                        event_dict = _save_event(
                            db=db,
                            ticker=ticker,
                            event_date=event_date,
                            scanner_type="liquidity_hunt_pre",
                            indicators=indicators_pre,
                            criteria_met=criteria_pre,
                            enrichment=enrichment,
                            previous_close=prior_day_close,
                            opening_price=session_metrics["regular_open"],
                            closing_price=session_metrics["regular_close"],
                            gate_metadata=gate_metadata,
                        )
```

**In the second `_save_event()` call** (post-market variant, line 585):
```python
# Before:
                            event_dict = _save_event(
                                db=db,
                                ticker=ticker,
                                event_date=event_date,
                                scanner_type="liquidity_hunt_post",
                                indicators=indicators_post,
                                criteria_met=criteria_post,
                                enrichment=enrichment,
                                previous_close=event_date_regular_close,
                                opening_price=session_metrics["regular_open"],
                                closing_price=session_metrics["regular_close"],
                            )

# After:
                            event_dict = _save_event(
                                db=db,
                                ticker=ticker,
                                event_date=event_date,
                                scanner_type="liquidity_hunt_post",
                                indicators=indicators_post,
                                criteria_met=criteria_post,
                                enrichment=enrichment,
                                previous_close=event_date_regular_close,
                                opening_price=session_metrics["regular_open"],
                                closing_price=session_metrics["regular_close"],
                                gate_metadata=gate_metadata,
                            )
```

### 5f. Verify no regressions on scanner imports:
```bash
docker-compose exec backend python -m pytest \
  backend/tests/services/test_pre_market_scan_module.py \
  backend/tests/services/test_oversold_bounce_scan_module.py \
  backend/tests/services/test_trend_pullback_scan.py \
  backend/tests/services/test_scan_orchestrator.py \
  -x 2>&1 | tail -20
# Expected: all pass
```

**5g. Commit:**
```bash
git add \
  backend/app/services/pre_market_scan.py \
  backend/app/services/oversold_bounce_scan.py \
  backend/app/services/pocket_pivot.py \
  backend/app/services/trend_pullback_scan.py \
  backend/app/services/liquidity_hunt.py
git commit -m "feat: thread gate_metadata through all 5 scanner adapters and run functions (#494)"
```

---

## Task 6 — Evaluate quality gate in `_run_universe_scan_logic`

**Files:** `backend/app/tasks/scanning.py`

This is the entry point where the gate is actually called. It goes between the tickers check and the `run.status = "running"` line.

### TDD

**6a. Write failing tests** — add to `backend/tests/tasks/test_scanning_tasks.py`:

The three tests below use a **model-keyed `query.side_effect` dispatcher** (per backend-patterns memory) rather than the index-based `_make_db` helper, because `_run_universe_scan_logic` now makes three distinct `db.query()` calls (ScannerRun, MonitoredStock, ScannerConfig). The dispatcher handles each by model class:

```python
def _make_gate_db(run_uuid, tickers, scanner_config=None):
    """Model-keyed mock DB for quality gate tests.

    Handles:
      db.query(ScannerRun).filter(...).first()    → run stub
      db.query(MonitoredStock).filter(...).all()  → ticker stubs
      db.query(ScannerConfig).filter(...).first() → scanner_config or None
    """
    from app.models.scanner_run import ScannerRun
    from app.models.monitored_stock import MonitoredStock
    from app.models.scanner_config import ScannerConfig
    from unittest.mock import MagicMock

    run = _make_run(run_uuid)
    ticker_stubs = [_make_ticker(t) for t in tickers]

    def _query_side_effect(model):
        q = MagicMock()
        if model is ScannerRun:
            q.filter.return_value.first.return_value = run
        elif model is MonitoredStock:
            q.filter.return_value.all.return_value = ticker_stubs
        elif model is ScannerConfig:
            q.filter.return_value.first.return_value = scanner_config
        else:
            q.filter.return_value.first.return_value = None
            q.filter.return_value.all.return_value = []
        return q

    db = MagicMock()
    db.query.side_effect = _query_side_effect
    return db, run


def test_quality_gate_called_at_scan_start():
    """QualityGateService.assess is called once before the day-walk loop."""
    from datetime import date
    from unittest.mock import MagicMock, patch
    from app.tasks.scanning import _run_universe_scan_logic
    import asyncio

    db, run = _make_gate_db("test-uuid-gate-1", ["AAPL", "TSLA"])

    mock_assessment = MagicMock()
    mock_assessment.verdict = "warning"
    mock_assessment.warnings = ["low_coverage"]
    mock_assessment.schema_version = "v1"

    async def fake_run(scanner_type, tickers, db, event_date, scanner_run=None, gate_metadata=None):
        return []

    with patch("app.services.quality_gate.QualityGateService.assess", return_value=mock_assessment) as mock_assess, \
         patch("app.services.scan_orchestrator.run", new=fake_run), \
         patch("app.tasks.scanning.asyncio.run", side_effect=lambda coro: asyncio.get_event_loop().run_until_complete(coro)):
        try:
            _run_universe_scan_logic(
                scan_id="test-uuid-gate-1",
                scanner_type="pre_market_volume_spike",
                universe_id=1,
                start=date(2026, 1, 6),
                end=date(2026, 1, 6),
                db=db,
                publish=lambda x: None,
                is_cancelled=lambda: False,
                task_id="celery-task-1",
            )
        except Exception:
            pass

    # No ScannerConfig stub → data_requirements=None
    mock_assess.assert_called_once_with(
        db=db,
        universe_id=1,
        scanner_type="pre_market_volume_spike",
        policy="advisory",
        data_requirements=None,
    )


def test_quality_gate_warning_does_not_block_scan():
    """A warning-verdict gate result does NOT prevent scan completion or event stamping."""
    from datetime import date
    from unittest.mock import MagicMock, patch
    from app.tasks.scanning import _run_universe_scan_logic
    import asyncio

    db, run = _make_gate_db("test-uuid-gate-2", ["AAPL"])

    mock_assessment = MagicMock()
    mock_assessment.verdict = "warning"
    mock_assessment.warnings = ["no_quality_report"]
    mock_assessment.schema_version = "v1"

    events_fired = []

    async def fake_run(scanner_type, tickers, db, event_date, scanner_run=None, gate_metadata=None):
        events_fired.append({"date": event_date, "gate_metadata": gate_metadata})
        return [{"id": 1, "ticker": "AAPL"}]

    with patch("app.services.quality_gate.QualityGateService.assess", return_value=mock_assessment), \
         patch("app.services.scan_orchestrator.run", new=fake_run), \
         patch("app.tasks.scanning.asyncio.run", side_effect=lambda coro: asyncio.get_event_loop().run_until_complete(coro)):
        try:
            _run_universe_scan_logic(
                scan_id="test-uuid-gate-2",
                scanner_type="pre_market_volume_spike",
                universe_id=2,
                start=date(2026, 1, 6),
                end=date(2026, 1, 6),
                db=db,
                publish=lambda x: None,
                is_cancelled=lambda: False,
                task_id="celery-task-2",
            )
        except Exception:
            pass

    assert len(events_fired) == 1
    assert events_fired[0]["gate_metadata"] == {
        "tier": "warning",
        "warnings": ["no_quality_report"],
        "schema_version": "v1",
    }


def test_quality_gate_error_degrades_gracefully():
    """Gate service exceptions degrade gracefully: gate_metadata=None, scan continues."""
    from datetime import date
    from unittest.mock import MagicMock, patch
    from app.tasks.scanning import _run_universe_scan_logic
    import asyncio

    db, run = _make_gate_db("test-uuid-gate-3", ["AAPL"])

    events_fired = []

    async def fake_run(scanner_type, tickers, db, event_date, scanner_run=None, gate_metadata=None):
        events_fired.append(gate_metadata)
        return []

    with patch("app.services.quality_gate.QualityGateService.assess", side_effect=RuntimeError("gate offline")), \
         patch("app.services.scan_orchestrator.run", new=fake_run), \
         patch("app.tasks.scanning.asyncio.run", side_effect=lambda coro: asyncio.get_event_loop().run_until_complete(coro)):
        try:
            _run_universe_scan_logic(
                scan_id="test-uuid-gate-3",
                scanner_type="pre_market_volume_spike",
                universe_id=3,
                start=date(2026, 1, 6),
                end=date(2026, 1, 6),
                db=db,
                publish=lambda x: None,
                is_cancelled=lambda: False,
                task_id="celery-task-3",
            )
        except Exception:
            pass

    # gate_metadata is None because assess() raised; scan still fired
    assert events_fired == [None]
```

**6b. Verify these tests fail** (gate not evaluated yet):
```bash
docker-compose exec backend python -m pytest backend/tests/tasks/test_scanning_tasks.py \
  -k "quality_gate_called or quality_gate_warning or quality_gate_error" -x 2>&1 | tail -20
```

**6c. Implement gate evaluation** in `backend/app/tasks/scanning.py`.

The insertion point is after the tickers check (after the `if not tickers:` block, line 188) and before `run.status = "running"` (line 196). Add these lines:

```python
    # ── Quality gate evaluation (advisory) ──────────────────────────────────
    # Runs once per scan, before the day-walk loop.
    # Never blocks: gate errors degrade to gate_metadata=None.
    from app.models.scanner_config import ScannerConfig as _ScannerConfig
    _sc = (
        db.query(_ScannerConfig)
        .filter(
            _ScannerConfig.scanner_type == scanner_type,
            _ScannerConfig.universe_id == universe_id,
            _ScannerConfig.is_active.is_(True),
        )
        .first()
    )
    _data_requirements = _sc.data_requirements if _sc else None
    try:
        import dataclasses as _dataclasses
        from app.services.quality_gate import QualityGateService as _QGS
        _assessment = _QGS.assess(
            db=db,
            universe_id=universe_id,
            scanner_type=scanner_type,
            policy="advisory",
            data_requirements=_data_requirements,
        )
        gate_metadata = {
            "tier": _assessment.verdict,
            "warnings": _assessment.warnings,
            "schema_version": _assessment.schema_version,
        }
        # Convert any datetime fields (e.g. generated_at) to strings so JSONB
        # serialization succeeds on db.commit() without raising TypeError.
        import json as _json
        _gate_dict = _json.loads(_json.dumps(_dataclasses.asdict(_assessment), default=str))
    except Exception as _gate_exc:
        logger.warning(
            "quality_gate assess failed for universe=%s scanner=%s: %s",
            universe_id, scanner_type, _gate_exc,
        )
        gate_metadata = None
        _gate_dict = None
    run.quality_gate = _gate_dict
    # ────────────────────────────────────────────────────────────────────────

    run.status = "running"
    run.stocks_scanned = len(tickers)
    ...
```

**Update the `_orchestrator.run()` call** at line 268 to pass `gate_metadata`:

```python
# Before:
        try:
            day_events = asyncio.run(
                _orchestrator.run(
                    scanner_type, tickers, db=db, event_date=day, scanner_run=run
                )
            )

# After:
        try:
            day_events = asyncio.run(
                _orchestrator.run(
                    scanner_type, tickers, db=db, event_date=day,
                    scanner_run=run, gate_metadata=gate_metadata,
                )
            )
```

Note: `gate_metadata` variable is defined in the gate block above and is available in scope throughout `_run_universe_scan_logic`.

**6d. Verify tests pass:**
```bash
docker-compose exec backend python -m pytest backend/tests/tasks/test_scanning_tasks.py \
  -k "quality_gate_called or quality_gate_warning or quality_gate_error" -x
# Expected: 3 passed
```

**6e. Confirm backend reloaded:**
```bash
docker-compose logs backend --tail=5
```

**6f. Commit:**
```bash
git add backend/app/tasks/scanning.py backend/tests/tasks/test_scanning_tasks.py
git commit -m "feat: evaluate advisory quality gate in _run_universe_scan_logic (#494)"
```

---

## Task 7 — Full test suite smoke check and final validation

**7a. Run the full test suite for affected modules:**
```bash
docker-compose exec backend python -m pytest \
  backend/tests/tasks/test_scanning_tasks.py \
  backend/tests/services/test_scan_orchestrator.py \
  backend/tests/services/test_pre_market_scan_module.py \
  backend/tests/services/test_oversold_bounce_scan_module.py \
  backend/tests/services/test_trend_pullback_scan.py \
  -v 2>&1 | tail -30
# Expected: all pass
```

**7b. TypeScript frontend check (no frontend changes, but confirm no regressions):**
```bash
cd /workspace/markethawk/frontend && npx tsc --noEmit 2>&1 | tail -10
# Expected: no errors
```

**7c. Verify the migration is reflected in DB:**
```bash
docker-compose exec backend python -m alembic current
# Expected: <hash> (head)

docker-compose exec backend python -c "
from app.core.database import SessionLocal
from app.models.scanner_run import ScannerRun
db = SessionLocal()
# Inspect column
cols = [c.name for c in ScannerRun.__table__.columns]
print('quality_gate in columns:', 'quality_gate' in cols)
db.close()
"
# Expected: quality_gate in columns: True
```

**7d. Final commit if any cleanup needed:**
```bash
git add -p  # review any residual changes
git commit -m "test: scanning quality gate integration tests (#494)"
```

---

## Acceptance Criteria Traceability

| AC | Task(s) | Verification |
|----|---------|--------------|
| Universe scanner runs call quality gate with advisory policy | Task 6 | `test_quality_gate_called_at_scan_start` |
| Scanner data requirements used when available from `ScannerConfig.data_requirements` | Task 6 | Gate call includes `data_requirements=_sc.data_requirements` |
| Advisory warnings do not block interactive scanner execution | Task 6 | `test_quality_gate_warning_does_not_block_scan` |
| Run-level gate status persisted in inspectable JSON field | Tasks 1+6 | `ScannerRun.quality_gate` JSONB column + `run.quality_gate = _gate_dict` |
| Event-level warnings written to `ScannerEvent.metadata_["quality_gate"]` | Tasks 2+5 | `test_save_event_merges_gate_metadata_into_enrichment` |
| Tests prove existing scanner runs continue when warnings exist | Task 6 | `test_quality_gate_warning_does_not_block_scan` |
| Tests prove warnings are persisted as evidence | Tasks 2+6 | `test_save_event_merges_gate_metadata_into_enrichment` |
| Upsert path does not overwrite previously-stamped gate | Task 2 | `test_save_event_upsert_does_not_overwrite_existing_gate_stamp` |
| Gate errors degrade gracefully (gate_metadata=None) | Task 6 | `test_quality_gate_error_degrades_gracefully` |
