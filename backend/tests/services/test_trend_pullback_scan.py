"""Unit tests for the trend_pullback scanner — 15 scenarios."""

import asyncio
from datetime import date
from typing import Any
from unittest.mock import MagicMock, patch

_EVENT_DATE = date(2026, 1, 15)
_TICKERS = ["AAPL"]


def _bar(
    close: float,
    high: float | None = None,
    low: float | None = None,
    volume: int = 1_000_000,
) -> MagicMock:
    b = MagicMock()
    b.close = close
    b.open = close * 0.99
    b.high = high if high is not None else close * 1.01
    b.low = low if low is not None else close * 0.99
    b.volume = volume
    return b


def _uptrend_bars(n: int = 260, base: float = 100.0) -> list[MagicMock]:
    """
    Build n bars in a smooth uptrend: close rises from base to base*1.3.
    Volume is 2M each bar so avg dollar volume = ~200M >> 5M.
    SMA200 < SMA50 < close by construction.
    """
    bars = []
    for i in range(n):
        c = base + (base * 0.3) * (i / (n - 1))
        bars.append(_bar(c, high=c * 1.015, low=c * 0.985, volume=2_000_000))
    return bars


def _run_scan(
    bars_fn,
    config: dict | None = None,
    tickers: list[str] = _TICKERS,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Run trend_pullback scan with mocked _get_daily_bars and _save_event."""
    from app.services.trend_pullback_scan import run_trend_pullback_scan

    diagnostics: dict[str, Any] = {}
    save_return = {"ticker": tickers[0]}

    with (
        patch("app.services.trend_pullback_scan._get_daily_bars", side_effect=bars_fn),
        patch(
            "app.services.trend_pullback_scan._save_event", return_value=save_return
        ) as mock_save,
        patch("app.services.trend_pullback_scan.scanner_events_total"),
    ):
        results = asyncio.run(
            run_trend_pullback_scan(
                tickers,
                db=MagicMock(),
                start_date=_EVENT_DATE,
                end_date=_EVENT_DATE,
                config=config,
                diagnostics_out=diagnostics,
            )
        )
    return results, diagnostics, mock_save


# ---------------------------------------------------------------------------
# Helper: build a pullback scenario on top of an uptrend base
# ---------------------------------------------------------------------------


def _pullback_bars(
    n: int = 260,
    base: float = 50.0,
    pullback_depth_pct: float = 6.0,
    consecutive_above: int = 10,
    final_low_pct: float = 0.5,  # final bar's low as % of SMA20 (≤1.01 to tag SMA20)
) -> list[MagicMock]:
    """
    Build bars that satisfy all trend_pullback criteria:
    - Smooth uptrend so SMA200 < SMA50 < close
    - SMA50 rising (today > 20 days ago)
    - Last `consecutive_above` bars have close > SMA20, then today tags SMA20
    - pullback_depth from swing high
    - RSI5 ends low (we simulate via a sharp down move on the last bar)
    """
    bars = []
    trend_end_price = base * 1.4  # swing high region
    for i in range(n - consecutive_above - 1):
        c = base + (trend_end_price - base) * (i / (n - consecutive_above - 2))
        bars.append(_bar(c, volume=2_000_000))

    swing_high = trend_end_price
    for j in range(consecutive_above):
        c = swing_high * (1 - 0.002 * j)  # gentle decline above SMA20
        bars.append(_bar(c, volume=2_000_000))

    # Final bar: close is pullback_depth_pct below swing_high
    pullback_close = swing_high * (1 - pullback_depth_pct / 100)
    # Low tags SMA20 — approximate SMA20 as close of bar at position (n-21)
    last_bar_low = pullback_close * (1 - final_low_pct / 100)
    bars.append(
        _bar(
            pullback_close,
            low=last_bar_low,
            high=pullback_close * 1.005,
            volume=500_000,
        )
    )

    return bars


# ---------------------------------------------------------------------------
# Scenario 1: Module import
# ---------------------------------------------------------------------------
def test_module_importable():
    from app.services.trend_pullback_scan import run_trend_pullback_scan

    assert callable(run_trend_pullback_scan)


# ---------------------------------------------------------------------------
# Scenario 2: Orchestrator self-registration
# ---------------------------------------------------------------------------
def test_orchestrator_registration():
    import app.services.trend_pullback_scan  # noqa: F401 — triggers registration
    from app.services.scan_orchestrator import _REGISTRY

    assert "trend_pullback" in _REGISTRY


# ---------------------------------------------------------------------------
# Scenario 3: No bars — counted in no_bars
# ---------------------------------------------------------------------------
def test_no_bars_skipped():
    results, diag, _ = _run_scan(lambda db, t, d, lb: [])
    assert results == []
    assert diag["no_bars"] == 1


# ---------------------------------------------------------------------------
# Scenario 4: Insufficient history (< SMA200 + 10) — insufficient_history
# ---------------------------------------------------------------------------
def test_insufficient_history_skipped():
    short = [_bar(100.0)] * 50  # well below 210 bars needed
    results, diag, _ = _run_scan(lambda db, t, d, lb: short)
    assert results == []
    assert diag["insufficient_history"] == 1


# ---------------------------------------------------------------------------
# Scenario 5: Downtrend — close < SMA50 — does not fire
# ---------------------------------------------------------------------------
def test_downtrend_does_not_fire():
    bars = []
    # Descending close so SMA50 > close
    for i in range(260):
        c = 200.0 - i * 0.5  # falling from 200 to 70
        bars.append(_bar(c, volume=2_000_000))
    results, diag, _ = _run_scan(lambda db, t, d, lb: bars)
    assert results == []
    assert diag["evaluated"] == 1
    assert diag["fired"] == 0


# ---------------------------------------------------------------------------
# Scenario 6: Below price floor ($4) — does not fire
# ---------------------------------------------------------------------------
def test_below_price_floor_does_not_fire():
    # Use uptrend bars but override final close to be below $5
    bars = _uptrend_bars(260, base=3.0)
    results, diag, _ = _run_scan(lambda db, t, d, lb: bars)
    assert results == []
    assert diag["fired"] == 0


# ---------------------------------------------------------------------------
# Scenario 7: RSI5 too high (≥40) — does not fire
# ---------------------------------------------------------------------------
def test_high_rsi_does_not_fire():
    # Steady uptrend with no meaningful down moves -> RSI5 stays high
    bars = _uptrend_bars(260, base=50.0)
    # All bars up, RSI5 will be near 100
    results, diag, _ = _run_scan(lambda db, t, d, lb: bars)
    assert results == []
    assert diag["fired"] == 0


# ---------------------------------------------------------------------------
# Scenario 8: Not near highs (>15% off 252d high) — does not fire
# ---------------------------------------------------------------------------
def test_too_far_from_high_does_not_fire():
    bars = _uptrend_bars(260, base=50.0)
    # Override last bar to be 20% below the 252d high
    peak = float(bars[-1].close) * 1.25
    for i in range(-20, 0):
        bars[i].close = peak
        bars[i].high = peak * 1.01
        bars[i].low = peak * 0.99
    # Final bar sits at peak * 0.78 (22% off)
    bars[-1].close = peak * 0.78
    bars[-1].high = peak * 0.79
    bars[-1].low = peak * 0.77
    results, diag, _ = _run_scan(lambda db, t, d, lb: bars)
    assert results == []
    assert diag["fired"] == 0


# ---------------------------------------------------------------------------
# Scenario 9: Pullback too deep (>12%) — does not fire
# ---------------------------------------------------------------------------
def test_pullback_too_deep_does_not_fire():
    bars = _pullback_bars(260, base=50.0, pullback_depth_pct=15.0, consecutive_above=10)
    results, diag, _ = _run_scan(lambda db, t, d, lb: bars)
    assert results == []
    assert diag["fired"] == 0


# ---------------------------------------------------------------------------
# Scenario 10: Pullback too shallow (<3%) — does not fire
# ---------------------------------------------------------------------------
def test_pullback_too_shallow_does_not_fire():
    bars = _pullback_bars(260, base=50.0, pullback_depth_pct=1.0, consecutive_above=10)
    results, diag, _ = _run_scan(lambda db, t, d, lb: bars)
    assert results == []
    assert diag["fired"] == 0


# ---------------------------------------------------------------------------
# Scenario 11: Low dollar volume — does not fire
# ---------------------------------------------------------------------------
def test_low_dollar_volume_does_not_fire():
    # Close ~$50, volume 10K -> dollar vol = $500K, well below $5M
    bars = _uptrend_bars(260, base=50.0)
    for b in bars:
        b.volume = 10_000
    results, diag, _ = _run_scan(lambda db, t, d, lb: bars)
    assert results == []
    assert diag["fired"] == 0


# ---------------------------------------------------------------------------
# Scenario 12: diagnostics populated for 3 tickers
# ---------------------------------------------------------------------------
def test_diagnostics_populated():
    from app.services.trend_pullback_scan import run_trend_pullback_scan

    tickers = ["AAPL", "MSFT", "GOOG"]
    diagnostics: dict[str, Any] = {}

    with (
        patch("app.services.trend_pullback_scan._get_daily_bars", return_value=[]),
        patch("app.services.trend_pullback_scan._save_event"),
        patch("app.services.trend_pullback_scan.scanner_events_total"),
    ):
        asyncio.run(
            run_trend_pullback_scan(
                tickers,
                db=MagicMock(),
                start_date=_EVENT_DATE,
                end_date=_EVENT_DATE,
                diagnostics_out=diagnostics,
            )
        )

    assert diagnostics["tickers"] == 3
    assert diagnostics["days"] == 1
    assert diagnostics["no_bars"] == 3


# ---------------------------------------------------------------------------
# Scenario 13: run_trend_pullback_scan_for_date wrapper
# ---------------------------------------------------------------------------
def test_scan_for_date_wrapper():
    from app.services.trend_pullback_scan import run_trend_pullback_scan_for_date

    with (
        patch("app.services.trend_pullback_scan._get_daily_bars", return_value=[]),
        patch("app.services.trend_pullback_scan.scanner_events_total"),
    ):
        result = asyncio.run(
            run_trend_pullback_scan_for_date("AAPL", _EVENT_DATE, MagicMock())
        )
    assert result == []


# ---------------------------------------------------------------------------
# Scenario 14: severity high when depth ≤8% and RSI5 <30
# ---------------------------------------------------------------------------
def test_severity_high_when_shallow_and_rsi_very_low():
    from app.services.event_helpers import compute_event_severity

    ind = {"pullback_depth_pct": 6.0, "rsi5": 25.0}
    assert compute_event_severity("trend_pullback", ind) == "high"


# ---------------------------------------------------------------------------
# Scenario 15: severity medium when depth >8% or RSI5 ≥30
# ---------------------------------------------------------------------------
def test_severity_medium_otherwise():
    from app.services.event_helpers import compute_event_severity

    assert (
        compute_event_severity(
            "trend_pullback", {"pullback_depth_pct": 10.0, "rsi5": 25.0}
        )
        == "medium"
    )
    assert (
        compute_event_severity(
            "trend_pullback", {"pullback_depth_pct": 6.0, "rsi5": 35.0}
        )
        == "medium"
    )
    assert (
        compute_event_severity(
            "trend_pullback", {"pullback_depth_pct": 10.0, "rsi5": 35.0}
        )
        == "medium"
    )


def test_trend_pullback_observes_slo_metrics():
    """scan_last_success_timestamp and scan_failed_tickers_ratio are set after a run."""
    import asyncio
    import time
    from unittest.mock import MagicMock, patch

    with (
        patch("app.services.trend_pullback_scan.scanner_events_total"),
        patch("app.services.trend_pullback_scan.scan_duration_seconds"),
        patch(
            "app.services.trend_pullback_scan.scan_last_success_timestamp"
        ) as mock_ts,
        patch(
            "app.services.trend_pullback_scan.scan_failed_tickers_ratio"
        ) as mock_ratio,
        patch("app.services.trend_pullback_scan._get_daily_bars", return_value=[]),
    ):
        mock_ts_lbl = MagicMock()
        mock_ts.labels.return_value = mock_ts_lbl
        mock_ratio_lbl = MagicMock()
        mock_ratio.labels.return_value = mock_ratio_lbl

        from app.services.trend_pullback_scan import run_trend_pullback_scan

        asyncio.run(
            run_trend_pullback_scan(
                [], db=MagicMock(), start_date=_EVENT_DATE, end_date=_EVENT_DATE
            )
        )

    mock_ts.labels.assert_called_with(scanner_type="trend_pullback")
    mock_ts_lbl.set.assert_called_once()
    assert abs(mock_ts_lbl.set.call_args[0][0] - time.time()) < 30
    mock_ratio.labels.assert_called_with(scanner_type="trend_pullback")
    mock_ratio_lbl.set.assert_called_once()
    assert 0.0 <= mock_ratio_lbl.set.call_args[0][0] <= 1.0


def test_trend_pullback_total_failure_does_not_mark_success():
    """Every ticker-day errors -> no last-success bump; duration still observed."""
    with (
        patch(
            "app.services.trend_pullback_scan._get_daily_bars",
            side_effect=RuntimeError("boom"),
        ),
        patch("app.services.trend_pullback_scan.scanner_events_total"),
        patch("app.services.trend_pullback_scan.scan_duration_seconds") as mock_dur,
        patch(
            "app.services.trend_pullback_scan.scan_last_success_timestamp"
        ) as mock_ts,
        patch(
            "app.services.trend_pullback_scan.scan_failed_tickers_ratio"
        ) as mock_ratio,
    ):
        mock_ts_lbl = MagicMock()
        mock_ts.labels.return_value = mock_ts_lbl
        mock_ratio.labels.return_value = MagicMock()
        mock_dur_lbl = MagicMock()
        mock_dur.labels.return_value = mock_dur_lbl

        from app.services.trend_pullback_scan import run_trend_pullback_scan

        asyncio.run(
            run_trend_pullback_scan(
                ["AAA"], db=MagicMock(), start_date=_EVENT_DATE, end_date=_EVENT_DATE
            )
        )

    mock_ts_lbl.set.assert_not_called()
    mock_dur_lbl.observe.assert_called_once()
