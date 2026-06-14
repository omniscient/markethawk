def test_run_oversold_bounce_scan_importable_from_module():
    from app.services.oversold_bounce_scan import run_oversold_bounce_scan

    assert callable(run_oversold_bounce_scan)


def test_oversold_bounce_observes_slo_metrics():
    """scan_last_success_timestamp and scan_failed_tickers_ratio are set after a run."""
    import asyncio
    import time
    from datetime import date
    from unittest.mock import AsyncMock, MagicMock, patch

    with (
        patch("app.services.oversold_bounce_scan.scanner_events_total"),
        patch("app.services.oversold_bounce_scan.scan_duration_seconds"),
        patch(
            "app.services.oversold_bounce_scan.scan_last_success_timestamp"
        ) as mock_ts,
        patch(
            "app.services.oversold_bounce_scan.scan_failed_tickers_ratio"
        ) as mock_ratio,
        patch(
            "app.services.scanner.ScannerService._get_batch_enrichment_data",
            return_value=({}, {}, {}),
        ),
        patch("app.services.scanner.load_ranker_config", return_value={}),
        patch("asyncio.to_thread", new=AsyncMock(return_value=({}, {}, {}))),
    ):
        mock_ts_lbl = MagicMock()
        mock_ts.labels.return_value = mock_ts_lbl
        mock_ratio_lbl = MagicMock()
        mock_ratio.labels.return_value = mock_ratio_lbl

        from app.services.oversold_bounce_scan import run_oversold_bounce_scan

        # tickers=[] skips the inner for-ticker loop; all metric observations still execute
        asyncio.run(
            run_oversold_bounce_scan([], db=MagicMock(), event_date=date(2026, 1, 15))
        )

    mock_ts.labels.assert_called_with(scanner_type="oversold_bounce")
    mock_ts_lbl.set.assert_called_once()
    assert abs(mock_ts_lbl.set.call_args[0][0] - time.time()) < 30
    mock_ratio.labels.assert_called_with(scanner_type="oversold_bounce")
    mock_ratio_lbl.set.assert_called_once()
    assert 0.0 <= mock_ratio_lbl.set.call_args[0][0] <= 1.0
