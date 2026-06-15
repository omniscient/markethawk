# Broker Adapter Extension Point Design

**Date:** 2026-06-15
**Issue:** #443
**Parent epic:** #438 (Formal module extension points for MarketHawk)
**Blocked by:** #439 (Extension loader and shared registry primitives)
**Status:** Draft

## Overview

MarketHawk's automated trading pipeline currently hard-codes `IBKROrderManager` as the only order execution path. Private extensions cannot substitute a different broker without modifying platform source code. This spec introduces a broker adapter extension point: a registered protocol that the auto-trading flow resolves at runtime, with the existing IBKR execution wrapped as the default built-in adapter and zero behavioral change for current deployments.

The scope is the five call sites in `auto_trade_service.py` and `tasks/trading.py` that directly instantiate `IBKROrderManager`:

| Call site | Function | Operation |
|---|---|---|
| `auto_trade_service.py:_submit_to_ibkr()` | bracket order placement | `place_bracket_order` |
| `auto_trade_service.py:_get_account_equity()` (live mode) | account equity fetch | `get_account_summary` |
| `auto_trade_service.py:cancel_order()` | order cancellation | `cancel_bracket` |
| `auto_trade_service.py:get_account()` | account display | `get_account_and_orders` |
| `tasks/trading.py:_poll_live_orders()` | fill status polling | `get_open_orders` / `get_order_status` |

## Requirements

1. **`BaseBrokerAdapter(ABC)`** — async abstract interface in `app/providers/base_broker.py` with five method groups matching the above operations:
   - `async place_bracket_order(...)` → `BracketOrderResult`
   - `async cancel_bracket(parent_order_id, stop_order_id, target_order_id)` → `None`
   - `async get_account_summary()` → `AccountSummary`
   - `async get_account_and_orders()` → `tuple[AccountSummary, list[OpenOrderInfo]]`
   - `async get_open_orders()` → `list[OpenOrderInfo]`
   - `async get_order_status(order_id: int)` → `dict | None`

2. **`BrokerAdapterDescriptor`** — `@dataclass(frozen=True)` with fields `.key: str` and `.adapter: BaseBrokerAdapter`; used as the descriptor type for `ExtensionRegistry[BrokerAdapterDescriptor]` from #439.

3. **`BROKER_REGISTRY`** — module-level `ExtensionRegistry[BrokerAdapterDescriptor]` instance in `app/providers/base_broker.py`. `register_broker_adapter(descriptor, replace=False)` wraps `BROKER_REGISTRY.register(descriptor, replace=replace)`.

4. **`IBKRBrokerAdapter(BaseBrokerAdapter)`** in `app/providers/ibkr_broker.py` — wraps `IBKROrderManager`, self-registers as `"ibkr"` at module import. The `IBKROrderManager` import remains lazy (existing `# pragma: no cover` guard is preserved).

5. **`resolve_broker_adapter(db: Session) -> BaseBrokerAdapter`** — reads `SystemConfig["BROKER_ADAPTER_KEY"]` (default `"ibkr"`), looks up in `BROKER_REGISTRY`, raises `BrokerError(operation="resolve", adapter_key=key)` if key is unknown.

6. **`BrokerError(MarketHawkError)`** in `app/exceptions.py` — fields `adapter_key: str | None`, `operation: str | None`, `order_id: int | None`, `symbol: str | None`, `is_retryable: bool = False`. Follows the constructor-with-context pattern of `ProviderError`.

7. **Five call-site replacements** in `auto_trade_service.py` and `tasks/trading.py` — each `from app.providers.ibkr_orders import IBKROrderManager; manager = IBKROrderManager()` block replaced with `adapter = resolve_broker_adapter(db)`. The enclosing `asyncio.new_event_loop()` pattern is preserved unchanged.

8. **Error wrapping** — each call site's bare `except Exception as exc` block in `_submit_to_ibkr` and `cancel_order` raises `BrokerError` before re-setting `order.status = "error"`. `_poll_live_orders` keeps its existing broad catch (it remains `# pragma: no cover`).

9. **Auto-registration wiring** — `app/providers/__init__.py` imports `app.providers.ibkr_broker` after existing provider imports to trigger the `"ibkr"` self-registration.

10. **Tests** in `backend/tests/services/test_broker_adapter.py`:
    - No SystemConfig key → `resolve_broker_adapter(db)` returns the `IBKRBrokerAdapter` instance
    - SystemConfig key `"custom"` + registered mock adapter → `resolve_broker_adapter(db)` returns mock
    - Unknown key in SystemConfig → `BrokerError` raised
    - `BrokerError` is catchable as `MarketHawkError` (following `test_exceptions.py` pattern)
    - One updated `maybe_execute()` test in `test_auto_trade_service.py` that registers a mock adapter through the registry instead of directly patching `IBKROrderManager`

## Architecture

### New files

```
backend/app/providers/base_broker.py
    BaseBrokerAdapter(ABC)               — async interface
    BrokerAdapterDescriptor              — @dataclass(frozen=True), .key + .adapter
    BROKER_REGISTRY                      — ExtensionRegistry[BrokerAdapterDescriptor]
    register_broker_adapter(d, replace)  — thin wrapper
    resolve_broker_adapter(db)           — SystemConfig lookup + registry dispatch

backend/app/providers/ibkr_broker.py
    IBKRBrokerAdapter(BaseBrokerAdapter) — wraps IBKROrderManager
    # self-registration at module level:
    register_broker_adapter(BrokerAdapterDescriptor(key="ibkr", adapter=IBKRBrokerAdapter()))

backend/tests/services/test_broker_adapter.py
    — unit tests (see req 10)
```

### Modified files

```
backend/app/exceptions.py
    + BrokerError(MarketHawkError)
      Fields: adapter_key, operation, order_id, symbol, is_retryable=False

backend/app/providers/__init__.py
    + import app.providers.ibkr_broker  (triggers "ibkr" registration)

backend/app/services/auto_trade_service.py
    _submit_to_ibkr()      — replace IBKROrderManager with resolve_broker_adapter(db)
    _get_account_equity()  — replace IBKROrderManager with resolve_broker_adapter(db)
    cancel_order()         — replace IBKROrderManager with resolve_broker_adapter(db)
    get_account()          — replace IBKROrderManager with resolve_broker_adapter(db=None? see note)

backend/app/tasks/trading.py
    _poll_live_orders()    — replace IBKROrderManager with resolve_broker_adapter(db)

backend/tests/services/test_auto_trade_service.py
    test_maybe_execute_live_mode_isolates_ibkr — updated to register mock adapter
```

### Data flow for a live bracket order (post-change)

```
AutoTradeExecutor.maybe_execute()
  └─ _submit_to_ibkr(order, calc, db)
        ├─ adapter = resolve_broker_adapter(db)
        │     └─ reads SystemConfig["BROKER_ADAPTER_KEY"] → "ibkr"
        │     └─ BROKER_REGISTRY.get("ibkr") → IBKRBrokerAdapter instance
        ├─ loop = asyncio.new_event_loop()
        └─ result = loop.run_until_complete(
               adapter.place_bracket_order(symbol, side, qty, ...)
           )
```

### `get_account()` call site — db-less resolution

`get_account()` (the account display function called from the router) takes no `db: Session` argument. Resolution options:
- Pass `db=None` to `resolve_broker_adapter` and use a short-lived session internally (analogous to how `_get_account_equity` already creates its own session in paper mode)
- Or: make `resolve_broker_adapter` accept `db: Session | None` — when `None`, use a `SessionLocal()` context internally

**Assumption:** `resolve_broker_adapter` accepts `db: Session | None`. When `None`, opens a `SessionLocal()` session for the SystemConfig read and closes it immediately. This is the minimal change to `get_account()`'s signature.

## Alternatives Considered

### A: Bespoke `BrokerAdapterFactory` (mirror of `DataProviderFactory`)
A class-level `_adapters: dict[str, BaseBrokerAdapter]` with `register()` / `get()` in `app/providers/__init__.py`, without using `ExtensionRegistry[T]` from #439.

**Rejected:** duplicates registry infrastructure that #439 is building specifically to serve this exact use case. The `feature:extensions` epic (#438) requires built-ins and private extensions to share the same registration contract. A bespoke factory creates a third registry pattern alongside `DataProviderFactory` and `ExtensionRegistry`, without the duplicate-key validation or `replace=True` semantics the spec requires.

### C: Inline `_BROKER_REGISTRY: dict` in `auto_trade_service.py`
Minimal surface — no new files, no provider layer.

**Rejected:** breaks the providers/services boundary established throughout the codebase. Providers encapsulate vendor-specific logic; services consume them. An extension module importing `auto_trade_service._BROKER_REGISTRY` to register a private adapter violates this boundary and creates a circular dependency risk.

## Open Questions (Non-Blocking)

- **Per-strategy adapter selection:** If two simultaneously running strategies need different broker accounts (e.g. one paper, one live with a different broker), `SystemConfig["BROKER_ADAPTER_KEY"]` is insufficient. Future work can layer `TradingStrategy.parameters["broker_adapter_key"]` as a per-strategy override with SystemConfig as fallback — no migration required, but outside scope for #443.
- **`BaseBrokerAdapter` method signatures:** The signatures above mirror `IBKROrderManager` methods directly. If future adapters require a different parameter shape (e.g. a futures broker needing exchange), the base signatures may need `**kwargs`. Deferred to #444 review.
- **`_poll_live_orders` adapter resolution:** This function creates multiple `loop.run_until_complete()` calls in a loop. After the refactor it will call `resolve_broker_adapter(db)` once before the loop, sharing the adapter instance. The SystemConfig read is fast (one DB query), but if many orders are pending, this could be optimised later.

## Assumptions

1. Issue #439 lands before this ticket is implemented. `ExtensionRegistry[T]`, `ExtensionDuplicateError`, and `ExtensionDescriptorError` are available in `app/core/extensions.py`.
2. `TradingStrategy.parameters` JSONB is left unchanged — no broker adapter key is read from it in this slice.
3. Paper-mode order execution path (`order.status = "submitted"`, `order.broker_order_id = f"PAPER-{order.id}"`) is untouched — paper mode bypasses the adapter entirely, as it does today.
4. The `# pragma: no cover` annotation on `_poll_live_orders` is preserved. The test suite verifies adapter resolution and registration, not live-IBKR fill polling.
5. `IBKRBrokerAdapter` re-raises IBKR exceptions as `BrokerError(is_retryable=True)` for connection timeouts and `BrokerError(is_retryable=False)` for order rejection, matching the `ProviderError` pattern in `ibkr.py`.
6. The `AccountSummary`, `BracketOrderResult`, and `OpenOrderInfo` dataclasses defined in `ibkr_orders.py` are re-exported from `base_broker.py` (or imported at the call sites) so callers do not need to import from `ibkr_orders` directly.
