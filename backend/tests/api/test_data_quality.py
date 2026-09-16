"""
Integration tests for POST /api/v1/data-quality/gate.

QualityGateService.assess() is patched so tests exercise the HTTP/validation
surface without requiring the #492 service implementation.
"""

from datetime import datetime, timezone
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.main import app
from app.models.stock_universe import StockUniverse
from app.schemas.quality_gate import (
    QualityGateAssessment,
    QualityGatePolicy,
    QualityGateScope,
    QualityGateVerdict,
)

client = TestClient(app)

_GATE_URL = "/api/v1/data-quality/gate"
_NOW = datetime(2026, 6, 21, 12, 0, 0, tzinfo=timezone.utc)


def _make_universe(db: Session) -> StockUniverse:
    u = StockUniverse(name="Test Universe", criteria={}, is_active=True)
    db.add(u)
    db.flush()
    return u


def _assessment(
    verdict: QualityGateVerdict, policy: QualityGatePolicy, uid: int
) -> QualityGateAssessment:
    return QualityGateAssessment(
        policy=policy,
        verdict=verdict,
        trusted=(verdict in (QualityGateVerdict.trusted, QualityGateVerdict.skipped)),
        scope=QualityGateScope(universe_id=uid),
        score=90.0 if verdict == QualityGateVerdict.trusted else None,
        grade="A" if verdict == QualityGateVerdict.trusted else None,
        generated_at=_NOW,
    )


# ---------------------------------------------------------------------------
# Verdict paths (service patched)
# ---------------------------------------------------------------------------


def test_gate_trusted(db: Session):
    u = _make_universe(db)
    assessment = _assessment(QualityGateVerdict.trusted, QualityGatePolicy.strict, u.id)

    with patch(
        "app.routers.data_quality.quality_gate_service.assess", return_value=assessment
    ):
        response = client.post(
            _GATE_URL,
            json={"universe_id": u.id, "policy": "strict", "consumer": "scanner"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["verdict"] == "trusted"
    assert data["trusted"] is True
    assert data["schema_version"] == "quality_gate.v1"


def test_gate_warning(db: Session):
    u = _make_universe(db)
    assessment = _assessment(
        QualityGateVerdict.warning, QualityGatePolicy.advisory, u.id
    )

    with patch(
        "app.routers.data_quality.quality_gate_service.assess", return_value=assessment
    ):
        response = client.post(
            _GATE_URL,
            json={"universe_id": u.id, "policy": "advisory", "consumer": "backtesting"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["verdict"] == "warning"
    assert data["trusted"] is False


def test_gate_blocked(db: Session):
    u = _make_universe(db)
    assessment = _assessment(QualityGateVerdict.blocked, QualityGatePolicy.strict, u.id)

    with patch(
        "app.routers.data_quality.quality_gate_service.assess", return_value=assessment
    ):
        response = client.post(
            _GATE_URL,
            json={"universe_id": u.id, "policy": "strict", "consumer": "auto_trading"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["verdict"] == "blocked"
    assert data["trusted"] is False


def test_gate_skipped(db: Session):
    u = _make_universe(db)
    assessment = _assessment(QualityGateVerdict.skipped, QualityGatePolicy.off, u.id)

    with patch(
        "app.routers.data_quality.quality_gate_service.assess", return_value=assessment
    ):
        response = client.post(
            _GATE_URL,
            json={"universe_id": u.id, "policy": "off", "consumer": "ui"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["verdict"] == "skipped"
    assert data["trusted"] is True


# ---------------------------------------------------------------------------
# Optional fields pass through correctly
# ---------------------------------------------------------------------------


def test_gate_with_requirements_and_date_range(db: Session):
    u = _make_universe(db)
    assessment = _assessment(QualityGateVerdict.trusted, QualityGatePolicy.strict, u.id)

    with patch(
        "app.routers.data_quality.quality_gate_service.assess", return_value=assessment
    ) as mock_assess:
        response = client.post(
            _GATE_URL,
            json={
                "universe_id": u.id,
                "policy": "strict",
                "consumer": "scorecard",
                "scanner_type": "pre_market_volume",
                "ticker": "AAPL",
                "start_date": "2026-01-01",
                "end_date": "2026-06-21",
                "requirements": {
                    "timespans": [
                        {"timespan": "minute", "multiplier": 1},
                        {"timespan": "day", "multiplier": 1},
                    ]
                },
            },
        )
    assert response.status_code == 200
    # Verify the full body was passed to the service
    call_body = mock_assess.call_args[0][1]
    assert call_body.ticker == "AAPL"
    assert call_body.requirements.timespans[0].timespan == "minute"


# ---------------------------------------------------------------------------
# 404 — universe not found
# ---------------------------------------------------------------------------


def test_gate_universe_not_found(db: Session):
    response = client.post(
        _GATE_URL,
        json={"universe_id": 999999, "policy": "strict", "consumer": "scanner"},
    )
    assert response.status_code == 404
    assert "Universe" in response.json()["detail"]


# ---------------------------------------------------------------------------
# 422 — validation errors
# ---------------------------------------------------------------------------


def test_gate_invalid_policy(db: Session):
    response = client.post(
        _GATE_URL,
        json={"universe_id": 1, "policy": "invalid", "consumer": "scanner"},
    )
    assert response.status_code == 422


def test_gate_invalid_consumer(db: Session):
    response = client.post(
        _GATE_URL,
        json={"universe_id": 1, "policy": "strict", "consumer": "unknown"},
    )
    assert response.status_code == 422


def test_gate_invalid_timespan(db: Session):
    response = client.post(
        _GATE_URL,
        json={
            "universe_id": 1,
            "policy": "strict",
            "consumer": "scanner",
            "requirements": {"timespans": [{"timespan": "tick", "multiplier": 1}]},
        },
    )
    assert response.status_code == 422


def test_gate_extra_field_rejected(db: Session):
    response = client.post(
        _GATE_URL,
        json={
            "universe_id": 1,
            "policy": "strict",
            "consumer": "scanner",
            "unknown_field": "value",
        },
    )
    assert response.status_code == 422
