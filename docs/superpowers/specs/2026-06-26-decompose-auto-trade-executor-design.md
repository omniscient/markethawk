# Decompose AutoTradeExecutor.maybe_execute()

**Status:** design
**Date:** 2026-06-26
**Issue:** #630 (architecture-audit-v4 — complexity top-10)
**Size:** S (pure refactor, no schema/API changes)

## Problem

`AutoTradeExecutor.maybe_execute()` (`backend/app/services/auto_trade_service.py:92–381`)
has grown to ~290 lines / 15+ decision branches — the #1 complexity entry in the v4
architecture review. The accumulation of #368 live-trading guards on top of existing
gating, concurrency, session, and sizing logic turned a manageable orchestrator into an
untestable cascade. Individual decision steps can't be unit-tested without exercising
the full pipeline.

## Requirements

1. Extract all sequential decision steps from `maybe_execute` into named private methods.
2. No behavior change — all existing `test_maybe_execute_*` tests must pass unmodified.
3. The Redis distributed lock (`try/finally` releasing the lock) stays owned by `maybe_execute`; extracted methods must not acquire or release it.
4. Pure go/no-go validators return `bool` (True = proceed), consistent with the existing `_gate_passes` helper.
5. Value-producing steps return `Optional[<result>]` (None = skip).
6. Add direct unit tests for the two value-producing extractions (`_validate_basics` and `_size_position`) where they reduce combinatorial test setup; keep all-else tested through the existing public-entry integration tests.

## Architecture / Approach

### Method map

Six private methods extracted, preserving the pre-lock / inside-lock boundary:

```
maybe_execute(rule, event, db) -> Optional[AutoTradeOrder]
│
│  ── pre-lock ──────────────────────────────────────────────
├─ _validate_basics(rule, db) -> Optional[TradingStrategy]
│     Steps 1 + 1b + 1c:
│     • rule.auto_trade + rule.trading_strategy_id check
│     • load TradingStrategy (active only)
│     • kill-switch: AUTO_TRADING_ENABLED SystemConfig (live mode only)
│     • max_position_usd required and > 0 for live strategies
│     Returns the loaded strategy on success, None to skip.
│
├─ _check_idempotency(event, strategy, today, db) -> bool
│     Step 2:
│     • query AutoTradeOrder for symbol/strategy/event_date == today
│     Returns True (no existing order → proceed), False (exists → skip).
│
├─ _validate_quality_gate(event, rule, db) -> bool
│     Step 2.5:
│     • _resolve_universe_id (already extracted)
│     • QualityGateService.assess under strict or off policy
│     • _gate_passes (already extracted)
│     • log bypass_used when verdict == skipped and gate_ok
│     Returns True (gate passes), False (refused).
│
│  ── redis lock acquired ────────────────────────────────────
│  try:
├─ _validate_concurrency(strategy, today, db) -> bool
│     Steps 4 + 5:
│     • daily trade count vs strategy.max_trades_per_day
│     • open position count vs strategy.max_concurrent_positions
│     Returns True (within limits), False (limit reached).
│
├─ _validate_session(event, strategy) -> bool
│     Step 6:
│     • event.metadata_.session vs strategy.allowed_sessions
│     Returns True (session allowed), False (not allowed).
│
├─ _size_position(event, strategy, db) -> Optional[PositionCalc]
│     Steps 7–10:
│     • _extract_trigger_price (already extracted)
│     • _determine_side (already extracted)
│     • _get_account_equity (already extracted)
│     • _calculate_position (already extracted)
│     Returns a populated PositionCalc, or None on any early-exit
│     (bad trigger price, undetermined side, zero equity, quantity == 0).
│  finally:
│     redis_client.delete(lock_key)
│
│  (steps 11–12: order creation + IBKR submission stay inline in maybe_execute)
```

### `maybe_execute` skeleton after refactor

```python
def maybe_execute(self, rule, event, db):
    strategy = self._validate_basics(rule, db)
    if strategy is None:
        return None

    today = datetime.now(timezone.utc).date()
    if not self._check_idempotency(event, strategy, today, db):
        return None

    if not self._validate_quality_gate(event, rule, db):
        return None

    redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True)
    lock_key = f"auto_trade_lock:{event.ticker}:{strategy.id}:{today}"
    acquired = redis_client.set(lock_key, "1", nx=True, ex=30)
    if not acquired:
        return None

    try:
        if not self._validate_concurrency(strategy, today, db):
            return None
        if not self._validate_session(event, strategy):
            return None

        calc = self._size_position(event, strategy, db)
        if calc is None:
            return None

        # Steps 11–12: order creation + submit/park (unchanged inline)
        ...
    except Exception as exc:
        logger.exception(...)
        return None
    finally:
        redis_client.delete(lock_key)
```

### Test additions

Following the existing `_calculate_position` / `_determine_side` precedent:

- **`_validate_basics`**: direct tests for the two `None` branches that are expensive to
  set up through `maybe_execute` — kill-switch blocked (live strategy + `AUTO_TRADING_ENABLED=off`)
  and `max_position_usd` missing/zero on live strategy. "Strategy not found/inactive" is already
  covered by public-path tests and needs no duplication.
- **`_size_position`**: direct tests for edge cases — `None` returned when
  trigger price is missing, side is undetermined, account equity is 0, and calculated
  quantity is 0 — mirroring the existing `test_calculate_position_*` pattern.
- All existing `test_maybe_execute_*`, `test_quality_gate_*`, and `test_determine_side_*`
  tests stay unchanged.

## Alternatives Considered

### A — Raise `_SkipTrade` exception for early exits
Rejected. `maybe_execute` already has a broad `except Exception` catch-all (lines 373–378)
that returns `None` and releases the lock. Introducing a skip exception adds control-flow
complexity on the hot path and risks interacting confusingly with the existing handler.

### B — Group idempotency (step 2) inside `_validate_concurrency`
Rejected. Idempotency (`symbol/strategy/event_date` uniqueness) and concurrency limits
(`max_trades_per_day`, `max_concurrent_positions`) use different filter shapes and answer
different questions. Idempotency also runs **before** the Redis lock; concurrency checks run
**inside** it — conflating them would require moving the idempotency check inside the lock,
which is a behavior change.

### C — Keep exactly 5 methods (fold idempotency into `_validate_basics`)
Acceptable but less clean. `_validate_basics` would then own both "is this strategy
tradeable?" and "have we already traded it today?" — two distinct questions. The `today`
boundary is also shared with steps 4 and 11, so passing it from `_validate_basics` back
to the caller (or computing it twice) adds friction. A dedicated `_check_idempotency` is the
cleaner split at negligible cost.

## Assumptions

- `[ASSUMED]` Steps 11–12 (AutoTradeOrder construction, `db.add`, `db.commit`, paper/IBKR submit) remain inline in `maybe_execute`. They are tightly coupled to the order object's lifecycle and benefit from being visible at the orchestrator level; their complexity is low relative to the decision cascade.
- `[ASSUMED]` No migration, no API change, no model change. This is a service-layer restructuring only.
- `[ASSUMED]` The fakeredis patch in `conftest.py` applies unchanged to the refactored code since `redis.from_url` is still called in `maybe_execute`.

## Open Questions (non-blocking)

- Could `_validate_quality_gate` be further simplified by inlining `_gate_passes` directly? Currently `_gate_passes` lives as a separate helper (lines 635–654). Since it is only called from `maybe_execute`, folding it into `_validate_quality_gate` would remove one indirection — but it is already independently testable as-is and the issue does not require it.

## Validation

- `pytest backend/tests/services/test_auto_trade_service.py` — all existing tests pass.
- `pytest backend/tests/` — no regression in sibling tests.
- New tests: `test__validate_basics_killswitch`, `test__validate_basics_no_max_position_usd`,
  `test__size_position_*` (4 branches). Expected coverage: ≥90% of new code paths.
- `npx tsc --noEmit` (no frontend changes expected; guard anyway).
- Backend reloaded confirmed via `docker-compose logs backend --tail=10` after deploy.
