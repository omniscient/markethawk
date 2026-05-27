# Eager Loading — Fix N+1 Query Hotspots

## Overview

The architecture quality audit (issue #100) flagged the Data Access Patterns section as 3/5, citing absent eager loading in router queries. A full code audit of the four listed hotspot endpoints and all service/task files reveals that only one genuine N+1 pattern exists in the current codebase: `GET /api/journal/trades`. Two complementary hardening changes are also warranted: adding `order_by` to the `ScannerEvent.reviews` relationship (making `latest_review` safe to call outside the one joinedloaded query), and enabling SQL echo in the development environment for regression visibility.

## Problem Statement

- `journal_service.get_trades()` issues `db.query(Trade).order_by(...).all()` with no eager loading. `TradeSchema` includes `executions: List[ExecutionSchema]` and `tags: List[TagSchema]`, both of which are lazy-loaded one-by-one during Pydantic serialization — a classic N+1 pattern.
- `ScannerEvent.latest_review` is safe at the `/results` endpoint (reviews are joinedloaded there), but the model property itself has no guard: any future code path that accesses `latest_review` on an un-joinedloaded `ScannerEvent` will silently trigger lazy loads.
- There is no per-request SQL logging in the development environment, so query count regressions are invisible without a profiler.

The four endpoints listed in the issue as "likely hotspots" are **not** actual N+1 problems in the current code:

| Endpoint | Audit finding |
|----------|--------------|
| `GET /api/scanner/results` | Already uses `joinedload(ScannerEvent.reviews)` — clean |
| `GET /api/alerts/rules` | Returns scalar columns only — no relationship traversal |
| `GET /api/scanner/history` | Returns scalar fields from `ScannerRun` — no relationship traversal |
| `GET /api/universe/{id}/stocks` | Returns scalar fields from `MonitoredStock` — no relationship traversal |

## Requirements

1. `GET /api/journal/trades` must not issue per-Trade lazy queries for `executions` or `tags`.
2. `selectinload` must be used (not `joinedload`) because loading two independent collections with `joinedload` produces a Cartesian product (rows × executions × tags).
3. `ScannerEvent.reviews` relationship must have `order_by="SignalReview.reviewed_at.desc()"` so that `latest_review` returns `self.reviews[0] if self.reviews else None` without requiring a particular eager-loading call site.
4. SQL echo must be enabled when `ENVIRONMENT == "development"` in `database.py`.
5. No changes to scanner, alerts, universe, or history endpoints — they are clean.
6. No migration required (relationship-level `order_by` is a Python-only change).

## Architecture / Approach

**Three targeted changes:**

### 1. `backend/app/services/journal_service.py` — add selectinload

```python
from sqlalchemy.orm import selectinload
from app.models.trade import Trade, TradeExecution, Tag

def get_trades(db, ...):
    query = (
        db.query(Trade)
        .options(
            selectinload(Trade.executions),
            selectinload(Trade.tags),
        )
        ...
        .order_by(Trade.open_date.desc())
        .all()
    )
```

`selectinload` issues two separate `IN (...)` follow-up queries — one for executions, one for tags — rather than a JOIN. This is the correct choice when loading two independent collections to avoid the multiplicative row count of `joinedload`.

### 2. `backend/app/models/scanner_event.py` — add order_by to reviews relationship

```python
reviews = relationship(
    "SignalReview",
    back_populates="event",
    cascade="all, delete-orphan",
    order_by="SignalReview.reviewed_at.desc()",
)
```

SQLAlchemy evaluates string `order_by` expressions lazily against the mapper registry — no import of `SignalReview` or `desc` is needed in `scanner_event.py`, avoiding the circular import. After this change, `latest_review` can be simplified:

```python
@property
def latest_review(self):
    return self.reviews[0] if self.reviews else None
```

No migration needed — this is a query construction change only.

### 3. `backend/app/core/database.py` — enable SQL echo in development

```python
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=(settings.ENVIRONMENT == "development"),
    ...
)
```

`config.py` already exposes `ENVIRONMENT` via `Settings`. When set to `"development"`, every SQL statement is logged to stdout, making query count regressions visible during local development.

## Alternatives Considered

### Alt A: Add `lazy="raise"` to all relationships in development

Setting `lazy="raise"` on relationships causes SQLAlchemy to raise `InvalidRequestError` when a lazy load is attempted — forcing all callers to use explicit eager loading. This is a stricter approach and catches regressions at test time. Rejected for this issue because it would require touching every relationship definition and updating all callsites that currently rely on lazy loading intentionally (e.g. single-object lookups). Too broad for a size: M task.

### Alt B: Add a query-count test fixture

A pytest fixture using `sqlalchemy-utils` or a custom event listener can assert that specific endpoints stay under a query budget. This is valuable but is test infrastructure work separate from the fixes themselves. Deferred — could be a follow-on issue.

### Alt C: Fix all four hotspots as originally listed

The original issue listed four endpoints as likely hotspots. Audit shows three of them are not actual N+1 patterns. Fixing them anyway would add dead code (unnecessary `joinedload` calls on queries that don't traverse relationships). Rejected — YAGNI.

## Open Questions

- `tasks/trading.py` `_check_entry_slippage()` accesses `order.trading_strategy` lazily (1+1 pattern, not N+1 — one order at a time). Not fixed here; if the trading execution path becomes high-frequency, a follow-on issue should add `selectinload(AutoTradeOrder.trading_strategy)` there.

## Assumptions

- `settings.ENVIRONMENT` is set to `"development"` in local `.env` files and `"production"` in deployed environments. If not, the SQL echo change is a no-op and harmless.
- The journal endpoint does not have pagination that would change the selectinload vs joinedload tradeoff. Confirmed: `journal_service.get_trades()` returns `.all()` with no `LIMIT`.
- String-form `order_by` in SQLAlchemy relationship definitions resolves correctly at runtime against the mapper registry. This is a standard SQLAlchemy pattern for avoiding circular imports.
