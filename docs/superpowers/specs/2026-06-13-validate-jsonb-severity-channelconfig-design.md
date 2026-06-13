# Validate JSONB Writes, Severity Enum, and ChannelConfig Schema

**Date:** 2026-06-13
**Issue:** #292
**Source:** v3 architecture review R07
**Status:** Spec

---

## Problem

Three validation gaps flagged in the v3 architecture review:

1. **JSONB fields unvalidated at write time** — `ScannerEvent.indicators`, `criteria_met`, and `metadata` are persisted as free-form JSONB. Malformed payloads (non-serializable types such as `datetime`, `Decimal`, callables) slip through to response serialization and fail there, making the error harder to trace.

2. **`severity` is an unconstrained string** — `ScannerEvent.severity` is `Column(String(10))` with no enum enforcement. The frontend types it as `"low" | "medium" | "high"`, but any string can be persisted server-side.

3. **`AlertRule.channel_config` accepts any dict** — the alert-rule create/update endpoints accept `Dict[str, Any]` with no validation. A misconfigured `channel_config` (missing key, wrong type) fails silently at notification delivery time rather than at write time.

---

## Requirements

1. `save_event()` (centralized batch-scanner write path in `alert_service.py`) must reject a `severity` value outside `{"low","medium","high"}` at call time.
2. `save_event()` must reject `indicators`, `criteria_met`, and `enrichment` dicts that are not JSON-serializable (e.g. contain raw `datetime`, `Decimal`, callables).
3. `live_scanner/publisher.py` must apply the same severity constraint when it writes `ScannerEvent` rows directly.
4. The alert-rule `POST /rules` and `PATCH /rules/{id}` endpoints must validate the `channel_config` payload field and return HTTP 422 with a field-level message when it is invalid.
5. No DB migration required — validation lives in the Python layer only.
6. Existing valid calls must not be broken. All callers already produce valid data, so no call-site changes are needed beyond the new validation in the write functions.

---

## Architecture / Approach

### 1. `SeverityLiteral` and `ChannelConfig` schemas

Add to `backend/app/schemas/event.py`:

```python
from typing import Literal
SeverityLiteral = Literal["low", "medium", "high"]
```

Add a new file `backend/app/schemas/alerts.py`:

```python
from typing import Optional
from pydantic import BaseModel

class ChannelConfig(BaseModel):
    model_config = {"extra": "forbid"}

    email: Optional[str] = None
    google_chat_webhook: Optional[str] = None
    webhook_url: Optional[str] = None
```

`extra = "forbid"` is intentional: unknown keys are rejected so a misconfiguration like `"gmail"` (wrong key) surfaces as a 422 field error, not silent data loss.

### 2. Coarse JSONB dict validation helper

Add a private helper near `save_event()` in `backend/app/services/alert_service.py`:

```python
import json

def _validate_jsonb_dict(value: Any, field_name: str) -> None:
    if not isinstance(value, dict):
        raise ValueError(f"{field_name} must be a dict, got {type(value).__name__}")
    try:
        json.dumps(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} contains non-JSON-serializable value: {exc}") from exc
```

This does **not** validate per-scanner-type schemas (indicator keys vary by scanner type and would require 8+ schemas to maintain). It catches the class of bug the issue names: passing a `datetime` object, `Decimal`, or callable that would fail at serialization time.

### 3. `save_event()` — apply both validators

In `backend/app/services/alert_service.py`, after computing `severity`:

```python
# Validate severity enum
from app.schemas.event import SeverityLiteral
import typing
if severity not in typing.get_args(SeverityLiteral):
    raise ValueError(f"Invalid severity '{severity}': must be one of {typing.get_args(SeverityLiteral)}")

# Validate JSONB dicts
_validate_jsonb_dict(indicators, "indicators")
_validate_jsonb_dict(criteria_met, "criteria_met")
_validate_jsonb_dict(enrichment, "enrichment")
```

`compute_event_severity()` always returns a valid value today, so this guard is defensive against future `SEVERITY_CALCULATORS` drift.

### 4. Live scanner `publisher.py` — severity validation

In `backend/live_scanner/publisher.py`, after `severity = compute_event_severity(...)`:

```python
import typing
from app.schemas.event import SeverityLiteral
if severity not in typing.get_args(SeverityLiteral):
    raise ValueError(f"LivePublisher: invalid severity '{severity}'")
```

The live scanner indicators come from `conditions.py` which uses only Python primitives (int, float, str, bool), so JSONB dict validation is not needed there.

### 5. Alert-rule endpoints — `ChannelConfig` validation

In `backend/app/routers/alerts.py`, both `create_rule` and `update_rule`:

```python
from pydantic import ValidationError
from app.schemas.alerts import ChannelConfig

def _parse_channel_config(raw: Any) -> dict:
    if raw is None:
        return {}
    try:
        return ChannelConfig.model_validate(raw).model_dump(exclude_none=True)
    except ValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail={"channel_config": exc.errors()},
        )
```

Call `_parse_channel_config(payload.get("channel_config", {}))` before assigning to the `AlertRule` model, in both `create_rule` and `update_rule`. The rest of the payload remains `Dict[str, Any]` — this is a targeted change, not a full endpoint rewrite (see Alternatives).

### 6. `ScannerEventResponse` — tighten the response schema

In `backend/app/schemas/event.py`, update the `severity` field from `Optional[str]` to `Optional[SeverityLiteral]`:

```python
severity: Optional[SeverityLiteral] = "medium"
```

This surfaces any existing invalid data at response serialization time (Pydantic v2 raises on invalid literal values) and documents the constraint in the response schema.

---

## Alternatives Considered

### Full typed request bodies for alert-rule endpoints

Replace `payload: Dict[str, Any]` with `AlertRuleCreate` / `AlertRuleUpdate` Pydantic models. Rejected: the issue's acceptance criterion is narrowly about `channel_config`; typing every field risks regressions on PATCH partial-update semantics and is out of scope for `size: M`.

### DB-level CHECK constraint on `severity`

Add an Alembic migration with `ALTER TABLE scanner_events ADD CONSTRAINT ck_severity CHECK (severity IN ('low','medium','high'))`. Rejected: severity is always computed server-side by `compute_event_severity()`, which already constrains the output; the Python guard in `save_event()` is sufficient and avoids a migration.

### Per-scanner-type Pydantic indicator schemas

Define `PreMarketIndicators`, `OversoldBounceIndicators`, etc. and validate `scanner_type`-specific shapes. Rejected: there are 8+ scanner types, the set is still growing, and the issue never asks for key-level validation. The coarse JSON-serializability check satisfies the stated problem.

---

## Open Questions

None blocking. The `ChannelConfig` `extra = "forbid"` policy means adding a new channel later requires updating the schema — this is the desired behavior (the schema is the source of truth for valid keys).

---

## Assumptions

- All existing `save_event()` callers produce valid data (severity from `compute_event_severity()`, indicators from Python primitives). Adding the guard is defensive, not corrective.
- The `live_scanner/publisher.py` file, while outside the batch-scanner centralized write path, writes `ScannerEvent` rows directly and must receive the same severity constraint.
- `ChannelConfig.extra = "forbid"` is the right policy for this schema. Unknown keys are a misconfiguration, not a future-compatibility concern at this stage.
