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

    session_label = "pre-market" if indicators.get("session") == "pre" else "post-market"
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


def _oversold_bounce_criteria(
    indicators: Dict[str, Any],
) -> Dict[str, Dict[str, Any]]:
    return {
        "volume_ma_3_ok": _criterion(
            "3-day volume average",
            indicators.get("vol_ma_3"),
            500000,
            ">=",
            unit="shares",
            source="daily_aggregates",
            lookback="3d",
            importance=0.7,
        ),
        "price_ge_5": _criterion(
            "Price floor",
            indicators.get("previous_close") or indicators.get("closing_price"),
            5,
            ">=",
            unit="$",
            source="daily_aggregates",
            importance=0.5,
        ),
        "rsi_2_crossed": _criterion(
            "RSI-2 recovery cross",
            indicators.get("rsi_2"),
            15,
            ">=",
            source="daily_aggregates",
            lookback="2d",
            importance=1.0,
        ),
        "rsi_5_crossed": _criterion(
            "RSI-5 recovery cross",
            indicators.get("rsi_5"),
            27,
            ">=",
            source="daily_aggregates",
            lookback="5d",
            importance=0.9,
        ),
        "no_gap_down": _criterion(
            "No gap below prior low",
            True,
            True,
            "==",
            source="daily_aggregates",
            importance=0.6,
        ),
    }


def build_oversold_bounce_explanation(
    indicators: Dict[str, Any],
    criteria_met: Dict[str, Any],
    gate_metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    criteria = _oversold_bounce_criteria(indicators)
    passed, failed = _split_criteria(criteria_met, criteria, "oversold_bounce")

    why = ["RSI-2 and RSI-5 recovered from oversold levels."]
    if indicators.get("rsi_2") is not None and indicators.get("rsi_5") is not None:
        why[0] = (
            f"RSI-2 recovered to {float(indicators['rsi_2']):.2f} and "
            f"RSI-5 recovered to {float(indicators['rsi_5']):.2f}."
        )
    if indicators.get("vol_ma_3") is not None:
        why.append(f"3-day average volume was {int(indicators['vol_ma_3']):,} shares.")

    payload = {
        "schema_version": "scanner_explanation.v1",
        "why": why,
        "criteria_passed": passed,
        "criteria_failed": failed,
        "confidence_inputs": {
            "scanner_type": "oversold_bounce",
            "rsi_2": indicators.get("rsi_2"),
            "rsi_5": indicators.get("rsi_5"),
            "vol_ma_3": indicators.get("vol_ma_3"),
            "relative_volume": indicators.get("relative_volume"),
            "avg_liquidity_5d": indicators.get("avg_liquidity_5d"),
            "gap_pct": indicators.get("gap_pct"),
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


def _pocket_pivot_criteria(
    indicators: Dict[str, Any],
) -> Dict[str, Dict[str, Any]]:
    return {
        "up_day": _criterion(
            "Up day",
            _pct(indicators.get("up_day_pct")),
            0,
            ">=",
            unit="%",
            source="daily_aggregates",
            importance=0.7,
        ),
        "volume_over_max_down": _criterion(
            "Volume exceeds highest down-day volume",
            indicators.get("today_volume"),
            indicators.get("max_down_day_vol"),
            ">",
            unit="shares",
            source="daily_aggregates",
            lookback=f"{indicators.get('lookback_days_available', 'n/a')}d",
            importance=1.0,
        ),
        "price_floor": _criterion(
            "Price floor",
            indicators.get("today_close"),
            indicators.get("price_floor", 5.0),
            ">=",
            unit="$",
            source="daily_aggregates",
            importance=0.5,
        ),
        "volume_floor": _criterion(
            "Volume floor",
            indicators.get("today_volume"),
            indicators.get("volume_floor", 100000),
            ">=",
            unit="shares",
            source="daily_aggregates",
            importance=0.5,
        ),
    }


def build_pocket_pivot_explanation(
    indicators: Dict[str, Any],
    criteria_met: Dict[str, Any],
    gate_metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    criteria = _pocket_pivot_criteria(indicators)
    passed, failed = _split_criteria(criteria_met, criteria, "pocket_pivot")

    why = ["Daily volume exceeded the highest down-day volume in the lookback."]
    if (
        indicators.get("today_volume") is not None
        and indicators.get("max_down_day_vol") is not None
    ):
        why[0] = (
            f"Volume was {int(indicators['today_volume']):,} shares versus "
            f"{int(indicators['max_down_day_vol']):,} on the highest down day."
        )
    if indicators.get("up_day_pct") is not None:
        why.append(f"Close was {_pct(indicators['up_day_pct']):.2f}% above prior close.")

    payload = {
        "schema_version": "scanner_explanation.v1",
        "why": why,
        "criteria_passed": passed,
        "criteria_failed": failed,
        "confidence_inputs": {
            "scanner_type": "pocket_pivot",
            "today_volume": indicators.get("today_volume"),
            "max_down_day_vol": indicators.get("max_down_day_vol"),
            "volume_over_max_down_pct": indicators.get("volume_over_max_down_pct"),
            "down_days_in_lookback": indicators.get("down_days_in_lookback"),
            "lookback_days_available": indicators.get("lookback_days_available"),
            "split_in_lookback": indicators.get("split_in_lookback"),
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


def _trend_pullback_criteria(
    indicators: Dict[str, Any],
) -> Dict[str, Dict[str, Any]]:
    return {
        "uptrend": _criterion(
            "SMA trend structure",
            {
                "close": indicators.get("close"),
                "sma50": indicators.get("sma50"),
                "sma200": indicators.get("sma200"),
            },
            "close > SMA50 > SMA200 and SMA50 rising",
            "==",
            source="daily_aggregates",
            lookback="200d",
            importance=1.0,
        ),
        "near_high": _criterion(
            "Near 252-day high",
            indicators.get("pct_off_252d_high"),
            15,
            "<=",
            unit="%",
            source="daily_aggregates",
            lookback="252d",
            importance=0.7,
        ),
        "pullback_in_progress": _criterion(
            "SMA20 pullback tag",
            {
                "low_near_sma20": indicators.get("sma20"),
                "consecutive_days_above_sma20": indicators.get(
                    "consecutive_days_above_sma20"
                ),
            },
            "low within configured SMA20 tolerance after prior closes above SMA20",
            "==",
            source="daily_aggregates",
            lookback="60d",
            importance=0.9,
        ),
        "orderly_pullback": _criterion(
            "Orderly pullback depth",
            indicators.get("pullback_depth_pct"),
            "configured depth range with no SMA50 breakdown",
            "==",
            unit="%",
            source="daily_aggregates",
            lookback="20d",
            importance=1.0,
        ),
        "rsi_reset": _criterion(
            "RSI-5 reset",
            indicators.get("rsi5"),
            40,
            "<",
            source="daily_aggregates",
            lookback="5d",
            importance=0.8,
        ),
        "liquidity": _criterion(
            "Dollar-volume liquidity floor",
            indicators.get("avg_dollar_vol_20d"),
            5_000_000,
            ">=",
            unit="$",
            source="daily_aggregates",
            lookback="20d",
            importance=0.6,
        ),
    }


def build_trend_pullback_explanation(
    indicators: Dict[str, Any],
    criteria_met: Dict[str, Any],
    gate_metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    criteria = _trend_pullback_criteria(indicators)
    passed, failed = _split_criteria(criteria_met, criteria, "trend_pullback")

    why = ["Trend pullback criteria were met."]
    if indicators.get("pullback_depth_pct") is not None:
        why[0] = (
            f"Pullback depth was {float(indicators['pullback_depth_pct']):.2f}% "
            "from the recent swing high."
        )
    if indicators.get("rsi5") is not None:
        why.append(f"RSI-5 reset to {float(indicators['rsi5']):.2f}.")
    if indicators.get("atr14") is not None:
        why.append(f"ATR-14 was {float(indicators['atr14']):.2f}.")

    payload = {
        "schema_version": "scanner_explanation.v1",
        "why": why,
        "criteria_passed": passed,
        "criteria_failed": failed,
        "confidence_inputs": {
            "scanner_type": "trend_pullback",
            "close": indicators.get("close"),
            "sma20": indicators.get("sma20"),
            "sma50": indicators.get("sma50"),
            "sma200": indicators.get("sma200"),
            "rsi5": indicators.get("rsi5"),
            "pct_off_252d_high": indicators.get("pct_off_252d_high"),
            "pullback_depth_pct": indicators.get("pullback_depth_pct"),
            "consecutive_days_above_sma20": indicators.get(
                "consecutive_days_above_sma20"
            ),
            "atr14": indicators.get("atr14"),
            "avg_dollar_vol_20d": indicators.get("avg_dollar_vol_20d"),
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
    elif event.scanner_type == "oversold_bounce":
        criteria = _oversold_bounce_criteria(indicators)
        passed, failed = _split_criteria(criteria_met, criteria, "oversold_bounce")
    elif event.scanner_type == "pocket_pivot":
        criteria = _pocket_pivot_criteria(indicators)
        passed, failed = _split_criteria(criteria_met, criteria, "pocket_pivot")
    elif event.scanner_type == "trend_pullback":
        criteria = _trend_pullback_criteria(indicators)
        passed, failed = _split_criteria(criteria_met, criteria, "trend_pullback")
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
