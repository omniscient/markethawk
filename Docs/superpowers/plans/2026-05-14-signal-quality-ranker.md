# Signal Quality Ranker — Implementation Plan

**Date**: 2026-05-14  
**Issue**: #23 — feat(phase-2c): Signal quality ranker  
**Spec**: `Docs/superpowers/specs/2026-05-14-signal-quality-ranker-design.md`  
**Branch**: `refine/issue-23-feat-phase-2c---signal-quality-ranker`

---

## Goal

Attach a `signal_quality_score` (Float, 0.0–1.0) to every `ScannerEvent` at creation time using a lightweight weighted sum of normalized indicator values. Surface the score in the scanner results UI (replacing the criteria_met badge) and add an EdgeExplorer validation chart that correlates score deciles with actual returns.

---

## Architecture

```
signal_ranker.py (new service)
  ├── compute_signal_quality_score(indicators, weights) → float
  └── load_ranker_config(db) → (enabled, weights, version)

ScannerService.run_pre_market_scan()
  └── loads ranker config once → passes weights to _save_event()

ScannerService._save_event()
  └── calls compute_signal_quality_score → sets event.signal_quality_score

LivePublisher._write_scanner_event()
  └── calls load_ranker_config + compute_signal_quality_score → sets event.signal_quality_score

GET /api/scanner/results
  └── sorts by signal_quality_score DESC NULLS LAST by default

GET /api/scanner/signal-quality-distribution
  └── joins scanner_events + scanner_outcome_summaries, groups by score decile
```

---

## Tech Stack

- **Backend**: FastAPI, SQLAlchemy 2.0 (sync ORM), Alembic migrations, Pydantic schemas
- **Frontend**: React 18, TypeScript, React Query, Recharts (ComposedChart)
- **Tests**: pytest (integration tests using real Postgres via testcontainers)

---

## File Structure

| File | Change |
|------|--------|
| `backend/app/services/signal_ranker.py` | **New** — `compute_signal_quality_score`, `load_ranker_config` |
| `backend/app/models/scanner_event.py` | Add `signal_quality_score Float nullable` column |
| `backend/app/alembic/versions/<rev>_add_signal_quality_score.py` | **New** migration — column, index, SystemConfig seeds |
| `backend/app/services/scanner.py` | Load ranker config per scan; pass weights to `_save_event`; set score |
| `backend/live_scanner/publisher.py` | Call `load_ranker_config` + scorer in `_write_scanner_event` |
| `backend/app/schemas/event.py` | Add `signal_quality_score: Optional[float]` to `ScannerEventResponse` |
| `backend/app/routers/scanner.py` | Default sort to `signal_quality_score` DESC NULLS LAST; add distribution endpoint |
| `backend/tests/services/test_signal_ranker.py` | **New** — unit tests for scorer |
| `backend/tests/api/test_scanner.py` | Add distribution endpoint tests |
| `frontend/src/api/scanner.ts` | Add `signal_quality_score?: number` + distribution types/function |
| `frontend/src/components/ScannerResults.tsx` | Replace criteria_met badge with score badge; Score → SortableHeader |
| `frontend/src/pages/Scanner.tsx` | Change default `sortBy` to `signal_quality_score` |
| `frontend/src/pages/EdgeExplorer.tsx` | Add Signal Quality Validation chart section |

---

## Task 1 — Create `signal_ranker.py` service with unit tests

**Files**: `backend/app/services/signal_ranker.py`, `backend/tests/services/test_signal_ranker.py`

### Step 1.1 — Write failing tests

Create `backend/tests/services/test_signal_ranker.py`:

```python
"""Unit tests for signal_ranker service."""

import pytest
from unittest.mock import MagicMock

from app.services.signal_ranker import compute_signal_quality_score, load_ranker_config
from app.models.system_config import SystemConfig


BASELINE_WEIGHTS = {
    "volume_spike_ratio": 0.35,
    "gap_pct": 0.25,
    "relative_volume": 0.20,
    "volume_anomaly_score": 0.15,
    "float_rotation_pct": 0.05,
}


class TestComputeSignalQualityScore:
    def test_all_features_present(self):
        indicators = {
            "volume_spike_ratio": 10.0,   # 10/20 = 0.5
            "gap_pct": 5.0,               # 5/20 = 0.25
            "relative_volume": 8.0,       # 8/20 = 0.4
            "volume_anomaly_score": 2.5,  # 2.5/5 = 0.5
            "float_rotation_pct": 25.0,   # 25/50 = 0.5
        }
        score = compute_signal_quality_score(indicators, BASELINE_WEIGHTS)
        # expected: (0.35*0.5 + 0.25*0.25 + 0.20*0.4 + 0.15*0.5 + 0.05*0.5) / 1.0
        # = (0.175 + 0.0625 + 0.08 + 0.075 + 0.025) = 0.4175
        assert score == pytest.approx(0.418, abs=0.001)

    def test_partial_features_renormalizes(self):
        indicators = {"volume_spike_ratio": 20.0}  # capped at 1.0
        score = compute_signal_quality_score(indicators, BASELINE_WEIGHTS)
        # Only volume_spike_ratio present: total_weight=0.35, score = 0.35*1.0/0.35 = 1.0
        assert score == 1.0

    def test_no_features_returns_zero(self):
        score = compute_signal_quality_score({}, BASELINE_WEIGHTS)
        assert score == 0.0

    def test_none_values_skipped(self):
        indicators = {"volume_spike_ratio": None, "gap_pct": 10.0}
        score = compute_signal_quality_score(indicators, BASELINE_WEIGHTS)
        # Only gap_pct: 10/20=0.5; total_weight=0.25; score=0.25*0.5/0.25=0.5
        assert score == 0.5

    def test_capped_at_one(self):
        indicators = {"volume_spike_ratio": 9999.0}
        score = compute_signal_quality_score(indicators, BASELINE_WEIGHTS)
        assert score == 1.0

    def test_negative_gap_uses_abs(self):
        # gap_pct of -10 should give same score as +10
        pos = compute_signal_quality_score({"gap_pct": 10.0}, BASELINE_WEIGHTS)
        neg = compute_signal_quality_score({"gap_pct": -10.0}, BASELINE_WEIGHTS)
        assert pos == neg

    def test_returns_3_decimal_places(self):
        indicators = {"volume_spike_ratio": 7.3}
        score = compute_signal_quality_score(indicators, BASELINE_WEIGHTS)
        assert score == round(score, 3)

    def test_empty_weights_returns_zero(self):
        indicators = {"volume_spike_ratio": 10.0}
        score = compute_signal_quality_score(indicators, {})
        assert score == 0.0


class TestLoadRankerConfig:
    def test_returns_defaults_when_no_config(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.all.return_value = []
        enabled, weights, version = load_ranker_config(db)
        assert enabled is True
        assert "volume_spike_ratio" in weights
        assert version == "0.1.0-baseline"

    def test_disabled_when_config_false(self):
        db = MagicMock()
        rows = [
            MagicMock(key="signal_ranker_enabled", value="false"),
        ]
        db.query.return_value.filter.return_value.all.return_value = rows
        enabled, weights, version = load_ranker_config(db)
        assert enabled is False

    def test_parses_json_weights(self):
        import json
        db = MagicMock()
        custom = {"volume_spike_ratio": 1.0}
        rows = [
            MagicMock(key="signal_ranker_weights", value=json.dumps(custom)),
        ]
        db.query.return_value.filter.return_value.all.return_value = rows
        enabled, weights, version = load_ranker_config(db)
        assert weights == custom
```

Run (expect collection, no implementation yet):
```bash
cd backend && python -m pytest tests/services/test_signal_ranker.py -v 2>&1 | tail -5
# Expected: ERROR/ImportError — module does not exist yet
```

### Step 1.2 — Implement `signal_ranker.py`

Create `backend/app/services/signal_ranker.py`:

```python
"""
Signal quality ranker — lightweight weighted scorer for ScannerEvent.
"""

import json
import logging
from typing import Any, Dict, Tuple

from sqlalchemy.orm import Session

from app.models.system_config import SystemConfig

logger = logging.getLogger(__name__)

_NORMALIZATION_CAPS: Dict[str, float] = {
    "volume_spike_ratio":   20.0,
    "gap_pct":              20.0,
    "relative_volume":      20.0,
    "volume_anomaly_score": 5.0,
    "float_rotation_pct":   50.0,
}

_DEFAULT_WEIGHTS: Dict[str, float] = {
    "volume_spike_ratio":   0.35,
    "gap_pct":              0.25,
    "relative_volume":      0.20,
    "volume_anomaly_score": 0.15,
    "float_rotation_pct":   0.05,
}

_DEFAULT_VERSION = "0.1.0-baseline"

_CONFIG_KEYS = [
    "signal_ranker_enabled",
    "signal_ranker_weights",
    "signal_ranker_version",
]


def compute_signal_quality_score(
    indicators: Dict[str, Any],
    weights: Dict[str, float],
) -> float:
    """
    Weighted sum of normalized feature values.
    Re-normalizes over present features only so the score stays 0.0–1.0.
    Returns 0.0 when weights or matching indicators are empty.
    """
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


def load_ranker_config(db: Session) -> Tuple[bool, Dict[str, float], str]:
    """
    Fetch signal ranker config from SystemConfig.
    Returns (enabled, weights, version). Falls back to defaults when keys absent.
    """
    rows = (
        db.query(SystemConfig)
        .filter(SystemConfig.key.in_(_CONFIG_KEYS))
        .all()
    )
    cfg = {r.key: r.value for r in rows}

    enabled = cfg.get("signal_ranker_enabled", "true").lower() == "true"
    version = cfg.get("signal_ranker_version", _DEFAULT_VERSION)

    raw_weights = cfg.get("signal_ranker_weights")
    if raw_weights:
        try:
            weights = json.loads(raw_weights)
        except (json.JSONDecodeError, TypeError):
            logger.warning("signal_ranker_weights is malformed JSON — using defaults")
            weights = _DEFAULT_WEIGHTS
    else:
        weights = _DEFAULT_WEIGHTS

    return enabled, weights, version
```

### Step 1.3 — Verify tests pass

```bash
cd backend && python -m pytest tests/services/test_signal_ranker.py -v
# Expected: 11 passed (8 compute tests + 3 config tests)
```

### Step 1.4 — Commit

```bash
git add backend/app/services/signal_ranker.py backend/tests/services/test_signal_ranker.py
git commit -m "feat(ranker): add signal_ranker service with scoring function and config loader"
```

---

## Task 2 — Add `signal_quality_score` column and migration

**Files**: `backend/app/models/scanner_event.py`, `backend/app/alembic/versions/<rev>_add_signal_quality_score.py`

### Step 2.1 — Add column to ORM model

Edit `backend/app/models/scanner_event.py`. Add after the `updated_at` column:

```python
from sqlalchemy import Column, Integer, String, DateTime, Date, Numeric, Uuid as UUID, Float, UniqueConstraint
```

Add the column after `updated_at`:

```python
    signal_quality_score = Column(Float, nullable=True, index=False)
```

Full updated model `__table_args__` — no change needed there.

### Step 2.2 — Generate migration

```bash
cd backend && python -m alembic revision --autogenerate -m "add_signal_quality_score_to_scanner_events"
# Expected output: Generating .../add_signal_quality_score_to_scanner_events.py ... done
```

### Step 2.3 — Edit migration to add index and seed SystemConfig

Open the generated file and replace the `upgrade()` / `downgrade()` functions:

```python
import json
from alembic import op
import sqlalchemy as sa


def upgrade() -> None:
    # 1. Add nullable column
    op.add_column(
        "scanner_events",
        sa.Column("signal_quality_score", sa.Float(), nullable=True),
    )
    # 2. Add descending index, NULLs last
    op.execute(
        "CREATE INDEX idx_scanner_events_score "
        "ON scanner_events (signal_quality_score DESC NULLS LAST)"
    )
    # 3. Seed SystemConfig rows — ON CONFLICT DO NOTHING so existing values survive
    #    Use sa.text() with bound params to avoid f-string interpolation in SQL.
    import json as _json
    default_weights = _json.dumps({
        "volume_spike_ratio": 0.35,
        "gap_pct": 0.25,
        "relative_volume": 0.20,
        "volume_anomaly_score": 0.15,
        "float_rotation_pct": 0.05,
    })
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "INSERT INTO system_config (key, value) VALUES "
            "(:k1, :v1), (:k2, :v2), (:k3, :v3) "
            "ON CONFLICT (key) DO NOTHING"
        ),
        {
            "k1": "signal_ranker_enabled",  "v1": "true",
            "k2": "signal_ranker_weights",  "v2": default_weights,
            "k3": "signal_ranker_version",  "v3": "0.1.0-baseline",
        },
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_scanner_events_score")
    op.drop_column("scanner_events", "signal_quality_score")
    op.execute(
        "DELETE FROM system_config WHERE key IN "
        "('signal_ranker_enabled','signal_ranker_weights','signal_ranker_version')"
    )
```

### Step 2.4 — Apply migration

```bash
cd backend && python -m alembic upgrade head
# Expected: Running upgrade ... -> <rev>, add_signal_quality_score_to_scanner_events
```

Verify:
```bash
docker-compose exec db psql -U postgres markethawk -c "\d scanner_events" | grep signal_quality
# Expected: signal_quality_score | double precision |
docker-compose exec db psql -U postgres markethawk -c "\di idx_scanner_events_score"
# Expected: idx_scanner_events_score | scanner_events | btree | signal_quality_score
docker-compose exec db psql -U postgres markethawk -c "SELECT key,value FROM system_config WHERE key LIKE 'signal_ranker%';"
# Expected: 3 rows
```

### Step 2.5 — Commit

```bash
git add backend/app/models/scanner_event.py backend/app/alembic/versions/
git commit -m "feat(ranker): add signal_quality_score column, index, and seed SystemConfig defaults"
```

---

## Task 3 — Integrate scorer into batch scanner

**Files**: `backend/app/services/scanner.py`

### Step 3.1 — Write failing test

Add to `backend/tests/api/test_scanner.py` (these are integration tests that use the real `db` fixture; do NOT add them to `test_scanner_refactor.py`, which is a unit-test file using mocks with no `db` fixture):

```python
def test_save_event_sets_signal_quality_score(db: Session):
    """_save_event populates signal_quality_score when weights are provided."""
    from app.services.scanner import ScannerService
    from app.utils.session import get_market_today

    today = get_market_today()
    indicators = {"volume_spike_ratio": 10.0, "gap_pct": 5.0}
    weights = {"volume_spike_ratio": 0.35, "gap_pct": 0.25}

    ScannerService._save_event(
        db=db,
        ticker="TST",
        event_date=today,
        scanner_type="pre_market_volume_spike",
        indicators=indicators,
        criteria_met={"v": True},
        enrichment={},
        ranker_enabled=True,
        ranker_weights=weights,
    )
    # _save_event calls db.flush() internally — no need to flush again

    from app.models.scanner_event import ScannerEvent
    event = db.query(ScannerEvent).filter(
        ScannerEvent.ticker == "TST",
        ScannerEvent.event_date == today,
    ).first()
    assert event.signal_quality_score is not None
    assert 0.0 <= event.signal_quality_score <= 1.0


def test_save_event_skips_score_when_disabled(db: Session):
    from app.services.scanner import ScannerService
    from app.utils.session import get_market_today

    today = get_market_today()
    ScannerService._save_event(
        db=db,
        ticker="TST2",
        event_date=today,
        scanner_type="pre_market_volume_spike",
        indicators={"volume_spike_ratio": 10.0},
        criteria_met={},
        enrichment={},
        ranker_enabled=False,
        ranker_weights={},
    )

    from app.models.scanner_event import ScannerEvent
    event = db.query(ScannerEvent).filter(ScannerEvent.ticker == "TST2").first()
    assert event.signal_quality_score is None
```

Run (expect failures):
```bash
cd backend && python -m pytest tests/api/test_scanner.py::test_save_event_sets_signal_quality_score -v
# Expected: FAILED — TypeError (unexpected kwargs) or AttributeError
```

### Step 3.2 — Update `scanner.py`

**Import**: Add at top of `scanner.py`:

```python
from app.services.signal_ranker import compute_signal_quality_score, load_ranker_config
```

**Update typing import** — `Optional` is not currently in `scanner.py`'s typing import. Update the existing line:
```python
# Before:
from typing import Dict, Any, List
# After:
from typing import Dict, Any, List, Optional
```

**Update `_save_event` signature** — add two new keyword params at the end:

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
    ranker_enabled: bool = True,
    ranker_weights: Optional[Dict[str, float]] = None,
) -> Dict[str, Any]:
```

**Score computation** — add after `severity = compute_event_severity(scanner_type, indicators)`:

```python
    score = None
    if ranker_enabled and ranker_weights:
        score = compute_signal_quality_score(indicators, ranker_weights)
```

**Set score on new event** — add ONE line (`model_data["signal_quality_score"] = score`) inside the existing new-event block. Do NOT remove any surrounding lines. The full replacement for the new-event branch (all other lines are already in the codebase — only the `signal_quality_score` line is new):

```python
    model_data = event_dict.copy()
    model_data["metadata_"] = model_data.pop("metadata")
    model_data["signal_quality_score"] = score      # ← this line is new; all others are existing
    new_event = ScannerEvent(**model_data)
    db.add(new_event)
    db.flush()                                      # ← existing line, keep it
    event_dict["id"] = new_event.id                 # ← existing line, keep it
    # keep any other existing lines here (e.g. evaluate_scanner_alerts.delay if present)
```

**Set score on existing event** — add `existing.signal_quality_score = score` *before* the existing `db.flush()` call. The full replacement block including the context lines that must be preserved (do NOT remove `event_dict["id"] = existing.id`):

```python
    for key, value in event_dict.items():
        if key == "metadata":
            setattr(existing, "metadata_", value)
        else:
            setattr(existing, key, value)
    existing.signal_quality_score = score   # ← add before db.flush()
    db.flush()
    event_dict["id"] = existing.id          # ← keep this line unchanged
```

**Load ranker config in `run_pre_market_scan`** — use `load_ranker_config(db)` (already imported), replacing any need for raw query blocks. Add immediately after the TimesFM `_cfg` dict is built (after `_cfg = {r.key: r.value for r in _cfg_rows}`):

```python
    # Load signal ranker config once per scan — reuses the same pattern as TimesFM config
    ranker_enabled, ranker_weights, _ = load_ranker_config(db)
```

**Two call sites** — there are exactly 2 calls to `_save_event` in `scanner.py`: one in `run_pre_market_scan` (line ~368) and one in `run_oversold_bounce_scan` (line ~493). Update both.

**Call site 1 — `run_pre_market_scan`** (ranker config loaded above):

```python
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
                        ranker_enabled=ranker_enabled,
                        ranker_weights=ranker_weights,
                    )
```

**Call site 2 — `run_oversold_bounce_scan`** — `run_oversold_bounce_scan` has no TimesFM block. Add `load_ranker_config(db)` immediately after the `enrichment_batch = await asyncio.to_thread(...)` call at the top of the method, before the ticker loop:

```python
    enrichment_batch = await asyncio.to_thread(
        ScannerService._get_batch_enrichment_data, tickers, event_date, db
    )
    ranker_enabled, ranker_weights, _ = load_ranker_config(db)   # ← add this line

    for ticker in tickers:
        # ... existing ticker loop
```

Then update the call site:

```python
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
                        ranker_enabled=ranker_enabled,
                        ranker_weights=ranker_weights,
                    )
```

**Also update `liquidity_hunt.py` call sites** — `backend/app/services/liquidity_hunt.py` has two additional `_save_event` calls (for `liquidity_hunt_pre` and `liquidity_hunt_post`). Without updating these, liquidity hunt events will always have `signal_quality_score = NULL`. Add `load_ranker_config(db)` at the start of `LiquidityHuntScanner.run()` (the method that calls `_save_event` twice), then pass the ranker kwargs to both call sites:

```python
# At the start of LiquidityHuntScanner.run() (after db is available):
ranker_enabled, ranker_weights, _ = load_ranker_config(db)

# At both _save_event call sites (liquidity_hunt_pre and liquidity_hunt_post):
event_dict = ScannerService._save_event(
    db=db,
    ticker=ticker,
    event_date=event_date,
    scanner_type="liquidity_hunt_pre",  # or "liquidity_hunt_post"
    indicators=indicators,
    criteria_met=criteria_met,
    enrichment=enrichment,
    previous_close=...,
    opening_price=...,
    closing_price=...,
    ranker_enabled=ranker_enabled,
    ranker_weights=ranker_weights,
)
```

Add the import at the top of `liquidity_hunt.py`:
```python
from app.services.signal_ranker import load_ranker_config
```

### Step 3.3 — Verify tests pass

```bash
cd backend && python -m pytest tests/api/test_scanner.py -v
# Expected: all pass (including the two new scorer tests)
```

### Step 3.4 — Commit

```bash
git add backend/app/services/scanner.py backend/app/services/liquidity_hunt.py
git commit -m "feat(ranker): integrate signal quality scorer into batch scanner"
```

---

## Task 4 — Integrate scorer into live scanner

**Files**: `backend/live_scanner/publisher.py`

> **Note — spec vs. codebase divergence**: The spec's File Changes table lists `backend/live_scanner/conditions.py` as the target. However, `conditions.py` only builds `ConditionResult` dataclasses and has no DB session access. All DB writes happen in `publisher.py: _write_scanner_event()`. The plan correctly targets `publisher.py` — the spec's file list was inaccurate. The autonomous implementor should NOT touch `conditions.py`.

### Step 4.1 — Update `_write_scanner_event`

**Import** at top of `publisher.py`:

```python
from app.services.signal_ranker import compute_signal_quality_score, load_ranker_config
```

**Compute and set score** — replace the existing `with Session(self._engine) as session:` block inside `_write_scanner_event`. The full updated block:

```python
        today = bar.minute_ts.astimezone(ET).date()

        with Session(self._engine) as session:
            try:
                # Load ranker config each event — live scanner is long-running; config may change
                ranker_enabled, ranker_weights, _ = load_ranker_config(session)
                score = (
                    compute_signal_quality_score(condition.indicators, ranker_weights)
                    if ranker_enabled
                    else None
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

### Step 4.2 — Verify (manual)

The live scanner requires IBKR connection for integration tests. Verify statically:

```bash
cd backend && python -c "from live_scanner.publisher import LivePublisher; print('import ok')"
# Expected: import ok
```

### Step 4.3 — Commit

```bash
git add backend/live_scanner/publisher.py
git commit -m "feat(ranker): integrate signal quality scorer into live scanner"
```

---

## Task 5 — API layer: schema, sort, and distribution endpoint

**Files**: `backend/app/schemas/event.py`, `backend/app/routers/scanner.py`, `backend/tests/api/test_scanner.py`

### Step 5.1 — Write failing tests

Add to `backend/tests/api/test_scanner.py`:

```python
def test_results_include_signal_quality_score_field(db: Session):
    """signal_quality_score field appears (nullable) in results response."""
    seed_scanner_events(db)
    app.dependency_overrides[get_db] = lambda: db
    response = client.get("/api/scanner/results")
    app.dependency_overrides.clear()
    assert response.status_code == 200
    data = response.json()
    assert len(data) > 0
    assert "signal_quality_score" in data[0]


def test_results_sort_by_signal_quality_score(db: Session):
    """sort_by=signal_quality_score returns 200."""
    seed_scanner_events(db)
    app.dependency_overrides[get_db] = lambda: db
    response = client.get("/api/scanner/results?sort_by=signal_quality_score&sort_order=desc")
    app.dependency_overrides.clear()
    assert response.status_code == 200


def test_signal_quality_distribution_empty(db: Session):
    """Distribution endpoint returns 200 with empty deciles when no data."""
    app.dependency_overrides[get_db] = lambda: db
    response = client.get("/api/scanner/signal-quality-distribution")
    app.dependency_overrides.clear()
    assert response.status_code == 200
    data = response.json()
    assert "deciles" in data
    assert isinstance(data["deciles"], list)
```

Run (expect failures):
```bash
cd backend && python -m pytest tests/api/test_scanner.py::test_results_include_signal_quality_score_field tests/api/test_scanner.py::test_signal_quality_distribution_empty -v
# Expected: FAILED
```

### Step 5.2 — Update `ScannerEventResponse` schema

Edit `backend/app/schemas/event.py`:

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

    indicators: Dict[str, Any] = Field(default_factory=dict)
    criteria_met: Dict[str, Any] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict, alias="metadata_")

    signal_quality_score: Optional[float] = None

    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)
```

### Step 5.3 — Update `/results` sort logic and default

In `backend/app/routers/scanner.py`, update the `get_scanner_results` signature to change defaults:

```python
@router.get("/results", response_model=List[ScannerEventResponse])
def get_scanner_results(
    ticker: Optional[str] = None,
    scanner_type: Optional[str] = None,
    event_type: Optional[str] = None,
    universe_id: Optional[int] = None,
    sort_by: Optional[str] = "signal_quality_score",
    sort_order: Optional[str] = "desc",
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db),
):
```

**Replace the entire existing sort block** with the following (`.nulls_last()` is SQLAlchemy 2.0 chained method; the new unified block handles all columns including `signal_quality_score`):

```python
    # Sorting — REPLACE the entire try/except block that currently exists here
    try:
        if sort_by:
            sort_col = getattr(ScannerEvent, sort_by, ScannerEvent.created_at)
            if sort_order and sort_order.lower() == "desc":
                order_expr = sort_col.desc().nulls_last()
            else:
                order_expr = sort_col.asc().nulls_last()
            query = query.order_by(order_expr)
        else:
            query = query.order_by(ScannerEvent.created_at.desc())
    except Exception:
        query = query.order_by(ScannerEvent.created_at.desc())
```

### Step 5.4 — Add distribution endpoint

First, add the following to the module-level imports at the top of `backend/app/routers/scanner.py`:

```python
# Add ScannerOutcomeSummary to the existing from app.models import line:
from app.models import ScannerEvent, ScannerRun, ..., ScannerOutcomeSummary

# Add load_ranker_config alongside other service imports (or at the end of the imports block):
from app.services.signal_ranker import load_ranker_config
```

Do NOT use local imports inside the function body for either of these.

Then add the endpoint after the `get_edge_distribution` endpoint:

```python
@router.get("/signal-quality-distribution")
def get_signal_quality_distribution(
    scanner_type: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """
    Groups completed scanner events by signal_quality_score decile.
    Returns avg eod_pct_change and follow_through rate per decile.
    Only events with completed ScannerOutcomeSummary rows are included.
    """

    query = (
        db.query(
            ScannerEvent.signal_quality_score,
            ScannerOutcomeSummary.eod_pct_change,
            ScannerOutcomeSummary.follow_through,
        )
        .join(
            ScannerOutcomeSummary,
            ScannerOutcomeSummary.scanner_event_id == ScannerEvent.id,
        )
        .filter(
            ScannerOutcomeSummary.is_complete.is_(True),
            ScannerEvent.signal_quality_score.isnot(None),
        )
    )

    if scanner_type:
        query = query.filter(ScannerEvent.scanner_type == scanner_type)
    if start_date:
        query = query.filter(ScannerEvent.event_date >= start_date)
    if end_date:
        query = query.filter(ScannerEvent.event_date <= end_date)

    rows = query.all()

    if not rows:
        return {"deciles": []}

    # Bucket into deciles [0.0–0.1), [0.1–0.2), ..., [0.9–1.0]
    buckets: dict[str, dict] = {}
    for i in range(10):
        label = f"{i/10:.1f}–{(i+1)/10:.1f}"
        buckets[label] = {"count": 0, "eod_sum": 0.0, "follow_count": 0}

    for score, eod_pct, follow_through in rows:
        bucket_idx = min(int(float(score) * 10), 9)
        label = f"{bucket_idx/10:.1f}–{(bucket_idx+1)/10:.1f}"
        b = buckets[label]
        b["count"] += 1
        if eod_pct is not None:
            b["eod_sum"] += float(eod_pct)
        if follow_through:
            b["follow_count"] += 1

    deciles = []
    for label, b in buckets.items():
        count = b["count"]
        deciles.append({
            "decile": label,
            "count": count,
            "avg_eod_pct": round(b["eod_sum"] / count, 3) if count > 0 else None,
            "follow_through_rate": round(b["follow_count"] / count, 3) if count > 0 else None,
        })

    # Embed signal_ranker_version so frontend doesn't need a separate API call
    # (load_ranker_config is imported at the module level — see Step 5.4 import instruction above)
    _, _, ranker_version = load_ranker_config(db)

    return {"deciles": deciles, "ranker_version": ranker_version}
```

### Step 5.5 — Verify tests pass

```bash
cd backend && python -m pytest tests/api/test_scanner.py -v
# Expected: all pass
```

Curl validate:
```bash
curl -s http://localhost:8000/api/scanner/results?limit=2 | python -m json.tool | grep signal_quality_score
# Expected: "signal_quality_score": null (or float)
curl -s "http://localhost:8000/api/scanner/signal-quality-distribution" | python -m json.tool
# Expected: {"deciles": [...]}
```

### Step 5.6 — Commit

```bash
git add backend/app/schemas/event.py backend/app/routers/scanner.py backend/tests/api/test_scanner.py
git commit -m "feat(ranker): add signal_quality_score to API schema, update sort defaults, add distribution endpoint"
```

---

## Task 6 — Frontend API layer

**Files**: `frontend/src/api/scanner.ts`

### Step 6.1 — Add `signal_quality_score` to `ScannerEvent` interface

In `frontend/src/api/scanner.ts`, update the `ScannerEvent` interface:

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

  indicators: Record<string, any>;
  criteria_met: Record<string, any>;
  metadata: Record<string, any>;

  signal_quality_score?: number | null;

  created_at: string;
  updated_at: string;
}
```

### Step 6.2 — Add distribution types and API function

Append to `frontend/src/api/scanner.ts`:

```typescript
// ---- Signal Quality Distribution ----------------------------------------- //

export interface SignalQualityDecile {
  decile: string;
  count: number;
  avg_eod_pct: number | null;
  follow_through_rate: number | null;
}

export interface SignalQualityDistribution {
  deciles: SignalQualityDecile[];
  ranker_version?: string;
}

export const fetchSignalQualityDistribution = async (params?: {
  scanner_type?: string;
  start_date?: string;
  end_date?: string;
}): Promise<SignalQualityDistribution> => {
  const response = await apiClient.get('/scanner/signal-quality-distribution', { params });
  return response.data;
};
```

### Step 6.3 — TypeScript check

```bash
cd frontend && npx tsc --noEmit
# Expected: no errors
```

### Step 6.4 — Commit

```bash
git add frontend/src/api/scanner.ts
git commit -m "feat(ranker): add signal_quality_score type and distribution API function"
```

---

## Task 7 — ScannerResults score badge and sort

**Files**: `frontend/src/components/ScannerResults.tsx`, `frontend/src/pages/Scanner.tsx`

### Step 7.1 — Add score badge helper and update Score column

In `frontend/src/components/ScannerResults.tsx`:

**Add** `getScoreBadgeStyle` helper after `getSeverityStyle`:

```typescript
const getScoreBadgeStyle = (score: number | null | undefined): string => {
  if (score == null) return 'bg-gray-700/40 text-gray-500 border-gray-600/30';
  if (score >= 0.7) return 'bg-green-500/20 text-green-400 border-green-500/30';
  if (score >= 0.4) return 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30';
  return 'bg-gray-500/20 text-gray-400 border-gray-500/30';
};
```

**Replace** the static `<th className="py-3 px-4">Score</th>` header with a sortable header:

```tsx
<SortableHeader
  label="Score"
  sortKey="signal_quality_score"
  currentSort={sortBy}
  currentOrder={sortOrder}
  onSort={onSort}
/>
```

**Replace** the Score `<td>` content — the existing column has a `<div className="flex items-center space-x-2">` wrapper inside the `<td>`. Replace the entire `<td>` including that wrapper:

```tsx
<td className="py-4 px-4 bg-gray-800 rounded-r-xl">
  {(() => {
    const score = event.signal_quality_score;
    const criteriaStr = `${Object.values(event.criteria_met || {}).filter(Boolean).length}/${Object.values(event.criteria_met || {}).length} criteria met`;
    return (
      <span
        className={`inline-flex items-center px-2 py-1 rounded text-xs font-black border shadow-sm ${getScoreBadgeStyle(score)}`}
        title={criteriaStr}
      >
        {score != null ? score.toFixed(3) : '—'}
      </span>
    );
  })()}
</td>
```

### Step 7.2 — Update Scanner page default sort

In `frontend/src/pages/Scanner.tsx`, change:

```typescript
const [sortBy, setSortBy] = useState<string>('created_at');
```

to:

```typescript
const [sortBy, setSortBy] = useState<string>('signal_quality_score');
```

Also verify `sortOrder` default is `'desc'` (check the existing `useState` for `sortOrder`). If not already set, add:

```typescript
const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('desc');
```

**Pre-existing bug to fix in `onSort`**: The existing `onSort` callback in `Scanner.tsx` only toggles `sortOrder` when the same column is clicked — it does not update `sortBy` when a *different* column is selected. Since Score is now the default, clicking e.g. "Date" column header will toggle the sort order without actually switching to date sort. Fix the `onSort` handler to also set `sortBy`:

```typescript
const onSort = (column: string) => {
  if (column === sortBy) {
    setSortOrder(sortOrder === 'asc' ? 'desc' : 'asc');
  } else {
    setSortBy(column);
    setSortOrder('desc');
  }
};
```

### Step 7.3 — TypeScript check

```bash
cd frontend && npx tsc --noEmit
# Expected: no errors
```

### Step 7.4 — Commit

```bash
git add frontend/src/components/ScannerResults.tsx frontend/src/pages/Scanner.tsx
git commit -m "feat(ranker): replace criteria_met badge with score badge; default sort by signal_quality_score"
```

---

## Task 8 — EdgeExplorer Signal Quality Validation chart

**Files**: `frontend/src/pages/EdgeExplorer.tsx`

### Step 8.1 — Add distribution query and chart

**Update the existing `../api/scanner` import** — `EdgeExplorer.tsx` already imports `fetchScannerConfigs` from `'../api/scanner'`. Do NOT add a second import line. Update the existing one to add `fetchSignalQualityDistribution`:

```typescript
// Before (example — find the actual line and add fetchSignalQualityDistribution):
import { fetchScannerConfigs } from '../api/scanner';
// After:
import { fetchScannerConfigs, fetchSignalQualityDistribution } from '../api/scanner';
```

**Update the existing Recharts import** — `EdgeExplorer.tsx` already imports `XAxis`, `YAxis`, `CartesianGrid`, `Tooltip`, `ResponsiveContainer`, `ScatterChart`, `Scatter`, `ZAxis`, `Cell`, `Legend`, `AreaChart`, `Area` from recharts. Do NOT add a second import statement. Merge `ComposedChart`, `Bar`, `Line` into the existing import:

```typescript
// Before (existing — add ComposedChart, Bar, Line at end):
import {
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  ScatterChart, Scatter, ZAxis, Cell, Legend, AreaChart, Area,
} from 'recharts';
// After:
import {
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  ScatterChart, Scatter, ZAxis, Cell, Legend, AreaChart, Area,
  ComposedChart, Bar, Line,
} from 'recharts';
```

**Add query** for distribution data after the `distribution` query:

```typescript
  const { data: qualityDist } = useQuery({
    queryKey: ['signalQualityDistribution', ticker, scannerType],
    queryFn: () => fetchSignalQualityDistribution({
      scanner_type: scannerType || undefined,
      start_date: undefined,
      end_date: undefined,
    }),
  });

  const qualityDeciles = qualityDist?.deciles ?? [];
  const hasQualityData = qualityDeciles.some(d => d.count > 0);
```

**Add chart section** inside the `<>` fragment, after the "Gapper Retention Correlation" / existing charts section:

```tsx
{/* Signal Quality Validation */}
<Card title="Signal Quality Validation" icon={TrendingUp as any}>
  {!hasQualityData ? (
    <div className="flex flex-col items-center justify-center h-[400px] text-center">
      <BarChart2 className="h-12 w-12 text-gray-700 mb-3" />
      <p className="text-gray-500 font-medium text-sm">No outcome data yet</p>
      <p className="text-gray-600 text-xs mt-1">
        Scores will appear once ScannerOutcomeSummary rows are completed by the scorecard pipeline.
      </p>
    </div>
  ) : (
    <div className="h-[400px]">
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart
          data={qualityDeciles}
          margin={{ top: 20, right: 40, bottom: 20, left: 20 }}
        >
          <CartesianGrid strokeDasharray="3 3" stroke="#374151" vertical={false} />
          <XAxis
            dataKey="decile"
            tick={{ fontSize: 10, fill: '#6b7280' }}
            label={{ value: 'Score Decile', position: 'insideBottom', offset: -10, fill: '#6b7280', fontSize: 11 }}
          />
          <YAxis
            yAxisId="left"
            tick={{ fontSize: 10, fill: '#6b7280' }}
            label={{ value: 'Avg EOD %', angle: -90, position: 'insideLeft', fill: '#6b7280', fontSize: 11 }}
          />
          <YAxis
            yAxisId="right"
            orientation="right"
            domain={[0, 1]}
            tickFormatter={(v: number) => `${(v * 100).toFixed(0)}%`}
            tick={{ fontSize: 10, fill: '#6b7280' }}
            label={{ value: 'Follow-Through %', angle: 90, position: 'insideRight', fill: '#6b7280', fontSize: 11 }}
          />
          <Tooltip
            contentStyle={{ backgroundColor: '#111827', border: '1px solid #374151', borderRadius: 8 }}
            labelStyle={{ color: '#e5e7eb', fontWeight: 'bold' }}
            formatter={(value: any, name: string) => {
              if (name === 'avg_eod_pct') return [`${Number(value).toFixed(2)}%`, 'Avg EOD Return'];
              if (name === 'follow_through_rate') return [`${(Number(value) * 100).toFixed(1)}%`, 'Follow-Through Rate'];
              return [value, name];
            }}
          />
          <Legend wrapperStyle={{ fontSize: 11, color: '#6b7280' }} />
          <Bar
            yAxisId="left"
            dataKey="avg_eod_pct"
            name="avg_eod_pct"
            fill="#3b82f6"
            opacity={0.8}
            radius={[3, 3, 0, 0]}
          />
          <Line
            yAxisId="right"
            type="monotone"
            dataKey="follow_through_rate"
            name="follow_through_rate"
            stroke="#10b981"
            strokeWidth={2}
            dot={{ fill: '#10b981', r: 4 }}
          />
        </ComposedChart>
      </ResponsiveContainer>
      <p className="text-[10px] text-gray-600 text-center mt-1">
        Weight set: {qualityDist?.ranker_version ?? '—'}
      </p>
    </div>
  )}
</Card>
```

### Step 8.2 — TypeScript check

```bash
cd frontend && npx tsc --noEmit
# Expected: no errors
```

### Step 8.3 — Commit

```bash
git add frontend/src/pages/EdgeExplorer.tsx
git commit -m "feat(ranker): add Signal Quality Validation chart to EdgeExplorer"
```

---

## Acceptance Criteria Checklist

- [ ] `signal_quality_score` populated on new batch scanner events
- [ ] `signal_quality_score` populated on new live scanner events
- [ ] When `signal_ranker_enabled = 'false'`, score is `NULL` on new events
- [ ] `GET /api/scanner/results` includes `signal_quality_score` field
- [ ] `GET /api/scanner/results` sorts by `signal_quality_score DESC NULLS LAST` by default
- [ ] `GET /api/scanner/signal-quality-distribution` returns decile data
- [ ] Score badge on scanner results: green ≥ 0.7, yellow 0.4–0.7, grey < 0.4, `—` for null
- [ ] Criteria met ratio demoted to `title` tooltip on badge
- [ ] "Score" column header is sortable
- [ ] Default sort in Scanner page is `signal_quality_score` desc
- [ ] EdgeExplorer shows Signal Quality Validation chart (or empty state)
- [ ] `npx tsc --noEmit` passes
- [ ] All backend tests pass
