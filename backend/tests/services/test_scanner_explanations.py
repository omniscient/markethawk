from datetime import date, datetime

from app.models.scanner_event import ScannerEvent
from app.services.pre_market_scan import EnrichedSignal, RawSignal
from app.services.scanner_explanations import (
    build_liquidity_hunt_explanation,
    build_live_price_move_explanation,
    build_live_volume_spike_explanation,
    build_oversold_bounce_explanation,
    build_pocket_pivot_explanation,
    build_pre_market_volume_explanation,
    build_social_callout_explanation,
    build_trend_pullback_explanation,
    reconstruct_explanation_for_event,
)


def _raw_signal(criteria_met=None):
    return RawSignal(
        ticker="AAPL",
        daily_bars=[],
        pre_market_volume=650000,
        volumes=[1000000] * 20,
        closes=[100.0] * 20,
        avg_volume_20d=125000,
        avg_volume_50d=None,
        previous_close=100.0,
        relative_volume=5.2,
        forecast={"p50": 100000, "p90": 350000},
        anomaly_score=2.4,
        threshold_method="timesfm",
        criteria_met=criteria_met
        or {"volume_spike": True, "minimum_volume": True, "liquidity": False},
    )


def _enriched_signal(criteria_met=None):
    return EnrichedSignal(
        raw=_raw_signal(criteria_met=criteria_met),
        day_metrics={"opening_price": 104.0, "closing_price": 106.0},
        indicators={
            "pre_market_volume": 650000,
            "avg_volume_20d": 125000,
            "relative_volume": 5.2,
            "volume_spike_ratio": 5.2,
            "volume_anomaly_score": 2.4,
            "volume_threshold_method": "timesfm",
            "gap_pct": 4.0,
            "has_news_catalyst": True,
        },
        enrichment={"quality_warnings": []},
    )


def test_build_pre_market_volume_explanation_splits_passed_and_failed_criteria():
    explanation = build_pre_market_volume_explanation(
        _enriched_signal(),
        signal_quality_score=88.0,
        gate_metadata={
            "tier": "warning",
            "warnings": [
                {
                    "code": "stale_bars",
                    "severity": "warning",
                    "message": "Some bars are stale.",
                }
            ],
        },
    )

    assert explanation["schema_version"] == "scanner_explanation.v1"
    assert "premarket.volume_spike" in explanation["criteria_passed"]
    assert "premarket.liquidity" in explanation["criteria_failed"]
    assert explanation["confidence_inputs"]["signal_quality_score"] == 88.0
    assert explanation["data_quality_warnings"][0]["severity"] == "medium"
    assert explanation["evidence"]["reconstructed"] is False


def test_build_liquidity_hunt_explanation_splits_variant_criteria():
    indicators = {
        "session": "pre",
        "session_volume": 350000,
        "avg_session_volume_20d": 35000,
        "session_volume_ratio": 10.0,
        "session_volume_pct_of_daily": 0.35,
        "session_high": 12.11,
        "reference_close": 11.0,
        "session_spike_pct": 0.1009,
        "regular_volume_ratio": 0.9474,
        "regular_range_ratio": 1.3575,
        "float_rotation_pct": 0.7,
    }
    criteria_met = {
        "volume_ratio": True,
        "volume_materiality": True,
        "session_spike": True,
        "quiet_regular_vol": True,
        "quiet_regular_range": False,
        "volume_floor": True,
    }

    explanation = build_liquidity_hunt_explanation(
        scanner_type="liquidity_hunt_pre",
        indicators=indicators,
        criteria_met=criteria_met,
        gate_metadata={
            "tier": "warning",
            "warnings": [
                {
                    "code": "provider_gaps",
                    "severity": "warning",
                    "message": "Provider gaps were detected.",
                }
            ],
        },
    )

    assert explanation["schema_version"] == "scanner_explanation.v1"
    assert "liquidity_hunt_pre.volume_ratio" in explanation["criteria_passed"]
    assert "liquidity_hunt_pre.quiet_regular_range" in explanation["criteria_failed"]
    assert explanation["confidence_inputs"]["session"] == "pre"
    assert explanation["data_quality_warnings"][0]["severity"] == "medium"
    assert explanation["evidence"]["reconstructed"] is False


def test_build_oversold_bounce_explanation_uses_named_criteria():
    indicators = {
        "rsi_2": 21.4,
        "rsi_5": 31.2,
        "vol_ma_3": 800000,
        "avg_liquidity_5d": 42_000_000,
        "gap_pct": 0.0,
        "relative_volume": 1.25,
    }
    criteria_met = {
        "volume_ma_3_ok": True,
        "price_ge_5": True,
        "rsi_2_crossed": True,
        "rsi_5_crossed": True,
        "no_gap_down": True,
    }

    explanation = build_oversold_bounce_explanation(
        indicators=indicators,
        criteria_met=criteria_met,
    )

    assert explanation["schema_version"] == "scanner_explanation.v1"
    assert "oversold_bounce.rsi_2_crossed" in explanation["criteria_passed"]
    assert explanation["criteria_passed"]["oversold_bounce.rsi_2_crossed"]["label"] == "RSI-2 recovery cross"
    assert explanation["confidence_inputs"]["rsi_2"] == 21.4
    assert explanation["evidence"]["reconstructed"] is False


def test_build_pocket_pivot_explanation_uses_named_criteria():
    indicators = {
        "today_close": 14.72,
        "prior_close": 14.15,
        "up_day_pct": 0.0403,
        "today_volume": 350000,
        "max_down_day_vol": 280000,
        "volume_over_max_down_pct": 0.25,
        "down_days_in_lookback": 4,
        "lookback_days_available": 10,
        "volume_floor": 100000,
        "price_floor": 5.0,
    }
    criteria_met = {
        "up_day": True,
        "volume_over_max_down": True,
        "price_floor": True,
        "volume_floor": True,
    }

    explanation = build_pocket_pivot_explanation(
        indicators=indicators,
        criteria_met=criteria_met,
    )

    assert explanation["schema_version"] == "scanner_explanation.v1"
    assert "pocket_pivot.volume_over_max_down" in explanation["criteria_passed"]
    assert (
        explanation["criteria_passed"]["pocket_pivot.volume_over_max_down"]["label"]
        == "Volume exceeds highest down-day volume"
    )
    assert explanation["confidence_inputs"]["down_days_in_lookback"] == 4
    assert explanation["evidence"]["reconstructed"] is False


def test_build_trend_pullback_explanation_uses_named_criteria():
    indicators = {
        "close": 65.8,
        "sma20": 66.1,
        "sma50": 63.4,
        "sma200": 51.9,
        "rsi5": 28.5,
        "pct_off_252d_high": 7.2,
        "pullback_depth_pct": 6.4,
        "consecutive_days_above_sma20": 9,
        "atr14": 1.37,
        "avg_dollar_vol_20d": 18_000_000,
    }
    criteria_met = {
        "uptrend": True,
        "near_high": True,
        "pullback_in_progress": True,
        "orderly_pullback": True,
        "rsi_reset": True,
        "liquidity": True,
    }

    explanation = build_trend_pullback_explanation(
        indicators=indicators,
        criteria_met=criteria_met,
    )

    assert explanation["schema_version"] == "scanner_explanation.v1"
    assert "trend_pullback.uptrend" in explanation["criteria_passed"]
    assert "trend_pullback.orderly_pullback" in explanation["criteria_passed"]
    assert (
        explanation["criteria_passed"]["trend_pullback.uptrend"]["label"]
        == "SMA trend structure"
    )
    assert explanation["confidence_inputs"]["atr14"] == 1.37
    assert explanation["evidence"]["reconstructed"] is False


def test_build_live_volume_spike_explanation_uses_named_criteria():
    indicators = {
        "volume_spike_ratio": 6.4,
        "session_volume": 128000,
        "avg_daily_volume": 500000,
        "projected_volume": 3200000,
        "minutes_elapsed": 12.0,
        "session": "regular",
    }
    criteria_met = {"volume_spike_4x": True, "sufficient_avg_volume": True}

    explanation = build_live_volume_spike_explanation(
        indicators=indicators,
        criteria_met=criteria_met,
    )

    assert explanation["schema_version"] == "scanner_explanation.v1"
    assert "live_volume_spike.volume_spike_4x" in explanation["criteria_passed"]
    assert (
        explanation["criteria_passed"]["live_volume_spike.volume_spike_4x"]["label"]
        == "Projected volume spike"
    )
    assert explanation["confidence_inputs"]["session"] == "regular"
    assert explanation["evidence"]["provider"] == "live_scanner"


def test_build_live_price_move_explanation_uses_named_criteria():
    indicators = {
        "price_move_pct": -3.25,
        "current_price": 96.75,
        "prior_close": 100.0,
        "session": "pre",
    }
    criteria_met = {"price_move_1pct": True}

    explanation = build_live_price_move_explanation(
        indicators=indicators,
        criteria_met=criteria_met,
    )

    assert explanation["schema_version"] == "scanner_explanation.v1"
    assert "live_price_move.price_move_1pct" in explanation["criteria_passed"]
    assert (
        explanation["criteria_passed"]["live_price_move.price_move_1pct"]["label"]
        == "Live price move"
    )
    assert explanation["confidence_inputs"]["price_move_pct"] == -3.25
    assert explanation["evidence"]["provider"] == "live_scanner"


def test_build_social_callout_explanation_uses_tweet_facts():
    indicators = {
        "confidence": 0.92,
        "source_account": "market_pro",
        "direction": "long",
        "price_entry": 185.0,
        "price_target": 195.0,
        "tweet_id": "12345",
    }
    criteria_met = {
        "has_cashtag": True,
        "has_price_level": True,
        "above_confidence_threshold": True,
    }

    explanation = build_social_callout_explanation(
        indicators=indicators,
        criteria_met=criteria_met,
    )

    assert explanation["schema_version"] == "scanner_explanation.v1"
    assert "social_callout.above_confidence_threshold" in explanation["criteria_passed"]
    assert (
        explanation["criteria_passed"]["social_callout.above_confidence_threshold"][
            "label"
        ]
        == "Classifier confidence"
    )
    assert explanation["confidence_inputs"]["tweet_id"] == "12345"
    assert explanation["evidence"]["provider"] == "tweet_monitor"


def test_reconstruct_explanation_for_existing_event_marks_best_effort():
    event = ScannerEvent(
        ticker="AAPL",
        event_date=date(2026, 6, 2),
        scanner_type="pre_market_volume_spike",
        indicators={
            "pre_market_volume": 650000,
            "avg_volume_20d": 125000,
            "relative_volume": 5.2,
            "volume_spike_ratio": 5.2,
        },
        criteria_met={"volume_spike": True, "liquidity": True},
        metadata_={"quality_gate": {"tier": "trusted", "warnings": []}},
        signal_quality_score=81.0,
        created_at=datetime(2026, 6, 2),
        updated_at=datetime(2026, 6, 2),
    )

    explanation = reconstruct_explanation_for_event(event)

    assert explanation["schema_version"] == "scanner_explanation.v1"
    assert explanation["evidence"]["reconstructed"] is True
    assert explanation["evidence"]["reconstruction_quality"] == "best_effort"
    assert explanation["confidence_inputs"]["signal_quality_score"] == 81.0


def test_reconstruct_liquidity_hunt_event_uses_named_criteria():
    event = ScannerEvent(
        ticker="AAPL",
        event_date=date(2026, 6, 2),
        scanner_type="liquidity_hunt_pre",
        indicators={
            "session": "pre",
            "session_volume_ratio": 10.0,
            "session_spike_pct": 0.1009,
            "session_volume_pct_of_daily": 0.35,
        },
        criteria_met={"volume_ratio": True, "quiet_regular_range": False},
        metadata_={"quality_gate": {"tier": "trusted", "warnings": []}},
        created_at=datetime(2026, 6, 2),
        updated_at=datetime(2026, 6, 2),
    )

    explanation = reconstruct_explanation_for_event(event)

    assert "liquidity_hunt_pre.volume_ratio" in explanation["criteria_passed"]
    assert "liquidity_hunt_pre.quiet_regular_range" in explanation["criteria_failed"]
    assert (
        explanation["criteria_passed"]["liquidity_hunt_pre.volume_ratio"]["label"]
        == "Off-hours volume ratio"
    )


def test_reconstruct_oversold_bounce_event_uses_named_criteria():
    event = ScannerEvent(
        ticker="AAPL",
        event_date=date(2026, 6, 2),
        scanner_type="oversold_bounce",
        indicators={"rsi_2": 21.4, "rsi_5": 31.2, "vol_ma_3": 800000},
        criteria_met={"rsi_2_crossed": True, "no_gap_down": True},
        metadata_={},
        created_at=datetime(2026, 6, 2),
        updated_at=datetime(2026, 6, 2),
    )

    explanation = reconstruct_explanation_for_event(event)

    assert "oversold_bounce.rsi_2_crossed" in explanation["criteria_passed"]
    assert (
        explanation["criteria_passed"]["oversold_bounce.rsi_2_crossed"]["label"]
        == "RSI-2 recovery cross"
    )


def test_reconstruct_pocket_pivot_event_uses_named_criteria():
    event = ScannerEvent(
        ticker="AAPL",
        event_date=date(2026, 6, 2),
        scanner_type="pocket_pivot",
        indicators={
            "today_volume": 350000,
            "max_down_day_vol": 280000,
            "volume_over_max_down_pct": 0.25,
        },
        criteria_met={"volume_over_max_down": True, "volume_floor": True},
        metadata_={},
        created_at=datetime(2026, 6, 2),
        updated_at=datetime(2026, 6, 2),
    )

    explanation = reconstruct_explanation_for_event(event)

    assert "pocket_pivot.volume_over_max_down" in explanation["criteria_passed"]
    assert (
        explanation["criteria_passed"]["pocket_pivot.volume_over_max_down"]["label"]
        == "Volume exceeds highest down-day volume"
    )


def test_reconstruct_trend_pullback_event_uses_named_criteria():
    event = ScannerEvent(
        ticker="AAPL",
        event_date=date(2026, 6, 2),
        scanner_type="trend_pullback",
        indicators={
            "close": 65.8,
            "sma20": 66.1,
            "sma50": 63.4,
            "sma200": 51.9,
            "rsi5": 28.5,
            "pullback_depth_pct": 6.4,
            "atr14": 1.37,
            "avg_dollar_vol_20d": 18_000_000,
        },
        criteria_met={"uptrend": True, "orderly_pullback": True, "liquidity": True},
        metadata_={},
        created_at=datetime(2026, 6, 2),
        updated_at=datetime(2026, 6, 2),
    )

    explanation = reconstruct_explanation_for_event(event)

    assert "trend_pullback.uptrend" in explanation["criteria_passed"]
    assert "trend_pullback.orderly_pullback" in explanation["criteria_passed"]
    assert (
        explanation["criteria_passed"]["trend_pullback.orderly_pullback"]["label"]
        == "Orderly pullback depth"
    )


def test_reconstruct_live_and_social_events_use_named_criteria():
    live_event = ScannerEvent(
        ticker="AAPL",
        event_date=date(2026, 6, 2),
        scanner_type="live_price_move",
        indicators={
            "price_move_pct": 2.4,
            "current_price": 102.4,
            "prior_close": 100.0,
            "session": "regular",
        },
        criteria_met={"price_move_1pct": True},
        metadata_={"source": "live_scanner"},
        created_at=datetime(2026, 6, 2),
        updated_at=datetime(2026, 6, 2),
    )
    social_event = ScannerEvent(
        ticker="AAPL",
        event_date=date(2026, 6, 2),
        scanner_type="social_callout",
        indicators={
            "confidence": 0.88,
            "source_account": "market_pro",
            "direction": "long",
            "tweet_id": "12345",
        },
        criteria_met={"above_confidence_threshold": True},
        metadata_={"source": "tweet_monitor"},
        created_at=datetime(2026, 6, 2),
        updated_at=datetime(2026, 6, 2),
    )

    live_explanation = reconstruct_explanation_for_event(live_event)
    social_explanation = reconstruct_explanation_for_event(social_event)

    assert "live_price_move.price_move_1pct" in live_explanation["criteria_passed"]
    assert "social_callout.above_confidence_threshold" in social_explanation[
        "criteria_passed"
    ]
