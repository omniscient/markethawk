from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.schemas.scanner_explanation import ScannerExplanation


def _payload():
    return {
        "schema_version": "scanner_explanation.v1",
        "why": ["Pre-market volume was 5.2x the 20-day average."],
        "criteria_passed": {
            "premarket.volume_spike": {
                "label": "Volume spike",
                "observed": 5.2,
                "threshold": 4.0,
                "operator": ">=",
                "unit": "x",
                "source": "minute_aggregates",
            }
        },
        "criteria_failed": {},
        "confidence_inputs": {"signal_quality_score": 82.5},
        "data_quality_warnings": [
            {
                "code": "stale_bars",
                "severity": "medium",
                "message": "Some bars are older than expected.",
                "affected_inputs": ["minute_aggregates"],
            }
        ],
        "evidence": {
            "reconstructed": False,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "generator_version": "explanation_builder.v1",
            "provider": "polygon",
        },
    }


def test_scanner_explanation_accepts_v1_payload():
    explanation = ScannerExplanation.model_validate(_payload())

    assert explanation.schema_version == "scanner_explanation.v1"
    assert "premarket.volume_spike" in explanation.criteria_passed
    assert explanation.data_quality_warnings[0].severity == "medium"


def test_scanner_explanation_rejects_unknown_schema_version():
    payload = _payload()
    payload["schema_version"] = "scanner_explanation.v2"

    with pytest.raises(ValidationError):
        ScannerExplanation.model_validate(payload)


def test_scanner_explanation_rejects_unqualified_criterion_id():
    payload = _payload()
    payload["criteria_passed"] = {"volume_spike": payload["criteria_passed"]["premarket.volume_spike"]}

    with pytest.raises(ValidationError, match="criterion id"):
        ScannerExplanation.model_validate(payload)


def test_scanner_explanation_rejects_unknown_operator():
    payload = _payload()
    payload["criteria_passed"]["premarket.volume_spike"]["operator"] = "around"

    with pytest.raises(ValidationError):
        ScannerExplanation.model_validate(payload)
