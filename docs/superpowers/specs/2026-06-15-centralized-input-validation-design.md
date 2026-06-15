# Centralized Input Validation Hardening — F-INPUT-02

**Date:** 2026-06-15
**Issue:** #380
**Status:** Pending review
**Security finding:** F-INPUT-02 (Defensive Security Review 2026-06-12)

## Problem Statement

Ticker/symbol inputs are validated ad-hoc across multiple files (scattered `.upper()` calls, `min_length=1, max_length=20` in one schema but nothing in others). `Dict[str, Any]` fields accept unbounded JSON payloads. Webhook URL fields accept any scheme (http or https). Date-range parameters have no upper cap. Request models accept unexpected extra fields, enabling mass-assignment attacks. The root cause is decentralization — every schema reinvents its own (weak or missing) validation rules, so coverage is uneven and gaps accumulate silently.

**Standards:** OWASP A03/A04:2021, CWE-20 (improper input validation), CWE-915 (mass assignment).

## Requirements

1. A canonical `Ticker` constrained type (equity) and `FuturesSymbol` constrained type (futures root), both defined in a single `backend/app/schemas/common.py` module and imported everywhere.
2. All `ticker`/`symbol` write fields upgraded to use the appropriate constrained type. Futures-capable mixed-type fields (e.g. `ActiveWatchlistAdd.symbol`) validated via `model_validator` dispatching on `security_type`.
3. Date-range write fields bounded: 366 days for interactive/ad-hoc operations, 1830 days for batch/historical operations. Both enforced as mixin base classes in `common.py`.
4. GET endpoint date-range query params bound via a shared `OutcomeDateRange` Depends class (366-day cap), eliminating repeated per-router inline checks.
5. `model_config = ConfigDict(extra="forbid")` applied to all request/write leaf models (Create, Update, Request suffix). Base classes shared with response models must NOT receive `extra="forbid"` to avoid leaking validation failures onto read paths.
6. `Dict[str, Any]` request fields bounded to 64 KB serialized size and max 50 keys (enforced at validation time via a reusable `@field_validator` in `common.py`). Response dicts are explicitly out of scope.
7. Webhook URL fields upgraded from `HttpUrl` (scheme-agnostic) to `HttpsUrl` (https-only), defined in `common.py`.
8. Missing `max_length` bounds added to free-form string fields in write models, grounded in DB column widths.
9. Invalid inputs return HTTP 422 with an explicit message naming the constraint violated. Silent clamping is not acceptable.
10. No database migration required (no model changes).

## Architecture / Approach

### New module: `backend/app/schemas/common.py`

All shared validation primitives live here. Every other schema imports from this one file.

```python
from typing import Annotated, Optional
from datetime import date
from pydantic import AnyUrl, StringConstraints, field_validator, model_validator

# ── Ticker types ─────────────────────────────────────────────────────────────

# Equity: 1-5 uppercase letters, optional single-letter dotted/hyphenated class suffix
# Covers: AAPL, MSFT, BRK.B, BF.B, BRK-B
Ticker = Annotated[str, StringConstraints(pattern=r"^[A-Z]{1,5}([.\-][A-Z])?$", to_upper=True)]

# Futures root symbol: 1-5 uppercase letters only (no month/year suffix — those are separate fields)
# Covers: ES, NQ, MES, MNQ, GC, ZB, RTY
FuturesSymbol = Annotated[str, StringConstraints(pattern=r"^[A-Z]{1,5}$", to_upper=True)]

# ── URL types ─────────────────────────────────────────────────────────────────

HttpsUrl = Annotated[AnyUrl, ...]  # enforce https-only via field_validator

def validate_https(v: Optional[AnyUrl]) -> Optional[AnyUrl]:
    """Reusable validator — call from @field_validator on any https-required URL field."""
    if v is not None and str(v).scheme != "https":
        raise ValueError("URL must use https scheme")
    return v

# ── Dict bounds ───────────────────────────────────────────────────────────────

_MAX_DICT_BYTES = 64 * 1024   # 64 KB
_MAX_DICT_KEYS  = 50

def validate_bounded_dict(v):
    """Reusable validator for Dict[str, Any] write fields — checks size and key count."""
    if v is None:
        return v
    import json
    serialized = json.dumps(v, default=str)
    if len(serialized.encode()) > _MAX_DICT_BYTES:
        raise ValueError(f"dict payload exceeds maximum size of {_MAX_DICT_BYTES // 1024} KB")
    if len(v) > _MAX_DICT_KEYS:
        raise ValueError(f"dict has {len(v)} keys; maximum is {_MAX_DICT_KEYS}")
    return v

# ── Date range mixins ─────────────────────────────────────────────────────────

_INTERACTIVE_MAX_DAYS = 366   # ad-hoc queries: outcomes, single-ticker scanner range
_BATCH_MAX_DAYS       = 1830  # long-running batch: backtest, backfill

class InteractiveDateRange(BaseModel):
    """Mixin for interactive endpoints — max 366-day range, start ≤ end enforced."""
    start_date: date
    end_date: date

    @model_validator(mode="after")
    def _validate_range(self):
        if self.end_date < self.start_date:
            raise ValueError("end_date must not be before start_date")
        if (self.end_date - self.start_date).days > _INTERACTIVE_MAX_DAYS:
            raise ValueError(
                f"date range exceeds maximum of {_INTERACTIVE_MAX_DAYS} days "
                f"(requested {(self.end_date - self.start_date).days})"
            )
        return self

class BatchDateRange(BaseModel):
    """Mixin for batch/historical endpoints — max 1830-day (5-year) range, start ≤ end enforced."""
    start_date: date
    end_date: date

    @model_validator(mode="after")
    def _validate_range(self):
        if self.end_date < self.start_date:
            raise ValueError("end_date must not be before start_date")
        if (self.end_date - self.start_date).days > _BATCH_MAX_DAYS:
            raise ValueError(
                f"date range exceeds maximum of {_BATCH_MAX_DAYS} days "
                f"(requested {(self.end_date - self.start_date).days})"
            )
        return self
```

### Ticker type application

| Schema / file | Field | Change |
|---|---|---|
| `scanner.py` | `ScannerRangeRequest.ticker` | `str` → `Ticker` |
| `scanner.py` | `ScannerRunRequest.tickers` | `Optional[List[str]]` → `Optional[List[Ticker]]` |
| `news_preference.py` | `NewsPreferenceBase.tracked_tickers` | `List[str]` → `List[Ticker]` |
| `journal.py` | `TradeBase.symbol` | `str` → `Ticker` |
| `active_watchlist.py` | `ActiveWatchlistAdd.symbol` | Keep `str` field; add `model_validator(mode="after")` that applies `Ticker` pattern when `security_type == "STK"` and `FuturesSymbol` pattern when `security_type == "FUT"`. Do not change the field type itself — the field accepts both forms and the validator dispatches. |
| `universe.py` (router inline) | `ExportAggregatesRequest.tickers` | `List[str]` → `List[Ticker]` |
| `universe.py` (router inline) | `DeleteAggregatesRequest.ticker` | `str` → `Ticker` |
| `universe.py` (router inline) | `NormalizeRequest.target_tickers` | `Optional[List[str]]` → `Optional[List[Ticker]]` |

**Not changed** (response models or path params): `ScannerEventResponse.ticker`, `BacktestTradeResponse.ticker`, `PreMarketMover.ticker`, `MonitoredStockResponse.ticker`, and the `/{ticker}` path parameters in routers (these are already uppercased via `.upper()` in the handler body).

### Date range bounds

| Schema | Change |
|---|---|
| `scanner.py:ScannerRangeRequest` | Inherit `InteractiveDateRange` (366-day cap) — remove existing `end_date_not_before_start` validator, it is superseded |
| `backtest.py:BacktestRunRequest` | Inherit `BatchDateRange` (1830-day cap) |
| `outcome.py:BackfillRequest` | Inherit `BatchDateRange` (1830-day cap) |
| `routers/backtest.py:67` | Delete inline `if payload.start_date > payload.end_date:` check — covered by mixin |

**Outcomes GET params** — introduce `OutcomeDateRange` as a `Depends` query-param model in `common.py`:

```python
class OutcomeDateRange(BaseModel):
    start_date: Optional[date] = None
    end_date: Optional[date] = None

    @model_validator(mode="after")
    def _validate(self):
        if self.start_date and self.end_date:
            if self.end_date < self.start_date:
                raise ValueError("end_date must not be before start_date")
            if (self.end_date - self.start_date).days > _INTERACTIVE_MAX_DAYS:
                raise ValueError(
                    f"date range exceeds maximum of {_INTERACTIVE_MAX_DAYS} days "
                    f"(requested {(self.end_date - self.start_date).days})"
                )
        return self
```

Inject via `Depends(OutcomeDateRange)` into the four affected endpoints in `routers/outcomes.py` that currently accept loose `Optional[date]` query params.

### `extra="forbid"` on request models

Apply `model_config = ConfigDict(extra="forbid")` to the following **leaf write models only** (not their `*Base` parents):

- `universe.py`: `StockUniverseCreate`, `StockUniverseUpdate`
- `scanner.py`: `ScannerRunRequest`, `ScannerRangeRequest`
- `backtest.py`: `BacktestRunRequest`
- `outcome.py`: `BackfillRequest`
- `signal_review.py`: `SignalReviewCreate`, `SignalReviewRequest`
- `active_watchlist.py`: `ActiveWatchlistAdd`, `ActiveWatchlistUpdate`
- `journal.py`: `TagCreate`, `ExecutionCreate`, `TradeCreate`, `TradeUpdate` — **not** `TagBase`, `ExecutionBase`, `TradeBase` (shared with response `*Schema` models)
- `news_preference.py`: `NewsPreferenceCreate`, `NewsPreferenceUpdate` — **not** `NewsPreferenceBase`
- `universe.py` (router inline): `ExportAggregatesRequest`, `DeleteAggregatesRequest`, `NormalizeRequest`

**Critical inheritance trap**: `journal.py` and `news_preference.py` share `*Base` classes between write and response models. Setting `extra="forbid"` on a `*Base` would cascade to `TagSchema`, `TradeSchema`, `NewsPreferenceResponse` etc., which use `from_attributes=True` and can carry ORM-derived extra attributes. Apply to the leaf write classes only.

`alerts.py:ChannelConfig` already has `extra: "forbid"` — normalize its dict-style config to `ConfigDict(extra="forbid")` for consistency.

### Dict[str, Any] bounds (request dicts only)

Apply `validate_bounded_dict` from `common.py` as a `@field_validator` to:

- `universe.py:StockUniverseCreate.criteria`
- `universe.py:StockUniverseUpdate.criteria`
- `backtest.py:BacktestRunRequest.scanner_config_params`
- `signal_review.py:SignalReviewCreate.enhance_suggestion`
- `signal_review.py:SignalReviewRequest.enhance_suggestion`

**Response dicts are explicitly out of scope** — `ScannerConfigResponse.parameters/criteria`, `ScannerRunResponse.diagnostics`, `ScannerEventResponse.indicators/criteria_met/metadata_`, `BacktestRunResponse.scanner_config_params/strategy_snapshot` etc. These are serialized from JSONB columns; validating them on reads adds CPU overhead and risks rejecting legitimate historical data.

### URL scheme hardening

Define `HttpsUrl` and `validate_https` in `common.py`. Apply to:

- `alerts.py:ChannelConfig.google_chat_webhook` — change from `Optional[HttpUrl]` to `Optional[HttpsUrl]`
- `alerts.py:ChannelConfig.webhook_url` — change from `Optional[HttpUrl]` to `Optional[HttpsUrl]`

`news_preference.py:NewsArticleResponse.article_url` and `image_url` are response-only fields populated from Polygon API data — do not validate scheme on response models.

### `max_length` on write string fields

Fields in write models currently missing a length bound, with values grounded in the DB column:

| Schema | Field | DB column | `max_length` to add |
|---|---|---|---|
| `journal.py:TagBase.name` | `name: str` | `String(50)` | `50` (safe to put on Base — DB column enforces the same bound) |
| `journal.py:ExecutionBase.external_id` | `external_id: Optional[str]` | `String(100)` | `100` |
| `journal.py:TradeBase.notes` | `notes: Optional[str]` | `Text` | `4096` |
| `universe.py:StockUniverseCreate.description` | `description: Optional[str]` | `Text` | `2048` |
| `universe.py:StockUniverseUpdate.description` | `description: Optional[str]` | `Text` | `2048` |
| `scanner.py:ScannerRunRequest.scanner_type` | `scanner_type: str` | `String` (unbounded) | `50` |

Response-only free-form string fields (`ScannerRunResponse.error_message`, `BacktestRunResponse.error_message`, `ScannerEventResponse.summary`, etc.) are not in scope for length bounds.

## Alternatives Considered

### A: Per-schema inline validators (status quo + patch)

Continue adding ad-hoc validators wherever gaps are found. Rejected because this is the pattern F-INPUT-02 exists to fix — the issue explicitly cites "decentralized" validation as the root cause. Each new schema added in the future would silently lack coverage.

### B: Single validation middleware (request body inspection)

Intercept all request bodies in a FastAPI middleware and reject tickers/oversized dicts before they reach Pydantic. Rejected because: (1) requires parsing the raw JSON before deserialization, duplicating Pydantic's work; (2) validation errors surface as 400 instead of 422 (breaking the existing error contract); (3) can't know which fields are "tickers" without schema metadata.

### C: `common.py` central module (chosen)

Define all primitives once, import everywhere. Chosen because: (1) zero overhead — Pydantic applies them at model parse time; (2) consistent 422 error contract; (3) future schemas automatically benefit by importing from `common.py`; (4) the primitives are self-documenting (the type name `Ticker` conveys the intent).

## Verification

After implementation, confirm:

1. `curl -X POST /api/v1/universe/create -d '{"name":"test","criteria":{"sector":"tech"},"unexpected_key":"evil"}' -H "Content-Type: application/json"` → 422 with `"Extra inputs are not permitted"`
2. `curl -X POST /api/v1/scanner/range -d '{"ticker":"../etc","scanner_types":["pre_market_volume"],"start_date":"2025-01-01","end_date":"2025-06-01"}' -H "Content-Type: application/json"` → 422 with pattern mismatch
3. `curl -X POST /api/v1/scanner/range -d '{"ticker":"AAPL","scanner_types":["pre_market_volume"],"start_date":"2020-01-01","end_date":"2026-01-01"}' -H "Content-Type: application/json"` → 422 with date range exceeded message
4. `curl -X POST /api/v1/universe/create -d '{"name":"test","criteria":{"k":"<50KB string>"}}' -H "Content-Type: application/json"` → 422 with dict size message
5. Normal payloads with valid tickers, bounded date ranges, and no extra keys continue to return 2xx.

```bash
# Confirm backend reloaded before testing
docker-compose logs backend --tail=10
```

## Open Questions

- **`ScannerRunRequest.scanner_type`** accepts free-form scanner type strings. Should a future spec constrain this to an enum of known scanner types? Not blocking — `max_length=50` prevents oversized values for now.
- **`ScannerConfigResponse.criteria`** is a `List[Dict[str, Any]]` that comes from the DB. A follow-on could define per-scanner-type criteria schemas validated at write time (scanner config CRUD). Out of scope for F-INPUT-02.
- **`NormalizeRequest` (universe router)**: if `target_tickers` is left as `Optional[List[Ticker]]` and caller passes `None`, the normalize operation applies to the whole universe — is there a max-tickers-per-call cap needed? Deferred.

## Assumptions

- `Ticker` pattern `^[A-Z]{1,5}([.\-][A-Z])?$` covers all equity symbols in the current universe (confirmed: `String(10)` DB columns hold no digits in the ticker field for stocks). If a new asset class adds numeric ticker components, `common.py` is the single file to update.
- Futures root symbols in this codebase never include month/year suffixes — those are stored in separate `contract_month` `String(8)` columns, confirmed from the models.
- `BacktestRunRequest` date ranges up to 5 years (1830 days) are a legitimate use case for multi-regime historical analysis; 2 years would be too restrictive.
- The `json.dumps(v, default=str)` serialization in `validate_bounded_dict` uses `default=str` to handle non-JSON-native values (datetime, Decimal) without raising — these would normally be caught downstream anyway, but the size check should not itself fail on type-serialization errors.
- No DB migration is needed: all changes are at the Pydantic schema layer only. The underlying `String`/`Text`/`JSONB` columns are unchanged.
