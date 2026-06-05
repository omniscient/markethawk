def test_run_pre_market_scan_importable_from_module():
    from app.services.pre_market_scan import run_pre_market_scan

    assert callable(run_pre_market_scan)
