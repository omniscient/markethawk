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
    """40k shares < 50k floor."""
    fires, _, criteria = _evaluate_criteria(
        **{**CLEAN_PRE, "session_vol": 40_000}
    )
    assert fires is False
    assert criteria["volume_floor"] is False
