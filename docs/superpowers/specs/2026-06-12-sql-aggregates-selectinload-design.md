# SQL Aggregates + selectinload Pagination Fix — Design (issue #291)

**Date**: 2026-06-12
**Issue**: [#291](https://github.com/omniscient/markethawk/issues/291) — [arch-v3][LOW] SQL aggregates in get_trade_stats + selectinload pagination fix

## Problem

Three related ORM inefficiencies flagged by the v3 architecture review (R06):

1. **`get_trade_stats` full-table scan** — `journal_service.get_trade_stats()` (`backend/app/services/journal_service.py:64`) loads every `Trade` row into Python then counts/sums in list comprehensions. This is O(n) for four aggregate numbers that PostgreSQL can compute in one pass.

2. **Pagination hazard in scanner results** — `routers/scanner.py:377` uses `joinedload(ScannerEvent.reviews)` combined with SQL `LIMIT/OFFSET`. SQLAlchemy's `joinedload` produces a JOIN that row-multiplies one-to-many results before the LIMIT is applied, so paginated pages return fewer events than `limit` when any event has multiple reviews. `selectinload` fixes this by issuing a second targeted SELECT, keeping the parent row count exact.

3. **Alerts/auto-trading list endpoints** — the issue notes these endpoints "load + transform in memory" and asks to spot-add `selectinload` if relationships are traversed.

## Requirements

1. `get_trade_stats` must issue no full-table row fetch. All seven `TradeStats` fields are computed via SQL aggregates plus Python arithmetic.
2. Scanner results `GET /api/v1/scanner/results` must return exactly `limit` events even when events have multiple reviews attached.
3. Alerts and auto-trading list endpoints must be audited for relationship traversal; `selectinload` added only where needed.

## Approach

### 1. Rewrite `get_trade_stats` — single aggregate query

Replace the full-table load with one SQL query using conditional `CASE` expressions:

```python
from sqlalchemy import func, case
from decimal import Decimal

def get_trade_stats(db: Session) -> TradeStats:
    row = db.query(
        func.count().label("total"),
        func.count(case((Trade.net_pnl > 0, 1))).label("winners"),
        func.count(case((Trade.net_pnl < 0, 1))).label("losers"),
        func.coalesce(func.sum(Trade.net_pnl), 0).label("total_pnl"),
        func.coalesce(func.sum(case((Trade.net_pnl > 0, Trade.net_pnl))), 0).label("gross_profit"),
        func.coalesce(func.sum(case((Trade.net_pnl < 0, Trade.net_pnl))), 0).label("gross_loss"),
    ).one()

    total = row.total
    winning_trades = row.winners
    losing_trades = row.losers
    total_pnl = Decimal(str(row.total_pnl))
    gross_profit = Decimal(str(row.gross_profit)) or Decimal("1")
    gross_loss = abs(Decimal(str(row.gross_loss))) or Decimal("1")

    win_rate = (winning_trades / total) if total > 0 else 0
    avg_profit = (total_pnl / total) if total > 0 else Decimal("0")
    profit_factor = float(gross_profit / gross_loss)

    return TradeStats(
        total_trades=total,
        winning_trades=winning_trades,
        losing_trades=losing_trades,
        win_rate=win_rate,
        total_pnl=total_pnl,
        avg_profit=avg_profit,
        profit_factor=profit_factor,
    )
```

Key semantics preserved:
- `COUNT(CASE WHEN net_pnl > 0 THEN 1 END)` counts non-NULL results only — correctly counts winners (same as `if t.net_pnl and t.net_pnl > 0`).
- `gross_loss` from `SUM(CASE WHEN net_pnl < 0 THEN net_pnl END)` is negative; `abs()` applied in Python before `profit_factor` calculation.
- `Decimal("1")` fallback for `gross_profit`/`gross_loss` when zero is preserved to replicate existing `profit_factor` edge-case behavior.

### 2. Swap `joinedload` → `selectinload` in scanner results

In `backend/app/routers/scanner.py:377`:

```python
# Before
query = db.query(ScannerEvent).options(joinedload(ScannerEvent.reviews))

# After
query = db.query(ScannerEvent).options(selectinload(ScannerEvent.reviews))
```

`selectinload` issues a separate `SELECT … WHERE scanner_event_id IN (…)` after the main paginated query, so `LIMIT/OFFSET` operates on the parent table directly without row-multiplication.

Update the import in `routers/scanner.py` to replace `joinedload` with `selectinload` (both from `sqlalchemy.orm`).

### 3. Alerts and auto-trading — audit result: no changes needed

Audit findings:

- **`alerts.py` `list_rules`** — `_rule_to_dict` serializes only scalar columns (`id`, `name`, `is_active`, `scanner_types`, `severity_filter`, `cooldown_minutes`, `channels`, `channel_config`, `auto_trade`, `trading_strategy_id`, `created_at`, `updated_at`). The `trading_strategy` relationship is never accessed. No lazy load triggered.

- **`auto_trading.py` `list_strategies`** — `TradingStrategyResponse.from_orm_dict` accesses only scalar attributes. The `alert_rules` and `auto_trade_orders` relationships are never accessed. No lazy load triggered.

- **`auto_trading.py` list orders** — `AutoTradeOrderResponse.from_orm_dict` similarly reads only scalar columns including the FK `trading_strategy_id` (not the `trading_strategy` relationship). No lazy load triggered.

**Conclusion**: no `selectinload` additions required for these endpoints. Adding them would issue extra SELECTs for relationships nothing reads, making the endpoints measurably slower. Per the issue's explicit "if relationships are traversed" qualifier, this is a negative result and no code change is made.

## Alternatives Considered

**Two queries for `get_trade_stats`** — separate count query and sum query. This would work but doubles the DB round-trips with no benefit. The single query with CASE expressions is standard SQL practice and already aligns with patterns in the scanner aggregate service. Rejected.

**Preemptive `selectinload` on alerts/auto-trading** — add it as defensive coding in case future serializers traverse relationships. Rejected: it adds overhead today to guard against a hypothetical future change. The right time to add eager loading is when a serializer actually traverses the relationship.

## Open Questions

None blocking.

## Assumptions

- `Trade.net_pnl` is a `Numeric`/`Decimal` column — `func.sum()` will return a `Decimal`-compatible value from PostgreSQL; wrapping with `Decimal(str(...))` handles the psycopg2/Numeric bridge safely.
- No migration required — no schema changes.
- The `TradeStats` schema is not changing; output shape is backward-compatible.
- `ScannerEvent.reviews` is a one-to-many relationship (confirmed by the pagination hazard description).
