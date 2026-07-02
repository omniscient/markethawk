from typing import Any, Dict, Optional

from app.models.scanner_event import ScannerEvent
from app.schemas.scanner_explanation import validate_scanner_explanation
from app.utils.time import utc_now

LIQUIDITY_HUNT_DEFAULT_CONFIG: dict[str, float] = {
    "volume_ratio_min": 4.0,
    "volume_pct_of_daily_min": 0.30,
    "spike_pct_min": 0.10,
    "regular_vol_ratio_max": 1000.0,
    "regular_range_ratio_max": 1.50,
    "session_volume_floor": 50_000,
}


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


def _split_criteria(
    criteria_met: Dict[str, Any],
    criteria: Dict[str, Dict[str, Any]],
    prefix: str,
):
    passed: Dict[str, Dict[str, Any]] = {}
    failed: Dict[str, Dict[str, Any]] = {}
    for raw_key, explanation in criteria.items():
        target = passed if bool(criteria_met.get(raw_key)) else failed
        target[f"{prefix}.{raw_key}"] = explanation
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
    passed, failed = _split_criteria(criteria_met, criteria, "premarket")

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


def _pct(value: Any) -> Optional[float]:
    return round(float(value) * 100, 2) if value is not None else None


def _liquidity_hunt_criteria(
    indicators: Dict[str, Any],
    config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Dict[str, Any]]:
    cfg = {**LIQUIDITY_HUNT_DEFAULT_CONFIG, **(config or {})}
    return {
        "volume_ratio": _criterion(
            "Off-hours volume ratio",
            indicators.get("session_volume_ratio"),
            cfg["volume_ratio_min"],
            ">=",
            unit="x",
            source="minute_aggregates",
            lookback="20d",
            importance=1.0,
        ),
        "volume_materiality": _criterion(
            "Off-hours share of daily volume",
            _pct(indicators.get("session_volume_pct_of_daily")),
            _pct(cfg["volume_pct_of_daily_min"]),
            ">=",
            unit="%",
            source="minute_aggregates",
            lookback="20d",
            importance=0.8,
        ),
        "session_spike": _criterion(
            "Off-hours price spike",
            _pct(indicators.get("session_spike_pct")),
            _pct(cfg["spike_pct_min"]),
            ">=",
            unit="%",
            source="minute_aggregates",
            importance=0.9,
        ),
        "quiet_regular_vol": _criterion(
            "Regular-session volume restraint",
            indicators.get("regular_volume_ratio"),
            cfg["regular_vol_ratio_max"],
            "<=",
            unit="x",
            source="minute_aggregates",
            lookback="20d",
            importance=0.4,
        ),
        "quiet_regular_range": _criterion(
            "Regular-session range restraint",
            indicators.get("regular_range_ratio"),
            cfg["regular_range_ratio_max"],
            "<=",
            unit="x",
            source="minute_aggregates",
            lookback="20d",
            importance=0.8,
        ),
        "volume_floor": _criterion(
            "Absolute off-hours volume floor",
            indicators.get("session_volume"),
            cfg["session_volume_floor"],
            ">=",
            unit="shares",
            source="minute_aggregates",
            importance=0.6,
        ),
    }


def build_liquidity_hunt_explanation(
    scanner_type: str,
    indicators: Dict[str, Any],
    criteria_met: Dict[str, Any],
    gate_metadata: Optional[Dict[str, Any]] = None,
    config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    criteria = _liquidity_hunt_criteria(indicators, config=config)
    passed, failed = _split_criteria(criteria_met, criteria, scanner_type)

    session_label = (
        "pre-market" if indicators.get("session") == "pre" else "post-market"
    )
    why = [f"{session_label.title()} liquidity matched the hunt criteria."]
    if indicators.get("session_volume_ratio") is not None:
        why[0] = (
            f"{session_label.title()} volume was "
            f"{float(indicators['session_volume_ratio']):.2f}x its 20-day session baseline."
        )
    if indicators.get("session_spike_pct") is not None:
        why.append(
            f"Session high was {_pct(indicators['session_spike_pct']):.2f}% above reference close."
        )

    payload = {
        "schema_version": "scanner_explanation.v1",
        "why": why,
        "criteria_passed": passed,
        "criteria_failed": failed,
        "confidence_inputs": {
            "scanner_type": scanner_type,
            "session": indicators.get("session"),
            "session_volume": indicators.get("session_volume"),
            "session_volume_ratio": indicators.get("session_volume_ratio"),
            "session_spike_pct": indicators.get("session_spike_pct"),
            "float_rotation_pct": indicators.get("float_rotation_pct"),
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
        passed, failed = _split_criteria(criteria_met, criteria, "premarket")
    elif event.scanner_type in {"liquidity_hunt_pre", "liquidity_hunt_post"}:
        criteria = _liquidity_hunt_criteria(indicators)
        passed, failed = _split_criteria(criteria_met, criteria, event.scanner_type)
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
