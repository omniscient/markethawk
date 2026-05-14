# Signal Quality Ranker — Implementation Plan

**Date**: 2026-05-14  
**Issue**: #23 — feat(phase-2c): Signal quality ranker  
**Spec**: `Docs/superpowers/specs/2026-05-14-signal-quality-ranker-design.md`  
**Status**: Pending Architect Review

---

## Goal

Attach a `signal_quality_score` (Float, 0.0–1.0) to every `ScannerEvent` at creation time, computed as a weighted sum of normalized indicator values. Weights are stored in `SystemConfig` so they can be updated without a code deploy. The scanner results UI sorts by score descending by default, and EdgeExplorer gains a "Signal Quality Validation" chart that plots average `eod_pct_change` and `follow_through` rate per score decile.

---

## Architecture

### Scoring flow — batch scanner
```
run_scanner Celery task
  └── ScannerService.run()
        ├── load ranker config (signal_ranker_enabled, signal_ranker_weights) — once, before ticker loop
        └── per ticker: _save_event(db, ticker, ..., indicators, ranker_config=ranker_config)
              ├── compute_signal_quality_score(indicators, weights)
              ├── event.signal_quality_score = score
              └── db.flush()
```

### Scoring flow — live scanner
```
LivePublisher.fire_alert_if_new()
  └── _write_scanner_event(bar, condition, ...)
        ├── load_ranker_config(session)   ← fresh read each event (long-running process)
        └── compute_signal_quality_score(indicators, weights)
        └── event.signal_quality_score = score
```

### New module
`backend/app/services/signal_ranker.py` — imported by both the batch scanner and the live scanner publisher. No circular dependency (it only imports `SystemConfig`).

---

## Tech Stack

- **Backend**: FastAPI + SQLAlchemy 2.0 + PostgreSQL + pytest
- **Frontend**: React 18 + TypeScript + Recharts + React Query
- **Pattern**: mirrors existing TimesFM config-loading pattern in `scanner.py`

---

## File Structure

| File | Change |
|------|--------|
| `backend/app/models/scanner_event.py` | Add `signal_quality_score` Float column |
| `backend/app/services/signal_ranker.py` | **New**: `compute_signal_quality_score()`, `load_ranker_config()` |
| `backend/app/services/scanner.py` | Load ranker config once per scan; pass to `_save_event()`; `_save_event()` calls scorer |
| `backend/live_scanner/publisher.py` | `_write_scanner_event()` calls `load_ranker_config()` + scorer. **Note**: the spec's file table lists `conditions.py`, but `conditions.py` is a stateless function with no DB session — scoring is correctly placed in `publisher.py` where the DB session exists. |
| `backend/app/schemas/event.py` | Add `signal_quality_score: Optional[float]` to `ScannerEventResponse` |
| `backend/app/routers/scanner.py` | Default sort to `signal_quality_score`, add `/signal-quality-distribution` |
| `backend/app/alembic/versions/<rev>_add_signal_quality_score.py` | **New**: column + index + seed SystemConfig rows |
| `backend/tests/services/test_signal_ranker.py` | **New**: unit tests for scorer |
| `backend/tests/api/test_scanner.py` | Extend: score in response, default sort, distribution endpoint |
| `frontend/src/api/scanner.ts` | Add `signal_quality_score?: number` to `ScannerEvent`; add `getSignalQualityDistribution()` |
| `frontend/src/components/ScannerResults.tsx` | Replace Score column with score badge; make header sortable |
| `frontend/src/pages/Scanner.tsx` | Change default sort to `signal_quality_score` |
| `frontend/src/pages/EdgeExplorer.tsx` | Add Signal Quality Validation chart |

---

## Tasks

### Task 1 — Add `signal_quality_score` column to `ScannerEvent` model and migration

**Files**: `backend/app/models/scanner_event.py`, `backend/app/alembic/versions/<rev>_add_signal_quality_score.py`

**TDD steps**:

1. **Write failing test** — `backend/tests/services/test_scanner_refactor.py`: add a test that verifies the `ScannerEvent` model has the new column attribute. This tests the ORM layer directly — no schema or endpoint needed at this stage:
   ```python
   def test_scanner_event_model_has_signal_quality_score():
       """Model column exists before any scorer is wired up."""
       from app.models.scanner_event import ScannerEvent
       assert hasattr(ScannerEvent, 'signal_quality_score')
   ```

2. **Verify fail**:
   ```bash
   cd backend && python -m pytest tests/services/test_scanner_refactor.py::test_scanner_event_model_has_signal_quality_score -x
   # Expected: AttributeError — column not yet defined
   ```

3. **Add column to model** — `backend/app/models/scanner_event.py`. Two changes:

   a. Update the import line — add `Float` (the existing line does not have it):
   ```python
   # Before:
   from sqlalchemy import Column, Integer, String, DateTime, Date, Numeric, Uuid as UUID, UniqueConstraint
   # After:
   from sqlalchemy import Column, Integer, String, DateTime, Date, Numeric, Float, Uuid as UUID, UniqueConstraint
   ```

   b. Add column after `updated_at`, before `__table_args__`:
   ```python
   signal_quality_score = Column(Float, nullable=True)
   ```

4. **Generate migration**:
   ```bash
   cd backend
   python -m alembic revision --autogenerate -m "add_signal_quality_score"
   ```
   Expected output: `Generating .../versions/<rev>_add_signal_quality_score.py`

5. **Edit migration** — open the generated file, replace the `upgrade()` body with:
   ```python
   def upgrade() -> None:
       op.add_column('scanner_events',
           sa.Column('signal_quality_score', sa.Float(), nullable=True))
       op.create_index(
           'idx_scanner_events_score',
           'scanner_events',
           ['signal_quality_score'],
           unique=False,
           postgresql_ops={'signal_quality_score': 'DESC NULLS LAST'},
       )
       op.execute("""
           INSERT INTO system_config (key, value, updated_at)
           VALUES
               ('signal_ranker_enabled',  'true',         NOW()),
               ('signal_ranker_weights',  '{"volume_spike_ratio": 0.35, "gap_pct": 0.25, "relative_volume": 0.20, "volume_anomaly_score": 0.15, "float_rotation_pct": 0.05}', NOW()),
               ('signal_ranker_version',  '0.1.0-baseline', NOW())
           ON CONFLICT (key) DO NOTHING
       """)
   
   def downgrade() -> None:
       op.execute("DELETE FROM system_config WHERE key IN ('signal_ranker_enabled', 'signal_ranker_weights', 'signal_ranker_version')")
       op.drop_index('idx_scanner_events_score', table_name='scanner_events')
       op.drop_column('scanner_events', 'signal_quality_score')
   ```

6. **Apply migration**:
   ```bash
   python -m alembic upgrade head
   # Expected: INFO  [alembic.runtime.migration] Running upgrade ... -> <rev>, add_signal_quality_score
   ```

7. **Verify pass**:
   ```bash
   python -m pytest tests/services/test_scanner_refactor.py::test_scanner_event_model_has_signal_quality_score -x
   # Expected: PASSED — column attribute exists on the model
   ```

8. **Commit**:
   ```bash
   git add backend/app/models/scanner_event.py backend/app/alembic/versions/<rev>_add_signal_quality_score.py
   git commit -m "feat(ranker): add signal_quality_score column and migration"
   ```

---

### Task 2 — Build `signal_ranker.py` service module

**Files**: `backend/app/services/signal_ranker.py`, `backend/tests/services/test_signal_ranker.py`

**TDD steps**:

1. **Write failing tests** — `backend/tests/services/test_signal_ranker.py`:
   ```python
   import pytest
   from unittest.mock import MagicMock
   from app.services.signal_ranker import compute_signal_quality_score, load_ranker_config
   from app.models.system_config import SystemConfig
   
   
   def test_score_all_features_present():
       weights = {"volume_spike_ratio": 0.35, "gap_pct": 0.25, "relative_volume": 0.20,
                  "volume_anomaly_score": 0.15, "float_rotation_pct": 0.05}
       indicators = {"volume_spike_ratio": 10.0, "gap_pct": 10.0, "relative_volume": 10.0,
                     "volume_anomaly_score": 2.5, "float_rotation_pct": 25.0}
       score = compute_signal_quality_score(indicators, weights)
       assert 0.0 <= score <= 1.0
       assert score == pytest.approx(0.5, abs=0.01)
   
   
   def test_score_normalizes_over_present_features_only():
       weights = {"volume_spike_ratio": 0.35, "gap_pct": 0.25, "relative_volume": 0.20,
                  "volume_anomaly_score": 0.15, "float_rotation_pct": 0.05}
       # volume_anomaly_score and float_rotation_pct absent
       indicators = {"volume_spike_ratio": 20.0, "gap_pct": 20.0, "relative_volume": 20.0}
       score = compute_signal_quality_score(indicators, weights)
       assert score == pytest.approx(1.0, abs=0.001)
   
   
   def test_score_caps_at_one():
       weights = {"volume_spike_ratio": 1.0}
       indicators = {"volume_spike_ratio": 999.0}  # far above cap of 20
       score = compute_signal_quality_score(indicators, weights)
       assert score == 1.0
   
   
   def test_score_gap_pct_uses_abs():
       weights = {"gap_pct": 1.0}
       positive = compute_signal_quality_score({"gap_pct": 10.0}, weights)
       negative = compute_signal_quality_score({"gap_pct": -10.0}, weights)
       assert positive == negative
   
   
   def test_score_returns_zero_when_no_features_match():
       weights = {"volume_spike_ratio": 0.5}
       score = compute_signal_quality_score({}, weights)
       assert score == 0.0
   
   
   def test_score_rounds_to_three_places():
       weights = {"volume_spike_ratio": 1.0}
       indicators = {"volume_spike_ratio": 7.0}  # 7/20 = 0.35 exactly
       score = compute_signal_quality_score(indicators, weights)
       assert score == 0.35
   
   
   def test_load_ranker_config_enabled():
       db = MagicMock()
       rows = [
           _cfg_row('signal_ranker_enabled', 'true'),
           _cfg_row('signal_ranker_weights', '{"volume_spike_ratio": 0.5, "gap_pct": 0.5}'),
           _cfg_row('signal_ranker_version', '0.1.0-baseline'),
       ]
       db.query.return_value.filter.return_value.all.return_value = rows
       enabled, weights, version = load_ranker_config(db)
       assert enabled is True
       assert weights == {"volume_spike_ratio": 0.5, "gap_pct": 0.5}
       assert version == "0.1.0-baseline"
   
   
   def test_load_ranker_config_disabled():
       db = MagicMock()
       rows = [_cfg_row('signal_ranker_enabled', 'false')]
       db.query.return_value.filter.return_value.all.return_value = rows
       enabled, weights, version = load_ranker_config(db)
       assert enabled is False
   
   
   def test_load_ranker_config_missing_keys_returns_defaults():
       db = MagicMock()
       db.query.return_value.filter.return_value.all.return_value = []
       enabled, weights, version = load_ranker_config(db)
       assert enabled is True
       assert "volume_spike_ratio" in weights
   
   
   def _cfg_row(key, value):
       r = MagicMock(spec=SystemConfig)
       r.key = key
       r.value = value
       return r
   ```

2. **Verify fail**:
   ```bash
   cd backend && python -m pytest tests/services/test_signal_ranker.py -x
   # Expected: ModuleNotFoundError — signal_ranker doesn't exist yet
   ```

3. **Implement** — `backend/app/services/signal_ranker.py`:
   ```python
   import json
   import logging
   from typing import Tuple
   
   from sqlalchemy.orm import Session
   
   from app.models.system_config import SystemConfig
   
   logger = logging.getLogger(__name__)
   
   _DEFAULT_WEIGHTS = {
       "volume_spike_ratio": 0.35,
       "gap_pct": 0.25,
       "relative_volume": 0.20,
       "volume_anomaly_score": 0.15,
       "float_rotation_pct": 0.05,
   }
   _DEFAULT_VERSION = "0.1.0-baseline"
   
   _NORMALIZATION_CAPS = {
       "volume_spike_ratio": 20.0,
       "gap_pct": 20.0,
       "relative_volume": 20.0,
       "volume_anomaly_score": 5.0,
       "float_rotation_pct": 50.0,
   }
   
   _RANKER_KEYS = ["signal_ranker_enabled", "signal_ranker_weights", "signal_ranker_version"]
   
   
   def compute_signal_quality_score(indicators: dict, weights: dict) -> float:
       total_weight = 0.0
       score = 0.0
       for feature, weight in weights.items():
           value = indicators.get(feature)
           if value is None:
               continue
           cap = _NORMALIZATION_CAPS.get(feature, 1.0)
           normalized = min(abs(float(value)) / cap, 1.0)
           score += weight * normalized
           total_weight += weight
       if total_weight == 0.0:
           return 0.0
       return round(score / total_weight, 3)
   
   
   def load_ranker_config(db: Session) -> Tuple[bool, dict, str]:
       rows = db.query(SystemConfig).filter(SystemConfig.key.in_(_RANKER_KEYS)).all()
       cfg = {r.key: r.value for r in rows}
       enabled = cfg.get("signal_ranker_enabled", "true").lower() == "true"
       version = cfg.get("signal_ranker_version", _DEFAULT_VERSION)
       try:
           weights = json.loads(cfg.get("signal_ranker_weights", "{}")) or _DEFAULT_WEIGHTS
       except (json.JSONDecodeError, TypeError):
           logger.warning("signal_ranker_weights invalid JSON — using defaults")
           weights = _DEFAULT_WEIGHTS
       return enabled, weights, version
   ```

4. **Verify pass**:
   ```bash
   python -m pytest tests/services/test_signal_ranker.py -v
   # Expected: all 9 tests PASSED
   ```

5. **Commit**:
   ```bash
   git add backend/app/services/signal_ranker.py backend/tests/services/test_signal_ranker.py
   git commit -m "feat(ranker): add signal_ranker service with compute and config loader"
   ```

---

### Task 3 — Integrate ranker into batch scanner (`ScannerService._save_event`)

**Files**: `backend/app/services/scanner.py`, `backend/tests/services/test_scanner_refactor.py`

**TDD steps**:

1. **Write failing test** — append to `backend/tests/services/test_scanner_refactor.py`:
   ```python
   def test_pre_market_scan_scores_events_when_ranker_enabled():
       """When signal_ranker_enabled=true, _save_event receives a scored event."""
       from app.models.system_config import SystemConfig as SC
   
       ticker = "SCORE"
       event_date = date(2025, 3, 10)
       daily_closes = [100.0] * 25
       daily_volumes = [1_000_000] * 25
       pm_volume = 5_000_000
   
       ranker_rows = [
           MagicMock(spec=SC, key='signal_ranker_enabled', value='true'),
           MagicMock(spec=SC, key='signal_ranker_weights',
                     value='{"volume_spike_ratio": 1.0}'),
           MagicMock(spec=SC, key='signal_ranker_version', value='0.1.0-test'),
       ]
       db = _mock_db_for_pre_market(ticker, event_date, daily_closes, daily_volumes,
                                    pm_volume, system_config_rows=ranker_rows)
   
       saved_events = []
   
       def capture_save(**kwargs):
           saved_events.append(kwargs)
           return {"id": 1, "signal_quality_score": kwargs.get("signal_quality_score")}
   
       with patch.object(ScannerService, '_get_batch_enrichment_data',
                         return_value=({ticker: {}}, {}, {})), \
            patch.object(ScannerService, 'calculate_day_metrics',
                         return_value={"closing_price": 102.0, "pre_market_close": 101.0,
                                       "opening_price": 101.0, "regular_high": 103.0,
                                       "regular_low": 99.0}), \
            patch.object(ScannerService, '_save_event', side_effect=capture_save):
           result = asyncio.run(ScannerService.run_pre_market_scan([ticker], db, event_date))
   
       assert len(saved_events) == 1
       assert "signal_quality_score" in saved_events[0]
       assert saved_events[0]["signal_quality_score"] is not None
   ```

2. **Verify fail**:
   ```bash
   python -m pytest tests/services/test_scanner_refactor.py::test_pre_market_scan_scores_events_when_ranker_enabled -x
   # Expected: AssertionError — signal_quality_score not in saved_events[0]
   ```

3. **Update `scanner.py`**:

   a. Add import at top of `scanner.py`:
   ```python
   from app.services.signal_ranker import compute_signal_quality_score, load_ranker_config
   ```

   b. In `_save_event`, add `signal_quality_score` parameter and apply it:
   ```python
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
       signal_quality_score: float = None,    # ← new param
   ) -> Dict[str, Any]:
   ```

   In the `event_dict` construction, add `"signal_quality_score"` alongside the existing keys:
   ```python
   event_dict = {
       "ticker": ticker,
       "event_date": event_date,
       "scanner_type": scanner_type,
       "summary": summary,
       "severity": severity,
       "previous_close": previous_close,
       "opening_price": opening_price,
       "closing_price": closing_price,
       "indicators": indicators,
       "criteria_met": criteria_met,
       "metadata": enrichment,
       "signal_quality_score": signal_quality_score,   # ← new
   }
   ```

   No other changes to `_save_event` body are needed:
   - **Existing-event branch**: the `for key, value in event_dict.items(): setattr(existing, key, value)` loop already handles `signal_quality_score` because it is a real column (not a special-cased key like `metadata`).
   - **New-event branch**: `model_data = event_dict.copy()` + `model_data["metadata_"] = model_data.pop("metadata")` already propagates `signal_quality_score` automatically since it is not the renamed `metadata` key.

   c. In `run_pre_market_scan`, load ranker config immediately after the TimesFM config block (around line 399 in `scanner.py`). Insert one line after the existing `fallback_multiplier = ...` assignment:
   ```python
   # existing TimesFM config block (unchanged)
   _timesfm_config_keys = [
       'timesfm_enabled', 'timesfm_anomaly_threshold',
       'timesfm_min_history_bars', 'timesfm_fallback_multiplier',
   ]
   _cfg_rows = db.query(SystemConfig).filter(SystemConfig.key.in_(_timesfm_config_keys)).all()
   _cfg = {r.key: r.value for r in _cfg_rows}
   timesfm_enabled = _cfg.get('timesfm_enabled', 'false').lower() == 'true'
   anomaly_threshold = float(_cfg.get('timesfm_anomaly_threshold', '2.0'))
   min_history_bars = int(_cfg.get('timesfm_min_history_bars', '30'))
   fallback_multiplier = float(_cfg.get('timesfm_fallback_multiplier', '4.0'))

   # NEW: load signal ranker config once before the ticker loop
   _ranker_enabled, _ranker_weights, _ranker_version = load_ranker_config(db)
   ```

   d. In the `_save_event` call within `run_pre_market_scan`, compute and pass the score:
   ```python
   _score = (
       compute_signal_quality_score(indicators, _ranker_weights)
       if _ranker_enabled else None
   )
   event_dict = ScannerService._save_event(
       db=db,
       ticker=ticker,
       event_date=event_date,
       scanner_type="pre_market_volume_spike",
       indicators=indicators,
       criteria_met=criteria_met,
       enrichment=enrichment,
       previous_close=previous_close,
       opening_price=day_metrics["opening_price"],
       closing_price=day_metrics["closing_price"],
       signal_quality_score=_score,
   )
   ```

   e. Apply the same pattern to `run_oversold_bounce_scan` (line 605). Add `load_ranker_config(db)` immediately after the `enrichment_batch, _, _` line — there is no TimesFM block, so insert after that `await asyncio.to_thread(...)` call:
   ```python
   enrichment_batch, _, _ = await asyncio.to_thread(
       ScannerService._get_batch_enrichment_data, tickers, event_date, db
   )

   # NEW: load signal ranker config once before the ticker loop
   _ranker_enabled, _ranker_weights, _ranker_version = load_ranker_config(db)
   ```

   At the `_save_event` call site inside `run_oversold_bounce_scan` (around line 710), add score computation and pass it:
   ```python
   _score = (
       compute_signal_quality_score(indicators, _ranker_weights)
       if _ranker_enabled else None
   )
   event_dict = ScannerService._save_event(
       db=db,
       ticker=ticker,
       event_date=event_date,
       scanner_type="oversold_bounce",
       indicators=indicators,
       criteria_met=criteria_met,
       enrichment=enrichment,
       previous_close=float(today['prev_close']),
       opening_price=float(today['Open']),
       closing_price=float(today['Close']),
       signal_quality_score=_score,
   )
   ```

4. **Verify pass**:
   ```bash
   python -m pytest tests/services/test_scanner_refactor.py -v
   # Expected: all existing tests still PASSED, new test PASSED
   ```

5. **Commit**:
   ```bash
   git add backend/app/services/scanner.py
   git commit -m "feat(ranker): integrate signal scorer into batch scanner _save_event"
   ```

---

### Task 4 — Integrate ranker into live scanner (`LivePublisher._write_scanner_event`)

**Files**: `backend/live_scanner/publisher.py`, `backend/tests/services/test_signal_ranker.py`

**TDD steps**:

1. **Write failing test** — append to `backend/tests/services/test_signal_ranker.py`:
   ```python
   def test_live_publisher_scores_event():
       """_write_scanner_event stores a non-null signal_quality_score when ranker enabled."""
       from unittest.mock import patch, MagicMock
       from live_scanner.publisher import LivePublisher
       from live_scanner.bar_aggregator import MinuteBar, ET
       from live_scanner.conditions import ConditionResult
       from datetime import datetime, timezone
   
       bar = MagicMock(spec=MinuteBar)
       bar.symbol = "TEST"
       bar.minute_ts = datetime(2026, 5, 14, 9, 31, tzinfo=timezone.utc)
       bar.prior_close = 50.0
       bar.close = 51.0
       bar.session = "pre"
   
       condition = ConditionResult(
           scanner_type="live_volume_spike",
           indicators={"volume_spike_ratio": 8.0, "relative_volume": 3.0},
           criteria_met={"volume_spike_4x": True},
       )
   
       publisher = LivePublisher.__new__(LivePublisher)
       publisher._engine = MagicMock()
   
       saved_kwargs = {}
   
       class FakeSession:
           def __enter__(self): return self
           def __exit__(self, *a): pass
           def add(self, obj): saved_kwargs['event'] = obj
           def commit(self): pass
           def refresh(self, obj): obj.id = 42
   
       with patch("live_scanner.publisher.Session", return_value=FakeSession()), \
            patch("live_scanner.publisher.load_ranker_config",
                  return_value=(True, {"volume_spike_ratio": 1.0}, "0.1.0-baseline")):
           result = publisher._write_scanner_event(bar, condition, "spike", "high")
   
       event = saved_kwargs['event']
       assert event.signal_quality_score is not None
       assert 0.0 <= event.signal_quality_score <= 1.0
   ```

2. **Verify fail**:
   ```bash
   python -m pytest tests/services/test_signal_ranker.py::test_live_publisher_scores_event -x
   # Expected: AttributeError — ScannerEvent has no signal_quality_score (before Task 1) 
   # or assertion failure (after Task 1, before integration)
   ```

3. **Update `publisher.py`**:

   Add import at top of `live_scanner/publisher.py`:
   ```python
   from app.services.signal_ranker import compute_signal_quality_score, load_ranker_config
   ```

   In `_write_scanner_event`, add scoring before the `ScannerEvent(...)` construction:
   ```python
   def _write_scanner_event(
       self,
       bar: MinuteBar,
       condition: ConditionResult,
       summary: str,
       severity: str,
   ) -> int | None:
       today = bar.minute_ts.astimezone(ET).date()
   
       with Session(self._engine) as session:
           ranker_enabled, ranker_weights, _ = load_ranker_config(session)
           score = (
               compute_signal_quality_score(condition.indicators, ranker_weights)
               if ranker_enabled else None
           )
   
           event = ScannerEvent(
               uuid=uuid_module.uuid4(),
               ticker=bar.symbol,
               event_date=today,
               scanner_type=condition.scanner_type,
               summary=summary,
               severity=severity,
               previous_close=bar.prior_close if bar.prior_close > 0 else None,
               closing_price=bar.close,
               indicators=condition.indicators,
               criteria_met=condition.criteria_met,
               metadata_={"source": "live_scanner", "session": bar.session},
               signal_quality_score=score,
           )
   
           try:
               session.add(event)
               session.commit()
               session.refresh(event)
               logger.debug(
                   f"LivePublisher: ScannerEvent created — "
                   f"{bar.symbol} {condition.scanner_type} {today}"
               )
               return event.id
           except IntegrityError:
               session.rollback()
               logger.debug(
                   f"LivePublisher: ScannerEvent already exists for "
                   f"{bar.symbol} {condition.scanner_type} {today} — skipping"
               )
               return None
   ```

   Note: the existing `with Session(...) as session:` block is being restructured — the session is opened once at the top of the method so `load_ranker_config` can use it.

4. **Verify pass**:
   ```bash
   python -m pytest tests/services/test_signal_ranker.py -v
   # Expected: all tests PASSED
   ```

5. **Commit**:
   ```bash
   git add backend/live_scanner/publisher.py
   git commit -m "feat(ranker): integrate signal scorer into live scanner event writer"
   ```

---

### Task 5 — Update API schema, scanner results endpoint, and add distribution endpoint

**Files**: `backend/app/schemas/event.py`, `backend/app/routers/scanner.py`, `backend/tests/api/test_scanner.py`

**TDD steps**:

1. **Write failing tests** — append to `backend/tests/api/test_scanner.py`:
   ```python
   def test_results_includes_signal_quality_score(db: Session):
       """score field present in API response after schema is updated."""
       seed_scanner_events(db)
       app.dependency_overrides[get_db] = lambda: db
       response = client.get("/api/scanner/results")
       app.dependency_overrides.clear()
       assert response.status_code == 200
       data = response.json()
       assert len(data) > 0
       assert "signal_quality_score" in data[0]

   def test_results_default_sort_is_signal_quality_score(db: Session):
       """GET /api/scanner/results with no sort_by defaults to signal_quality_score DESC."""
       seed_scanner_events(db)
       # Set scores on events so we can verify ordering
       events = db.query(ScannerEvent).all()
       for i, ev in enumerate(events):
           ev.signal_quality_score = round(i * 0.1 % 1.0, 3)
       db.flush()
   
       app.dependency_overrides[get_db] = lambda: db
       response = client.get("/api/scanner/results")
       app.dependency_overrides.clear()
   
       assert response.status_code == 200
       data = response.json()
       scores = [e.get("signal_quality_score") for e in data if e.get("signal_quality_score") is not None]
       if len(scores) >= 2:
           assert scores == sorted(scores, reverse=True)
   
   
   def test_signal_quality_distribution_returns_deciles(db: Session):
       """GET /api/scanner/signal-quality-distribution returns decile data."""
       app.dependency_overrides[get_db] = lambda: db
       response = client.get("/api/scanner/signal-quality-distribution")
       app.dependency_overrides.clear()
       assert response.status_code == 200
       body = response.json()
       assert "deciles" in body
       assert isinstance(body["deciles"], list)
   
   
   def test_signal_quality_distribution_empty_when_no_outcomes(db: Session):
       """Distribution returns empty deciles when no complete ScannerOutcomeSummary rows."""
       seed_scanner_events(db)
       app.dependency_overrides[get_db] = lambda: db
       response = client.get("/api/scanner/signal-quality-distribution")
       app.dependency_overrides.clear()
       assert response.status_code == 200
       assert response.json()["deciles"] == []
   ```

2. **Verify fail**:
   ```bash
   python -m pytest tests/api/test_scanner.py::test_results_default_sort_is_signal_quality_score tests/api/test_scanner.py::test_signal_quality_distribution_returns_deciles -x
   # Expected: assertion failure on sort, 404 on distribution endpoint
   ```

3. **Update schema** — `backend/app/schemas/event.py`:
   ```python
   class ScannerEventResponse(BaseModel):
       """Full detailed schema for scanner event API responses."""
       id: int
       uuid: uuid.UUID
       ticker: str
       event_date: date
       scanner_type: str
   
       summary: Optional[str] = None
       severity: Optional[str] = "medium"
   
       previous_close: Optional[float] = None
       opening_price: Optional[float] = None
       closing_price: Optional[float] = None
   
       signal_quality_score: Optional[float] = None   # ← new
   
       indicators: Dict[str, Any] = Field(default_factory=dict)
       criteria_met: Dict[str, Any] = Field(default_factory=dict)
       metadata: Dict[str, Any] = Field(default_factory=dict, alias="metadata_")
   
       created_at: datetime
       updated_at: datetime
   
       model_config = ConfigDict(from_attributes=True, populate_by_name=True)
   ```

4. **Update scanner results endpoint** — `backend/app/routers/scanner.py`:

   Change default parameter:
   ```python
   @router.get("/results", response_model=List[ScannerEventResponse])
   def get_scanner_results(
       ticker: Optional[str] = None,
       scanner_type: Optional[str] = None,
       event_type: Optional[str] = None,
       universe_id: Optional[int] = None,
       sort_by: Optional[str] = "signal_quality_score",   # ← was "created_at"
       sort_order: Optional[str] = "desc",
       limit: int = 100,
       offset: int = 0,
       db: Session = Depends(get_db),
   ):
   ```

   Update the sorting block to handle `signal_quality_score` null-last ordering:
   ```python
   try:
       if sort_by:
           if sort_by == "signal_quality_score":
               if sort_order.lower() == "desc":
                   query = query.order_by(ScannerEvent.signal_quality_score.desc().nulls_last())
               else:
                   query = query.order_by(ScannerEvent.signal_quality_score.asc().nulls_last())
           else:
               sort_attr = getattr(ScannerEvent, sort_by, ScannerEvent.created_at)
               if sort_order.lower() == "desc":
                   query = query.order_by(sort_attr.desc())
               else:
                   query = query.order_by(sort_attr.asc())
       else:
           query = query.order_by(ScannerEvent.created_at.desc())
   except Exception:
       query = query.order_by(ScannerEvent.created_at.desc())
   ```

5. **Add distribution endpoint** — append to `backend/app/routers/scanner.py`:

   Add imports at top of file (if not already present):
   ```python
   from sqlalchemy import func   # promote to module level; also DELETE the local `from sqlalchemy import func` lines inside `get_scanner_stats` and `get_scan_status_block` (two occurrences)
   from app.models.scanner_outcome_summary import ScannerOutcomeSummary   # new model import
   from app.models.system_config import SystemConfig   # needed for version lookup in distribution endpoint
   ```
   Note: `import sqlalchemy as sa` is already present at line 13 of `scanner.py` — do not add it again.

   Add the endpoint:
   ```python
   @router.get("/signal-quality-distribution")
   def get_signal_quality_distribution(
       scanner_type: Optional[str] = None,
       start_date: Optional[str] = None,
       end_date: Optional[str] = None,
       db: Session = Depends(get_db),
   ):
       """Return avg eod_pct_change and follow_through rate per score decile."""
       query = (
           db.query(
               func.floor(ScannerEvent.signal_quality_score * 10) / 10,
               func.count(ScannerOutcomeSummary.id),
               func.avg(ScannerOutcomeSummary.eod_pct_change),
               func.avg(sa.cast(ScannerOutcomeSummary.follow_through, sa.Float)),
           )
           .join(ScannerOutcomeSummary,
                 ScannerOutcomeSummary.scanner_event_id == ScannerEvent.id)
           .filter(
               ScannerOutcomeSummary.is_complete == True,
               ScannerEvent.signal_quality_score.isnot(None),
           )
       )
   
       if scanner_type:
           query = query.filter(ScannerEvent.scanner_type == scanner_type)
       if start_date:
           query = query.filter(ScannerEvent.event_date >= start_date)
       if end_date:
           query = query.filter(ScannerEvent.event_date <= end_date)
   
       query = query.group_by(func.floor(ScannerEvent.signal_quality_score * 10) / 10)
       query = query.order_by(func.floor(ScannerEvent.signal_quality_score * 10) / 10)
   
       rows = query.all()
   
       deciles = []
       for decile_floor, count, avg_eod, avg_follow in rows:
           if decile_floor is None:
               continue
           lo = float(decile_floor)
           hi = round(lo + 0.1, 1)
           deciles.append({
               "decile": f"{lo:.1f}–{hi:.1f}",
               "count": count,
               "avg_eod_pct": round(float(avg_eod), 3) if avg_eod is not None else None,
               "follow_through_rate": round(float(avg_follow), 3) if avg_follow is not None else None,
           })
   
       # Include signal_ranker_version so the frontend can display the weight set subtitle
       version_row = db.query(SystemConfig).filter(SystemConfig.key == "signal_ranker_version").first()
       version = version_row.value if version_row else "0.1.0-baseline"

       return {"deciles": deciles, "signal_ranker_version": version}
   ```

   Also add `import sqlalchemy as sa` near the top imports block if not already present, and add `ScannerOutcomeSummary` to the model imports if not already present.

6. **Verify pass**:
   ```bash
   python -m pytest tests/api/test_scanner.py -v
   # Expected: all tests PASSED including the 3 new ones
   ```

7. **Commit**:
   ```bash
   git add backend/app/schemas/event.py backend/app/routers/scanner.py
   git commit -m "feat(ranker): expose signal_quality_score in API, default sort, add distribution endpoint"
   ```

---

### Task 6 — Frontend: API types, ScannerResults score badge, Scanner page default sort

**Files**: `frontend/src/api/scanner.ts`, `frontend/src/components/ScannerResults.tsx`, `frontend/src/pages/Scanner.tsx`

**TDD steps** (TypeScript — verify with `tsc`):

1. **Write failing check**:
   ```bash
   cd frontend && npx tsc --noEmit 2>&1 | head -20
   # Baseline: should be clean now (no errors before our changes)
   ```

2. **Update `ScannerEvent` interface** — `frontend/src/api/scanner.ts`:
   ```typescript
   export interface ScannerEvent {
     id: number;
     uuid: string;
     ticker: string;
     event_date: string;
     scanner_type: string;
   
     summary?: string;
     severity: 'low' | 'medium' | 'high';
   
     previous_close?: number;
     opening_price?: number;
     closing_price?: number;
   
     signal_quality_score?: number | null;   // ← new
   
     indicators: Record<string, any>;
     criteria_met: Record<string, any>;
     metadata: Record<string, any>;
   
     created_at: string;
     updated_at: string;
   }
   ```

3. **Add `getSignalQualityDistribution` API function** — `frontend/src/api/scanner.ts`, append before the last export:
   ```typescript
   export interface SignalQualityDecile {
     decile: string;
     count: number;
     avg_eod_pct: number | null;
     follow_through_rate: number | null;
   }
   
   export interface SignalQualityDistributionResponse {
     deciles: SignalQualityDecile[];
   }
   
   export const getSignalQualityDistribution = async (params: {
     scanner_type?: string;
     start_date?: string;
     end_date?: string;
   } = {}): Promise<SignalQualityDistributionResponse> => {
     const query = new URLSearchParams();
     if (params.scanner_type) query.append('scanner_type', params.scanner_type);
     if (params.start_date) query.append('start_date', params.start_date);
     if (params.end_date) query.append('end_date', params.end_date);
     const response = await apiClient.get<SignalQualityDistributionResponse>(
       `/api/scanner/signal-quality-distribution?${query.toString()}`
     );
     return response.data;
   };
   ```

4. **Update `ScannerResults.tsx`** — replace the Score column header `<th>` and the score cell:

   Replace this block (Score column header, currently a plain `<th>`):
   ```tsx
   <th className="py-3 px-4">Score</th>
   ```
   With:
   ```tsx
   <SortableHeader
     label="Score"
     sortKey="signal_quality_score"
     currentSort={sortBy}
     currentOrder={sortOrder}
     onSort={onSort}
   />
   ```

   Replace the score cell (currently renders `criteria_met` ratio badge):
   ```tsx
   {/* was: criteria_met ratio badge */}
   <td className="py-3 px-4">
     <ScoreQualityBadge
       score={event.signal_quality_score ?? null}
       criteriaMet={event.criteria_met}
     />
   </td>
   ```

   Add the `ScoreQualityBadge` helper component at the bottom of the file (before the default export):
   ```tsx
   interface ScoreQualityBadgeProps {
     score: number | null | undefined;
     criteriaMet: Record<string, any>;
   }
   
   const ScoreQualityBadge: React.FC<ScoreQualityBadgeProps> = ({ score, criteriaMet }) => {
     const criteriaRatio = `${Object.values(criteriaMet || {}).filter(Boolean).length}/${Object.values(criteriaMet || {}).length}`;
   
     if (score == null) {
       return (
         <span className="text-gray-500 font-mono text-xs" title={criteriaRatio}>—</span>
       );
     }
   
     let colorClass: string;
     if (score >= 0.7) {
       colorClass = 'bg-green-500/20 text-green-400 border-green-500/30';
     } else if (score >= 0.4) {
       colorClass = 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30';
     } else {
       colorClass = 'bg-gray-500/20 text-gray-400 border-gray-500/30';
     }
   
     return (
       <span
         className={`px-2 py-1 rounded text-xs font-black border ${colorClass}`}
         title={criteriaRatio}
       >
         {score.toFixed(2)}
       </span>
     );
   };
   ```

5. **Update `Scanner.tsx`** — change initial state for `sortBy`:
   ```typescript
   const [sortBy, setSortBy] = useState<string>('signal_quality_score');
   ```
   (was `'created_at'`)

6. **Verify pass**:
   ```bash
   cd frontend && npx tsc --noEmit
   # Expected: no errors
   ```

7. **Commit**:
   ```bash
   git add frontend/src/api/scanner.ts frontend/src/components/ScannerResults.tsx frontend/src/pages/Scanner.tsx
   git commit -m "feat(ranker): add score badge to scanner results, default sort by signal_quality_score"
   ```

---

### Task 7 — Frontend: EdgeExplorer Signal Quality Validation chart

**Files**: `frontend/src/pages/EdgeExplorer.tsx`

**TDD steps**:

1. **Add import** — `frontend/src/pages/EdgeExplorer.tsx`:
   ```typescript
   import {
     getSignalQualityDistribution,
     SignalQualityDecile,
   } from '../api/scanner';
   import {
     ComposedChart,
     Bar,
     Line,
     XAxis,
     YAxis,
     CartesianGrid,
     Tooltip,
     Legend,
     ResponsiveContainer,
   } from 'recharts';
   ```
   (Add any Recharts imports not already present to the existing import line.)

2. **Update `SignalQualityDistributionResponse` interface** — `frontend/src/api/scanner.ts`:
   Add `signal_ranker_version: string` to the response interface:
   ```typescript
   export interface SignalQualityDistributionResponse {
     deciles: SignalQualityDecile[];
     signal_ranker_version: string;
   }
   ```

3. **Add query** — inside the `EdgeExplorer` component, alongside existing queries. Pass only `scanner_type` — the existing component has `scannerType` and `ticker` state but no explicit `startDate`/`endDate` state variables:
   ```typescript
   const { data: qualityDist, isLoading: loadingQualityDist } = useQuery({
     queryKey: ['signalQualityDistribution', scannerType],
     queryFn: () => getSignalQualityDistribution({
       scanner_type: scannerType || undefined,
     }),
   });
   ```

4. **Add chart section** — in the JSX, after the existing charts block:
   ```tsx
   <Card title="Signal Quality Validation" icon={TrendingUp as any}>
     {loadingQualityDist ? (
       <div className="flex items-center justify-center h-48 text-gray-500">Loading…</div>
     ) : !qualityDist?.deciles?.length ? (
       <div className="flex items-center justify-center h-48 text-gray-500 text-sm">
         No outcome data yet — scores will appear here once ScannerOutcomeSummary rows are complete.
       </div>
     ) : (
       <>
         <p className="text-xs text-gray-500 mb-3">
           Weight set:{' '}
           <span className="font-mono">{qualityDist.signal_ranker_version}</span>
         </p>
         <ResponsiveContainer width="100%" height={260}>
           <ComposedChart data={qualityDist.deciles} margin={{ top: 10, right: 30, left: 0, bottom: 0 }}>
             <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
             <XAxis dataKey="decile" tick={{ fill: '#9CA3AF', fontSize: 10 }} />
             <YAxis
               yAxisId="left"
               tickFormatter={(v) => `${v.toFixed(1)}%`}
               tick={{ fill: '#9CA3AF', fontSize: 10 }}
               label={{ value: 'Avg EOD %', angle: -90, position: 'insideLeft', fill: '#6B7280', fontSize: 11 }}
             />
             <YAxis
               yAxisId="right"
               orientation="right"
               tickFormatter={(v) => `${(v * 100).toFixed(0)}%`}
               tick={{ fill: '#9CA3AF', fontSize: 10 }}
               label={{ value: 'Follow-through', angle: 90, position: 'insideRight', fill: '#6B7280', fontSize: 11 }}
             />
             <Tooltip
               contentStyle={{ backgroundColor: '#1F2937', border: '1px solid #374151' }}
               formatter={(value: number, name: string) => {
                 if (name === 'avg_eod_pct') return [`${value?.toFixed(2)}%`, 'Avg EOD %'];
                 if (name === 'follow_through_rate') return [`${(value * 100).toFixed(1)}%`, 'Follow-through'];
                 return [value, name];
               }}
             />
             <Legend />
             <Bar yAxisId="left" dataKey="avg_eod_pct" fill="#3B82F6" name="avg_eod_pct" radius={[2, 2, 0, 0]} />
             <Line yAxisId="right" type="monotone" dataKey="follow_through_rate" stroke="#10B981" dot={false} name="follow_through_rate" />
           </ComposedChart>
         </ResponsiveContainer>
       </>
     )}
   </Card>
   ```

4. **Verify pass**:
   ```bash
   cd frontend && npx tsc --noEmit
   # Expected: no errors
   ```

5. **Commit**:
   ```bash
   git add frontend/src/pages/EdgeExplorer.tsx
   git commit -m "feat(ranker): add Signal Quality Validation chart to EdgeExplorer"
   ```

---

## Validation Checklist

After all tasks are complete, run the full validation sequence:

```bash
# 1. Confirm migration applied
docker-compose exec backend python -m alembic current
# Expected: <rev> (head)

# 2. Run all backend tests
docker-compose exec backend python -m pytest -x
# Expected: no failures

# 3. Confirm backend reloaded and new endpoint works
curl -s http://localhost:8000/api/scanner/signal-quality-distribution | python -m json.tool
# Expected: {"deciles": []}  (empty — no complete outcomes yet)

# 4. Confirm results default sort
curl -s "http://localhost:8000/api/scanner/results?limit=5" | python -m json.tool | grep signal_quality_score
# Expected: signal_quality_score field present in each object

# 5. TypeScript check
cd frontend && npx tsc --noEmit
# Expected: no errors
```

---

## Open Questions (from spec, non-blocking)

- Should Phase 2b weights eventually be scanner-type-specific? Current design: single weight set. Extensible later by making `signal_ranker_weights` a dict keyed by scanner type.
- Historical backfill of `signal_quality_score` for existing `ScannerEvent` rows? Column is nullable — backfill is optional and can be done via a one-off script.
- `signal_ranker_version` is hardcoded in the EdgeExplorer chart — a future task could fetch it dynamically from `/api/system/config`.
