# Eager Loading — Fix N+1 Query Hotspots

**Issue**: #100  
**Spec**: `Docs/superpowers/specs/2026-05-27-eager-loading-n1-queries-design.md`  
**Branch**: `refine/issue-100-add-eager-loading--joinedload--to-n-1-qu`

## Goal

Fix the one confirmed N+1 pattern (`GET /api/journal/trades`), harden `ScannerEvent.latest_review` so it is safe at any call site, and enable SQL echo in development for query-count regression visibility.

## Architecture

Three targeted, independent changes. No new files (except two test files), no migrations, no schema changes.

## Tech Stack

SQLAlchemy 2.0 (sync ORM, `Session`) · FastAPI · pytest + testcontainers

## File Structure

| File | Change |
|------|--------|
| `backend/app/services/journal_service.py` | Add `selectinload(Trade.executions)` and `selectinload(Trade.tags)` to `get_trades()` |
| `backend/app/models/scanner_event.py` | Add `order_by="SignalReview.reviewed_at.desc()"` to `reviews` relationship; replace `max()` in `latest_review` with `self.reviews[0]` |
| `backend/app/core/database.py` | Add `echo=(settings.ENVIRONMENT == "development")` to `create_engine` |
| `backend/tests/services/test_journal_service.py` | Add eager-load proof test for `get_trades()` |
| `backend/tests/api/test_signal_reviews.py` | Add relationship ordering tests |
| `backend/tests/test_database.py` *(new)* | Add `engine.echo` configuration test |

---

## Task 1: Fix N+1 in `journal_service.get_trades()` via `selectinload`

**Files**: `backend/tests/services/test_journal_service.py`, `backend/app/services/journal_service.py`

### Step 1.1 — Write failing test

Append to `backend/tests/services/test_journal_service.py`:

```python
def test_get_trades_eagerly_loads_executions_and_tags(db: Session):
    """selectinload must populate executions and tags without separate per-trade queries."""
    from datetime import datetime, timezone
    from decimal import Decimal
    from app.models.trade import Trade, TradeExecution, Tag

    tag = Tag(name="eager_test_tag", color="#AABBCC")
    db.add(tag)
    db.flush()

    trade = Trade(
        symbol="EAGERTEST",
        status="open",
        open_date=datetime.now(timezone.utc).replace(tzinfo=None),
    )
    db.add(trade)
    db.flush()

    db.add_all([
        TradeExecution(
            trade_id=trade.id,
            timestamp=datetime.now(timezone.utc).replace(tzinfo=None),
            side="buy",
            price=Decimal("100"),
            quantity=Decimal("10"),
        ),
        TradeExecution(
            trade_id=trade.id,
            timestamp=datetime.now(timezone.utc).replace(tzinfo=None),
            side="sell",
            price=Decimal("105"),
            quantity=Decimal("10"),
        ),
    ])
    db.flush()
    trade.tags = [tag]
    db.flush()

    db.expire_all()  # clear identity map to simulate a fresh read

    trades = get_trades(db, symbol="EAGERTEST")
    assert len(trades) == 1
    result = trades[0]

    # If selectinload ran, both collections are in __dict__ before we access them
    assert "executions" in result.__dict__, "executions were not eagerly loaded"
    assert "tags" in result.__dict__, "tags were not eagerly loaded"
    assert len(result.executions) == 2
    assert len(result.tags) == 1
```

### Step 1.2 — Verify test fails

```bash
docker-compose exec backend python -m pytest \
  backend/tests/services/test_journal_service.py::test_get_trades_eagerly_loads_executions_and_tags -v
```

Expected:
```
FAILED backend/tests/services/test_journal_service.py::test_get_trades_eagerly_loads_executions_and_tags
AssertionError: executions were not eagerly loaded
```

### Step 1.3 — Implement fix

In `backend/app/services/journal_service.py`:

Change line 1 import:
```python
# Before
from sqlalchemy.orm import Session

# After
from sqlalchemy.orm import Session, selectinload
```

Replace the `get_trades` function body:
```python
def get_trades(db: Session, symbol: Optional[str] = None, status: Optional[str] = None):
    query = (
        db.query(Trade)
        .options(
            selectinload(Trade.executions),
            selectinload(Trade.tags),
        )
    )
    if symbol:
        query = query.filter(Trade.symbol == symbol.upper())
    if status:
        query = query.filter(Trade.status == status)
    return query.order_by(Trade.open_date.desc()).all()
```

### Step 1.4 — Verify test passes

```bash
docker-compose exec backend python -m pytest backend/tests/services/test_journal_service.py -v
```

Expected: all tests pass including the new one.

### Step 1.5 — Commit

```bash
git add backend/app/services/journal_service.py \
        backend/tests/services/test_journal_service.py
git commit -m "$(cat <<'EOF'
fix(journal): add selectinload for Trade.executions and Trade.tags in get_trades

With selectinload, SQLAlchemy issues 2 follow-up IN-queries (one per collection)
instead of N per-trade lazy queries during Pydantic serialization. selectinload
chosen over joinedload to avoid the Cartesian product that loading two independent
collections via JOIN produces.

Closes part of #100.
EOF
)"
```

---

## Task 2: Harden `ScannerEvent.reviews` ordering; simplify `latest_review`

**Files**: `backend/tests/api/test_signal_reviews.py`, `backend/app/models/scanner_event.py`

### Step 2.1 — Write failing test

Append to `backend/tests/api/test_signal_reviews.py`:

```python
def test_reviews_relationship_ordered_newest_first(db: Session):
    """ScannerEvent.reviews must be ordered newest-first by the relationship itself."""
    from datetime import datetime, timezone, timedelta, date

    event = ScannerEvent(
        ticker="ORDTEST",
        event_date=date.today(),
        scanner_type="order_check",
        indicators={},
        criteria_met={},
        metadata_={},
    )
    db.add(event)
    db.flush()

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    # Insert older review first (lower PK) so without order_by it loads first
    older = SignalReview(
        scanner_event_id=event.id,
        verdict="rejected",
        reject_reason="noise",
        reviewed_at=now - timedelta(hours=2),
    )
    newer = SignalReview(
        scanner_event_id=event.id,
        verdict="confirmed",
        reviewed_at=now - timedelta(hours=1),
    )
    db.add_all([older, newer])
    db.flush()

    db.expire(event)
    reviews = event.reviews  # trigger relationship load

    assert reviews[0].verdict == "confirmed", "newest review must be first"
    assert reviews[1].verdict == "rejected", "older review must be last"
    assert event.latest_review.verdict == "confirmed"


def test_latest_review_returns_none_for_event_with_no_reviews(db: Session):
    """latest_review must return None when the event has no reviews."""
    from datetime import date

    event = ScannerEvent(
        ticker="NOREV",
        event_date=date.today(),
        scanner_type="norev_type",
        indicators={},
        criteria_met={},
        metadata_={},
    )
    db.add(event)
    db.flush()
    db.expire(event)

    assert event.latest_review is None
```

### Step 2.2 — Verify ordering test fails

```bash
docker-compose exec backend python -m pytest \
  backend/tests/api/test_signal_reviews.py::test_reviews_relationship_ordered_newest_first -v
```

Expected:
```
FAILED backend/tests/api/test_signal_reviews.py::test_reviews_relationship_ordered_newest_first
AssertionError: newest review must be first
```

(Without `order_by`, PostgreSQL returns rows in PK/insertion order: `older` is first.)

### Step 2.3 — Implement fix

In `backend/app/models/scanner_event.py`, replace lines 50–56:

```python
# Before
reviews = relationship("SignalReview", back_populates="event", cascade="all, delete-orphan")

@property
def latest_review(self):
    if not self.reviews:
        return None
    return max(self.reviews, key=lambda r: r.reviewed_at)

# After
reviews = relationship(
    "SignalReview",
    back_populates="event",
    cascade="all, delete-orphan",
    order_by="SignalReview.reviewed_at.desc()",
)

@property
def latest_review(self):
    return self.reviews[0] if self.reviews else None
```

String-form `order_by` avoids a circular import between `scanner_event.py` and `signal_review.py`. SQLAlchemy resolves the string lazily against the mapper registry at query time.

### Step 2.4 — Verify all signal review tests pass

```bash
docker-compose exec backend python -m pytest backend/tests/api/test_signal_reviews.py -v
```

Expected: all tests pass.

### Step 2.5 — Commit

```bash
git add backend/app/models/scanner_event.py \
        backend/tests/api/test_signal_reviews.py
git commit -m "$(cat <<'EOF'
fix(scanner): order ScannerEvent.reviews newest-first; simplify latest_review

Adds order_by="SignalReview.reviewed_at.desc()" to the reviews relationship so
latest_review is safe from any code path, not just the joinedload call site in
/api/scanner/results. String-form order_by avoids a circular import.

latest_review simplified from max() to self.reviews[0] since ordering is now
guaranteed by the relationship definition.

Closes part of #100.
EOF
)"
```

---

## Task 3: Enable SQL echo in development

**Files**: `backend/tests/test_database.py` *(new)*, `backend/app/core/database.py`

### Step 3.1 — Write test

Create `backend/tests/test_database.py`:

```python
"""
Tests for database engine configuration.
"""
from app.core.database import engine
from app.core.config import settings


def test_engine_echo_follows_environment():
    """engine.echo must be True when ENVIRONMENT=development, False otherwise."""
    expected = settings.ENVIRONMENT == "development"
    assert engine.echo == expected, (
        f"engine.echo={engine.echo!r} but ENVIRONMENT={settings.ENVIRONMENT!r}; "
        "database.py must pass echo=(settings.ENVIRONMENT == 'development') to create_engine"
    )
```

### Step 3.2 — Verify test behaviour before fix

```bash
docker-compose exec backend python -m pytest backend/tests/test_database.py -v
```

- **In development** (`ENVIRONMENT=development`): FAILED — `engine.echo is False` but expected `True`.
- **In CI** (`ENVIRONMENT=production`): PASSES — both sides are `False`. The test is a regression guard; it becomes load-bearing when run locally in dev.

### Step 3.3 — Implement fix

In `backend/app/core/database.py`, replace line 13:

```python
# Before
engine = create_engine(settings.DATABASE_URL)

# After
engine = create_engine(
    settings.DATABASE_URL,
    echo=(settings.ENVIRONMENT == "development"),
)
```

### Step 3.4 — Verify test passes

```bash
docker-compose exec backend python -m pytest backend/tests/test_database.py -v
```

Expected: PASSED in all environments.

### Step 3.5 — Full suite smoke check

```bash
docker-compose exec backend python -m pytest -x --tb=short 2>&1 | tail -20
```

Expected: all tests pass.

### Step 3.6 — Commit

```bash
git add backend/app/core/database.py \
        backend/tests/test_database.py
git commit -m "$(cat <<'EOF'
feat(db): enable SQL echo when ENVIRONMENT=development

Adds echo=(settings.ENVIRONMENT == "development") to create_engine so every SQL
statement is printed to stdout during local development. No effect in production
since ENVIRONMENT defaults to "production" when unset.

Closes #100.
EOF
)"
```
