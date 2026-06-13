# Plan: Validate JSONB Writes, Severity Enum, and ChannelConfig Schema

**Goal:** Close three validation gaps flagged in the v3 architecture review: unvalidated JSONB writes, unconstrained `severity` string, and `channel_config` accepting any dict.
**Issue:** #292
**Spec:** docs/superpowers/specs/2026-06-13-validate-jsonb-severity-channelconfig-design.md
**Date:** 2026-06-13

---

## Architecture

Python-layer validation only — no DB migration. Guards live in the write functions (`save_event()`, `publisher.py`) and at the API boundary (`routers/alerts.py`). A shared `SeverityLiteral` type alias is the single source of truth for valid values. `ChannelConfig` is a strict Pydantic model (`extra = "forbid"`) that validates `channel_config` before the `AlertRule` is persisted.

## Tech Stack

Backend: FastAPI + SQLAlchemy (sync) + Pydantic v2 + pytest (testcontainers Postgres)

---

## File Structure

| File | Change |
|------|--------|
| `backend/app/schemas/event.py` | Add `SeverityLiteral`; tighten `ScannerEventResponse.severity` |
| `backend/app/schemas/alerts.py` | New file — `ChannelConfig` Pydantic model |
| `backend/app/services/alert_service.py` | Add `_validate_jsonb_dict()`; add guards to `save_event()` |
| `backend/live_scanner/publisher.py` | Add severity guard in `fire_alert_if_new()` |
| `backend/app/routers/alerts.py` | Add `_parse_channel_config()`; wire to `create_rule` and `update_rule` |
| `backend/tests/services/test_alert_service.py` | New tests for `save_event()` validation |
| `backend/tests/live_scanner/test_publisher.py` | New tests for live publisher severity guard |
| `backend/tests/api/test_alerts.py` | New tests for endpoint channel_config 422 |

---

## Task 1: Add `SeverityLiteral` and tighten `ScannerEventResponse`

**Files:** `backend/app/schemas/event.py`, `backend/tests/services/test_alert_service.py`

### Steps

**1a. Write failing tests**

Add to `backend/tests/services/test_alert_service.py`:

```python
from app.schemas.event import ScannerEventResponse, SeverityLiteral
import typing


def test_severity_literal_values():
    assert set(typing.get_args(SeverityLiteral)) == {"low", "medium", "high"}


def test_scanner_event_response_rejects_invalid_severity():
    import pytest
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        ScannerEventResponse(
            id=1,
            uuid="00000000-0000-0000-0000-000000000001",
            ticker="AAPL",
            event_date="2026-06-13",
            scanner_type="pre_market_volume_spike",
            severity="INVALID",
            created_at="2026-06-13T10:00:00",
            updated_at="2026-06-13T10:00:00",
        )


def test_scanner_event_response_accepts_valid_severity():
    from pydantic import ValidationError
    for sev in ("low", "medium", "high"):
        ScannerEventResponse(
            id=1,
            uuid="00000000-0000-0000-0000-000000000001",
            ticker="AAPL",
            event_date="2026-06-13",
            scanner_type="pre_market_volume_spike",
            severity=sev,
            created_at="2026-06-13T10:00:00",
            updated_at="2026-06-13T10:00:00",
        )  # must not raise
```

Run to confirm failure:
```bash
docker-compose exec backend python -m pytest backend/tests/services/test_alert_service.py::test_severity_literal_values backend/tests/services/test_alert_service.py::test_scanner_event_response_rejects_invalid_severity -x 2>&1 | tail -20
```
Expected: `ImportError: cannot import name 'SeverityLiteral'`

**1b. Implement**

Edit `backend/app/schemas/event.py`:

```python
# Add after existing imports:
from typing import Any, Dict, Literal, Optional

SeverityLiteral = Literal["low", "medium", "high"]
```

In `ScannerEventResponse`, change:
```python
# Before:
severity: Optional[str] = "medium"

# After:
severity: Optional[SeverityLiteral] = "medium"
```

**1c. Verify pass**

```bash
docker-compose exec backend python -m pytest backend/tests/services/test_alert_service.py::test_severity_literal_values backend/tests/services/test_alert_service.py::test_scanner_event_response_rejects_invalid_severity backend/tests/services/test_alert_service.py::test_scanner_event_response_accepts_valid_severity -v 2>&1 | tail -15
```
Expected: `3 passed`

**1d. Commit**

```bash
git add backend/app/schemas/event.py backend/tests/services/test_alert_service.py
git commit -m "feat(schemas): add SeverityLiteral type alias and tighten ScannerEventResponse.severity"
```

---

## Task 2: Create `ChannelConfig` Pydantic model

**Files:** `backend/app/schemas/alerts.py`, `backend/tests/services/test_alert_service.py`

### Steps

**2a. Write failing tests**

Add to `backend/tests/services/test_alert_service.py`:

```python
def test_channel_config_accepts_valid_keys():
    from app.schemas.alerts import ChannelConfig
    cfg = ChannelConfig(email="user@example.com", google_chat_webhook=None, webhook_url=None)
    assert cfg.email == "user@example.com"


def test_channel_config_rejects_unknown_key():
    import pytest
    from pydantic import ValidationError
    from app.schemas.alerts import ChannelConfig
    with pytest.raises(ValidationError):
        ChannelConfig(gmail="user@example.com")  # wrong key — should be "email"


def test_channel_config_all_none():
    from app.schemas.alerts import ChannelConfig
    cfg = ChannelConfig()
    assert cfg.email is None
    assert cfg.google_chat_webhook is None
    assert cfg.webhook_url is None


def test_channel_config_model_dump_excludes_none():
    from app.schemas.alerts import ChannelConfig
    cfg = ChannelConfig(email="user@example.com")
    dumped = cfg.model_dump(exclude_none=True)
    assert dumped == {"email": "user@example.com"}
    assert "google_chat_webhook" not in dumped
```

Run to confirm failure:
```bash
docker-compose exec backend python -m pytest backend/tests/services/test_alert_service.py::test_channel_config_accepts_valid_keys -x 2>&1 | tail -10
```
Expected: `ImportError: cannot import name 'ChannelConfig'`

**2b. Implement**

Create `backend/app/schemas/alerts.py`:

```python
"""
Pydantic schemas for alert rules.
"""
from typing import Optional

from pydantic import BaseModel


class ChannelConfig(BaseModel):
    model_config = {"extra": "forbid"}

    email: Optional[str] = None
    google_chat_webhook: Optional[str] = None
    webhook_url: Optional[str] = None
```

**2c. Verify pass**

```bash
docker-compose exec backend python -m pytest backend/tests/services/test_alert_service.py::test_channel_config_accepts_valid_keys backend/tests/services/test_alert_service.py::test_channel_config_rejects_unknown_key backend/tests/services/test_alert_service.py::test_channel_config_all_none backend/tests/services/test_alert_service.py::test_channel_config_model_dump_excludes_none -v 2>&1 | tail -15
```
Expected: `4 passed`

**2d. Commit**

```bash
git add backend/app/schemas/alerts.py backend/tests/services/test_alert_service.py
git commit -m "feat(schemas): add ChannelConfig Pydantic model with extra=forbid"
```

---

## Task 3: Add JSONB dict validation helper and update `save_event()`

**Files:** `backend/app/services/alert_service.py`, `backend/tests/services/test_alert_service.py`

### Steps

**3a. Write failing tests**

Add to `backend/tests/services/test_alert_service.py`:

```python
import pytest
from datetime import date
from sqlalchemy.orm import Session
from app.services.alert_service import save_event


def test_save_event_rejects_invalid_severity(db: Session):
    with pytest.raises(ValueError, match="Invalid severity"):
        save_event(
            db=db,
            ticker="AAPL",
            event_date=date(2026, 6, 13),
            scanner_type="pre_market_volume_spike",
            indicators={"volume_spike_ratio": 6.0, "gap_pct": 2.0},
            criteria_met={"gap_pct_above_threshold": True},
            enrichment={},
        )


def test_save_event_rejects_non_serializable_indicators(db: Session):
    from datetime import datetime
    with pytest.raises(ValueError, match="indicators contains non-JSON-serializable"):
        save_event(
            db=db,
            ticker="AAPL",
            event_date=date(2026, 6, 13),
            scanner_type="pre_market_volume_spike",
            indicators={"ts": datetime(2026, 6, 13, 9, 30)},
            criteria_met={},
            enrichment={},
        )


def test_save_event_rejects_non_serializable_criteria_met(db: Session):
    from decimal import Decimal
    with pytest.raises(ValueError, match="criteria_met contains non-JSON-serializable"):
        save_event(
            db=db,
            ticker="AAPL",
            event_date=date(2026, 6, 13),
            scanner_type="pre_market_volume_spike",
            indicators={"volume_spike_ratio": 5.0},
            criteria_met={"threshold": Decimal("1.5")},
            enrichment={},
        )


def test_save_event_rejects_non_serializable_enrichment(db: Session):
    with pytest.raises(ValueError, match="enrichment contains non-JSON-serializable"):
        save_event(
            db=db,
            ticker="AAPL",
            event_date=date(2026, 6, 13),
            scanner_type="pre_market_volume_spike",
            indicators={"volume_spike_ratio": 5.0},
            criteria_met={},
            enrichment={"fn": lambda x: x},
        )


def test_save_event_valid_data_persists(db: Session):
    result = save_event(
        db=db,
        ticker="TSLA",
        event_date=date(2026, 6, 13),
        scanner_type="pre_market_volume_spike",
        indicators={"volume_spike_ratio": 7.0, "gap_pct": 3.0},
        criteria_met={"gap_pct_above_threshold": True},
        enrichment={"source": "batch_scanner"},
    )
    assert result["ticker"] == "TSLA"
    assert result["severity"] in ("low", "medium", "high")
```

Run to confirm failure:
```bash
docker-compose exec backend python -m pytest backend/tests/services/test_alert_service.py::test_save_event_rejects_invalid_severity -x 2>&1 | tail -20
```
Expected: test passes without raising (no ValueError yet), or assertion error — either way the guard is absent.

**3b. Implement**

Edit `backend/app/services/alert_service.py`.

Add after the existing imports block (after the `from app.utils.time import utc_now` line):

```python
import typing
from typing import Any
```

Note: `json` and `logging` are already imported.

Add this private helper immediately before the `save_event` function (around line 346):

```python
def _validate_jsonb_dict(value: Any, field_name: str) -> None:
    if not isinstance(value, dict):
        raise ValueError(f"{field_name} must be a dict, got {type(value).__name__}")
    try:
        json.dumps(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"{field_name} contains non-JSON-serializable value: {exc}"
        ) from exc
```

In `save_event()`, add the guards immediately after `severity = compute_event_severity(scanner_type, indicators)`:

```python
    from app.schemas.event import SeverityLiteral

    if severity not in typing.get_args(SeverityLiteral):
        raise ValueError(
            f"Invalid severity '{severity}': must be one of {typing.get_args(SeverityLiteral)}"
        )

    _validate_jsonb_dict(indicators, "indicators")
    _validate_jsonb_dict(criteria_met, "criteria_met")
    _validate_jsonb_dict(enrichment, "enrichment")
```

**3c. Verify pass**

```bash
docker-compose exec backend python -m pytest backend/tests/services/test_alert_service.py::test_save_event_rejects_invalid_severity backend/tests/services/test_alert_service.py::test_save_event_rejects_non_serializable_indicators backend/tests/services/test_alert_service.py::test_save_event_rejects_non_serializable_criteria_met backend/tests/services/test_alert_service.py::test_save_event_rejects_non_serializable_enrichment backend/tests/services/test_alert_service.py::test_save_event_valid_data_persists -v 2>&1 | tail -20
```
Expected: `5 passed`

Also run the full alert_service test suite to confirm no regressions:
```bash
docker-compose exec backend python -m pytest backend/tests/services/test_alert_service.py -v 2>&1 | tail -20
```

**3d. Commit**

```bash
git add backend/app/services/alert_service.py backend/tests/services/test_alert_service.py
git commit -m "feat(alert_service): validate severity enum and JSONB dict serializability in save_event()"
```

---

## Task 4: Add severity guard in `publisher.py`

**Files:** `backend/live_scanner/publisher.py`, `backend/tests/live_scanner/test_publisher.py`

### Steps

**4a. Write failing tests**

Add to `backend/tests/live_scanner/test_publisher.py`:

```python
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from live_scanner.publisher import LivePublisher
from live_scanner.conditions import ConditionResult
from live_scanner.bar_aggregator import MinuteBar
from datetime import datetime, timezone


def _make_bar(symbol="AAPL"):
    bar = MagicMock(spec=MinuteBar)
    bar.symbol = symbol
    bar.minute_ts = datetime(2026, 6, 13, 9, 31, tzinfo=timezone.utc)
    bar.prior_close = 150.0
    bar.close = 155.0
    bar.session = "pre"
    return bar


def _make_condition(scanner_type="pre_market_volume_spike"):
    cond = MagicMock(spec=ConditionResult)
    cond.scanner_type = scanner_type
    cond.indicators = {"volume_spike_ratio": 6.0}
    cond.criteria_met = {"volume_above_threshold": True}
    return cond


def test_fire_alert_if_new_raises_on_invalid_severity():
    pub = LivePublisher("redis://localhost:6379")
    pub._redis = AsyncMock()
    pub._redis.set = AsyncMock(return_value=True)  # dedup acquired

    bar = _make_bar()
    condition = _make_condition()

    with patch("live_scanner.publisher.compute_event_severity", return_value="BOGUS"), \
         patch("live_scanner.publisher.generate_event_summary", return_value="Test summary"):
        with pytest.raises(ValueError, match="invalid severity"):
            asyncio.run(pub.fire_alert_if_new(bar, condition))
```

Run to confirm failure:
```bash
docker-compose exec backend python -m pytest backend/tests/live_scanner/test_publisher.py::test_fire_alert_if_new_raises_on_invalid_severity -x 2>&1 | tail -20
```
Expected: test fails (no ValueError raised — function does not validate severity yet).

**4b. Implement**

Edit `backend/live_scanner/publisher.py`.

Add import after the existing imports (after line 27 `from live_scanner.conditions import ConditionResult`):

```python
import typing
from app.schemas.event import SeverityLiteral
```

In `fire_alert_if_new()`, add the guard immediately after `severity = compute_event_severity(...)` (currently line 134):

```python
        if severity not in typing.get_args(SeverityLiteral):
            raise ValueError(
                f"LivePublisher: invalid severity '{severity}' for "
                f"{bar.symbol}/{condition.scanner_type}"
            )
```

**4c. Verify pass**

```bash
docker-compose exec backend python -m pytest backend/tests/live_scanner/test_publisher.py -v 2>&1 | tail -20
```
Expected: all tests pass, including the new `test_fire_alert_if_new_raises_on_invalid_severity`.

**4d. Commit**

```bash
git add backend/live_scanner/publisher.py backend/tests/live_scanner/test_publisher.py
git commit -m "feat(publisher): guard against invalid severity in LivePublisher.fire_alert_if_new()"
```

---

## Task 5: Validate `channel_config` in alert-rule endpoints

**Files:** `backend/app/routers/alerts.py`, `backend/tests/api/test_alerts.py`

### Steps

**5a. Write failing tests**

Add to `backend/tests/api/test_alerts.py`:

```python
def test_create_rule_rejects_invalid_channel_config(db: Session):
    response = client.post(
        "/api/v1/alerts/rules",
        json={
            "name": "Bad Config Rule",
            "channel_config": {"gmail": "user@example.com"},  # invalid key
        },
    )
    assert response.status_code == 422
    body = response.json()
    assert "channel_config" in str(body)


def test_create_rule_accepts_valid_channel_config(db: Session):
    response = client.post(
        "/api/v1/alerts/rules",
        json={
            "name": "Valid Config Rule",
            "channel_config": {"email": "user@example.com"},
        },
    )
    assert response.status_code == 201
    assert response.json()["channel_config"]["email"] == "user@example.com"


def test_update_rule_rejects_invalid_channel_config(db: Session):
    create = client.post(
        "/api/v1/alerts/rules",
        json={"name": "Update Target", "channel_config": {}},
    )
    rule_id = create.json()["id"]

    response = client.patch(
        f"/api/v1/alerts/rules/{rule_id}",
        json={"channel_config": {"slack_webhook": "https://hooks.slack.com/..."}},
    )
    assert response.status_code == 422
    body = response.json()
    assert "channel_config" in str(body)


def test_update_rule_accepts_valid_channel_config(db: Session):
    create = client.post(
        "/api/v1/alerts/rules",
        json={"name": "Update Target 2", "channel_config": {}},
    )
    rule_id = create.json()["id"]

    response = client.patch(
        f"/api/v1/alerts/rules/{rule_id}",
        json={"channel_config": {"webhook_url": "https://example.com/hook"}},
    )
    assert response.status_code == 200
    assert response.json()["channel_config"]["webhook_url"] == "https://example.com/hook"


def test_create_rule_empty_channel_config_is_valid(db: Session):
    response = client.post(
        "/api/v1/alerts/rules",
        json={"name": "Empty Config Rule", "channel_config": {}},
    )
    assert response.status_code == 201
```

Run to confirm failure:
```bash
docker-compose exec backend python -m pytest backend/tests/api/test_alerts.py::test_create_rule_rejects_invalid_channel_config -x 2>&1 | tail -20
```
Expected: `AssertionError: assert 201 == 422` (no validation yet, endpoint accepts any dict).

**5b. Implement**

Edit `backend/app/routers/alerts.py`.

Add to the import block (after `from app.utils.time import utc_now`):

```python
from pydantic import ValidationError

from app.schemas.alerts import ChannelConfig
```

Add this private helper after the `_rule_to_dict` function (around line 87):

```python
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

In `create_rule()`, replace the `channel_config` assignment line:

```python
# Before:
        channel_config=payload.get("channel_config", {}),

# After:
        channel_config=_parse_channel_config(payload.get("channel_config")),
```

In `update_rule()`, in the `for key, value in payload.items()` loop, intercept `channel_config`:

```python
    for key, value in payload.items():
        if key not in updatable:
            continue
        if key == "channel_config":
            value = _parse_channel_config(value)
        setattr(rule, key, value)
```

**5c. Verify pass**

```bash
docker-compose exec backend python -m pytest backend/tests/api/test_alerts.py::test_create_rule_rejects_invalid_channel_config backend/tests/api/test_alerts.py::test_create_rule_accepts_valid_channel_config backend/tests/api/test_alerts.py::test_update_rule_rejects_invalid_channel_config backend/tests/api/test_alerts.py::test_update_rule_accepts_valid_channel_config backend/tests/api/test_alerts.py::test_create_rule_empty_channel_config_is_valid -v 2>&1 | tail -20
```
Expected: `5 passed`

Run full alerts API test suite to confirm no regressions:
```bash
docker-compose exec backend python -m pytest backend/tests/api/test_alerts.py -v 2>&1 | tail -30
```

**5d. Commit**

```bash
git add backend/app/routers/alerts.py backend/tests/api/test_alerts.py
git commit -m "feat(alerts): validate channel_config against ChannelConfig schema in create/update endpoints"
```

---

## Final Smoke Test

```bash
docker-compose exec backend python -m pytest backend/tests/services/test_alert_service.py backend/tests/live_scanner/test_publisher.py backend/tests/api/test_alerts.py -v 2>&1 | tail -30
```
Expected: all tests pass.

```bash
docker-compose logs backend --tail=5
```
Expected: no import errors; backend reload clean.
