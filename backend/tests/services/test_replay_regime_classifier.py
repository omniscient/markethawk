"""Tests for deterministic replay benchmark regime classification."""

from datetime import date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


def _rows(closes: list[float], start: date = date(2025, 1, 1)):
    rows = []
    day = start
    for close in closes:
        while day.weekday() >= 5:
            day += timedelta(days=1)
        rows.append(SimpleNamespace(timestamp=datetime(day.year, day.month, day.day), close=Decimal(str(close))))
        day += timedelta(days=1)
    return rows


def _db_with_rows(rows):
    db = MagicMock()
    db.query.return_value.filter.return_value.order_by.return_value.all.return_value = rows
    return db


def test_regime_classifier_labels_bull_and_bear_by_sma200():
    from app.services.replay.classifier import RegimeClassifier

    rows = _rows([100.0] * 200 + [101.0, 99.0])
    bull_day = rows[-2].timestamp.date()
    bear_day = rows[-1].timestamp.date()
    classifier = RegimeClassifier("SPY")
    classifier.classify(bull_day, bear_day, _db_with_rows(rows))

    assert classifier.regime_map[bull_day].trend == "bull"
    assert classifier.regime_map[bear_day].trend == "bear"


def test_regime_classifier_unknown_trend_before_warmup():
    from app.services.replay.classifier import RegimeClassifier

    rows = _rows([100.0] * 20)
    day = rows[-1].timestamp.date()
    classifier = RegimeClassifier("SPY")
    classifier.classify(day, day, _db_with_rows(rows))

    assert classifier.regime_map[day].trend == "unknown"


def test_regime_classifier_vol_thresholds_are_overridable():
    from app.services.replay.classifier import RegimeClassifier

    closes = [100.0] * 220 + [100 + ((-1) ** i) * 0.1 for i in range(25)]
    rows = _rows(closes)
    day = rows[-1].timestamp.date()
    classifier = RegimeClassifier(
        "SPY", vol_thresholds={"calm_below": 0.5, "turbulent_above": 0.7}
    )
    classifier.classify(day, day, _db_with_rows(rows))

    assert classifier.regime_map[day].vol == "calm"


def test_regime_classifier_rejects_invalid_thresholds():
    from app.services.replay.classifier import RegimeClassifier

    with pytest.raises(ValueError, match="calm_below"):
        RegimeClassifier(
            "SPY", vol_thresholds={"calm_below": 0.3, "turbulent_above": 0.2}
        )


def test_get_benchmark_regime_carries_forward_non_trading_days():
    from app.services.replay.classifier import (
        RegimeClassifier,
        ReplayRegime,
        get_benchmark_regime,
    )

    classifier = RegimeClassifier.__new__(RegimeClassifier)
    classifier.regime_map = {date(2026, 1, 2): ReplayRegime("bull", "normal")}

    assert get_benchmark_regime(classifier, date(2026, 1, 3)) == ReplayRegime(
        "bull", "normal"
    )
    assert get_benchmark_regime(classifier, date(2025, 12, 31)) == ReplayRegime(
        "unknown", "normal"
    )
