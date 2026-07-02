from typing import Any, Dict, Optional

from app.models.scanner_event import ScannerEvent
from app.schemas.scanner_explanation import validate_scanner_explanation
from app.utils.time import utc_now


def _criterion(
    label: str,
    observed: Any,
    threshold: Any,
    operator: str,
    unit: Optional[str] = None,
    source: Optional[str] = None,
    lookback: Optional[str] = None,
    importance: Optional[float] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "label": label,
        "observed": observed,
        "threshold": threshold,
        "operator": operator,
    }
    if unit is not None:
        payload["unit"] = unit
    if source is not None:
        payload["source"] = source
    if lookback is not None:
        payload["lookback"] = lookback
    if importance is not None:
        payload["importance"] = importance
    return payload


def _split_criteria(criteria_met: Dict[str, Any], criteria: Dict[str, Dict[str, Any]]):
    passed: Dict[str, Dict[str, Any]] = {}
    failed: Dict[str, Dict[str, Any]] = {}
    for raw_key, explanation in criteria.items():
        target = passed if bool(criteria_met.get(raw_key)) else failed
        target[f"premarket.{raw_key}"] = explanation
    return passed, failed


def _quality_warnings(gate_metadata: Optional[Dict[str, Any]]) -> list[Dict[str, Any]]:
    warnings = []
    for warning in (gate_metadata or {}).get("warnings", []) or []:
        warnings.append(
            {
                "code": warning.get("code", "quality_gate_warning"),
                "severity": warning.get("severity", "medium"),
                "message": warning.get("message", "Data quality warning."),
                "affected_inputs": warning.get("affected_inputs", []),
            }
        )
    return warnings


def build_pre_market_volume_explanation(
    signal: Any,
    signal_quality_score: Optional[float] = None,
    gate_metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    raw = signal.raw
    indicators = signal.indicators or {}
    criteria_met = raw.criteria_met or {}

    threshold = (
        indicators.get("volume_anomaly_score")
        if raw.threshold_method == "timesfm"
        else 4.0
    )
    threshold_unit = "z" if raw.threshold_method == "timesfm" else "x"
    observed_spike = (
        indicators.get("volume_anomaly_score")
        if raw.threshold_method == "timesfm"
        else indicators.get("volume_spike_ratio", raw.relative_volume)
    )

    criteria = {
        "volume_spike": _criterion(
            "Volume spike",
            observed_spike,
            threshold,
            ">=",
            unit=threshold_unit,
            source="minute_aggregates",
            lookback="20d",
            importance=1.0,
        ),
        "minimum_volume": _criterion(
            "Minimum pre-market volume",
            indicators.get("pre_market_volume", raw.pre_market_volume),
            100000,
            ">",
            unit="shares",
            source="minute_aggregates",
            importance=0.8,
        ),
        "liquidity": _criterion(
            "Baseline liquidity",
            indicators.get("avg_volume_20d", raw.avg_volume_20d),
            500000,
            ">",
            unit="shares",
            source="daily_aggregates",
            lookback="20d",
            importance=0.7,
        ),
    }
    passed, failed = _split_criteria(criteria_met, criteria)

    why = [
        (
            f"Pre-market volume was {indicators.get('volume_spike_ratio', raw.relative_volume):.2f}x "
            "the 20-day average."
        )
    ]
    if indicators.get("gap_pct") is not None:
        why.append(f"Opening gap was {indicators['gap_pct']}%.")
    if indicators.get("has_news_catalyst"):
        why.append("A news catalyst was present in enrichment data.")

    payload = {
        "schema_version": "scanner_explanation.v1",
        "why": why,
        "criteria_passed": passed,
        "criteria_failed": failed,
        "confidence_inputs": {
            "signal_quality_score": signal_quality_score,
            "threshold_method": raw.threshold_method,
            "relative_volume": raw.relative_volume,
            "anomaly_score": raw.anomaly_score,
            "has_news_catalyst": indicators.get("has_news_catalyst"),
        },
        "data_quality_warnings": _quality_warnings(gate_metadata),
        "evidence": {
            "reconstructed": False,
            "generated_at": utc_now(),
            "generator_version": "explanation_builder.v1",
            "provider": "polygon",
        },
    }
    return validate_scanner_explanation(payload)


def reconstruct_explanation_for_event(event: ScannerEvent) -> Dict[str, Any]:
    indicators = event.indicators or {}
    criteria_met = event.criteria_met or {}
    if event.scanner_type == "pre_market_volume_spike":
        criteria = {
            "volume_spike": _criterion(
                "Volume spike",
                indicators.get("volume_spike_ratio")
                or indicators.get("relative_volume"),
                4.0,
                ">=",
                unit="x",
                source="scanner_event.indicators",
                lookback="20d",
                importance=1.0,
            ),
            "minimum_volume": _criterion(
                "Minimum pre-market volume",
                indicators.get("pre_market_volume"),
                100000,
                ">",
                unit="shares",
                source="scanner_event.indicators",
                importance=0.8,
            ),
            "liquidity": _criterion(
                "Baseline liquidity",
                indicators.get("avg_volume_20d"),
                500000,
                ">",
                unit="shares",
                source="scanner_event.indicators",
                lookback="20d",
                importance=0.7,
            ),
        }
        passed, failed = _split_criteria(criteria_met, criteria)
    else:
        scanner_prefix = event.scanner_type.replace("_", ".")
        passed = {}
        failed = {}
        for key, value in criteria_met.items():
            target = passed if bool(value) else failed
            target[f"{scanner_prefix}.{key}"] = _criterion(
                key.replace("_", " ").title(),
                value,
                True,
                "==",
                source="scanner_event.criteria_met",
            )

    ratio = indicators.get("volume_spike_ratio") or indicators.get("relative_volume")
    why = ["Historical scanner event reconstructed from stored indicators."]
    if ratio is not None:
        why = [f"Stored indicators show {ratio}x pre-market relative volume."]

    payload = {
        "schema_version": "scanner_explanation.v1",
        "why": why,
        "criteria_passed": passed,
        "criteria_failed": failed,
        "confidence_inputs": {
            "signal_quality_score": event.signal_quality_score,
            "scanner_type": event.scanner_type,
        },
        "data_quality_warnings": _quality_warnings(
            (event.metadata_ or {}).get("quality_gate")
        ),
        "evidence": {
            "reconstructed": True,
            "reconstruction_quality": "best_effort",
            "generated_at": utc_now(),
            "generator_version": "explanation_backfill.v1",
            "provider": "stored_scanner_event",
        },
    }
    return validate_scanner_explanation(payload)
