"""Tests for benchmark daily-bar gap-fill ingestion."""

from datetime import date, datetime, timezone
from unittest.mock import MagicMock

import pytest

from app.exceptions import ProviderError


def _provider(bars=None):
    provider = MagicMock()
    provider.get_bars.return_value = bars if bars is not None else []
    return provider


def _db(existing_timestamps=None):
    db = MagicMock()
    db.query.return_value.filter.return_value.all.return_value = [
        (ts,) for ts in (existing_timestamps or [])
    ]
    return db


def _bar(day: date, close: float = 500.0):
    return {
        "timestamp": datetime(day.year, day.month, day.day, tzinfo=timezone.utc),
        "open": close - 1,
        "high": close + 2,
        "low": close - 2,
        "close": close,
        "volume": 10_000_000,
        "vwap": close,
        "transactions": 100_000,
    }


def test_benchmark_ingestor_inserts_missing_daily_bars():
    from app.services.replay.benchmark import BenchmarkIngestor

    provider = _provider([_bar(date(2026, 1, 5)), _bar(date(2026, 1, 6))])
    db = _db()

    count = BenchmarkIngestor(provider).ingest(
        "SPY", date(2026, 1, 5), date(2026, 1, 6), db
    )

    assert count == 2
    db.bulk_save_objects.assert_called_once()
    db.commit.assert_called_once()


def test_benchmark_ingestor_returns_zero_when_range_is_fully_present():
    from app.services.replay.benchmark import BenchmarkIngestor

    provider = _provider()
    db = _db(
        [
            datetime(2026, 1, 5),
            datetime(2026, 1, 6),
            datetime(2026, 1, 7),
        ]
    )

    count = BenchmarkIngestor(provider).ingest(
        "QQQ", date(2026, 1, 5), date(2026, 1, 7), db
    )

    assert count == 0
    provider.get_bars.assert_not_called()


def test_benchmark_ingestor_detects_interior_gaps():
    from app.services.replay.benchmark import BenchmarkIngestor

    provider = _provider([_bar(date(2026, 1, 6)), _bar(date(2026, 1, 7))])
    db = _db([datetime(2026, 1, 5), datetime(2026, 1, 8)])

    count = BenchmarkIngestor(provider).ingest(
        "SPY", date(2026, 1, 5), date(2026, 1, 8), db
    )

    assert count == 2
    assert provider.get_bars.call_args.kwargs["from_date"] == "2026-01-06"
    assert provider.get_bars.call_args.kwargs["to_date"] == "2026-01-07"


def test_benchmark_ingestor_wraps_provider_errors():
    from app.services.replay.benchmark import (
        BenchmarkIngestionError,
        BenchmarkIngestor,
    )

    provider = MagicMock()
    provider.get_bars.side_effect = ProviderError(
        "down", provider="polygon", endpoint="get_bars", is_retryable=True
    )

    with pytest.raises(BenchmarkIngestionError, match="SPY") as exc:
        BenchmarkIngestor(provider).ingest(
            "SPY", date(2026, 1, 5), date(2026, 1, 6), _db()
        )

    assert exc.value.symbol == "SPY"
