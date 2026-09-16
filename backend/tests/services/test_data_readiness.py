from datetime import date, datetime
from types import SimpleNamespace

from app.models.scanner_config import ScannerConfig
from app.services.data_readiness import DataReadinessService


class _QueryResult:
    def __init__(self, *, first_value=None, rows=None):
        self._first_value = first_value
        self._rows = list(rows or [])

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def first(self):
        return self._first_value

    def all(self):
        return list(self._rows)


class _ReadinessDb:
    def __init__(self, config, row_sets):
        self._config = config
        self._row_sets = list(row_sets)

    def query(self, *entities):
        if len(entities) == 1 and entities[0] is ScannerConfig:
            return _QueryResult(first_value=self._config)
        rows = self._row_sets.pop(0) if self._row_sets else []
        return _QueryResult(rows=rows)


def _config(data_requirements):
    return SimpleNamespace(data_requirements=data_requirements)


def _bar(
    ts: datetime,
    *,
    open=10,
    high=11,
    low=9,
    close=10,
    volume=1000,
):
    return SimpleNamespace(
        timestamp=ts,
        open=open,
        high=high,
        low=low,
        close=close,
        volume=volume,
    )


def test_event_warnings_support_flat_requirements_and_affected_inputs():
    db = _ReadinessDb(
        _config({"timespan": "day", "multiplier": 1, "min_bars": 260}),
        [[_bar(datetime(2026, 6, 1))]],
    )

    warnings = DataReadinessService.event_warnings(
        db,
        ticker="AAPL",
        scanner_type="trend_pullback",
        event_date=date(2026, 6, 2),
    )

    assert [w["code"] for w in warnings] == ["insufficient_lookback"]
    assert warnings[0]["affected_inputs"] == ["daily_aggregates", "close", "volume"]
    assert warnings[0]["detail"]["observed_bars"] == 1
    assert warnings[0]["detail"]["required_bars"] == 260


def test_event_warnings_emit_shared_codes_for_event_quality_failures():
    db = _ReadinessDb(
        _config(
            {
                "timespans": [
                    {
                        "timespan": "minute",
                        "multiplier": 1,
                        "lookback_days": 1,
                        "min_bars": 10,
                    }
                ]
            }
        ),
        [
            [
                _bar(datetime(2026, 6, 1, 9, 30)),
                _bar(datetime(2026, 6, 1, 9, 30)),
                _bar(datetime(2026, 6, 1, 10, 30), high=8),
            ]
        ],
    )

    warnings = DataReadinessService.event_warnings(
        db,
        ticker="AAPL",
        scanner_type="pre_market_volume_spike",
        event_date=date(2026, 6, 2),
    )

    codes = {w["code"] for w in warnings}
    assert {
        "low_coverage",
        "integrity_violation",
        "continuity_gap",
        "stale_data",
        "insufficient_lookback",
    }.issubset(codes)
    assert all("minute_aggregates" in w["affected_inputs"] for w in warnings)


def test_missing_required_timespan_short_circuits_other_timespan_warnings():
    db = _ReadinessDb(
        _config({"timespans": [{"timespan": "minute", "lookback_days": 1}]}),
        [[]],
    )

    warnings = DataReadinessService.event_warnings(
        db,
        ticker="AAPL",
        scanner_type="pre_market_volume_spike",
        event_date=date(2026, 6, 2),
    )

    assert [w["code"] for w in warnings] == ["missing_required_timespan"]


def test_event_warning_metadata_merges_with_existing_quality_gate_metadata():
    metadata = DataReadinessService.event_warning_metadata(
        base_metadata={
            "tier": "warning",
            "schema_version": "quality_gate.v1",
            "warnings": [
                {
                    "code": "provider_gap",
                    "severity": "warning",
                    "message": "Provider gaps were detected.",
                }
            ],
        },
        warnings=[
            {
                "code": "low_coverage",
                "severity": "medium",
                "message": "AAPL minute coverage is below target.",
                "affected_inputs": ["minute_aggregates"],
            }
        ],
    )

    assert metadata["tier"] == "warning"
    assert metadata["schema_version"] == "quality_gate.v1"
    assert [w["code"] for w in metadata["warnings"]] == [
        "provider_gap",
        "low_coverage",
    ]
