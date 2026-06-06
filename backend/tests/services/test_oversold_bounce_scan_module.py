def test_run_oversold_bounce_scan_importable_from_module():
    from app.services.oversold_bounce_scan import run_oversold_bounce_scan

    assert callable(run_oversold_bounce_scan)
