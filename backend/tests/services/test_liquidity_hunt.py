"""Unit tests for the liquidity_hunt scanner."""
import pytest
from app.services.liquidity_hunt import _evaluate_criteria, DEFAULT_CONFIG

# Baseline fixture representing a ticker with 20 days of history
BASELINES = {
    "avg_pre_vol_20d": 35_000,
    "avg_post_vol_20d": 30_000,
    "avg_regular_vol_20d": 950_000,
    "avg_total_daily_vol_20d": 1_000_000,
    "avg_regular_range_pct_20d": 0.020,   # 2% average daily range
    "days_available": 20,
}

# Kwargs for a clean "pre" fire — all six criteria satisfied
CLEAN_PRE = dict(
    session="pre",
    session_vol=350_000,    # c1: 350k/35k=10x ≥ 4 ✓  c2: 350k/1M=35% ≥ 30% ✓  c6: >50k ✓
    session_high=12.11,     # c3: (12.11-11.00)/11.00 = 10.09% ≥ 10% ✓
    reference_close=11.00,
    regular_vol=900_000,    # c4: 900k/950k = 0.947 ≤ 1.2 ✓
    regular_high=11.20,
    regular_low=10.90,
    regular_open=11.05,     # c5: (11.20-10.90)/11.05=2.71% → ratio 1.36 ≤ 1.5 ✓
    baselines=BASELINES,
    config=None,
)


def test_pre_variant_fires():
    fires, indicators, criteria = _evaluate_criteria(**CLEAN_PRE)
    assert fires is True
    assert indicators["session"] == "pre"
    assert all(criteria.values()), f"All criteria should be True, got {criteria}"


def test_c2_materiality_fails_when_vol_too_small():
    """200k/1M = 20% < 30% — materiality criterion fails."""
    fires, _, criteria = _evaluate_criteria(
        **{**CLEAN_PRE, "session_vol": 200_000}
    )
    assert fires is False
    assert criteria["volume_materiality"] is False


def test_c3_spike_fails_when_less_than_10_pct():
    """6% spike — does not meet the 10% threshold."""
    fires, _, criteria = _evaluate_criteria(
        **{**CLEAN_PRE, "session_high": 11.66}   # (11.66-11.00)/11.00 = 6%
    )
    assert fires is False
    assert criteria["session_spike"] is False


def test_c4_fails_when_regular_vol_exceeds_threshold():
    """2× regular vol — day was not quiet."""
    fires, _, criteria = _evaluate_criteria(
        **{**CLEAN_PRE, "regular_vol": 2_000_000}  # 2M/950k = 2.1 > 1.2
    )
    assert fires is False
    assert criteria["quiet_regular_vol"] is False


def test_c6_fails_when_below_absolute_floor():
    """40k shares < 50k floor — only c6 fails, all others pass."""
    isolated_baselines = {
        **BASELINES,
        "avg_pre_vol_20d": 1_000,           # 40k/1k = 40x ≥ 4 ✓ (c1 passes)
        "avg_total_daily_vol_20d": 100_000, # 40k/100k = 40% ≥ 30% ✓ (c2 passes)
    }
    fires, _, criteria = _evaluate_criteria(
        **{**CLEAN_PRE, "session_vol": 40_000, "baselines": isolated_baselines}
    )
    assert fires is False
    assert criteria["volume_floor"] is False
    assert criteria["volume_ratio"] is True
    assert criteria["volume_materiality"] is True


def test_c5_fails_when_range_too_wide():
    """Wide intraday range — day was volatile."""
    fires, _, criteria = _evaluate_criteria(
        **{**CLEAN_PRE, "regular_high": 13.50, "regular_low": 8.50}
        # range = (13.50-8.50)/11.05 = 45.2% → ratio = 45.2%/2% = 22.6 > 1.5
    )
    assert fires is False
    assert criteria["quiet_regular_range"] is False


def test_zero_session_baseline_fires_when_floor_and_materiality_pass():
    """avg_pre_vol_20d=0: ratio criterion is trivially satisfied; other checks carry the load."""
    zero_baselines = {
        **BASELINES,
        "avg_pre_vol_20d": 0,
        "avg_total_daily_vol_20d": 200_000,   # 75k/200k = 37.5% ≥ 30%
        "avg_regular_vol_20d": 190_000,
    }
    fires, indicators, criteria = _evaluate_criteria(
        session="pre",
        session_vol=75_000,       # > 50k floor ✓  and 37.5% of daily ✓
        session_high=12.11,
        reference_close=11.00,
        regular_vol=180_000,      # 180k/190k = 0.95 ≤ 1.2 ✓
        regular_high=11.20,
        regular_low=10.90,
        regular_open=11.05,
        baselines=zero_baselines,
        config=None,
    )
    assert fires is True
    assert criteria["volume_ratio"] is True   # trivially satisfied
    assert indicators["session_volume_ratio"] is None  # signals "infinite"


def test_post_variant_fires():
    """After-market variant routes to avg_post_vol_20d (not avg_pre_vol_20d)."""
    # session_vol=130k: 130k/30k=4.33x passes post threshold but 130k/35k=3.71x fails pre
    post_baselines = {
        **BASELINES,
        "avg_total_daily_vol_20d": 400_000,  # 130k/400k=32.5% ≥ 30% ✓
    }
    fires, indicators, criteria = _evaluate_criteria(
        session="post",
        session_vol=130_000,
        session_high=12.11,
        reference_close=11.00,
        regular_vol=900_000,
        regular_high=11.20,
        regular_low=10.90,
        regular_open=11.05,
        baselines=post_baselines,
        config=None,
    )
    assert fires is True
    assert indicators["session"] == "post"
    assert all(criteria.values())


def test_c1_fails_for_post_when_after_market_vol_too_low():
    """Post variant: 60k / 30k = 2x < 4x threshold."""
    fires, _, criteria = _evaluate_criteria(
        session="post",
        session_vol=60_000,       # 60k/30k = 2x < 4 ✗  (also: 60k/1M = 6% < 30%)
        session_high=12.11,
        reference_close=11.00,
        regular_vol=900_000,
        regular_high=11.20,
        regular_low=10.90,
        regular_open=11.05,
        baselines=BASELINES,
        config=None,
    )
    assert fires is False
    assert criteria["volume_ratio"] is False
    assert criteria["volume_materiality"] is False
