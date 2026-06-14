"""Unit tests for the pocket_pivot scanner — 12 scenarios from spec Section 9."""

import asyncio
from datetime import date
from typing import Any
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_EVENT_DATE = date(2026, 1, 15)  # Thursday
_TICKERS = ["AAPL"]

_EMPTY_ENRICHMENT: dict[str, Any] = {
    "market_cap": None,
    "outstanding_shares": None,
    "recent_split_date": None,
    "catalyst_tags": [],
    "catalyst_summary": None,
}


def _bar(close: float, volume: int = 200_000) -> MagicMock:
    """Create a minimal bar mock (close + volume)."""
    b = MagicMock()
    b.close = close
    b.volume = volume
    return b


def _make_lookback(closes: list[float], volumes: list[int]) -> list[MagicMock]:
    """Build ascending lookback bars from parallel close/volume lists."""
    return [_bar(c, v) for c, v in zip(closes, volumes)]


# 11-bar fixture: bars[0] = context, bars[1..10] = 10 lookback days.
# Down days: bars[2]=280K, bars[4]=240K, bars[6]=260K, bars[9]=200K -> max=280K
_STANDARD_LOOKBACK = _make_lookback(
    closes=[
        10.00,
        10.50,
        10.20,
        10.40,
        10.10,
        10.30,
        10.00,
        10.20,
        10.40,
        10.30,
        10.50,
    ],
    volumes=[
        150_000,
        150_000,
        280_000,
        170_000,
        240_000,
        180_000,
        260_000,
        150_000,
        130_000,
        200_000,
        160_000,
    ],
)


def _run_scan(
    today_bar: dict | None,
    prior_close: float | None,
    lookback_bars: list,
    enrichment: dict | None = None,
    config: dict | None = None,
    tickers: list[str] = _TICKERS,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Run pocket_pivot scan with mocked DB helpers. Returns (results, diagnostics, mock_save)."""
    from app.services.pocket_pivot import run_pocket_pivot_scan

    enrichment = enrichment or _EMPTY_ENRICHMENT
    diagnostics: dict[str, Any] = {}

    save_return = {"ticker": tickers[0]} if today_bar else {}

    with (
        patch("app.services.pocket_pivot._get_today_bar", return_value=today_bar),
        patch("app.services.pocket_pivot._get_prior_close", return_value=prior_close),
        patch(
            "app.services.pocket_pivot._get_lookback_bars", return_value=lookback_bars
        ),
        patch("app.services.pocket_pivot._get_enrichment", return_value=enrichment),
        patch(
            "app.services.pocket_pivot._save_event", return_value=save_return
        ) as mock_save,
        patch("app.services.pocket_pivot.scanner_events_total"),
    ):
        results = asyncio.run(
            run_pocket_pivot_scan(
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
# Scenario 1: Clean pocket pivot — all criteria satisfied
# ---------------------------------------------------------------------------
def test_clean_pocket_pivot_fires():
    today = {"close": 14.72, "volume": 350_000}  # 350K > 280K (max down-day)
    results, diag, mock_save = _run_scan(
        today, prior_close=14.15, lookback_bars=_STANDARD_LOOKBACK
    )
    assert len(results) == 1
    assert diag["fired"] == 1
    indicators = mock_save.call_args.kwargs["indicators"]
    assert indicators["today_close"] == 14.72
    assert indicators["prior_close"] == 14.15
    assert indicators["today_volume"] == 350_000
    assert indicators["max_down_day_vol"] == 280_000
    assert abs(indicators["volume_over_max_down_pct"] - 0.25) < 0.001
    assert indicators["down_days_in_lookback"] == 4
    assert indicators["lookback_days_available"] == 10
    assert indicators["split_in_lookback"] is False
    assert mock_save.call_args.kwargs["scanner_type"] == "pocket_pivot"


# ---------------------------------------------------------------------------
# Scenario 2: Down day — up-day check fails
# ---------------------------------------------------------------------------
def test_down_day_does_not_fire():
    today = {"close": 13.50, "volume": 350_000}  # 13.50 < prior_close=14.15 -> down day
    results, diag, _ = _run_scan(
        today, prior_close=14.15, lookback_bars=_STANDARD_LOOKBACK
    )
    assert len(results) == 0
    assert diag["fired"] == 0
    assert diag["evaluated"] == 0


# ---------------------------------------------------------------------------
# Scenario 3: Volume below max down-day — volume criterion fails
# ---------------------------------------------------------------------------
def test_volume_below_max_down_day_does_not_fire():
    today = {"close": 14.72, "volume": 200_000}  # 200K < 280K (max down-day)
    results, diag, _ = _run_scan(
        today, prior_close=14.15, lookback_bars=_STANDARD_LOOKBACK
    )
    assert len(results) == 0
    assert diag["fired"] == 0


# ---------------------------------------------------------------------------
# Scenario 4: Volume exactly equals max down-day — strict inequality requires >
# ---------------------------------------------------------------------------
def test_volume_equals_max_down_day_does_not_fire():
    today = {"close": 14.72, "volume": 280_000}  # 280K == 280K — strict > fails
    results, diag, _ = _run_scan(
        today, prior_close=14.15, lookback_bars=_STANDARD_LOOKBACK
    )
    assert len(results) == 0
    assert diag["fired"] == 0


# ---------------------------------------------------------------------------
# Scenario 5: Below price floor ($4.50 < $5.00)
# ---------------------------------------------------------------------------
def test_below_price_floor_does_not_fire():
    today = {"close": 4.50, "volume": 350_000}  # up day but below price floor
    results, diag, _ = _run_scan(
        today, prior_close=4.20, lookback_bars=_STANDARD_LOOKBACK
    )
    assert len(results) == 0
    assert diag["fired"] == 0


# ---------------------------------------------------------------------------
# Scenario 6: Below volume floor (80K shares < 100K floor)
# ---------------------------------------------------------------------------
def test_below_volume_floor_does_not_fire():
    lookback = _make_lookback(
        closes=[
            10.00,
            10.50,
            10.20,
            10.40,
            10.10,
            10.30,
            10.00,
            10.20,
            10.40,
            10.30,
            10.50,
        ],
        volumes=[
            50_000,
            50_000,
            60_000,
            50_000,
            60_000,
            50_000,
            55_000,
            50_000,
            50_000,
            55_000,
            50_000,
        ],
    )
    today = {
        "close": 14.72,
        "volume": 80_000,
    }  # 80K > 60K (volume criterion passes), 80K < 100K (floor fails)
    results, diag, _ = _run_scan(today, prior_close=14.15, lookback_bars=lookback)
    assert len(results) == 0
    assert diag["fired"] == 0


# ---------------------------------------------------------------------------
# Scenario 7: Fewer than 5 prior trading days of data
# ---------------------------------------------------------------------------
def test_insufficient_lookback_days_does_not_fire():
    short_lookback = _make_lookback(
        closes=[10.00, 10.20, 10.10, 10.30],
        volumes=[200_000, 180_000, 220_000, 190_000],
    )
    today = {"close": 14.72, "volume": 350_000}
    results, diag, _ = _run_scan(today, prior_close=14.15, lookback_bars=short_lookback)
    assert len(results) == 0
    assert diag["no_baseline"] == 1


# ---------------------------------------------------------------------------
# Scenario 8: No down days in lookback — all prior 10 days were up days
# ---------------------------------------------------------------------------
def test_no_down_days_does_not_fire():
    all_up = _make_lookback(
        closes=[
            10.00,
            10.10,
            10.20,
            10.30,
            10.40,
            10.50,
            10.60,
            10.70,
            10.80,
            10.90,
            11.00,
        ],
        volumes=[200_000] * 11,
    )
    today = {"close": 11.20, "volume": 350_000}
    results, diag, _ = _run_scan(today, prior_close=11.00, lookback_bars=all_up)
    assert len(results) == 0
    assert diag["no_down_days"] == 1


# ---------------------------------------------------------------------------
# Scenario 9: Stock split within lookback window -> fires with split_in_lookback=True
# ---------------------------------------------------------------------------
def test_split_in_lookback_fires_with_flag():
    enrichment = {
        **_EMPTY_ENRICHMENT,
        "recent_split_date": "2026-01-05",  # 10 days before event_date 2026-01-15, within 28 days
    }
    today = {"close": 14.72, "volume": 350_000}
    results, diag, mock_save = _run_scan(
        today,
        prior_close=14.15,
        lookback_bars=_STANDARD_LOOKBACK,
        enrichment=enrichment,
    )
    assert len(results) == 1
    indicators = mock_save.call_args.kwargs["indicators"]
    assert indicators["split_in_lookback"] is True


# ---------------------------------------------------------------------------
# Scenario 10: Near IPO with exactly 5 prior days
# ---------------------------------------------------------------------------
def test_near_ipo_with_5_days_fires():
    ipo_lookback = _make_lookback(
        closes=[10.50, 10.60, 10.40, 10.50, 10.30, 10.50],
        volumes=[150_000, 150_000, 280_000, 180_000, 240_000, 160_000],
    )
    today = {"close": 14.72, "volume": 350_000}  # 350K > 280K
    results, diag, mock_save = _run_scan(
        today, prior_close=14.15, lookback_bars=ipo_lookback
    )
    assert len(results) == 1
    indicators = mock_save.call_args.kwargs["indicators"]
    assert indicators["lookback_days_available"] == 5


# ---------------------------------------------------------------------------
# Scenario 11: Missing today's daily bar -> skip, counted in no_today_bar
# ---------------------------------------------------------------------------
def test_missing_today_bar_does_not_fire():
    results, diag, _ = _run_scan(
        today_bar=None, prior_close=14.15, lookback_bars=_STANDARD_LOOKBACK
    )
    assert len(results) == 0
    assert diag["no_today_bar"] == 1


# ---------------------------------------------------------------------------
# Scenario 12: diagnostics_out populated — 3 tickers, 2 fire, 1 fails volume criterion
# ---------------------------------------------------------------------------
def test_diagnostics_populated_correctly():
    from app.services.pocket_pivot import run_pocket_pivot_scan

    tickers = ["AAPL", "MSFT", "GOOG"]

    def today_bar_per_ticker(db, ticker, event_date):
        if ticker == "GOOG":
            return {
                "close": 14.72,
                "volume": 280_000,
            }  # == max_down_day -> strict > fails
        return {"close": 14.72, "volume": 350_000}

    def prior_close_side_effect(db, ticker, event_date):
        return 14.15

    def lookback_side_effect(db, ticker, event_date, lookback_days):
        return _STANDARD_LOOKBACK

    def enrichment_side_effect(db, ticker, event_date):
        return _EMPTY_ENRICHMENT

    diagnostics: dict[str, Any] = {}

    with (
        patch(
            "app.services.pocket_pivot._get_today_bar", side_effect=today_bar_per_ticker
        ),
        patch(
            "app.services.pocket_pivot._get_prior_close",
            side_effect=prior_close_side_effect,
        ),
        patch(
            "app.services.pocket_pivot._get_lookback_bars",
            side_effect=lookback_side_effect,
        ),
        patch(
            "app.services.pocket_pivot._get_enrichment",
            side_effect=enrichment_side_effect,
        ),
        patch("app.services.pocket_pivot._save_event", return_value={"ticker": "X"}),
        patch("app.services.pocket_pivot.scanner_events_total"),
    ):
        results = asyncio.run(
            run_pocket_pivot_scan(
                tickers,
                db=MagicMock(),
                start_date=_EVENT_DATE,
                end_date=_EVENT_DATE,
                diagnostics_out=diagnostics,
            )
        )

    assert len(results) == 2
    assert diagnostics["evaluated"] == 3  # all 3 had data and were up days
    assert diagnostics["fired"] == 2  # GOOG fails volume criterion
    assert diagnostics["tickers"] == 3
    assert diagnostics["days"] == 1


def test_pocket_pivot_observes_slo_metrics():
    """scan_last_success_timestamp and scan_failed_tickers_ratio are set after a run."""
    import asyncio
    import time
    from unittest.mock import MagicMock, patch

    with (
        patch("app.services.pocket_pivot._get_today_bar", return_value=None),
        patch("app.services.pocket_pivot._get_prior_close", return_value=None),
        patch("app.services.pocket_pivot._get_lookback_bars", return_value=[]),
        patch("app.services.pocket_pivot._get_enrichment", return_value={}),
        patch("app.services.pocket_pivot._save_event", return_value={}),
        patch("app.services.pocket_pivot.scanner_events_total"),
        patch("app.services.pocket_pivot.scan_duration_seconds"),
        patch("app.services.pocket_pivot.scan_last_success_timestamp") as mock_ts,
        patch("app.services.pocket_pivot.scan_failed_tickers_ratio") as mock_ratio,
    ):
        mock_ts_lbl = MagicMock()
        mock_ts.labels.return_value = mock_ts_lbl
        mock_ratio_lbl = MagicMock()
        mock_ratio.labels.return_value = mock_ratio_lbl

        from app.services.pocket_pivot import run_pocket_pivot_scan

        asyncio.run(
            run_pocket_pivot_scan(
                [], db=MagicMock(), start_date=_EVENT_DATE, end_date=_EVENT_DATE
            )
        )

    mock_ts.labels.assert_called_with(scanner_type="pocket_pivot")
    mock_ts_lbl.set.assert_called_once()
    assert abs(mock_ts_lbl.set.call_args[0][0] - time.time()) < 30
    mock_ratio.labels.assert_called_with(scanner_type="pocket_pivot")
    mock_ratio_lbl.set.assert_called_once()
    assert 0.0 <= mock_ratio_lbl.set.call_args[0][0] <= 1.0
